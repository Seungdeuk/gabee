"""가족 채팅에 올린 문서를 가족 공유 문서함(knowledge)에 자동 등록한다(`shared/chat_library.py` 통로의 처리 쪽).

- 가족 전체방의 문서 첨부만 온다. 민감 문서(처방전·신분증 등)도 등록한다(2026-11-09 사용자 결정): 기록에 민감 표시가 붙고, 그 문서의 챙길 일 뽑기는 건너뛴다.
- ingest 가 지원하지 않는 형식(hwp·hwpx·예전 doc/xls/ppt 등)은 읽기 전에 거르고 보관하지도 않는다(채팅 파일로만 남는다).
- 같은 첨부는 한 번만(`knowledge_items.source_attachment_id` 유일). 읽기·저장은 기존 업로드 뒷처리(`files.process_file`)를 그대로 쓴다:
  `photos` 행을 만들고 knowledge 기록 id 를 그 id 와 같게 둬서 상태·원본 보기·삭제가 기존 문서와 똑같이 동작한다.
- 채팅 메시지를 지우면 연결된 기록·원본도 함께 지운다(`files.delete_record`)."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import Session

from app.shared import chat_library, image_features
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import consent_gate

from . import files, service
from .ingest import siglip_margin
from .ingest.detect import Unsupported, detect
from .knowledge import repository as knowledge_repo

logger = logging.getLogger(__name__)

# 읽기(OCR)는 CPU 를 쓰므로 채팅 전송과 따로, 한 번에 둘까지만(files.process_file 안의 칸도 둘이다)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chat-library")


def _submit(fn, *args) -> None:
    """등록을 백그라운드에서 실행한다(시험은 이 함수를 그 자리 실행으로 바꾼다)."""
    _executor.submit(fn, *args)


def supported(data: bytes, filename: str) -> bool:
    """ingest 가 읽을 수 있는 형식인지(예전 형식·알 수 없는 형식은 등록하지 않는다)."""
    try:
        detect(data, filename)
    except Unsupported:
        return False
    return True


def register_chat_document(
    group_id: str,
    user_id: str,
    attachment_id: str,
    filename: str,
    content_type: str,
    data: bytes,
) -> None:
    """채팅 문서 첨부 하나를 문서함에 등록한다(읽기 → 저장, 민감 문서는 민감 표시를 붙여 저장). 어떤 실패도 던지지 않는다.
    가족 채팅 목적의 처리라 가족 AI 동의가 있을 때만 외부(Claude·Jev)로 보낸다: 동의가 없으면 등록을 보류하고(채팅 첨부는 그대로) 외부 호출을
    하지 않는다. 처리 도중 동의를 끄면 그 뒤의 외부 호출은 나가지 않고 등록하지 않는다(`consent_gate`)."""
    try:
        if not settings.ingest_llm_mask:
            # Claude 가리기가 꺼져 있으면 로컬 규칙(주민번호 등만 가림, 이름·주소·전화번호는 남음)으로만 가린 문서가 AI 검색 지식베이스에 들어간다.
            # 그런 문서는 등록하지 않는다(채팅 첨부는 그대로, 외부 호출도 시작하지 않는다). 메인 AI 직접 업로드는 이 경로가 아니라 영향이 없다.
            logger.info("chat library document held: masking unavailable")
            return
        with consent_gate.family_chat(group_id):
            if not consent_gate.allowed_now():
                logger.info("chat library document held: family ai consent required")
                return
            if not supported(data, filename):
                return
            with SessionLocal() as db:
                if knowledge_repo.get_by_attachment(db, group_id, attachment_id) is not None:
                    return  # 이미 등록했다(재시도·중복 요청)
                if not chat_library.attachment_exists(db, group_id, attachment_id):
                    return  # 대기하는 사이 메시지가 지워졌다
                photo = service.receive_file(db, group_id, user_id, filename, content_type, data)
                photo_id = photo.id
            files.process_file(
                photo_id, group_id, user_id, data, filename, source_attachment_id=attachment_id
            )
    except Exception as exc:  # noqa: BLE001  내용이 로그에 남지 않게 종류만 적는다
        logger.warning("chat library register failed error=%s", type(exc).__name__)


def _on_document(
    group_id: str, user_id: str, attachment_id: str, filename: str, content_type: str, data: bytes
) -> None:
    _submit(register_chat_document, group_id, user_id, attachment_id, filename, content_type, data)


def _on_removed(db: Session, group_id: str, attachment_id: str) -> None:
    item = knowledge_repo.get_by_attachment(db, group_id, attachment_id)
    if item is not None:
        files.delete_record(db, group_id, item.id)


# ---------- 사진 ----------

PHOTO_QUEUE_LIMIT = 20  # 가족마다 처리를 기다리는 사진 수(사진 바이트가 메모리에 있으므로 상한을 둔다). 한 가족이 다른 가족을 막지 않는다
PHOTO_QUEUE_INSTANCE_LIMIT = 40  # 서버 인스턴스 전체에서 처리를 기다리는 사진 수(가족마다 20장씩 여러 가족이 쌓여도 메모리가 늘지 않게)
PHOTO_QUEUE_INSTANCE_BYTES = (
    96 * 1024 * 1024
)  # 서버 인스턴스 전체에서 기다리는 사진 바이트 합(사진 한 장 최대 8MB, 2GiB 인스턴스 기준)
_photo_bytes = 0  # 인스턴스 전체에서 기다리는 사진 바이트 합(직접 저장 포함)
_photo_lock = threading.Lock()
_photo_pending: dict[str, int] = {}  # 가족 → 처리를 기다리는 사진 수
_photo_inflight: set[tuple[str, str, bool]] = (
    set()
)  # (가족, 첨부, 직접 저장 여부) 진행 중인 것: 같은 요청을 겹쳐 처리하지 않는다


def _judge_photo(group_id: str, data: bytes) -> tuple[str, str | None]:
    """사진 판별 결과 (상태, 실패 종류). 상태는 document | unsure | failed 셋 중 하나다(**photo 는 없다**: 모델 판정만으로 일반 사진을
    확정하지 않는다. 일반 사진 확인은 업로더가 직접 한다, D-13). 판별은 **로컬 SigLIP2 단독**이다(ADR 0025, 로컬 OCR 은 서비스에서 제거했다):
    margin > 5 이면 document, 아니면 unsure. 사진을 외부로 보내지 않는다. `PHOTO_CLASSIFY_SIGLIP` 이 꺼져 있으면 판별 수단이 없어서 unsure 이고
    (문서 자동 등록이 멈춘다), 점수를 못 구하면(모델 파일·로드·메모리·추론 오류) 문서·일반 사진으로 확정하지 않고 failed 다(기존 재검사 규칙을 따른다).
    하루 상한은 없다(2026-11-09 사용자 결정)."""
    if not settings.photo_classify_siglip:
        return "unsure", None
    try:
        margin = siglip_margin.get_scorer().score(data)
    except siglip_margin.MarginError as exc:
        logger.warning("chat library photo siglip failed error=%s", exc)
        return "failed", f"Siglip{exc}"[:40]
    except Exception as exc:  # noqa: BLE001  내용이 로그에 남지 않게 종류만 적는다
        logger.warning("chat library photo siglip failed error=%s", type(exc).__name__)
        return "failed", f"Siglip{type(exc).__name__}"[:40]
    return siglip_margin.photo_status(margin), None


def _is_document_photo(group_id: str, data: bytes) -> bool:
    """자동 등록할 문서 사진인지(판별 결과가 document 일 때만 True)."""
    return _judge_photo(group_id, data)[0] == "document"


def register_chat_photo(
    group_id: str, user_id: str, attachment_id: str, data: bytes, forced: bool = False
) -> None:
    """채팅 사진 하나를 판별해서 문서 사진이면 문서함에 등록한다(읽기 → 저장, 민감 문서는 민감 표시를 붙여 저장). 어떤 실패도 던지지 않는다.
    forced 는 사용자가 직접 저장을 눌러 판별을 건너뛰는 경우다."""
    try:
        if not settings.ingest_llm_mask:
            # 판별 상태도 바꾸지 않고(사진은 채팅에 남는다) 로컬 규칙으로만 가린 문서를 만들지 않는다. 외부 호출도 시작하지 않는다
            logger.info("chat library photo held: masking unavailable")
            return
        with consent_gate.family_chat(group_id):
            _register_chat_photo_in_scope(group_id, user_id, attachment_id, data, forced)
    except Exception as exc:  # noqa: BLE001  내용이 로그에 남지 않게 종류만 적는다
        logger.warning("chat library photo register failed error=%s", type(exc).__name__)


def _register_chat_photo_in_scope(
    group_id: str, user_id: str, attachment_id: str, data: bytes, forced: bool
) -> None:
    """가족 채팅 목적의 동의 관문 범위 안에서 판별·등록한다. 판별(로컬 OCR, 동의한 가족만 Claude)은 그대로 하고 상태를 적되,
    문서함 등록(외부 읽기·가리기)은 가족 AI 동의가 있을 때만 한다(없으면 보류: 문서로 판별된 사진은 unsure 로 적고 사진은 채팅에 그대로)."""
    with SessionLocal() as db:
        if knowledge_repo.get_by_attachment(db, group_id, attachment_id) is not None:
            return
        if not chat_library.attachment_exists(db, group_id, attachment_id):
            return
    if not forced:
        status, error = _judge_photo(group_id, data)
        if status == "document" and not consent_gate.allowed_now():
            # 문서로 보이지만 가족 AI 동의가 없어 문서함 등록을 보류한다: document 로 적으면 확인 목록·재검사·일반 사진 확인이 모두 막혀
            # 업로더가 손댈 수 없는 사진이 된다. unsure 로 적어 두면 업로더가 확인하거나, 동의를 켠 뒤 재검사로 다시 판별·등록할 수 있다
            logger.info("chat library photo held: family ai consent required")
            chat_library.photo_judged(group_id, attachment_id, "unsure", None)
            return
        # 결과를 판별 상태 표에 적는다(문서함 등록보다 먼저: 문서면 바로 숨김 상태가 된다). 못 적어도 pending 으로 남아 안전하다
        may_register = chat_library.photo_judged(group_id, attachment_id, status, error)
        if status != "document":
            return
        if not may_register:
            return  # 업로더가 이미 일반 사진으로 확인한 사진: 문서함에 올리면 타임라인과 문서함에 둘 다 있게 된다(b0-2a 리뷰)
        with SessionLocal() as db:
            if not chat_library.attachment_exists(db, group_id, attachment_id):
                return  # 판별하는 사이 메시지가 지워졌다: 지운 사진이 문서함에 남지 않게(재검사처럼 오래 걸리는 판별 뒤의 경합)
    if not consent_gate.allowed_now():
        # 가족 AI 동의가 없다: 외부 읽기·가리기를 하지 않고 등록을 보류한다(판별 상태는 남고 사진은 채팅에 그대로)
        logger.info("chat library photo held: family ai consent required")
        return
    with SessionLocal() as db:
        photo = service.receive_file(
            db, group_id, user_id, f"{attachment_id}.jpg", "image/jpeg", data
        )
        photo_id = photo.id
    files.process_file(
        photo_id, group_id, user_id, data, f"{attachment_id}.jpg",
        source_attachment_id=attachment_id, keep_photo=forced or settings.photo_classify_siglip,
    )  # fmt: skip
    # 단계형(E)이 켜져 있으면 문서로 판정된 사진은 글자가 적어도 문서함에 남긴다: 글자가 적은 문서를 SigLIP2 가 구한 경우(rescue)를 읽기 단계가
    # 다시 "사진"으로 버리면, 판별 상태는 document 인데 문서함에는 없는 채로 업로더가 일반 사진 확인도 못 하게 된다.


def _on_photo(
    group_id: str, user_id: str, attachment_id: str, data: bytes, forced: bool = False
) -> None:
    global _photo_bytes
    key = (group_id, attachment_id, forced)
    with _photo_lock:
        if key in _photo_inflight:
            return  # 같은 요청이 이미 처리 중이다(연타·재요청)
        if not forced and (
            _photo_pending.get(group_id, 0) >= PHOTO_QUEUE_LIMIT
            or sum(_photo_pending.values()) >= PHOTO_QUEUE_INSTANCE_LIMIT
            or _photo_bytes + len(data) > PHOTO_QUEUE_INSTANCE_BYTES
        ):
            # 가족·인스턴스 건수나 바이트 상한을 넘었다: 이번 사진은 건너뛴다(pending 으로 남아 15분 뒤 확인 필요 목록·재검사로 복구된다).
            # 직접 누른 저장은 버리지 않는다(요청 횟수는 라우터가 제한한다)
            logger.info("chat library photo queue full")
            return
        _photo_pending[group_id] = _photo_pending.get(group_id, 0) + 1
        _photo_inflight.add(key)
        _photo_bytes += len(data)

    def release() -> None:
        global _photo_bytes
        with _photo_lock:
            _photo_bytes = max(0, _photo_bytes - len(data))
            _photo_inflight.discard(key)
            left = _photo_pending.get(group_id, 1) - 1
            if left > 0:
                _photo_pending[group_id] = left
            else:
                _photo_pending.pop(group_id, None)

    def run() -> None:
        try:
            register_chat_photo(group_id, user_id, attachment_id, data, forced)
        finally:
            release()

    try:
        _submit(run)
    except Exception as exc:  # noqa: BLE001  서버를 끄는 중이면 작업이 들어가지 않는다: 자리를 되돌린다
        release()
        logger.warning("chat library photo submit failed error=%s", type(exc).__name__)


def _photo_registered(db: Session, group_id: str, attachment_id: str) -> bool:
    return knowledge_repo.get_by_attachment(db, group_id, attachment_id) is not None


def _photos_registered(db: Session, group_id: str, attachment_ids: list[str]) -> set[str]:
    return knowledge_repo.registered_attachment_ids(db, group_id, attachment_ids)


def register() -> None:
    """ai_assistant 가 시작할 때 처리 함수를 채팅 쪽 통로에 등록한다."""
    chat_library.register_handlers(_on_document, _on_removed)
    chat_library.register_photo_handler(_on_photo, _photo_registered, _photos_registered)
    image_features.register_analyzer(
        _analyze_for_timeline
    )  # 가족 타임라인이 (문서 margin, 임베딩)을 구하는 통로(문서함 등록 정책과 별개, 외부 전송 없음)


def _analyze_for_timeline(data: bytes) -> tuple[float, list[float]]:
    """로컬 SigLIP2 한 번의 추론으로 (문서 margin, 정규화 임베딩). `PHOTO_CLASSIFY_SIGLIP`(문서함 자동 등록 스위치)와 무관하다:
    모델 폴더(`PHOTO_CLASSIFY_MODEL_DIR`)가 없으면 MarginError(`ModelDirMissing`)라서 타임라인은 그 사진을 자동 후보에서 뺀다."""
    analyze = getattr(siglip_margin.get_scorer(), "analyze", None)
    if analyze is None:
        raise image_features.FeaturesUnavailable("NoAnalyzer")
    return analyze(data)
