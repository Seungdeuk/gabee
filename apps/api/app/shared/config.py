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
    # 얼굴 찾기 사용 여부. 기본은 꺼짐: 얼굴은 생체정보라 가족 동의·삭제 연동이 정해지기 전에는 모델 파일이 있어도 돌리지 않는다
    face_enabled: bool = False
    # 원본 파일(가리기 전)을 그대로 보관하는 폴더. 비우면 DATA_DIR/raw. 접근을 제한해야 하는 곳이라 서버만 읽는다
    raw_dir: str = ""
    # 글자 없는 사진 설명(Ollama 이미지 모델). 사진은 서버 밖으로 나가지 않는다
    caption_enabled: bool = True
    caption_model: str = "qwen2.5vl:3b"
    caption_timeout: float = 60.0
    ollama_keep_alive: str = "30m"  # 모델을 메모리에 올려 두는 시간(처음 불러오는 데 1분쯤 걸린다)
    # 채팅(외부 Claude)이 근거로 읽을 수 있는 기록에 민감 기록(처방전·신분증·통장·인물 사진 등)을 넣을지
    chat_include_sensitive: bool = True

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

    # 이메일 인증·비밀번호 재설정(PR 4-B). 메일 설정이 없으면(기본) 관련 API 는 503 mail_not_configured 이고 발송 성공으로 처리하지 않는다.
    # MAIL_BACKEND: "smtp"(실제 발송, SMTP_* 필요) | "console"(개발 전용: 메일 내용을 서버 로그에 출력, 로컬 SQLite/DEBUG=true 에서만) | ""(꺼짐)
    mail_backend: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""  # .env 에만 둔다
    smtp_from: str = ""  # 보내는 사람 주소(예: no-reply@example.com)
    smtp_security: str = "starttls"  # starttls | ssl | none(로컬 테스트 서버 전용)
    smtp_timeout_seconds: int = 10
    # 메일 링크의 앱 주소(모바일 딥링크 또는 웹 주소). 링크는 <base>verify-email?token=..., <base>reset-password?token=...
    email_link_base: str = "gabee://"
    email_verify_ttl_seconds: int = 24 * 3600
    password_reset_ttl_seconds: int = 30 * 60
    # 이메일 미인증 정식 회원의 가족 그룹 생성·참여를 막는다(docs/requirements/family-group.md). 메일 설정 전 임시로 끌 수 있다
    require_email_verification: bool = True
    # 메일 요청 제한(프로세스 메모리, login 제한과 같은 한계): 인증 메일 재발송 간격/시간당, 재설정 메일 이메일별/IP별 시간당
    verify_resend_cooldown_seconds: int = 60
    verify_max_per_hour: int = 5
    reset_max_per_email_per_hour: int = 3
    reset_max_per_ip_per_hour: int = 20  # 0 이면 IP 제한 끔

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")


settings = Settings()
