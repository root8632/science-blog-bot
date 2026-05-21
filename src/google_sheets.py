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
                        range='설정!A1:B3',
                        valueInputOption='RAW',
                        body={
                            'values': [
                                ['Key', 'Value'],
                                ['System Prompt', '당신은 대중을 사로잡는 프리미엄 과학 에디터이자 전문 블로거입니다. 일상 속에 숨겨진 과학적 사실을 깊이 있으면서도 흥미진진하게 풀어내며, 가독성이 높고 풍부한 HTML 포맷의 지식을 전달합니다.'],
                                ['Style Guide', self._get_default_style_guide()]
                            ]
                        }
                    ).execute()
                    
                if '로그' not in existing_sheets:
                    # 로그 헤더 추가
                    self.service.spreadsheets().values().update(
                        spreadsheetId=self.spreadsheet_id,
                        range='로그!A1:E1',
                        valueInputOption='RAW',
                        body={
                            'values': [
                                ['Title', 'URL', 'Published At', 'System Prompt', 'Style Guide Source']
                            ]
                        }
                    ).execute()
            
            # 기존 '설정' 시트가 존재하는데 'Style Guide' 키만 누락된 경우를 위한 자동 보완 로직
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
                for r in rows:
                    if r and r[0].strip() == 'Style Guide':
                        has_style_guide = True
                        break
                        
                if not has_style_guide:
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
                return self._get_default_prompt()
                
            for row in rows:
                if len(row) >= 2 and row[0].strip() == 'System Prompt':
                    return row[1].strip()
                    
            logger.warning("'System Prompt' key not found in settings sheet. Using default.")
            return self._get_default_prompt()
            
        except HttpError as e:
            logger.error(f"Error fetching system prompt from Google Sheet: {e}")
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
                return self._get_default_style_guide()
                
            for row in rows:
                if len(row) >= 2 and row[0].strip() == 'Style Guide':
                    return row[1].strip()
                    
            logger.warning("'Style Guide' key not found in settings sheet. Using default.")
            return self._get_default_style_guide()
            
        except HttpError as e:
            logger.error(f"Error fetching style guide from Google Sheet: {e}")
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

    def append_log(self, title: str, url: str, published_at: str, system_prompt: str = "", style_guide_source: str = ""):
        """새로 발행된 글을 '로그' 시트에 기록하여 중복 방지 DB를 최신화합니다."""
        try:
            # 기존 헤더를 불러와 검사하여, 필요한 경우 컬럼 확장 (하위 호환 마이그레이션)
            try:
                header_res = self.service.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id,
                    range='로그!A1:E1'
                ).execute()
                headers = header_res.get('values', [[]])[0]
            except Exception:
                headers = []
                
            if len(headers) < 5:
                logger.info("Migrating Google Sheets '로그' header for tracking Prompt & Style Guide Source...")
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range='로그!A1:E1',
                    valueInputOption='RAW',
                    body={
                        'values': [['Title', 'URL', 'Published At', 'System Prompt', 'Style Guide Source']]
                    }
                ).execute()
                
            body = {
                'values': [[title, url, published_at, system_prompt, style_guide_source]]
            }
            self.service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range='로그!A:E',
                valueInputOption='RAW',
                insertDataOption='INSERT_ROWS',
                body=body
            ).execute()
            logger.info(f"Logged published post in Google Sheet: '{title}' with custom configurations info.")
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

    def _get_default_style_guide(self) -> str:
        """시트 통신 실패 시 백업용 및 최초 초기화용으로 사용할 기본 물리적 서식 요구사항 가이드입니다."""
        return (
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
