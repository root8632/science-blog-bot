import os
import sys
import time
import random
import logging
from datetime import datetime

from config import Config
from google_sheets import GoogleSheetsClient
from gemini_client import GeminiClient
from image_processor import ImageProcessor
from git_manager import GitManager
from blogger_client import BloggerClient

logger = logging.getLogger("ScienceBlogBot.Main")

def retry_with_backoff(func, *args, max_attempts: int = 5, initial_delay: float = 2.0, factor: float = 2.0, **kwargs):
    """
    임의의 함수를 지수 백오프 및 지터(Jitter) 알고리즘을 적용하여 안전하게 재시도합니다.
    API 할당량 초과 및 일시적 다운 현상을 극복합니다.
    """
    delay = initial_delay
    for attempt in range(1, max_attempts + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt == max_attempts:
                logger.error(f"Function {func.__name__} failed permanently after {max_attempts} attempts.")
                raise e
            
            # 지터(Jitter) 추가로 동시 요청 분산
            sleep_time = (delay * (0.5 + random.random()))
            logger.warning(
                f"Error in {func.__name__} ({e}). "
                f"Retrying in {sleep_time:.2f} seconds (Attempt {attempt}/{max_attempts})..."
            )
            time.sleep(sleep_time)
            delay *= factor

def run_pipeline():
    logger.info("=" * 60)
    logger.info("STARTING SCIENCE BLOG AUTOMATION PIPELINE")
    logger.info("=" * 60)

    # 1. 설정 유효성 검증
    if not Config.validate():
        logger.error("Configuration validation failed. Exiting.")
        sys.exit(1)

    # 2. Google OAuth Credentials 생성
    logger.info("Initializing Google API Credentials...")
    try:
        credentials = Config.get_google_credentials()
    except Exception as e:
        logger.error(f"Failed to generate Google credentials: {e}")
        sys.exit(1)

    # 3. Google Sheets 연동 및 정보 획득
    logger.info("Connecting to Google Sheets...")
    try:
        sheets_client = GoogleSheetsClient(credentials, Config.GOOGLE_SHEETS_ID)
        
        # 설정된 커스텀 시스템 프롬프트 로드
        system_prompt = sheets_client.get_system_prompt()
        logger.info(f"Loaded custom System Prompt (Length: {len(system_prompt)})")
        
        # 기 발행된 중복 방지 타이틀 리스트 확보
        published_topics = sheets_client.get_published_topics()
        logger.info(f"Loaded {len(published_topics)} already published topic(s) to lock duplication.")
        
    except Exception as e:
        logger.error(f"Failed to communicate with Google Sheets: {e}")
        sys.exit(1)

    # 4. Gemini 클라이언트 세팅 및 7대 정책 기반 주제 도출
    logger.info("Initializing Gemini Client...")
    try:
        gemini_client = GeminiClient(
            Config.GEMINI_API_KEY,
            topic_model=Config.GEMINI_TOPIC_MODEL,
            post_model=Config.GEMINI_POST_MODEL
        )
        
        # 주제 도출 단계 (지수 백오프 적용)
        topic_plan = retry_with_backoff(
            gemini_client.select_topic, 
            system_prompt, 
            published_topics,
            max_attempts=4,
            initial_delay=3.0
        )
        
        post_title = topic_plan.get("title")
        keywords = topic_plan.get("keywords", ["과학", "트렌드"])
        logger.info(f"Topic Selected Successfully: '{post_title}'")
        
    except Exception as e:
        logger.error(f"Failed to select topic via Gemini API: {e}")
        sys.exit(1)

    # 5. 본문 내용 작성 (HTML 본문 및 이미지 태그)
    logger.info("Generating premium science essay HTML body...")
    try:
        # 본문 작성 단계 (지수 백오프 적용)
        raw_html_content = retry_with_backoff(
            gemini_client.generate_blog_post,
            system_prompt,
            topic_plan,
            max_attempts=4,
            initial_delay=4.0
        )
    except Exception as e:
        logger.error(f"Failed to generate blog content via Gemini: {e}")
        sys.exit(1)

    # 6. 이미지 생성 및 로컬 WebP 최적화
    logger.info("Processing image prompt tags and converting to WebP...")
    image_processor = ImageProcessor()
    
    # 이미지 생성 및 WebP 인코딩 단계 (개별 이미지 생성 내부에서 백오프 제어)
    try:
        # 이미지 생성을 안전하게 감싸서 호출할 수 있도록 람다 정의
        def process_images_safe():
            return image_processor.process_and_replace_tags(raw_html_content, gemini_client)
            
        content_with_tags, processed_images = retry_with_backoff(
            process_images_safe,
            max_attempts=3,
            initial_delay=5.0
        )
        logger.info(f"Successfully processed {len(processed_images)} visual images.")
        
    except Exception as e:
        logger.error(f"Critical error during image generation/WebP conversion: {e}")
        sys.exit(1)

    # 7. Git Orphan Branch 격리 호스팅 작업
    logger.info("Initializing Git Manager for WebP image hosting...")
    git_manager = GitManager(
        github_token=Config.GITHUB_TOKEN,
        github_repo=Config.GITHUB_REPOSITORY,
        branch_name=Config.IMAGE_BRANCH
    )

    try:
        # 이미지 브랜치 독립 체크아웃
        git_manager.checkout_image_branch()
        
        # 이미지 매핑 동기화
        git_manager.sync_new_images(processed_images)
        
        # 깃 충돌 방지(Rebase loop) 탑재 푸시
        push_success = git_manager.commit_and_push_with_retry(max_retries=5, delay=5)
        if not push_success:
            raise RuntimeError("Git push for images failed after multiple conflict resolution retries.")
            
    except Exception as e:
        logger.error(f"Git hosting operation failed: {e}")
        git_manager.cleanup()
        sys.exit(1)

    # 8. Blogger Client 초기화 및 태그 CDN 치환
    logger.info("Preparing Blogger publisher...")
    try:
        blogger_client = BloggerClient(credentials, Config.BLOG_ID)
        
        # 본문의 [IMAGE_PROMPT: ...] 태그를 실제 업로드된 Pages CDN URL 기반 이미지블록으로 치환
        final_html_content = blogger_client.embed_premium_images(
            content_with_tags, 
            processed_images, 
            git_manager
        )
        
        # Blogger 글 최종 발행
        published_url = retry_with_backoff(
            blogger_client.publish_post,
            post_title,
            final_html_content,
            keywords,
            max_attempts=3,
            initial_delay=3.0
        )
        
    except Exception as e:
        logger.error(f"Failed to publish post to Blogger: {e}")
        git_manager.cleanup()
        sys.exit(1)

    # 9. Google Sheets 로그기록에 적재하여 DB 업데이트
    logger.info("Logging publication to Google Sheets Database...")
    try:
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheets_client.append_log(
            title=post_title,
            url=published_url,
            published_at=current_time_str
        )
        logger.info("Google Sheets log update complete.")
    except Exception as e:
        logger.error(f"Failed to update Google Sheet logs (Post published successfully though!): {e}")

    # 10. 자원 정리 및 최종 성공
    git_manager.cleanup()
    logger.info("=" * 60)
    logger.info("PIPELINE EXECUTED SUCCESSFULLY")
    logger.info(f"New Post: '{post_title}' is live at {published_url}")
    logger.info("=" * 60)

if __name__ == "__main__":
    run_pipeline()
