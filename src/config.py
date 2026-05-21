import os
import sys
import logging
from google.oauth2.credentials import Credentials

# 로깅 기본 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("ScienceBlogBot.Config")

class Config:
    # Gemini API 설정
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GEMINI_TOPIC_MODEL = os.getenv("GEMINI_TOPIC_MODEL", "gemini-2.5-flash")
    GEMINI_POST_MODEL = os.getenv("GEMINI_POST_MODEL", "gemini-3.5-flash")
    
    # Google API 설정
    GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
    BLOG_ID = os.getenv("BLOG_ID")
    
    # OAuth2 Credentials
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")
    
    # GitHub 및 이미지 호스팅 설정
    GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "user/repo")  # format: "owner/repo"
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # GitHub Actions에서 제공하거나 PAT 사용
    IMAGE_BRANCH = os.getenv("IMAGE_BRANCH", "images-hosting")
    
    @classmethod
    def validate(cls):
        """필수 환경 변수들이 제대로 채워졌는지 검증합니다."""
        missing = []
        if not cls.GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")
        if not cls.GOOGLE_SHEETS_ID:
            missing.append("GOOGLE_SHEETS_ID")
        if not cls.BLOG_ID:
            missing.append("BLOG_ID")
        if not cls.GOOGLE_CLIENT_ID:
            missing.append("GOOGLE_CLIENT_ID")
        if not cls.GOOGLE_CLIENT_SECRET:
            missing.append("GOOGLE_CLIENT_SECRET")
        if not cls.GOOGLE_REFRESH_TOKEN:
            missing.append("GOOGLE_REFRESH_TOKEN")
            
        if missing:
            logger.error(f"Missing required environment variables: {', '.join(missing)}")
            return False
        return True

    @classmethod
    def get_google_credentials(cls):
        """OAuth2 Client ID, Client Secret, Refresh Token 기반 Credentials 객체를 생성합니다."""
        if not cls.GOOGLE_CLIENT_ID or not cls.GOOGLE_CLIENT_SECRET or not cls.GOOGLE_REFRESH_TOKEN:
            raise ValueError("Google OAuth2 credentials are not fully configured.")
            
        return Credentials(
            token=None,
            refresh_token=cls.GOOGLE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=cls.GOOGLE_CLIENT_ID,
            client_secret=cls.GOOGLE_CLIENT_SECRET
        )
