from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
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
    # Anthropic 모델은 환경변수 ANTHROPIC_MODEL 로 고른다(예전 이름 LLM_MODEL 도 읽는다). 비우면 기본값.
    llm_model: str = Field(
        default="claude-haiku-5-5", validation_alias=AliasChoices("ANTHROPIC_MODEL", "LLM_MODEL")
    )
    # DB 스키마 준비 상태 재점검 주기(초): 준비된 동안은 드물게, 준비 안 됐으면(자동 배포 진행 중) 자주
    schema_recheck_ready_seconds: int = 30
    schema_recheck_not_ready_seconds: int = 2
    schema_force_min_interval_seconds: float = 1  # /health/db 가 강제 재점검할 수 있는 최소 간격
    # TypeSafe Jev — 정해진 보기 중 고르기·예/아니오 판단. 가린 글자만 보낸다
    typesafe_api_key: str = ""
    jev_model: str = "jev-latest"
    jev_timeout: float = 15.0
    # 원본 파일(가리기 전)을 그대로 보관하는 폴더. 비우면 DATA_DIR/raw. 접근을 제한해야 하는 곳이라 서버만 읽는다
    raw_dir: str = ""
    # 채팅(외부 Claude)이 근거로 읽을 수 있는 기록에 민감 기록(처방전·신분증·통장·인물 사진 등)을 넣을지
    chat_include_sensitive: bool = (
        True  # 가린 글만 채팅 근거로 쓴다. 끄려면 CHAT_INCLUDE_SENSITIVE=false
    )

    # 임시 경로 스위치(app/shared/route_switch.py): 쉼표로 구분한 `METHOD /path`(경로에 * 허용). 걸린 요청은 503 route_disabled. 비우면 끄는 경로 없음
    disabled_ai_routes: str = ""

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
    # 예약: 메일에는 지금 링크를 넣지 않는다(6자리 코드만). 링크를 다시 넣을 때 쓸 앱 주소(딥링크 또는 웹 주소).
    email_link_base: str = "gabee://"
    email_verify_ttl_seconds: int = 3 * 60  # 인증번호·링크 유효 시간: 3분
    password_reset_ttl_seconds: int = 30 * 60
    # 6자리 코드: 코드(메일 1통)마다 틀려도 되는 횟수. 넘으면 그 코드는 못 쓰고 메일을 다시 받아야 한다
    code_max_attempts: int = 5
    # 이메일은 가입 때 선택이고, 인증하지 않아도 가족 그룹을 만들고 참여할 수 있다(기본). true 로 켜면 이메일이 있는데 미인증인 정식 회원의
    # 그룹 생성·참여를 막는다(메일 발송이 설정된 환경에서만). 이메일이 없는 계정은 켜도 막지 않는다.
    require_email_verification: bool = False
    # 테스트 참여 동의서에 동의한 회원만 API 를 쓸 수 있게 한다(기본은 꺼짐). 앱의 동의서 버전(CONSENT_VERSION)과 같게 둔다.
    require_tester_consent: bool = False
    tester_consent_version: str = "v0.2"
    # 돌봄 서버 API(/care/*) 사용 여부(기본 꺼짐). 팀 회의 결과로 돌봄 탭을 지갑으로 바꾸면서 닫았다. 꺼져 있으면 /care/* 요청을 403 care_disabled 로 막는다.
    # 위치 동의 철회·조회(/care/location/consent)는 저장된 내 위치를 지우는 길이라 꺼져 있어도 열어 둔다.
    care_api_enabled: bool = False
    # 돌봄 위치 공유 사용 여부(기본 꺼짐). 꺼져 있으면 위치 저장·조회·동의와 에이전트의 위치 도구를 403 location_disabled 로 막는다.
    # 동의 철회(저장된 내 위치 삭제)와 동의 상태 조회는 꺼져 있어도 된다.
    care_location_enabled: bool = False
    # 메일 요청 제한(프로세스 메모리, login 제한과 같은 한계): 인증 메일 재발송 간격/시간당, 재설정 메일 이메일별/IP별 시간당
    verify_resend_cooldown_seconds: int = 60
    verify_max_per_hour: int = 5
    reset_max_per_email_per_hour: int = 3
    reset_max_per_ip_per_hour: int = 20  # 0 이면 IP 제한 끔

    # 가족 초대·가입 승인(PR 4-B): 새로 발급하는 초대 코드는 24시간·1회. 코드를 틀리게 입력한 실패가 이 횟수에 이르면
    # 계정별·IP별로 막고(invite_attempts, 슬라이딩 윈도우), 윈도우가 지나면 다시 시도할 수 있다.
    invite_ttl_seconds: int = 24 * 3600
    invite_max_uses: int = 20  # 가족 단톡방에 한 번 공유한 코드로 여러 명이 들어올 수 있게
    invite_max_failures: int = 5
    invite_failure_window_seconds: int = 15 * 60

    # Google·Kakao 로그인(PR 4-D). 비어 있으면 그 제공자 로그인은 503 social_not_configured 로 막힌다. 비밀키·앱 키는 .env 에만 둔다.
    # GOOGLE_CLIENT_IDS: 앱이 ID 토큰을 받을 때 쓴 Google OAuth 클라이언트 ID(웹/iOS/Android 여러 개면 쉼표로). ID 토큰의 aud 가 이 중 하나여야 한다.
    # KAKAO_APP_ID: Kakao 개발자 콘솔의 앱 ID(숫자). 액세스 토큰이 우리 앱에서 발급된 것인지 확인한다.
    google_client_ids: str = ""
    kakao_app_id: str = ""
    social_http_timeout_seconds: int = 5

    # Anthropic(AI) 호출 비용 관리. 키·모델은 서버 환경변수(ANTHROPIC_API_KEY / ANTHROPIC_MODEL)로만 정한다(앱에는 두지 않는다).
    # 일반 채팅 메시지 전송에서는 AI 를 부르지 않고, 구성원이 AI 기능을 눌렀을 때만 최소한으로 부른다.
    anthropic_max_tokens: int = (
        2048  # ANTHROPIC_MAX_TOKENS: 한 번의 응답에서 쓸 수 있는 출력 토큰 상한
    )
    ai_effort: str = "low"  # 추론 비용을 줄이려고 낮게 둔다(low|medium|high)
    ai_auto_analysis_enabled: bool = (
        False  # 설계만 있고 기본 꺼짐(켜도 메시지마다 부르지 않고 시간·새 메시지 수로 모아서)
    )
    ai_auto_analysis_min_new_messages: int = 30
    ai_auto_analysis_min_interval_seconds: int = 3600
    ai_max_calls_per_user_per_day: int = 10  # 사용자별 하루 AI 호출 수(캐시 적중은 세지 않는다)
    ai_max_calls_per_group_per_day: int = 30  # 가족 그룹별 하루 AI 호출 수
    ai_request_cooldown_seconds: int = 30  # 같은 사용자의 AI 호출 사이 최소 간격
    ai_result_cache_ttl_seconds: int = (
        600  # 같은 요청의 결과를 다시 쓰는 시간(가족 그룹별로 따로 보관)
    )
    ai_max_concurrent_requests_per_group: int = (
        1  # 한 가족 그룹에서 동시에 진행할 수 있는 AI 호출 수
    )
    ai_inflight_stale_seconds: int = 120  # 이 시간이 지난 진행 표시는 죽은 요청으로 보고 치운다
    ai_analysis_max_chars: int = (
        12000  # 한 번에 AI 로 보내는 대화 글자 수(넘으면 오래된 것부터 뺀다)
    )
    ai_day_utc_offset_hours: int = 9  # 하루 한도를 세는 날짜 경계(기본 한국 시간 자정)
    # 일정 에이전트는 위 기본 한도와 따로 센다(ai_guard.register_bucket). 채팅은 한 번에 두 번(분류·답변) 부르므로 쿨다운을 두지 않는다.
    # 정산·돌봄 탭 에이전트(질문 1번 = 호출 묶음 1번으로 센다). 기본 한도·일정과 따로 센다
    ai_tab_agent_cooldown_seconds: int = 0
    ai_tab_agent_max_calls_per_user_per_day: int = 60
    ai_tab_agent_max_calls_per_group_per_day: int = 200
    ai_schedule_chat_cooldown_seconds: int = 0
    ai_schedule_chat_max_calls_per_user_per_day: int = 30
    ai_schedule_chat_max_calls_per_group_per_day: int = 100
    # 먼저 권해드려요 카드 공급(미리 만들어 저장): 하루 3번(5개씩 15개), 요청 간격 5초
    ai_schedule_card_cooldown_seconds: int = 5
    ai_schedule_card_max_calls_per_user_per_day: int = 3
    ai_schedule_card_max_calls_per_group_per_day: int = 15

    # AI 어시스턴트(채팅·기록 질문)도 기본 한도와 따로 센다. 예전 값(사용자 100회/일, 쿨다운 없음)을 유지하고, 가족 상한은 넉넉히 둔 새 값
    ai_assistant_cooldown_seconds: int = 0
    ai_assistant_max_calls_per_user_per_day: int = 100
    ai_assistant_max_calls_per_group_per_day: int = 300
    # 탭 에이전트(정산·돌봄·가족 채팅)가 사용자에게 줄 답을 만들었으면 메인이 다시 모델을 부르지 않고 그 답을 그대로 돌려준다(질문당 모델 호출 1번 절약)
    assistant_direct_agent_reply: bool = True

    # 가명화 NER 보강(app/shared/privacy/ner.py, KoELECTRA-small ONNX). 모델 파일은 저장소에 없고 서버 폴더에서 읽는다.
    # off: 안 씀 / auto: 모델이 있고 로드되면 쓰고, 없거나 실패하면 규칙만(프로세스당 한 번 경고) / required: 못 쓰면 503 privacy_unavailable(fail-closed)
    privacy_ner_mode: str = "auto"
    privacy_ner_model_dir: str = ""  # 비우면 <DATA_DIR>/models/ner
    privacy_ner_threads: int = 2  # onnxruntime CPU 스레드 수
    privacy_ner_max_concurrency: int = (
        2  # 동시에 돌리는 추론 수(요청이 몰리면 대기, 오래 걸리면 auto 는 규칙만·required 는 503)
    )
    privacy_ner_model_file: str = "model.onnx"  # 폴더 안 모델 파일(양자화 모델은 model.int8.onnx)

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", populate_by_name=True)

    @field_validator("llm_model")
    @classmethod
    def _llm_model_default_when_blank(cls, value: str) -> str:
        return value.strip() or "claude-haiku-5-5"


settings = Settings()
