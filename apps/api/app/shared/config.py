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

    # 로그인/JWT(PR 4-B). JWT_SECRET 은 환경변수(.env)로만 준다 — 코드·Git 에 넣지 않는다.
    # 비어 있으면: 로컬 SQLite 나 DEBUG=true 에서만 프로세스 임시 키를 쓴다(재시작하면 로그인이 풀림). PostgreSQL(공용·운영)에서는
    # 로그인/Bearer 인증이 503 auth_not_configured 가 된다(서버 시작·레거시 인증·다른 API 는 그대로). 32자 이상 무작위 값을 설정한다 (예: python -c "import secrets;print(secrets.token_urlsafe(48))").
    jwt_secret: str = ""
    jwt_issuer: str = "gabee-api"
    jwt_audience: str = "gabee-app"
    access_token_ttl_seconds: int = 15 * 60  # Access Token: 15분
    refresh_token_ttl_seconds: int = 30 * 24 * 3600  # Refresh Token: 30일(사용할 때마다 회전)
    # 레거시 X-Gyeot-Token(익명 계정) 인증. 현재 모바일 앱이 쓰므로 기본은 켬 — 앱 전환이 끝나면 false 로 끈다.
    # 이 값과 상관없이 정식 회원(아이디/비밀번호 가입 계정)은 레거시 토큰으로 인증할 수 없다.
    allow_legacy_token_auth: bool = True
    # 로그인 실패 제한(프로세스 메모리, 재시작하면 초기화): 아이디별/IP별 실패 횟수와 집계 시간
    login_max_failures_per_id: int = 5
    login_max_failures_per_ip: int = (
        50  # 0 이면 IP 제한을 끈다(리버스 프록시 뒤에서 uvicorn --proxy-headers 없이 쓸 때)
    )
    login_failure_window_seconds: int = 15 * 60

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")


settings = Settings()
