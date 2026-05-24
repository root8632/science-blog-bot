import json
import logging
import re
from google import genai
from google.genai import types
from google.genai.errors import APIError

logger = logging.getLogger("ScienceBlogBot.GeminiClient")

# 모델별 100만 토큰당 요금 (USD) - 2026년 5월 기준 Google AI Studio Pay-as-you-go
MODEL_PRICING = {
    "gemini-2.5-flash":      {"input": 0.30, "output": 2.50},
    "gemini-2.0-flash":      {"input": 0.10, "output": 0.40},
    "gemini-1.5-flash":      {"input": 0.075, "output": 0.30},
    "gemini-3.5-flash":      {"input": 0.50, "output": 3.00},
    "gemini-3.0-flash":      {"input": 0.50, "output": 3.00},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},
}

# 원/달러 환산 근사치
USD_TO_KRW = 1380


class GeminiClient:
    # 503/429 에러 시 자동 전환할 대체 모델 목록 (우선순위 순서)
    # 2026년 기준 1.5-flash는 단종(404), 2.0-flash는 무료 티어 제한(429)이 있으므로 최신 Lite 모델로 대체
    FALLBACK_MODELS = ["gemini-2.5-flash-lite", "gemini-3.1-flash-lite"]

    def __init__(self, api_key: str, topic_model: str = "gemini-2.5-flash", post_model: str = "gemini-3.5-flash", image_model: str = "imagen-3.0-generate-002", pixabay_api_key: str = None):
        # 최신 google-genai SDK 클라이언트 초기화
        self.client = genai.Client(api_key=api_key)
        # 이미지 생성이나 일반 텍스트용 기본 모델 지정
        self.text_model = topic_model  # Grounding 및 텍스트 처리에 적합한 모델 (주제 선정용)
        self.post_model = post_model  # 블로그 본문 글작성용 모델
        self.image_model = image_model  # 최신 고화질 무료 이미지 모델
        self.pixabay_api_key = pixabay_api_key
        
        # 누적 토큰 사용량 추적
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_estimated_cost_usd = 0.0
        self.last_style_guide_source = "Local"
        self.last_topic_model = "Unknown"
        self.last_post_model = "Unknown"

    def _log_token_usage(self, response, model_name: str, step_name: str):
        """
        API 응답에서 토큰 사용량 메타데이터를 추출하여 로그에 실시간 출력하고,
        예상 비용을 원화로 환산하여 누적 추적합니다.
        """
        try:
            usage = response.usage_metadata
            if not usage:
                logger.info(f"💡 [{step_name}] Token usage metadata not available for this response.")
                return
            
            input_tokens = getattr(usage, 'prompt_token_count', 0) or 0
            output_tokens = getattr(usage, 'candidates_token_count', 0) or 0
            total_tokens = getattr(usage, 'total_token_count', 0) or (input_tokens + output_tokens)
            
            # 비용 계산
            pricing = MODEL_PRICING.get(model_name, {"input": 0.30, "output": 2.50})
            input_cost = pricing["input"] * (input_tokens / 1_000_000)
            output_cost = pricing["output"] * (output_tokens / 1_000_000)
            step_cost_usd = input_cost + output_cost
            step_cost_krw = step_cost_usd * USD_TO_KRW
            
            # 누적 추적
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.total_estimated_cost_usd += step_cost_usd
            
            logger.info(
                f"📊 [{step_name}] 토큰 사용량: "
                f"입력 {input_tokens:,} + 출력 {output_tokens:,} = 총 {total_tokens:,} tokens | "
                f"예상 비용: ${step_cost_usd:.4f} (약 {step_cost_krw:.1f}원) | "
                f"모델: {model_name}"
            )
        except Exception as e:
            logger.warning(f"Token usage logging failed (non-critical): {e}")

    def _log_cumulative_usage(self):
        """파이프라인 전체 누적 토큰 사용량 및 총 비용을 요약 로그로 출력합니다."""
        total_krw = self.total_estimated_cost_usd * USD_TO_KRW
        logger.info(
            f"💰 [누적 합계] 입력 {self.total_input_tokens:,} + 출력 {self.total_output_tokens:,} tokens | "
            f"총 예상 비용: ${self.total_estimated_cost_usd:.4f} (약 {total_krw:.1f}원)"
        )

    def _generate_with_fallback(self, primary_model: str, contents, config, step_name: str):
        """
        주 모델로 API 호출을 시도하고, 503/429 등 서버 에러 발생 시
        대체 모델 목록(FALLBACK_MODELS)을 순회하며 자동 전환합니다.
        성공한 (response, 사용된_모델명) 튜플을 반환합니다.
        """
        # 시도할 모델 순서: 주 모델 → 대체 모델들
        models_to_try = [primary_model] + [m for m in self.FALLBACK_MODELS if m != primary_model]
        
        last_error = None
        for model_name in models_to_try:
            try:
                if model_name != primary_model:
                    logger.warning(f"🔄 [{step_name}] 대체 모델 '{model_name}'(으)로 자동 전환하여 재시도합니다...")
                
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )
                
                if model_name != primary_model:
                    logger.info(f"✅ [{step_name}] 대체 모델 '{model_name}' 호출 성공!")
                
                # 토큰 사용량 로깅
                self._log_token_usage(response, model_name, step_name)
                
                return response, model_name
                
            except Exception as e:
                last_error = e
                error_str = str(e)
                # 503, 429, UNAVAILABLE, RESOURCE_EXHAUSTED 등 서버측 에러만 폴백 대상
                is_server_error = any(code in error_str for code in ["503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "overloaded"])
                
                if is_server_error and model_name != models_to_try[-1]:
                    logger.warning(f"⚠️ [{step_name}] 모델 '{model_name}' 서버 에러 ({e}). 다음 대체 모델로 전환합니다.")
                    continue
                else:
                    # 서버 에러가 아니거나, 마지막 대체 모델까지 실패한 경우
                    raise last_error

    def select_topic(self, system_prompt: str, published_topics: list[str]) -> dict:
        """
        7대 주제 선정 정책(Strict Topic Policy)을 준수하는 과학 블로그 주제를 실시간 검색으로 도출합니다.
        중복 방지를 위해 기존 발행 주제 목록을 제외시킵니다.
        """
        logger.info("Starting real-time topic research with Google Search Grounding...")
        
        # 기 발행된 목록을 프롬프트용 텍스트로 가공
        exclude_text = "\n".join([f"- {t}" for t in published_topics]) if published_topics else "없음"
        
        # 1단계: 구글 검색을 사용해 자유롭게 트렌드 분석 및 기획안 도출
        research_prompt = f"""
당신은 최고의 실시간 트렌드 분석가이자 테크 저널리스트입니다.
구글 검색(Google Search) 툴을 활성화하여 현재 개발자나 일반 직장인들이 인터넷상에서 많이 검색하고 있는 최신 IT 기술 스택, 실무 프로그래밍 스킬 관련 이슈를 엮은 가장 적합한 포스팅 주제를 **딱 하나** 선정하고 상세 기획안을 작성해 주십시오.

[중복 방지 정책]
아래 목록에 있는 이미 발행된 주제는 절대로 다시 다루면 안 됩니다. 완전히 새로운 소재를 찾으십시오.
---
기 발행 목록:
{exclude_text}
---

[7대 IT/프로그래밍 주제 선정 정책 (Strict Tech-Topic Policy)]
반드시 아래의 7가지 기준을 '동시에 100% 만족'하는 주제만 선정해야 하며, 만족하지 못할 경우 대안을 모색해야 합니다.
1. [Practical & Tutorial]: 개발자들이 실무에서 흔히 직면하는 실무 해결책, 자동화 스크립트 작성법(예: Python 크롤링, 웹 자동화, 엑셀 자동화), 데이터 분석 등 실용적인 튜토리얼 주제.
2. [Stack Popularity]: Python, JavaScript, SQL 등 대중적이고 검색 수요가 매우 높은 프로그래밍 언어와 핵심 프레임워크(BeautifulSoup, Pandas, Selenium 등) 관련 주제.
3. [48시간 내 검색 트렌드]: 최근 48시간 이내에 블로그, StackOverflow, GitHub 등에서 이슈가 되었거나 많은 개발자들의 구글 검색량 그래프가 크게 상승하고 있는 키워드.
4. [코드 레벨 설명성 (Code Illustrated)]: 실제 동작 가능한 코드 블록(Code Snippet) 예제와 이에 대한 주석 설명이 직관적으로 매끄럽게 어우러질 수 있는 주제.
5. [IT 스토리지 시각화 (IT Photography)]: 무료 이미지 플랫폼(Pixabay)에서 고품질 사진이 풍부하게 검색될 수 있도록 1~3단어 수준의 명확하고 실제 사물 위주의 영문 키워드(예: 'computer board', 'data server', 'developer typing', 'cloud infrastructure')를 뽑을 수 있을 것.
   - ⚠️ **[중요 - 추상화/비유 금지]**: '양자 컴퓨터 톱니바퀴 모식도'나 '인공지능의 가상 뉴런 망'처럼 복잡한 시각적 CG나 추상적 모식도를 유도하는 키워드 대신, 물리적 실체나 자연스러운 개발 환경(예: 'computer hardware', 'developer coding', 'datacenter server', 'ethernet cable')을 사진(Photography) 스타일로 직설적으로 묘사하는 단순한 키워드만 선정해야 합니다. 추상적인 비유(톱니바퀴, AI 사람, 합성 그래픽 등)를 절대 유도하지 마십시오.
6. [초보자 독자 공감성]: 초보 개발자나 일반 직장인도 삶의 현장(엑셀 자동화, 웹 자동 수집 등)에서 직접 체감하고 활용해보고 싶은 매력적인 실무 스킬.
7. [광고 친화적]: 불법 크래킹, 타인 정보 무단 우회 해킹, 우회 스팸성 코딩 기법 등 보안 및 윤리적 이슈가 되는 기술적 내용은 전면 배제할 것.

구글 검색 툴을 사용해 최신 자료를 충분히 검색한 뒤, 7대 정책을 어떻게 모두 만족했는지 기술하고, 최종 선정된 '주제 제목', '키워드 태그(3~5개)', '본문 이미지 검색용 영어 키워드 2가지(각각 1~3단어 수준의 아주 구체적이고 물리적 실체가 있는 직설적 단어 조합)'를 자유롭고 상세하게 텍스트로 기술해 주십시오.
"""
        try:
            # 1단계: 구글 검색을 사용해 자유롭게 트렌드 분석 및 기획안 도출 (response_mime_type을 지정하지 않아 400 에러 우회)
            logger.info("Step 1: Grounded Research with Google Search...")
            research_response, used_model = self._generate_with_fallback(
                primary_model=self.text_model,
                contents=research_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.7
                ),
                step_name="주제 리서치"
            )
            research_result = research_response.text
            logger.info("Research complete. Grounded output received.")
            
            # 2단계: 도출된 자유 텍스트를 구조화된 JSON 데이터로 완벽하게 변환 (도구 미사용 + response_mime_type="application/json" 사용)
            logger.info("Step 2: Formatting Grounded Research into JSON...")
            formatting_prompt = f"""
당신은 최고의 데이터 파서(Data Parser)입니다.
아래의 [실시간 과학 트렌드 조사 결과]를 분석하여 지정된 JSON 형식 데이터로 정확하게 구조화해서 출력하십시오.

[실시간 과학 트렌드 조사 결과]
{research_result}

[요구사항]
다음 JSON 형식을 엄격히 준수하여 출력하십시오. 어떠한 여담이나 설명도 출력에 포함하지 마십시오.

{{
  "title": "선정된 매력적인 포스팅 국문 제목 (예: '왜 비누방울은 햇빛 아래서 무지갯빛으로 빛날까?')",
  "keywords": ["주요", "검색", "태그", "3~5개"],
  "rationale": "7대 정책을 어떻게 충족했는지 상세한 설명",
  "image_keyword_1": "본문 전반부에 삽입될 이미지 검색을 위한 1~3단어 수준의 명확하고 단순한 영문 키워드 (예: 'lactobacillus', 'bubble')",
  "image_caption_1": "본문 전반부 이미지 하단에 노출할 세련된 미니멀 해시태그 캡션 (예: '#유산균 #microscope #세포'와 같이 2~3개 해시태그 결합)",
  "image_keyword_2": "본문 후반부에 삽입될 이미지 검색을 위한 1~3단어 수준의 명확하고 단순한 영문 키워드 (예: 'probiotics', 'microscope')",
  "image_caption_2": "본문 후반부 이미지 하단에 노출할 세련된 미니멀 해시태그 캡션 (예: '#probiotics #유산균 #장건강'과 같이 2~3개 해시태그 결합)"
}}
"""
            json_response, used_model_2 = self._generate_with_fallback(
                primary_model=used_model,  # 1단계에서 성공한 모델을 그대로 사용
                contents=formatting_prompt,
                config=types.GenerateContentConfig(
                    system_instruction="You are a strict data formatter that outputs only valid JSON.",
                    temperature=0.2,
                    response_mime_type="application/json"
                ),
                step_name="JSON 구조화"
            )
            
            # JSON 결과 파싱
            plan = json.loads(json_response.text)
            self.last_topic_model = used_model_2
            logger.info(f"Selected Topic: '{plan.get('title')}' satisfy all 7 strict policies.")
            return plan
            
        except Exception as e:
            logger.error(f"Error selecting topic with Gemini: {e}")
            raise

    def generate_blog_post(self, system_prompt: str, topic_plan: dict, style_guide_template: str = None) -> str:
        """
        선정된 주제와 구글 시트에서 동적으로 가져온 스타일 가이드 템플릿을 바탕으로 본문을 작성합니다.
        가이드 내의 플레이스홀더({title}, {img_prompt1}, {img_prompt2})가 유효한지 검증하고 적용합니다.
        """
        title = topic_plan.get("title")
        img_prompt1 = topic_plan.get("image_keyword_1") or topic_plan.get("image_prompt_1")
        img_prompt2 = topic_plan.get("image_keyword_2") or topic_plan.get("image_prompt_2")
        
        logger.info(f"Generating HTML blog post body for topic: '{title}'...")
        logger.info(f"System Instruction Loaded (Length: {len(system_prompt)} chars). Preview: '{system_prompt[:120].strip()}...'")
        
        # 기본 안전 fallback 스타일 가이드
        default_style_guide = (
            "[작성 및 서식 요구사항 (Strict Tech-Style Policy)]\n\n"
            "1. **HTML 형식 작성**: Blogger 본문에 바로 깔끔하게 삽입되도록 마크다운이 아닌 **순수 HTML 태그**로 작성하십시오.\n"
            "   - 대제목은 생략(Blogger의 Post Title이 됨)하고, 본문 내 소주제는 `<h2>`, `<h3>` 태그를 활용하십시오.\n"
            "   - 핵심 요약이나 주의사항은 `<blockquote>` 태그를 활용하십시오.\n"
            "   - 강조 단어는 `<strong>` 또는 `<u>` 태그를 사용하십시오.\n\n"
            "2. **간결한 강의 스타일**: 글자수를 채우기 위한 장황설이나 반복적 설명은 절대 하지 마십시오. "
            "핵심 설명을 간결하게 전달하고, 코드 블록이 글의 주인공이 되도록 구성하십시오.\n\n"
            "3. **실무 코드 예제(Code Snippet) 포함**:\n"
            "   - 본문에 **실제 동작이 가능한 완성형 코딩 예제**를 1회 이상 포함하십시오.\n"
            "   - 코드 블록은 `<pre><code class=\"language-python\">` (또는 해당 언어 태그) 구조를 활용하십시오.\n"
            "   - 코드 내부에 초보자용 한글 주석(`# 설명`)을 필수로 달아주십시오.\n\n"
            "4. **이미지 배치**:\n"
            "   - 본문 중간 2곳에 아래 형식을 정확하게 삽입하십시오.\n"
            "     - `[IMAGE_PROMPT: {img_prompt1}]`\n"
            "     - `[IMAGE_PROMPT: {img_prompt2}]`\n"
            "   - 이미지 캡션은 2~3개 해시태그 형식으로만 작성하십시오. (예: `#python #web_scraping`)"
        )
        
        # 시트에서 받아온 템플릿 유효성 정밀 검증
        style_guide = None
        if style_guide_template:
            # 필수 토큰 존재 검사 (이미지 처리를 위한 프롬프트 토큰은 필수, {title}은 선택적이므로 검증에서 제외)
            required_tokens = ["{img_prompt1}", "{img_prompt2}"]
            missing_tokens = [t for t in required_tokens if t not in style_guide_template]
            
            if missing_tokens:
                logger.warning(
                    f"⚠️ [STYLE GUIDE VALIDATION FAILED] Google Sheets template is missing mandatory placeholders {missing_tokens}. "
                    f"Falling back to built-in safe default style guide."
                )
                self.last_style_guide_source = "Local"
                style_guide = default_style_guide.format(
                    title=title,
                    img_prompt1=img_prompt1,
                    img_prompt2=img_prompt2
                )
            else:
                try:
                    # 템플릿 렌더링
                    style_guide = style_guide_template.format(
                        title=title,
                        img_prompt1=img_prompt1,
                        img_prompt2=img_prompt2
                    )
                    logger.info("✅ [STYLE GUIDE VALIDATION SUCCESS] Safely loaded and parsed custom Style Guide from Google Sheets.")
                    logger.info(f"Style Guide Preview: '{style_guide[:150].strip()}...'")
                    self.last_style_guide_source = "GoogleSheet"
                except Exception as e:
                    logger.error(f"❌ Failed to format style guide template: {e}. Falling back to default.")
                    self.last_style_guide_source = "Local"
                    style_guide = default_style_guide.format(
                        title=title,
                        img_prompt1=img_prompt1,
                        img_prompt2=img_prompt2
                    )
        else:
            logger.info("ℹ️ No Style Guide template provided in sheet cells. Using built-in default style guide.")
            self.last_style_guide_source = "Local"
            style_guide = default_style_guide.format(
                title=title,
                img_prompt1=img_prompt1,
                img_prompt2=img_prompt2
            )
            
        post_prompt = f"""
당신은 최고의 과학 블로거입니다. 선정된 다음의 기획안과 서식 요구사항을 바탕으로 대중에게 감동을 주는 프리미엄 과학 에세이를 완성하십시오.

[기획안]
- 제목: {title}
- 이미지 1 검색 키워드: {img_prompt1}
- 이미지 2 검색 키워드: {img_prompt2}

{style_guide}

HTML 포스트 본문만 즉시 반환하십시오. 앞뒤의 ```html 이나 여타 안내 텍스트 없이 오직 HTML 본문 코드만 출력하십시오.
"""
        try:
            response, used_model = self._generate_with_fallback(
                primary_model=self.post_model,
                contents=post_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.75
                ),
                step_name="블로그 본문 작성"
            )
            
            content = response.text.strip()
            # 마크다운 펜스(```html ... ```)가 들어간 경우 정제
            content = re.sub(r"^```html\s*", "", content, flags=re.IGNORECASE)
            content = re.sub(r"```$", "", content)
            
            # 본문에 IMAGE_PROMPT 가 2개 정상 존재 확인
            prompt_count = len(re.findall(r"\[IMAGE_PROMPT:\s*[^\]]+\]", content))
            logger.info(f"Generated post body size: {len(content)} characters. Found {prompt_count} image tags.")
            
            if prompt_count != 2:
                logger.warning(f"Expected exactly 2 [IMAGE_PROMPT: ...] tags, but found {prompt_count}. Repairing or falling back...")
                
            self.last_post_model = used_model
            # 누적 사용량 요약 출력
            self._log_cumulative_usage()
            
            return content.strip()
            
        except Exception as e:
            logger.error(f"Error generating blog post content: {e}")
            raise

    def generate_image_by_prompt(self, english_prompt: str) -> bytes:
        """
        Pixabay 무료 이미지 API를 호출하여 입력받은 영어 키워드에 해당하는 고해상도 이미지를 바이너리로 내려받습니다.
        """
        import requests
        
        # 키워드 정리: [IMAGE_PROMPT: ...] 형식에서 추출된 프롬프트가 다소 길 경우, 쉼표나 띄어쓰기로 앞 단어 일부만 추출하거나 전체 검색 시도
        # Pixabay API는 단어 수가 너무 많고 복잡하면 결과가 안 나올 수 있으므로, 적절히 앞 3~4단어만 잘라서 사용하거나 단어 분리
        search_query = english_prompt.strip()
        
        # 혹시나 예전 스타일의 너무 긴 프롬프트가 들어올 것에 대비해 5단어 이하로 제한
        words = search_query.split()
        if len(words) > 5:
            # 쉼표가 있다면 첫 절을 선택, 없으면 앞 4단어 선택
            if "," in search_query:
                search_query = search_query.split(",")[0].strip()
            else:
                search_query = " ".join(words[:4])
                
        logger.info(f"Searching Pixabay for keyword: '{search_query}' (Original: '{english_prompt[:40]}...')")
        
        if not self.pixabay_api_key:
            logger.warning("Pixabay API Key is missing. Skipping image download (will fall back to text-only mode).")
            return None
            
        try:
            # Pixabay API 호출 파라미터 세팅
            params = {
                "key": self.pixabay_api_key,
                "q": search_query,
                "image_type": "photo",
                "safesearch": "true",
                "per_page": 5,
                "orientation": "horizontal"
            }
            
            response = requests.get("https://pixabay.com/api/", params=params, timeout=10)
            if response.status_code != 200:
                logger.error(f"Pixabay API returned non-200 status: {response.status_code}, response: {response.text}")
                return None
                
            data = response.json()
            hits = data.get("hits", [])
            
            if not hits:
                # 결과가 전혀 없는 경우, 조금 더 광범위하게 검색해보기 위해 단어 하나로 축소하여 재시도
                fallback_query = words[0] if words else "science"
                logger.warning(f"No results for '{search_query}'. Trying fallback search with '{fallback_query}'...")
                params["q"] = fallback_query
                response = requests.get("https://pixabay.com/api/", params=params, timeout=10)
                if response.status_code == 200:
                    hits = response.json().get("hits", [])
            
            if not hits:
                logger.warning(f"No images found on Pixabay for query and fallback.")
                return None
                
            # 가장 해상도가 높고 적합한 이미지 URL 선택 (largeImageURL 또는 webformatURL)
            image_url = hits[0].get("largeImageURL") or hits[0].get("webformatURL")
            if not image_url:
                logger.warning("No valid image URL found in Pixabay response hits.")
                return None
                
            logger.info(f"Downloading selected image from Pixabay: {image_url}")
            
            img_response = requests.get(image_url, timeout=15)
            if img_response.status_code == 200:
                logger.info(f"Successfully downloaded Pixabay image. Size: {len(img_response.content)} bytes.")
                return img_response.content
            else:
                logger.error(f"Failed to download image bytes. Status: {img_response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error occurred during Pixabay image search/download: {e}")
            return None
