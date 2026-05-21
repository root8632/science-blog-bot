import json
import logging
import re
from google import genai
from google.genai import types
from google.genai.errors import APIError

logger = logging.getLogger("ScienceBlogBot.GeminiClient")

class GeminiClient:
    def __init__(self, api_key: str, topic_model: str = "gemini-2.5-flash", post_model: str = "gemini-3.5-flash", image_model: str = "imagen-3.0-generate-002", pixabay_api_key: str = None):
        # 최신 google-genai SDK 클라이언트 초기화
        self.client = genai.Client(api_key=api_key)
        # 이미지 생성이나 일반 텍스트용 기본 모델 지정
        self.text_model = topic_model  # Grounding 및 텍스트 처리에 적합한 모델 (주제 선정용)
        self.post_model = post_model  # 블로그 본문 글작성용 모델
        self.image_model = image_model  # 최신 고화질 무료 이미지 모델
        self.pixabay_api_key = pixabay_api_key

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
당신은 최고의 실시간 트렌드 분석가이자 과학 저널리스트입니다.
구글 검색(Google Search) 툴을 활성화하여 현재 인터넷상에서 화제가 되고 있는 최신 실시간 이슈와 과학을 엮은 가장 적합한 포스팅 주제를 **딱 하나** 선정하고 상세 기획안을 작성해 주십시오.

[중복 방지 정책]
아래 목록에 있는 이미 발행된 주제는 절대로 다시 다루면 안 됩니다. 완전히 새로운 소재를 찾으십시오.
---
기 발행 목록:
{exclude_text}
---

[7대 주제 선정 정책 (Strict Topic Policy)]
반드시 아래의 7가지 기준을 '동시에 100% 만족'하는 주제만 선정해야 하며, 만족하지 못할 경우 대안을 모색해야 합니다.
1. [Evergreen + Trend Hybrid]: 지금 매우 핫하게 논의되는 트렌디한 뉴스/현상이면서도, 수개월 후에도 정보 가치와 매력을 지니는 주제.
2. [검색량 증가율 존재]: 구글 실시간 트렌드 및 대중 검색 흐름상 최근 검색량 그래프가 크게 상승하고 있는 키워드.
3. [48시간 내 급상승]: 최근 48시간 이내에 새롭게 관찰되었거나 해외/국내 뉴스를 통해 재조명받기 시작한 현상, 이론 또는 이슈.
4. [과학적 설명 가능]: 현상 이면에 물리(역학, 열역학, 양자 등), 화학, 생물학 등 명확하고 심도 깊은 '일상 속 과학 원리'가 존재할 것.
5. [이미지화 가능]: 원리를 직관적인 모형, 도표, 실물 이미지로 시각화하기 쉬운 주제이며, 무료 이미지 플랫폼(Pixabay)에서 검색해낼 수 있는 1~3단어 수준의 명확한 영어 키워드(예: 'quantum computer', 'microscope cells', 'solar eclipse')를 뽑을 수 있을 것.
6. [일반인 공감 가능]: 대중이 삶의 현장에서 직접 체감하고 흥미를 느낄 만한 주제.
7. [광고 친화적]: 폭력성, 선정성, 정치/종교 분쟁, 질병 공포 등을 완전히 배제할 것.

구글 검색 툴을 사용해 최신 자료를 충분히 검색한 뒤, 7대 정책을 어떻게 모두 만족했는지 기술하고, 최종 선정된 '주제 제목', '키워드 태그(3~5개)', '본문 이미지 검색용 영어 키워드 2가지(각각 1~3단어 수준의 아주 구체적이고 대중적인 단어 조합)'를 자유롭고 상세하게 텍스트로 기술해 주십시오.
"""
        try:
            # 1단계: 구글 검색을 사용해 자유롭게 트렌드 분석 및 기획안 도출 (response_mime_type을 지정하지 않아 400 에러 우회)
            logger.info("Step 1: Grounded Research with Google Search...")
            research_response = self.client.models.generate_content(
                model=self.text_model,
                contents=research_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.7
                )
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
  "image_caption_1": "본문 전반부 이미지 하단에 노출할 친절하고 세련된 한글 설명 캡션 (예: '현미경으로 관찰한 김치 속 유산균의 모습')",
  "image_keyword_2": "본문 후반부에 삽입될 이미지 검색을 위한 1~3단어 수준의 명확하고 단순한 영문 키워드 (예: 'probiotics', 'microscope')",
  "image_caption_2": "본문 후반부 이미지 하단에 노출할 친절하고 세련된 한글 설명 캡션"
}}
"""
            json_response = self.client.models.generate_content(
                model=self.text_model,
                contents=formatting_prompt,
                config=types.GenerateContentConfig(
                    system_instruction="You are a strict data formatter that outputs only valid JSON.",
                    temperature=0.2,
                    response_mime_type="application/json"
                )
            )
            
            # JSON 결과 파싱
            plan = json.loads(json_response.text)
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
            "[작성 및 서식 요구사항 (Strict Style Policy)]\n"
            "1. **HTML 형식 작성**: Blogger 본문에 바로 삽입될 것이므로 마크다운이 아닌 **순수 HTML 태그**로 작성하십시오.\n"
            "   - 대제목은 생략(Blogger의 Post Title이 됨)하고, 본문 내 소주제는 `<h2>`, `<h3>` 태그를 활용하십시오.\n"
            "   - 단락은 `<p>` 태그로 묶고 문체는 부드러운 경어체('~합니다', '~시죠?')를 사용하십시오.\n"
            "   - 과학적 핵심 단어나 문장은 `<strong>` 또는 `<u>` 태그로 강조하여 독자의 시선을 사로잡으십시오.\n"
            "   - 전문적인 해설이 들어가는 구역은 `<blockquote>` 태그로 감싸 세련된 프리미엄 블로그 스타일을 구축하십시오.\n"
            "   - 핵심 요약이나 비교 데이터가 있다면 `<ul>`, `<li>` 또는 깔끔하게 스타일링된 `<table>`을 활용해 전문성을 극대화하십시오.\n"
            "2. **풍부한 지식 전달**: 분량은 깊이 있는 정보가 담길 수 있도록 한글 기준 공백 제외 최소 1,500자 이상으로 매우 상세하고 지적으로 작성하십시오.\n"
            "3. **구체적인 이미지 배치**: 본문 중간 흐름상 시각화 자료가 반드시 필요한 위치 2곳에 아래 형식을 **토씨 하나 틀리지 않고 정확하게** 작성해 삽입해야 합니다. (스크립트 파싱용)\n"
            "   - 첫 번째 시각 자료 위치: `[IMAGE_PROMPT: {img_prompt1}]`\n"
            "   - 두 번째 시각 자료 위치: `[IMAGE_PROMPT: {img_prompt2}]`\n"
            "   - 주의: 대괄호와 IMAGE_PROMPT 콜론 뒤 띄어쓰기까지 완벽히 일치해야 합니다."
        )
        
        # 시트에서 받아온 템플릿 유효성 정밀 검증
        style_guide = None
        if style_guide_template:
            # 필수 3대 토큰 존재 검사
            required_tokens = ["{title}", "{img_prompt1}", "{img_prompt2}"]
            missing_tokens = [t for t in required_tokens if t not in style_guide_template]
            
            if missing_tokens:
                logger.warning(
                    f"⚠️ [STYLE GUIDE VALIDATION FAILED] Google Sheets template is missing mandatory placeholders {missing_tokens}. "
                    f"Falling back to built-in safe default style guide."
                )
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
                except Exception as e:
                    logger.error(f"❌ Failed to format style guide template: {e}. Falling back to default.")
                    style_guide = default_style_guide.format(
                        title=title,
                        img_prompt1=img_prompt1,
                        img_prompt2=img_prompt2
                    )
        else:
            logger.info("ℹ️ No Style Guide template provided in sheet cells. Using built-in default style guide.")
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
            response = self.client.models.generate_content(
                model=self.post_model,
                contents=post_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.75
                )
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
