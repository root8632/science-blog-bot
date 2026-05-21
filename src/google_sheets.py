import logging
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger("ScienceBlogBot.GoogleSheets")

class GoogleSheetsClient:
    def __init__(self, credentials, spreadsheet_id):
        self.service = build('sheets', 'v4', credentials=credentials)
        self.spreadsheet_id = spreadsheet_id
        self._ensure_sheets_exist()

    def _ensure_sheets_exist(self):
        """필요한 시트(설정, 로그)가 스프레드시트에 존재하는지 확인하고, 없으면 생성합니다."""
        try:
            spreadsheet = self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            ).execute()
            
            existing_sheets = [sheet['properties']['title'] for sheet in spreadsheet.get('sheets', [])]
            
            requests = []
            
            # '설정' 시트 확인 및 추가
            if '설정' not in existing_sheets:
                requests.append({
                    'addSheet': {
                        'properties': {
                            'title': '설정'
                        }
                    }
                })
                
            # '로그' 시트 확인 및 추가
            if '로그' not in existing_sheets:
                requests.append({
                    'addSheet': {
                        'properties': {
                            'title': '로그'
                        }
                    }
                })
                
            if requests:
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={'requests': requests}
                ).execute()
                logger.info("Successfully created missing sheets: 설정, 로그")
                
                # 기본 구조 삽입
                if '설정' not in existing_sheets:
                    # 헤더 및 기본 설정 추가
                    self.service.spreadsheets().values().update(
                        spreadsheetId=self.spreadsheet_id,
                        range='설정!A1:B2',
                        valueInputOption='RAW',
                        body={
                            'values': [
                                ['Key', 'Value'],
                                ['System Prompt', '당신은 대중을 사로잡는 프리미엄 과학 에디터이자 전문 블로거입니다. 일상 속에 숨겨진 과학적 사실을 깊이 있으면서도 흥미진진하게 풀어내며, 가독성이 높고 풍부한 HTML 포맷의 지식을 전달합니다.']
                            ]
                        }
                    ).execute()
                    
                if '로그' not in existing_sheets:
                    # 로그 헤더 추가
                    self.service.spreadsheets().values().update(
                        spreadsheetId=self.spreadsheet_id,
                        range='로그!A1:C1',
                        valueInputOption='RAW',
                        body={
                            'values': [
                                ['Title', 'URL', 'Published At']
                            ]
                        }
                    ).execute()
                    
        except HttpError as e:
            logger.error(f"Error ensuring sheets exist: {e}")
            raise

    def get_system_prompt(self) -> str:
        """'설정' 시트에서 'System Prompt' 키에 대응하는 값을 가져옵니다."""
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range='설정!A:B'
            ).execute()
            
            rows = result.get('values', [])
            if not rows:
                logger.warning("Settings sheet is empty. Using default system prompt.")
                return self._get_default_prompt()
                
            for row in rows:
                if len(row) >= 2 and row[0].strip() == 'System Prompt':
                    return row[1].strip()
                    
            logger.warning("'System Prompt' key not found in settings sheet. Using default.")
            return self._get_default_prompt()
            
        except HttpError as e:
            logger.error(f"Error fetching system prompt from Google Sheet: {e}")
            return self._get_default_prompt()

    def get_published_topics(self) -> list[str]:
        """'로그' 시트에서 이미 발행된 글의 주제(Title) 목록을 중복 방지용으로 수집합니다."""
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range='로그!A2:A'
            ).execute()
            
            rows = result.get('values', [])
            # A열에서 가져온 타이틀들의 리스트 반환
            return [row[0].strip() for row in rows if row]
        except HttpError as e:
            logger.error(f"Error fetching published topics: {e}")
            return []

    def append_log(self, title: str, url: str, published_at: str):
        """새로 발행된 글을 '로그' 시트에 기록하여 중복 방지 DB를 최신화합니다."""
        try:
            body = {
                'values': [[title, url, published_at]]
            }
            self.service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range='로그!A:C',
                valueInputOption='RAW',
                insertDataOption='INSERT_ROWS',
                body=body
            ).execute()
            logger.info(f"Logged published post in Google Sheet: '{title}'")
        except HttpError as e:
            logger.error(f"Error logging published post: {e}")
            raise

    def _get_default_prompt(self) -> str:
        """시트 통신 실패 시 백업용으로 사용할 기본 프리미엄 과학 블로거 시스템 프롬프트입니다."""
        return (
            "당신은 전 세계의 흥미롭고 신비로운 일상 현상을 예리하게 분석하는 최고의 과학 블로거입니다.\n"
            "물리학, 화학, 생물학 등의 기초 과학부터 현대 첨단 공학 기술까지, 복잡한 개념을 일반 대중이\n"
            "직관적으로 이해하고 탄성을 자아낼 수 있도록 스토리가 풍부하고 논리 정연한 HTML 블로그 글을 작성합니다.\n"
            "모든 본문에는 유익한 정보와 신뢰성 높은 출처, 과학적 수식이 조화롭게 어우러져야 합니다."
        )
