import os
import re
import hashlib
import logging
from datetime import datetime
from io import BytesIO
from PIL import Image

logger = logging.getLogger("ScienceBlogBot.ImageProcessor")

class ImageProcessor:
    def __init__(self, output_base_dir: str = "."):
        """
        output_base_dir: 이미지를 저장할 프로젝트 루트 또는 특정 디렉토리 경로
        """
        self.output_base_dir = output_base_dir

    def extract_prompts(self, content: str) -> list[str]:
        """포스트 본문에서 [IMAGE_PROMPT: 영어 묘사] 태그를 찾아 영어 묘사 문자열 리스트를 추출합니다."""
        # [IMAGE_PROMPT: ...] 형태 매칭
        pattern = r"\[IMAGE_PROMPT:\s*([^\]]+)\]"
        prompts = re.findall(pattern, content)
        return [p.strip() for p in prompts]

    def convert_to_webp(self, image_bytes: bytes, quality: int = 80) -> bytes:
        """Pillow를 사용해 이미지 바이트를 고효율 WebP 포맷으로 변환합니다."""
        try:
            img = Image.open(BytesIO(image_bytes))
            
            output_io = BytesIO()
            # WebP 포맷으로 저장 (손실 압축, 퀄리티 80~85% 수준으로 고화질 대비 최소 용량 확보)
            img.save(output_io, format="WEBP", quality=quality, method=6)  # method=6은 최고 압축 속도/품질 비율
            
            webp_bytes = output_io.getvalue()
            logger.info(f"Converted to WebP. Size reduced from {len(image_bytes)} to {len(webp_bytes)} bytes.")
            return webp_bytes
        except Exception as e:
            logger.error(f"Failed to convert image to WebP: {e}")
            raise

    def get_image_path_and_hash(self, webp_bytes: bytes) -> tuple[str, str]:
        """
        WebP 바이트 기반 SHA-256 해시를 산출하고, 
        요구사항인 `/images/yyyy/mm/{hash}.webp` 구조의 저장 상대 경로와 해시값을 생성합니다.
        """
        hasher = hashlib.sha256()
        hasher.update(webp_bytes)
        img_hash = hasher.hexdigest()[:16]  # 긴 해시값 중 고유성이 충분히 보장되는 앞 16자리 사용
        
        now = datetime.now()
        year_str = now.strftime("%Y")
        month_str = now.strftime("%m")
        
        # 상대 경로 생성: images/2026/05/{hash}.webp
        rel_dir = os.path.join("images", year_str, month_str)
        rel_path = os.path.join(rel_dir, f"{img_hash}.webp")
        
        return rel_path, img_hash

    def save_image(self, rel_path: str, webp_bytes: bytes) -> str:
        """변환된 WebP 이미지를 로컬 물리 디스크(지정 폴더 구조)에 저장하고 절대 경로를 반환합니다."""
        full_path = os.path.abspath(os.path.join(self.output_base_dir, rel_path))
        dir_path = os.path.dirname(full_path)
        
        # 디렉토리가 없으면 재귀적으로 생성
        os.makedirs(dir_path, exist_ok=True)
        
        with open(full_path, "wb") as f:
            f.write(webp_bytes)
            
        logger.info(f"Saved WebP image to: {full_path}")
        return full_path

    def process_and_replace_tags(self, content: str, gemini_client, topic_plan: dict = None) -> tuple[str, list[dict]]:
        """
        본문 내 모든 이미지 태그를 찾아 이미지를 생성하고, WebP 변환 및 저장을 거친 후 
        임시 해시 매핑 메타데이터 리스트를 작성하여 반환합니다.
        
        실제 CDN URL은 Git Push 이후에 확정되므로, 이 메서드에서는 
        생성된 로컬 상대 경로와 원본 태그 매핑 목록을 반환합니다.
        """
        prompts = self.extract_prompts(content)
        processed_images = []
        
        for idx, prompt in enumerate(prompts):
            try:
                # 1. Pixabay 이미지 다운로드
                raw_bytes = gemini_client.generate_image_by_prompt(prompt)
                if not raw_bytes:
                    logger.warning(f"Skipping image #{idx+1} for keyword '{prompt}' (no image bytes returned).")
                    continue
                
                # 2. WebP 변환 및 용량 최적화 (품질 82%)
                webp_bytes = self.convert_to_webp(raw_bytes, quality=82)
                
                # 3. yyyy/mm/{hash}.webp 경로 획득
                rel_path, img_hash = self.get_image_path_and_hash(webp_bytes)
                
                # 4. 파일 저장
                full_path = self.save_image(rel_path, webp_bytes)
                
                # 원본 태그 텍스트 재구성
                tag_to_replace = f"[IMAGE_PROMPT: {prompt}]"
                
                # 슬래시 경로 정규화 (윈도우 환경 대응 및 URL 포맷 호환을 위해 슬래시 '/'로 통일)
                url_friendly_rel_path = rel_path.replace("\\", "/")
                
                # 순서에 따라 topic_plan에서 미리 준비된 한글 캡션 가져오기
                caption = None
                if topic_plan:
                    if idx == 0:
                        caption = topic_plan.get("image_caption_1")
                    elif idx == 1:
                        caption = topic_plan.get("image_caption_2")
                
                if not caption:
                    caption = prompt
                
                processed_images.append({
                    "tag": tag_to_replace,
                    "prompt": prompt,
                    "caption": caption,
                    "rel_path": url_friendly_rel_path,
                    "full_path": full_path,
                    "hash": img_hash
                })
                
            except Exception as e:
                logger.error(f"Failed to process image #{idx+1} for prompt '{prompt[:30]}...': {e}")
                # 이미지 생성에 실패하더라도 글 발행 전체가 실패하지 않도록 일단 넘어가며 경고를 남김
                continue
                
        return content, processed_images
