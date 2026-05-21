import sys
from google_auth_oauthlib.flow import InstalledAppFlow

# 구글 시트 쓰기 및 Blogger 포스트 발행을 위한 필수 권한 범위 (Scopes)
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/blogger"
]

def main():
    print("=" * 70)
    print("  GOOGLE OAUTH2 REFRESH TOKEN GENERATOR FOR SCIENCE BLOG BOT")
    print("=" * 70)
    print("이 스크립트는 로컬 PC에서 1회만 실행하며, 구글 인증 브라우저 창을 띄워")
    print("GitHub Secrets에 삽입할 GOOGLE_REFRESH_TOKEN을 안전하게 발급받습니다.\n")
    print("선행 조건: Google Cloud Console에서 '데스크톱 앱(Desktop App)' 유형의")
    print("OAuth 2.0 클라이언트 ID를 만들고 대기 중이어야 합니다.\n")
    
    try:
        client_id = input("👉 Google OAuth Client ID를 입력하세요: ").strip()
        client_secret = input("👉 Google OAuth Client Secret을 입력하세요: ").strip()
        
        if not client_id or not client_secret:
            print("\n❌ 에러: ID와 Secret은 필수 입력값입니다. 종료합니다.")
            sys.exit(1)
            
        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        
        # OAuth Flow 시작
        flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
        
        # 로컬 서버를 가동해 인증 콜백 접수
        credentials = flow.run_local_server(
            port=0,
            authorization_prompt_message="브라우저에서 로그인을 완료하면 자동으로 닫힙니다.",
            success_message="인증에 성공했습니다! 콘솔 창의 토큰 값을 확인해 주세요."
        )
        
        print("\n" + "=" * 70)
        print("🎉 축하합니다! 구글 API 연동 인증이 성공적으로 완료되었습니다.")
        print("아래의 키와 토큰을 그대로 복사하여 GitHub 저장소 -> Settings -> Secrets -> Actions에")
        print("각각 New Repository Secret으로 고스란히 추가해 주세요.")
        print("=" * 70)
        print(f"🔑 [GOOGLE_CLIENT_ID] (그대로 복사)\n{client_id}\n")
        print(f"🔑 [GOOGLE_CLIENT_SECRET] (그대로 복사)\n{client_secret}\n")
        print(f"🔑 [GOOGLE_REFRESH_TOKEN] (⭐가장 중요: 전체 복사)\n{credentials.refresh_token}")
        print("=" * 70)
        
    except KeyboardInterrupt:
        print("\n사용자에 의해 인증 작업이 강제 중단되었습니다.")
    except Exception as e:
        print(f"\n❌ 인증 중 에러가 발생했습니다: {e}")
        print("구글 클라우드 콘솔의 OAuth 동의 화면(Consent Screen)에 '테스트 사용자'로")
        print("본인의 구글 계정이 정상 등록되어 있는지 확인해 보시기 바랍니다.")

if __name__ == "__main__":
    main()
