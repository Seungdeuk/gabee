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
    support_email: str = ""  # 공개 안내 페이지(/privacy·/terms 등)에 보이는 문의 이메일. 비우면 이메일 줄은 보이지 않는다
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

    # 업로드 파일의 글자 읽기(OCR)·개인정보 가리기를 Claude 로 한다(docs/adr/0014). 호출이 실패하면 가리지 않은 글을 저장하지 않고 파일을 failed 로 둔다.
    # 글자 읽기와 가리기는 항상 Claude 로 한다(사용자 결정 2026-11-09). 로컬 OCR(RapidOCR)은 서비스에서 제거했다(2026-11-23): 사진 속 글자는 Claude 만 읽으므로
    # **서비스에서는 INGEST_LLM_OCR=true 가 필수**다(false 면 사진은 읽을 수단이 없어 실패한다). false 는 읽기 구성 요소를 끼우는 시험에서만 쓴다(conftest.py).
    # 외부로 보내는 모든 갈래(사진·PDF 스캔 쪽 읽기, 글 가리기, PPT 그림 설명, 분류, 챙길 일 뽑기)는 가족 AI 동의가 있을 때만 쓴다.
    ingest_llm_ocr: bool = True  # 사진·PDF 쪽을 Claude 로 읽는다
    ingest_llm_mask: bool = True  # 글을 Claude 로 가리고 가족 이름 후보를 문맥으로 판단한다
    ingest_ocr_model: str = "claude-sonnet-5-5"  # 표·머리말 구분이 좋은 모델
    ingest_mask_model: str = ""  # 비우면 llm_model(Haiku)
    # (더 이상 쓰지 않음) 가족방 사진 판별을 Claude 로 하던 스위치. 사진 판별은 로컬 SigLIP2 단독이고 사진을 외부로 보내지 않는다(2026-11-23). 값은 무시된다.
    photo_judge_llm: bool = False
    photo_judge_model: str = ""  # 비우면 llm_model(Haiku)
    # 가족방 사진 판별을 로컬 SigLIP2 단독으로 한다(margin > 5 이면 document, 아니면 unsure; 로컬 OCR 은 없다). **기본 꺼짐: 꺼져 있으면 판별 수단이 없어서 모든 사진이
    # unsure 가 되고 문서 자동 등록이 멈춘다.** 켜도 외부 AI 호출 없이 로컬 모델만 쓴다. 모델은 ONNX 이미지 인코더(CPU, torch 없음)이고 폴더에 `siglip2_vision.onnx`·`head.json` 이 있어야 한다
    photo_classify_siglip: bool = False
    photo_classify_model_dir: str = ""  # 변환한 SigLIP2 ONNX 모델 폴더(저장소에 없다). 비었거나 파일이 없으면 판별은 failed 가 된다
    photo_classify_threads: int = 2  # onnxruntime CPU 스레드 수
    # AI 추억 분석의 서버 기능 스위치(ADR 0020 3중 조건의 ①). 기본 꺼짐: 꺼져 있으면 가족 설정·업로더 동의가 켜져 있어도 분석 자격이 없고 동의를 새로 받지 않는다
    family_memory_enabled: bool = False
    # AI 추억 분석 작업 워커(PR3, 단일 경량 스레드). 기본 꺼짐: `FAMILY_MEMORY_ENABLED` 와 이 값이 모두 켜져 있을 때만 서버가 시작하며 돌린다
    family_memory_worker_enabled: bool = False
    family_memory_worker_poll_seconds: float = 5.0  # 일이 없을 때 다음 확인까지 기다리는 시간
    family_memory_job_lease_seconds: int = (
        300  # 선점한 작업의 임대 시간(넘기면 다른 워커가 되찾는다)
    )
    # 이미지 임베딩 인코더(PR4): off(기본) | siglip2(로컬 모델 파일만, 다운로드 안 함) | fake(개발·시험용 가짜). 모델은 별도 워커 프로세스(worker_main)에서만 올라간다
    family_memory_encoder: str = "off"
    family_memory_siglip2_path: str = ""  # 이미 내려받은 SigLIP2 스냅샷 폴더(로컬 경로)
    family_memory_encoder_device: str = "auto"  # auto | cpu | cuda
    family_memory_encoder_fp16: bool = False  # GPU 일 때만 반 정밀도(메모리 약 절반)
    # 추억 후보 조회 API(PR6) 미출시 가드: 기본 꺼짐(꺼져 있으면 404 로 존재를 숨긴다). 앱(PR7) 개발·검증 때만 켠다. 후보는 비공개이며 자동 게시하지 않는다
    family_memory_candidates_api_enabled: bool = False
    # 동의할 때 consent_version 을 **반드시** 보내야 하게 한다(T31 고지문 확정 뒤 켠다). 기본 꺼짐: 켜면 버전을 안 보낸 동의 요청은 409 consent_version_required — 버전 확인을 우회하지 못한다
    family_memory_consent_version_required: bool = False
    # 사용자 요청형 추억 생성(PR10) 진입점. **실제 가족 사진을 처리하는 입구라서** T31 고지문·동의 UX 와 별도 출시 승인이 끝나기 전에는 켜지 않는다(기본 꺼짐, 꺼져 있으면 404).
    # 켜져 있어도 `family_memory_consent_version_required` 가 함께 켜져 있어야 열린다(동의 버전 확인 없이는 실제 사진을 처리하지 않는다)
    family_memory_generate_enabled: bool = False
    family_memory_generate_max_photos: int = (
        300  # 요청 한 번에 새로 등록하는 사진 수 상한(나머지는 다음 요청에서)
    )
    ingest_mask_chunk_chars: int = 6000  # 가리기 호출 한 번에 보내는 최대 글자 수(긴 문서는 나눠서)
    ingest_pdf_max_pages: int = 20  # Claude 로 읽는 PDF 최대 쪽 수(비용 상한)
    # Claude 연결 실패(llm_unavailable)로 failed 가 될 파일을 자동으로 다시 처리하는 횟수와 기다리는 시간(n번째 재시도는 n×이 초)
    ingest_retry_max: int = 2
    ingest_retry_wait_seconds: int = 20
    # 올린 문서의 날짜에서 챙길 일을 뽑는다(Claude 1회 호출). 켜도 사용자마다 챙겨주기 스위치로 끌 수 있다
    ingest_reminders: bool = False
    # AI 채팅 탭에서 Claude 가 웹 검색을 쓸 수 있게 한다(docs/requirements/ai_assistant-web-search.md). 검색 1,000회에 10달러가 더 든다
    web_search_enabled: bool = False
    web_search_max_uses: int = 3  # 질문 하나에 검색할 수 있는 횟수

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
    # 통합관리자 허용 목록(app/shared/auth.py require_operator("admin")): 쉼표로 구분한 사용자 id. 비어 있거나 없으면 아무도 허용하지 않는다.
    # 서비스 관리(/admin/service/*)와 운영 관리(/admin/ops/*)를 함께 연다(2026-11-06 결정: 권한은 통합관리자 하나).
    # 실제 id 는 환경변수(.env·비밀 관리)에만 두고 코드·Git·문서에 넣지 않는다.
    admin_user_ids: str = ""
    # 관리자 챗봇 실행 기록을 LangSmith 로 보낼지(기본 꺼짐). 이 챗봇의 실행에만 붙이고 서버 전체 추적(LANGSMITH_TRACING)은 쓰지 않는다.
    # 켜면 Claude 에게 보낸 글(가린 질문, 답 규칙·FAQ, 도구가 준 숫자)과 답이 LangSmith 서버에 저장된다. 키는 .env 에만 둔다.
    admin_langsmith_enabled: bool = False
    admin_langsmith_api_key: str = ""
    admin_langsmith_project: str = "gabee-admin-chatbot"
    # 구독·통신비 서버 API(/billing/subscriptions*) 사용 여부(기본 꺼짐). 지갑 탭에서 구독 기능을 빼면서 닫았다. 꺼져 있으면 403 subscription_disabled 로 막고,
    # 일정 추천도 구독 결제일을 읽지 않는다. 테이블과 데이터는 그대로 둔다.
    subscription_api_enabled: bool = False
    # 메일 요청 제한(프로세스 메모리, login 제한과 같은 한계): 인증 메일 재발송 간격/시간당, 재설정 메일 이메일별/IP별 시간당
    verify_resend_cooldown_seconds: int = 60
    verify_max_per_hour: int = 5
    reset_max_per_email_per_hour: int = 3
    reset_max_per_ip_per_hour: int = 20  # 0 이면 IP 제한 끔

    # 가족 초대·가입 승인(PR 4-B): 새로 발급하는 초대 코드는 24시간·1회. 코드를 틀리게 입력한 실패가 이 횟수에 이르면
    # 계정별·IP별로 막고(invite_attempts, 슬라이딩 윈도우), 윈도우가 지나면 다시 시도할 수 있다.
    invite_ttl_seconds: int = 24 * 3600
    # 정산하기 알림을 보낸 뒤 이 시간이 지나도 송금 완료를 안 눌렀으면 알림함에 재알림을 한 번 남긴다(테스트 중에는 줄여서 쓴다).
    settlement_remind_hours: int = 24
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
    # 전화 이야깃거리(데일리 체크): 쿨다운 없음, 하루 10번(가족 30번). 결과 캐시는 서버 기본 시간(ai_result_cache_ttl_seconds)을 따른다
    ai_call_talk_cooldown_seconds: int = 0
    ai_call_talk_max_calls_per_user_per_day: int = 10
    ai_call_talk_max_calls_per_group_per_day: int = 30
    # 주간 가족 뉴스 생성(구성원당 한 주에 한 번 저장하므로 하루 한도는 재시도 여유): 요청 간격 10초, 구성원 하루 2번(가족 10번)
    weekly_news_model: str = ""  # 비우면 llm_model(Haiku)
    ai_news_cooldown_seconds: int = 10
    ai_news_max_calls_per_user_per_day: int = 2
    ai_news_max_calls_per_group_per_day: int = 10
    # 먼저 권해드려요 카드 공급(미리 만들어 저장): 하루 3번(5개씩 15개), 요청 간격 5초
    # 골든벨 가비 추천: 하루 한 번 만들어 당일 자정까지 캐시한다. 실패·결과 없음일 때만 다시 불러서 별도 한도로 센다(ai_guard.register_bucket)
    ai_play_quiz_rec_cooldown_seconds: int = 5
    ai_play_quiz_rec_max_calls_per_user_per_day: int = 3
    ai_play_quiz_rec_max_calls_per_group_per_day: int = 5
    # 이게 뭐게 가비 추천: 골든벨과 같다. 추천 한 번(그림 5개를 동시에 불러도)이 1회이고 성공하면 당일 자정까지 캐시라 2·3회는 실패했을 때의 시도분
    ai_play_draw_rec_cooldown_seconds: int = 5
    ai_play_draw_rec_max_calls_per_user_per_day: int = 3
    ai_play_draw_rec_max_calls_per_group_per_day: int = 5
    # 탐정단 사진 추천에 가족 앨범 사진을 쓸지(꺼짐이면 카드 3개 모두 흔한 사진, AI 호출·가족 사진 접근 없음). 위험 검토 뒤 켠다
    photo_rec_family_enabled: bool = False
    # 탐정단 사진 추천(내용 질문): 사진 한 장당 AI 한 번. 값은 이게 뭐게와 같게 시작하고 별도 한도로 센다
    ai_play_photo_rec_cooldown_seconds: int = 5
    ai_play_photo_rec_max_calls_per_user_per_day: int = 3
    ai_play_photo_rec_max_calls_per_group_per_day: int = 5
    # 찰칵 흔한 사진 자동 보충: 서버 안 백그라운드 작업이 하루 한 번 Pixabay 사진 + AI 질문으로 흔한 사진을 채운다. 기본 꺼짐.
    # 사진 한 장당 AI 한 번(ai_guard 를 쓰지 않으므로 호출 수는 per_day x max_attempts x 시도당 후보 상한으로 묶인다). 키는 로그에 찍지 않는다
    pixabay_api_key: str = ""
    photo_rec_auto_enabled: bool = False
    photo_rec_auto_per_day: int = 3
    photo_rec_auto_max_attempts: int = 3
    photo_rec_auto_cooldown_seconds: int = (
        600  # 찰칵 추천을 열 때 보충을 띄우는 최소 간격(이 프로세스 기준)
    )
    ai_schedule_card_cooldown_seconds: int = 5
    ai_schedule_card_max_calls_per_user_per_day: int = 3
    ai_schedule_card_max_calls_per_group_per_day: int = 15

    # AI 어시스턴트(채팅·기록 질문)도 기본 한도와 따로 센다. 예전 값(사용자 100회/일, 쿨다운 없음)을 유지하고, 가족 상한은 넉넉히 둔 새 값
    ai_assistant_cooldown_seconds: int = 0
    ai_assistant_max_calls_per_user_per_day: int = 100
    ai_assistant_max_calls_per_group_per_day: int = 300
    # 탭 에이전트(정산·돌봄·가족 채팅)가 사용자에게 줄 답을 만들었으면 메인이 다시 모델을 부르지 않고 그 답을 그대로 돌려준다(질문당 모델 호출 1번 절약)
    assistant_direct_agent_reply: bool = True
    # 메인 채팅의 첫 호출에서 도구를 꼭 쓰게 하는 기준(올린 문서와 질문의 최고 코사인 유사도, 로컬 임베딩이라 모델 비용 없음). 0 이하면 끈다.
    # 근거(2026-11-09, 평가 dev 표본 + 임시 사본 색인): 문서 질문의 최고 점수는 가족 문서 87건 중 최저 0.83, 공개 문서 80건 중 최저 0.78
    # (0.82 이상 76건). 도구 없이 답했던 20건은 모두 0.83 이상. 인사·잡담·앱 사용법·계산 8문장은 가족 색인 0.76~0.81, 공개 색인 0.77~0.85
    # (앱 사용법 한 문장만 0.845). 그래서 0.82: 문서 질문 대부분을 잡고 잡담은 거의 자유롭게 둔다. 임베딩 모델을 바꾸면 다시 잰다.
    chat_force_search_min_score: float = 0.82
    # 문서 검색(search_knowledge)에 글자 2·3개 묶음 TF-IDF 를 임베딩과 섞는다(순위 합치기 RRF). 임베딩 상위 `chat_hybrid_candidates` 조각 안에서만 계산한다.
    # 근거(2026-11-10 오프라인, eval/rag/hybrid_candidates_check.py, dev): 공개 PDF 정답 쪽 Hit@3 임베딩 59.8% → 후보 50/100/200 에서 66.0/67.0/67.5%
    # (전체 조각 섞기 68.9%), 정답 문서 Hit@1 85.6 → 90.9/90.4/90.9%. 가족 v2 문서 Hit@1 95.5 → 96.0/95.8/96.0%, Hit@3 98.6 → 99.4%.
    # 후보 100: 200 과 효과 차이가 0.5%p 이하이고 TF-IDF 계산이 공개 PDF(조각이 긴 경우) 약 14~32ms 로 200 의 절반이다. 가중치 1 은 실험의 값(TF-IDF 만 쓰면 가족 Hit@1 84.8% 로 떨어진다).
    # 끄면(false) 예전처럼 임베딩 순서 그대로다. 첫 호출 검색 강제(chat_force_search_min_score)는 섞지 않은 임베딩 점수를 쓴다.
    chat_hybrid_search: bool = True
    chat_hybrid_candidates: int = 100
    chat_hybrid_text_weight: float = 1.0
    # 문서 검색(search_knowledge/get_item)으로 답한 메인 채팅 답을 돌려주기 전에 Haiku 로 한 번 더 확인한다(근거 글에 없는 사실 문장 삭제, 못 찾았는데
    # 다른 값을 덧붙인 답은 "찾지 못했어요"로). 웹 검색·탭 에이전트 직통·잡담에는 걸지 않는다. 호출은 ai_guard 한도·사용량에 센다(질문당 모델 호출 +1).
    # 근거: 사용자 결정(2026-11-10, 근거 없는 주장과 못 찾고 다른 값 덧붙이기를 최대한 막는다). 막는 효과와 과잉 거절은 평가로 확인해야 한다.
    chat_verify_answer: bool = True
    # 답 확인은 근거 글이 이 글자 수 이하일 때만 한다. 평가 근거(2026-11-10): 가족 문서는 근거 글 중앙값 약 6천 자에서
    # 근거 없는 주장 2.6→0.9%, 정확도 유지. 긴 공개 PDF(중앙값 약 1만 1천 자, 상위 25% 2만 3천 자 이상)는 정확도 85.0→78.3%,
    # 질문당 비용 +35%, 지연 2배로 손해. 그래서 짧은 문서에만 확인한다
    chat_verify_max_evidence_chars: int = 8000
    # 모델의 최종 답 초안이 '찾지 못했다' 유형이고 이 대화에서 문서 검색 결과가 있었으면, 코드가 검색 결과 상위 3개 문서 안을
    # 원래 질문으로 다시 찾아(search_in_item) 그 조각을 근거로 한 번 더 답하게 한다(최대 1회, 모델 호출 +1). 기본은 꺼짐: 평가에서만 켠다.
    chat_retry_not_found: bool = False

    # 가명화 NER 보강(app/shared/privacy/ner.py, KoELECTRA-small ONNX). 모델 파일은 저장소에 없고 서버 폴더에서 읽는다.
    # off: 안 씀 / auto: 모델이 있고 로드되면 쓰고, 없거나 실패하면 규칙만(프로세스당 한 번 경고) / required: 못 쓰면 503 privacy_unavailable(fail-closed)
    privacy_ner_mode: str = "auto"
    privacy_ner_model_dir: str = ""  # 비우면 <DATA_DIR>/models/ner
    privacy_ner_threads: int = 2  # onnxruntime CPU 스레드 수
    privacy_ner_max_concurrency: int = (
        2  # 동시에 돌리는 추론 수(요청이 몰리면 대기, 오래 걸리면 auto 는 규칙만·required 는 503)
    )
    privacy_ner_model_file: str = "model.onnx"  # 폴더 안 모델 파일(양자화 모델은 model.int8.onnx)
    # 운영 관리자 요청 지표(app/features/ops_admin). 기본 꺼짐: 공용 DB 에 ops_request_metrics 가 생긴 뒤 켠다.
    # 켜면 요청마다 X-Trace-Id 를 내려주고 메서드·경로 패턴·상태코드 구분·지연 시간만 집계한다(URL 원문·본문·헤더·사용자 id 저장 안 함).
    # 구간 길이와 보관 일수는 추측으로 정한 초기값이라 실제 트래픽·저장량을 본 뒤 조정한다.
    ops_metrics_enabled: bool = False
    ops_metrics_bucket_seconds: int = 300
    ops_metrics_retention_days: int = 90
    # 운영 관리자 오류 이벤트(5xx·처리되지 않은 예외·401/403): 기본 꺼짐. 공용 DB 에 ops_error_events 가 생긴 뒤 켠다.
    # 켜도 응답에는 영향이 없고(응답을 보내기 전 요청 안에서 저장), 메시지는 가려서 200자까지만, 인증 실패는 메시지 없이 code 만 저장한다.
    ops_errors_enabled: bool = False
    ops_errors_retention_days: int = 90
    # 운영 관리자 인프라 상태(Cloud Run 설정·Cloud Monitoring 조회, 읽기 전용): 기본 꺼짐. 실행 서비스 계정에 roles/run.viewer·monitoring.viewer 가 필요하다.
    ops_infra_enabled: bool = False
    # 관리자 알림(admin_alerts): 기본 꺼짐. 켜면 점검 주소(/internal/alerts/run)가 규칙을 돌려 알림 기록표에 넣는다.
    # 점검 주소는 X-Alert-Token 이 이 값과 같을 때만 통과한다. 토큰이 비어 있으면 아무도 통과하지 못한다.
    admin_alerts_enabled: bool = False
    admin_alerts_token: str = ""
    # 폰 푸시(app/shared/push.py). 기본 꺼짐: 켜면 알림함 알림을 저장한 뒤(커밋 후) Expo 푸시 서비스로 발송한다.
    # 푸시 토큰이 없거나 발송이 실패해도 원래 기능에는 영향이 없다. Expo 계정에서 '푸시 보안'을 켠 경우에만
    # PUSH_EXPO_ACCESS_TOKEN 을 넣는다(안드로이드 FCM 키는 EAS 에 올리며 서버에는 두지 않는다).
    push_enabled: bool = False
    push_expo_access_token: str = ""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", populate_by_name=True)

    @field_validator("llm_model")
    @classmethod
    def _llm_model_default_when_blank(cls, value: str) -> str:
        return value.strip() or "claude-haiku-5-5"


settings = Settings()
