from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api 의 .env 를 가리킨다. 상대경로(".env")로 두면 실행 위치(cwd)에 따라
# 저장소 루트의 .env(DATABASE_URL 없음 → SQLite 로 조용히 빠짐)를 집어버릴 수 있어
# 이 파일 기준 절대경로로 고정한다.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    app_name: str = "가비 API"
    debug: bool = False
    # 로컬 개발은 SQLite, docker compose 에서는 PostgreSQL 주소로 바꾼다 (.env.example 참고)
    database_url: str = "sqlite:///./data/gabee.db"
    data_dir: str = "./data"
    cors_origins: str = "*"
    anthropic_api_key: str = ""
    llm_model: str = "claude-haiku-5-5"
    # DB 스키마 준비 상태 재점검 주기(초): 준비된 동안은 드물게, 준비 안 됐으면(자동 배포 진행 중) 자주
    schema_recheck_ready_seconds: int = 30
    schema_recheck_not_ready_seconds: int = 2
    schema_force_min_interval_seconds: float = 1  # /health/db 가 강제 재점검할 수 있는 최소 간격
    # 로컬 언어 모델(Ollama). 개인정보가 섞일 수 있는 글자는 외부 대신 여기로 보낸다
    local_llm_url: str = "http://localhost:11434"
    local_llm_model: str = "qwen2.5:7b"
    local_llm_timeout: float = 120.0
    # TypeSafe Jev — 정해진 보기 중 고르기·예/아니오 판단. 가린 글자만 보낸다
    typesafe_api_key: str = ""
    jev_model: str = "jev-latest"
    jev_timeout: float = 15.0
    # 얼굴 찾기 모델(YuNet·SFace) 폴더. 비우면 DATA_DIR/models/faces. 모델이 없으면 얼굴 찾기를 건너뛴다
    face_model_dir: str = ""
    # 원본 파일(가리기 전)을 그대로 보관하는 폴더. 비우면 DATA_DIR/raw. 접근을 제한해야 하는 곳이라 서버만 읽는다
    raw_dir: str = ""
    # 글자 없는 사진 설명(Ollama 이미지 모델). 사진은 서버 밖으로 나가지 않는다
    caption_enabled: bool = True
    caption_model: str = "qwen2.5vl:3b"
    caption_timeout: float = 180.0
    ollama_keep_alive: str = "30m"  # 모델을 메모리에 올려 두는 시간(처음 불러오는 데 1분쯤 걸린다)
    # 채팅(외부 Claude)이 근거로 읽을 수 있는 기록에 민감 기록(처방전·신분증·통장·인물 사진 등)을 넣을지
    chat_include_sensitive: bool = False

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")


settings = Settings()
