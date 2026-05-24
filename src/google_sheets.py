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
            "당신은 대중의 마음을 사로잡는 프리미엄 소프트웨어 엔지니어이자 전문 테크 에디터입니다. "
            "어렵고 복잡하게 느껴지는 개발 지식, 업무 자동화, 데이터 크롤링, 실무 코딩 스킬 등을 초보자도 쉽게 따라 할 수 있도록 "
            "원리부터 코드 한 줄까지 친절하고 흥미진진하게 풀어내는 역할을 수행합니다.\n\n"
            "모든 텍스트는 신뢰성 높으면서도 상냥하고 부드러운 경어체('~합니다', '~시죠?')로 작성해 주십시오. "
            "글을 작성할 때 단순히 코드만 나열하는 지루한 튜토리얼 방식을 배제하고, 반드시 '이 기술을 통해 우리가 일상이나 실무에서 "
            "겪는 비효율을 어떻게 획기적으로 개선할 수 있는지' 당사자 시점의 구체적인 상황극이나 가상 예시(예: '매일 아침 수동으로 1시간씩 "
            "걸리던 엑셀 복사-붙여넣기 업무를 단 15줄의 파이썬 코드로 해결한 순간...')를 한 단락 이상 구체적으로 포함하십시오. "
            "이를 통해 독자가 왜 이 코드를 배워야 하는지 강렬한 오리지널리티와 공감을 이끌어내야 합니다.\n\n"
            "모든 한글 텍스트는 표준 한글 유니코드 범위 내에서만 작성되어야 합니다. "
            "시각적으로 유사한 일본어 가타카나(예: 로, 카, 토, 에, 하 등의 유사 글자 오타)를 한글 단어 내에 혼용하는 오류를 절대 범하지 마십시오."
        )

    def _get_default_style_guide(self) -> str:
        """시트 통신 실패 시 백업용 및 최초 초기화용으로 사용할 기본 테크 서식 요구사항 가이드입니다."""
        return (
            "[작성 및 서식 요구사항 (Strict Tech-Style Policy)]\n\n"
            "1. **HTML 형식 작성**: Blogger 본문에 바로 깔끔하게 삽입되도록 마크다운이 아닌 **순수 HTML 태그**로 작성하십시오.\n"
            "   - 대제목은 생략(Blogger의 Post Title이 됨)하고, 본문 내 소주제는 `<h2>`, `<h3>` 태그를 활용하십시오.\n"
            "   - 핵심적인 개발 팁이나 주의해야 할 에러 로그 분석, 핵심 요약은 `<blockquote>` 태그로 감싸 세련된 프리미엄 블로그 스타일을 구축하십시오.\n"
            "   - 과학적/기술적 강조 단어는 `<strong>` 또는 `<u>` 태그로 강조하여 독자의 시선을 사로잡으십시오.\n\n"
            "2. **실무 코드 예제(Code Snippet) 포함**:\n"
            "   - 본문 중간 흐름상 가장 필요한 위치에 **실제 동작이 가능한 완성형 코딩 예제**를 1회 이상 반드시 포함하십시오.\n"
            "   - 코드 블록은 반드시 `<pre><code class='language-python'>` (또는 해당 코딩 언어 태그) 구조를 활용해 감싸주십시오.\n"
            "   - 소스코드 내부에는 초보자도 코드를 완독할 수 있도록 친절한 한글 주석(예: `# 1단계: 웹페이지 HTML 가져오기`)을 각 기능별로 꼼꼼하게 한 줄씩 필수로 달아주어야 합니다.\n\n"
            "3. **미니멀 해시태그 시작 자료 배치**:\n"
            "   - 본문 중간 흐름상 기술 묘사를 위한 시각 자료가 필요한 위치 2곳에 아래 형식을 **토씨 하나 틀리지 않고 정확하게** 작성해 삽입해야 합니다.\n"
            "     - 첫 번째 시각 자료 위치: `[IMAGE_PROMPT: {img_prompt1}]`\n"
            "     - 두 번째 시각 자료 위치: `[IMAGE_PROMPT: {img_prompt2}]`\n"
            "   - 이미지 하단 캡션 문구는 긴 문장 형태의 서술을 완전히 배제하고, 독자에게 세련된 트렌디함을 선사하도록 2~3개의 간결한 **해시태그 형식**으로만 생성하십시오. (예: `#python #web_scraping #beautifulsoup`)"
        )
