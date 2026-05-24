import logging
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger("ScienceBlogBot.GoogleSheets")

class GoogleSheetsClient:
    def __init__(self, credentials, spreadsheet_id):
        self.service = build('sheets', 'v4', credentials=credentials)
        self.spreadsheet_id = spreadsheet_id
        self.last_system_prompt_source = "Local"
        self.last_style_guide_source = "Local"
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
                        range='설정!A1:B3',
                        valueInputOption='RAW',
                        body={
                            'values': [
                                ['Key', 'Value'],
                                ['System Prompt', self._get_default_prompt()],
                                ['Style Guide', self._get_default_style_guide()]
                            ]
                        }
                    ).execute()
                    
                if '로그' not in existing_sheets:
                    # 로그 헤더 추가 (주제 선정 모델 및 본문 작성 모델 추적 포함)
                    self.service.spreadsheets().values().update(
                        spreadsheetId=self.spreadsheet_id,
                        range='로그!A1:G1',
                        valueInputOption='RAW',
                        body={
                            'values': [
                                ['Title', 'URL', 'Published At', 'System Prompt', 'Style Guide Source', 'Topic Model', 'Post Model']
                            ]
                        }
                    ).execute()
            
            # 기존 '설정' 시트 마이그레이션 및 자동 보완 로직
            if '설정' in existing_sheets:
                try:
                    res = self.service.spreadsheets().values().get(
                        spreadsheetId=self.spreadsheet_id,
                        range='설정!A:B'
                    ).execute()
                    rows = res.get('values', [])
                except Exception:
                    rows = []
                
                has_style_guide = False
                needs_tech_migration = False
                
                for idx, r in enumerate(rows):
                    if r:
                        key = r[0].strip()
                        if key == 'Style Guide':
                            has_style_guide = True
                        elif key == 'System Prompt':
                            # 기존 과학 블로거 텍스트가 감지될 경우 마이그레이션 대상 지정
                            if len(r) >= 2 and ("과학 에디터" in r[1] or "과학적 사실" in r[1] or "물리학" in r[1]):
                                needs_tech_migration = True
                
                if needs_tech_migration:
                    logger.info("Detected legacy Science Blog settings. Migrating settings to IT/Programming Tech Blogger format...")
                    self.service.spreadsheets().values().update(
                        spreadsheetId=self.spreadsheet_id,
                        range='설정!A2:B3',
                        valueInputOption='RAW',
                        body={
                            'values': [
                                ['System Prompt', self._get_default_prompt()],
                                ['Style Guide', self._get_default_style_guide()]
                            ]
                        }
                    ).execute()
                    logger.info("Successfully migrated 'System Prompt' and 'Style Guide' to IT Tech Blogger format.")
                    
                elif not has_style_guide:
                    next_row = len(rows) + 1
                    self.service.spreadsheets().values().update(
                        spreadsheetId=self.spreadsheet_id,
                        range=f'설정!A{next_row}:B{next_row}',
                        valueInputOption='RAW',
                        body={
                            'values': [['Style Guide', self._get_default_style_guide()]]
                        }
                    ).execute()
                    logger.info("Successfully auto-initialized 'Style Guide' key in existing 설정 sheet.")
                    
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
                self.last_system_prompt_source = "Local"
                return self._get_default_prompt()
                
            for row in rows:
                if len(row) >= 2 and row[0].strip() == 'System Prompt':
                    self.last_system_prompt_source = "GoogleSheet"
                    return row[1].strip()
                    
            logger.warning("'System Prompt' key not found in settings sheet. Using default.")
            self.last_system_prompt_source = "Local"
            return self._get_default_prompt()
            
        except HttpError as e:
            logger.error(f"Error fetching system prompt from Google Sheet: {e}")
            self.last_system_prompt_source = "Local"
            return self._get_default_prompt()

    def get_style_guide(self) -> str:
        """'설정' 시트에서 'Style Guide' 키에 대응하는 값을 가져옵니다."""
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range='설정!A:B'
            ).execute()
            
            rows = result.get('values', [])
            if not rows:
                logger.warning("Settings sheet is empty. Using default style guide.")
                self.last_style_guide_source = "Local"
                return self._get_default_style_guide()
                
            for row in rows:
                if len(row) >= 2 and row[0].strip() == 'Style Guide':
                    self.last_style_guide_source = "GoogleSheet"
                    return row[1].strip()
                    
            logger.warning("'Style Guide' key not found in settings sheet. Using default.")
            self.last_style_guide_source = "Local"
            return self._get_default_style_guide()
            
        except HttpError as e:
            logger.error(f"Error fetching style guide from Google Sheet: {e}")
            self.last_style_guide_source = "Local"
            return self._get_default_style_guide()

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

    def append_log(self, title: str, url: str, published_at: str, system_prompt: str = "", style_guide_source: str = "", topic_model: str = "", post_model: str = ""):
        """새로 발행된 글을 '로그' 시트에 기록하여 중복 방지 DB를 최신화합니다."""
        try:
            # 기존 헤더를 불러와 검사하여, 필요한 경우 컬럼 확장 (하위 호환 마이그레이션)
            try:
                header_res = self.service.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id,
                    range='로그!A1:G1'
                ).execute()
                headers = header_res.get('values', [[]])[0]
            except Exception:
                headers = []
                
            if len(headers) < 7:
                logger.info("Migrating Google Sheets '로그' header for tracking Models, Prompt & Style Guide...")
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range='로그!A1:G1',
                    valueInputOption='RAW',
                    body={
                        'values': [['Title', 'URL', 'Published At', 'System Prompt', 'Style Guide Source', 'Topic Model', 'Post Model']]
                    }
                ).execute()
                
            body = {
                'values': [[title, url, published_at, system_prompt, style_guide_source, topic_model, post_model]]
            }
            self.service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range='로그!A:G',
                valueInputOption='RAW',
                insertDataOption='INSERT_ROWS',
                body=body
            ).execute()
            logger.info(f"Logged published post in Google Sheet: '{title}' with custom configurations info.")
        except HttpError as e:
            logger.error(f"Error logging published post: {e}")
            raise

    def _get_default_prompt(self) -> str:
        """시트 통신 실패 시 백업용으로 사용할 기본 프리미엄 프로그래밍 테크 에디터 시스템 프롬프트입니다."""
        return (
            "당신은 핵심만 전달하는 프리미엄 테크 에디터입니다. "
            "업무 자동화, 데이터 크롤링, 코딩 스킬 등을 이해하기 쉽게 풀어내되, "
            "불필요한 장황설 없이 핵심 설명과 코드 예제 위주로 간결하게 작성합니다.\n\n"
            "문체는 부드러운 경어체('~합니다', '~시죠?')를 사용하십시오. "
            "글자수를 채우기 위한 서론이나 반복적 설명은 절대 하지 마십시오. "
            "독자가 '이걸 왜 배워야 하지?'를 자연스럽게 이해할 수 있는 짧은 실무 예시(예: '매일 수동으로 1시간 걸리던 엑셀 "
            "업무를 10줄 코드로 해결했다면?')를 도입부에 2~3문장 이내로 넣으십시오.\n\n"
            "모든 한글 텍스트는 표준 한글 유니코드 범위 내에서만 작성되어야 합니다. "
            "시각적으로 유사한 일본어 가타카나를 한글 단어 내에 혼용하는 오류를 절대 범하지 마십시오."
        )

    def _get_default_style_guide(self) -> str:
        """시트 통신 실패 시 백업용 및 최초 초기화용으로 사용할 기본 테크 서식 요구사항 가이드입니다."""
        return (
            "[작성 및 서식 요구사항 (Strict Tech-Style Policy)]\n\n"
            "1. **HTML 형식 작성**: Blogger 본문에 바로 깔끔하게 삽입되도록 마크다운이 아닌 **순수 HTML 태그**로 작성하십시오.\n"
            "   - 대제목은 생략(Blogger의 Post Title이 됨)하고, 본문 내 소주제는 `<h2>`, `<h3>` 태그를 활용하십시오.\n"
            "   - 독자를 위한 중요 정보, 주의 사항, 유용한 팁은 반드시 `<blockquote>` 태그로 감싸서 작성하십시오. 이때 박스 시작 부분에 `<strong>주의:</strong>` 또는 `<strong>팁/참고:</strong>` 처럼 첫머리에 역할을 분명히 명시해 주십시오 (백엔드 스타일 트리거용).\n"
            "   - 강조 단어는 `<strong>` 또는 `<u>` 태그를 사용하십시오.\n\n"
            "2. **간결한 강의 스타일**: 글자수를 채우기 위한 장황설이나 반복적 설명은 절대 하지 마십시오. "
            "핵심 설명을 간결하게 전달하고, 코드 블록이 글의 주인공이 되도록 구성하십시오.\n\n"
            "3. **실무 코드 예제(Code Snippet) 포함**:\n"
            "   - 본문에 **실제 동작이 가능한 완성형 코딩 예제**를 1회 이상 포함하십시오.\n"
            "   - 코드 블록은 `<pre><code class='language-python'>` (또는 해당 언어 태그) 구조를 활용하십시오.\n"
            "   - 코드 내부에 초보자용 한글 주석(`# 설명`)을 필수로 달아주십시오.\n\n"
            "4. **이미지 배치**:\n"
            "   - 본문 중간 2곳에 아래 형식을 정확하게 삽입하십시오.\n"
            "     - `[IMAGE_PROMPT: {img_prompt1}]`\n"
            "     - `[IMAGE_PROMPT: {img_prompt2}]`\n"
            "   - 이미지 캡션은 2~3개 해시태그 형식으로만 작성하십시오. (예: `#python #web_scraping`)"
        )
