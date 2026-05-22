import html
import re
import logging
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger("ScienceBlogBot.BloggerClient")

class BloggerClient:
    def __init__(self, credentials, blog_id: str):
        self.service = build('blogger', 'v3', credentials=credentials)
        self.blog_id = blog_id

    def embed_premium_images(self, content: str, processed_images: list, git_manager) -> str:
        """
        본문의 [IMAGE_PROMPT: ...] 태그를 실제 CDN URL을 지닌
        세련되고 보기 좋은 프리미엄 HTML 이미지 카드 블록으로 치환합니다.
        """
        final_content = content
        
        for img in processed_images:
            original_tag = img["tag"]
            prompt = img["prompt"]
            rel_path = img["rel_path"]
            
            # CDN URL 도출
            cdn_url = git_manager.get_public_cdn_url(rel_path)
            
            # 국문용 짧은 설명 또는 영어 프롬프트의 에센스 추출 (캡션용)
            caption = img.get("caption") or prompt
            if not img.get("caption"):
                # 영어 프롬프트가 너무 길 수 있으므로 핵심 앞 40자만 캡션으로 처리 (역호환성)
                caption = prompt.split(",")[0] if "," in prompt else prompt
                if len(caption) > 50:
                    caption = caption[:47] + "..."
            
            # 해시태그 형식 변환 방어 로직 적용
            caption = caption.strip()
            if not caption.startswith("#"):
                # 문장 내 단어들을 추출하여 해시태그 형태로 가공 (길이 2자 이상인 의미 있는 단어 최대 3개 선별)
                clean_caption = re.sub(r"[^\w\s]", "", caption)
                words = [w for w in clean_caption.split() if len(w) >= 2]
                if words:
                    # 최대 3개 단어만 해시태그로 결합
                    caption = " ".join([f"#{w}" for w in words[:3]])
                else:
                    # 마땅한 단어가 없으면 프롬프트 앞 단어로 대체
                    clean_prompt = re.sub(r"[^\w\s]", "", prompt.split(",")[0])
                    prompt_words = [w for w in clean_prompt.split() if len(w) >= 2]
                    caption = " ".join([f"#{w}" for w in prompt_words[:2]]) if prompt_words else "#science"
                
            # HTML 특수기호 에스케이프 처리
            caption_esc = html.escape(caption)
            prompt_esc = html.escape(prompt)
            
            # 프리미엄 블로그 스타일의 이미지 카드 블록 빌드 (해시태그 전용 모던 미니멀 스타일)
            # 반응형 크기 설정, 둥근 모서리(border-radius: 12px), 은은한 쉐도우(box-shadow), 미니멀 해시태그
            premium_image_html = f"""
<div class="science-blog-image-card" style="text-align: center; margin: 35px 0; padding: 10px; background-color: #fafafa; border-radius: 16px; border: 1px solid #eaeaea;">
    <a href="{cdn_url}" target="_blank" style="text-decoration: none;">
        <img src="{cdn_url}" alt="{prompt_esc}" style="max-width: 100%; height: auto; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.08); transition: transform 0.3s ease-in-out;" onmouseover="this.style.transform='scale(1.01)'" onmouseout="this.style.transform='scale(1)'" />
    </a>
    <p style="color: #888; font-size: 0.82em; margin: 12px 0 4px 0; font-family: 'Inter', 'Noto Sans KR', sans-serif; font-weight: 500; letter-spacing: 0.5px; line-height: 1.4;">
        {caption_esc}
    </p>
</div>
"""
            # 본문의 이미지 태그 치환
            final_content = final_content.replace(original_tag, premium_image_html)
            logger.info(f"Replaced tag '{original_tag[:30]}...' with premium CDN image card.")
            
        # 이미지 생성이 실패하여 치환되지 않고 남은 이미지 프롬프트 태그([IMAGE_PROMPT: ...])가 있다면 본문에서 깨끗하게 제거합니다.
        import re
        final_content = re.sub(r"\[IMAGE_PROMPT:\s*[^\]]+\]", "", final_content)
        
        return final_content

    def publish_post(self, title: str, html_content: str, keywords: list) -> str:
        """Blogger에 준비된 타이틀과 본문을 즉시 발행(Publish) 처리합니다."""
        logger.info(f"Publishing post to Blogger. Title: '{title}'...")
        
        # Blogger 포스트 바디 작성
        post_body = {
            "kind": "blogger#post",
            "title": title,
            "content": html_content,
            "labels": keywords
        }
        
        try:
            # isDraft=False 로 설정하여 대기 없이 즉시 전체 공개 발행
            result = self.service.posts().insert(
                blogId=self.blog_id,
                body=post_body,
                isDraft=False
            ).execute()
            
            post_url = result.get("url")
            logger.info(f"Successfully published post! URL: {post_url}")
            return post_url
            
        except HttpError as e:
            logger.error(f"HTTP Error publishing post to Blogger API: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error publishing post: {e}")
            raise
