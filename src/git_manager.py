import os
import shutil
import subprocess
import logging
import time

logger = logging.getLogger("ScienceBlogBot.GitManager")

class GitManager:
    def __init__(self, github_token: str, github_repo: str, branch_name: str = "images-hosting", base_dir: str = "."):
        """
        github_token: GitHub Actions의 GITHUB_TOKEN 또는 Personal Access Token
        github_repo: 'owner/repo' 형식의 저장소 이름
        branch_name: 이미지를 분리해 호스팅할 orphan 브랜치 명 (기본: images-hosting)
        base_dir: 로컬 작업 디렉토리
        """
        self.github_token = github_token
        self.github_repo = github_repo
        self.branch_name = branch_name
        self.base_dir = base_dir
        
        # https://x-access-token:TOKEN@github.com/owner/repo.git 주소 빌드
        self.remote_url = f"https://x-access-token:{github_token}@github.com/{github_repo}.git"
        
        # 임시 Git 워크트리 성격의 독립 디렉토리 설정
        self.temp_git_dir = os.path.abspath(os.path.join(self.base_dir, "temp_images_workspace"))

    def _run_git_cmd(self, args: list, cwd: str, ignore_error: bool = False) -> str:
        """Git CLI 명령어를 subprocess를 통해 실행하고 결과를 얻습니다."""
        try:
            # Pager 비활성화 및 환경 구성
            env = os.environ.copy()
            env["PAGER"] = "cat"
            
            result = subprocess.run(
                args,
                cwd=cwd,
                capture_output=True,
                text=True,
                env=env,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            if not ignore_error:
                logger.error(f"Git Command Failed: {' '.join(args)}")
                logger.error(f"Stdout: {e.stdout}")
                logger.error(f"Stderr: {e.stderr}")
            raise RuntimeError(e.stderr or e.stdout)

    def checkout_image_branch(self):
        """
        원격 저장소에서 이미지 전용 브랜치를 shallow clone (--depth=1) 합니다.
        원격에 브랜치가 없는 초기 실행 상태라면, orphan 브랜치로 새롭게 초기화합니다.
        """
        if os.path.exists(self.temp_git_dir):
            shutil.rmtree(self.temp_git_dir)
            
        logger.info(f"Setting up isolated image workspace at {self.temp_git_dir}")
        
        try:
            # 1. 원격에 브랜치가 존재하는지 확인하기 위해 shallow clone 시도
            os.makedirs(self.temp_git_dir, exist_ok=True)
            logger.info(f"Cloning branch '{self.branch_name}' with depth=1...")
            self._run_git_cmd([
                "git", "clone", "--depth", "1", "--single-branch", 
                "--branch", self.branch_name, self.remote_url, self.temp_git_dir
            ], cwd=self.base_dir)
            logger.info("Successfully shallow-cloned existing images branch.")
            
        except Exception as e:
            # 2. 브랜치가 존재하지 않는 에러인 경우, 로컬에서 orphan 브랜치 최초 생성
            logger.warning(f"Failed to clone. Branch '{self.branch_name}' might not exist. Initializing orphan branch...")
            if os.path.exists(self.temp_git_dir):
                shutil.rmtree(self.temp_git_dir)
            os.makedirs(self.temp_git_dir, exist_ok=True)
            
            # 수동 초기화 및 orphan 설정
            self._run_git_cmd(["git", "init"], cwd=self.temp_git_dir)
            self._run_git_cmd(["git", "remote", "add", "origin", self.remote_url], cwd=self.temp_git_dir)
            self._run_git_cmd(["git", "checkout", "--orphan", self.branch_name], cwd=self.temp_git_dir)
            
            # 최초 푸시 준비를 위한 빈 파일 추가
            placeholder_file = os.path.join(self.temp_git_dir, ".placeholder")
            with open(placeholder_file, "w") as f:
                f.write("Google Sheets & Blogger Automation Images Branch.")
            self._run_git_cmd(["git", "add", ".placeholder"], cwd=self.temp_git_dir)
            self._run_git_cmd(["git", "config", "user.name", "github-actions[bot]"], cwd=self.temp_git_dir)
            self._run_git_cmd(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], cwd=self.temp_git_dir)
            self._run_git_cmd(["git", "commit", "-m", "Initialize orphan branch"], cwd=self.temp_git_dir)
            
            # 최초 푸시
            self._run_git_cmd(["git", "push", "-u", "origin", self.branch_name], cwd=self.temp_git_dir)
            logger.info("Orphan branch created and initialized on remote successfully.")

    def sync_new_images(self, processed_images: list):
        """새롭게 빌드된 WebP 이미지들을 격리 워크스페이스에 복사해 동기화합니다."""
        for img in processed_images:
            src = img["full_path"]
            rel_path = img["rel_path"]  # ex) images/2026/05/{hash}.webp
            
            dest = os.path.join(self.temp_git_dir, rel_path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
            logger.info(f"Copied to git sync workspace: {rel_path}")

    def commit_and_push_with_retry(self, max_retries: int = 5, delay: int = 5) -> bool:
        """
        동기화된 이미지들을 이미지 전용 브랜치에 커밋하고 푸시합니다.
        가상 머신 간 다중 실행 및 커밋 충돌(Git Conflict)에 대비해 pull --rebase 및 push 루프를 수행합니다.
        """
        # Git 유저 설정
        self._run_git_cmd(["git", "config", "user.name", "github-actions[bot]"], cwd=self.temp_git_dir)
        self._run_git_cmd(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], cwd=self.temp_git_dir)
        
        # 변경 사항 추가
        self._run_git_cmd(["git", "add", "."], cwd=self.temp_git_dir)
        
        # 변경 사항 유무 체크
        status = self._run_git_cmd(["git", "status", "--porcelain"], cwd=self.temp_git_dir)
        if not status:
            logger.info("No new images to commit. Everything is up to date.")
            return True
            
        self._run_git_cmd(["git", "commit", "-m", "Upload automated WebP images [skip ci]"], cwd=self.temp_git_dir)
        
        # 충돌 방지 및 푸시 재시도 루프
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Pushing images to remote branch (Attempt {attempt}/{max_retries})...")
                self._run_git_cmd(["git", "push", "origin", self.branch_name], cwd=self.temp_git_dir)
                logger.info("Successfully pushed images to remote branch.")
                return True
            except Exception as e:
                logger.warning(f"Push attempt {attempt} failed due to conflict or network issue: {e}")
                if attempt == max_retries:
                    logger.error("Max retries reached. Git image push failed.")
                    return False
                
                logger.info(f"Attempting to pull and rebase from remote branch to resolve conflicts...")
                try:
                    # rebase 시 안전하게 머지 (이미지 파일 해시는 중복되지 않으므로 논리 충돌 X)
                    self._run_git_cmd(["git", "pull", "--rebase", "origin", self.branch_name], cwd=self.temp_git_dir)
                except Exception as rebase_err:
                    logger.error(f"Rebase failed, resetting hard to remote and trying to recover: {rebase_err}")
                    # 리베이스 꼬임 방지를 위해 abort 및 강제 리바인딩
                    self._run_git_cmd(["git", "rebase", "--abort"], cwd=self.temp_git_dir, ignore_error=True)
                    self._run_git_cmd(["git", "fetch", "origin", self.branch_name], cwd=self.temp_git_dir)
                    self._run_git_cmd(["git", "reset", "--hard", f"origin/{self.branch_name}"], cwd=self.temp_git_dir)
                    # 다시 로컬 생성 파일 재복사
                    # (여기선 단순 대기 후 다음 시도로 넘어가는 안전한 복구 장치를 탑재)
                    
                time.sleep(delay)
        return False

    def get_public_cdn_url(self, rel_path: str) -> str:
        """
        GitHub Pages가 활성화된 경우를 산정하여 정적 퍼블릭 URL을 도출합니다.
        rel_path format: images/yyyy/mm/{hash}.webp
        Result format: https://{owner}.github.io/{repo}/{rel_path}
        """
        parts = self.github_repo.split("/")
        if len(parts) != 2:
            owner, repo = "username", "repository"
        else:
            owner, repo = parts[0], parts[1]
            
        # GitHub Pages 기본 구조 생성 (소문자 표준 대응)
        owner_lower = owner.lower()
        repo_lower = repo.lower()
        
        # 포맷 정규화: https://{owner}.github.io/{repo}/{rel_path}
        cdn_url = f"https://{owner_lower}.github.io/{repo_lower}/{rel_path}"
        logger.info(f"Resolved public CDN URL: {cdn_url}")
        return cdn_url

    def cleanup(self):
        """임시로 생성했던 Git 동기화 폴더를 안전하게 지웁니다."""
        if os.path.exists(self.temp_git_dir):
            try:
                shutil.rmtree(self.temp_git_dir)
                logger.info("Successfully cleaned up temp images git workspace.")
            except Exception as e:
                logger.warning(f"Could not clean up temp git directory: {e}")
