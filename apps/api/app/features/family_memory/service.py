"""AI 추억 분석의 동의·설정 업무 규칙(ADR 0020·0021, docs/requirements/auto-memory-consent.md). **PR1 은 동의 기록과 자격 판정만 한다** —
이미지 분석·작업 큐·카드는 아직 없다.

- 3중 조건: ① 서버 스위치(`FAMILY_MEMORY_ENABLED`, 기본 꺼짐) ② 가족 활성화(소유자·관리자) ③ 올린 사람의 동의. 하나라도 빠지면 분석 자격이 없다.
- 철회는 요청 안에서 즉시 효력이 생긴다(`withdrawn_at` 이 곧 차단). 정리 훅(`memory_hooks`)이 같은 트랜잭션에서 일하고, 실패하면 철회도 롤백한다.
- 이 모듈은 `ai_group_settings`(대화 분석 동의)를 읽지도 쓰지도 않고 `chat_photo_checks` 상태를 바꾸지 않는다(D-13).
- 로그에는 개수·사유 코드만 남기고 사진 내용·라벨·경로를 남기지 않는다."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared import member_exit, memory_hooks
from app.shared.config import settings
from app.shared.errors import ApiError, not_found
from app.shared.schema import monitor

from . import repository as repo
from .models import MemberMemoryConsent
from .schemas import ExclusionOut, MemoryStateOut, MyConsentOut

logger = logging.getLogger(__name__)

CONSENT_VERSION = 1  # 동의 문구의 버전 번호(문구 원문은 저장하지 않는다)
MANAGER_ROLES = (
    "owner",
    "admin",
)  # docs/contracts/permissions.md 와 같은 기준(family_group.join_service)
CHECK_PHOTO = "photo"  # chat_photo_checks 상태: 업로더가 일반 사진으로 확인한 것(E0 자격)


# ---------- 자격 판정 ----------
@dataclass(frozen=True)
class EligibilityInput:
    server_enabled: bool
    family_enabled: bool
    photo_found: bool  # 첨부가 있고(지워지지 않았고) 사진(image)임
    in_family_room: bool  # 가족 전체방 사진임(1:1 방은 항상 제외)
    uploader_consented: bool
    uploader_retro_consented: bool
    excluded: bool  # 업로더가 AI 분석에서 뺌
    check_status: str | None  # chat_photo_checks 상태(읽기만)
    retro: bool = False  # 과거 사진 소급 분석인가


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    reason: str  # ok | server_off | family_off | photo_missing | not_family_room | no_consent | no_retro_consent | excluded | not_confirmed_photo


def evaluate(i: EligibilityInput) -> Eligibility:
    """순수 함수: 입력만으로 분석 자격과 사유 코드를 돌려준다. 앞의 사유가 우선한다. 모르는 값·빠진 값은 모두 자격 없음(fail-closed).
    E0(현재): 업로더가 `photo` 로 확인한 사진만 자격이 있다. `unsure` 를 넣는 E1 은 독립 안전성 평가와 별도 승인 뒤에만 연다(ADR 0021)."""
    if not i.server_enabled:
        return Eligibility(False, "server_off")
    if not i.family_enabled:
        return Eligibility(False, "family_off")
    if not i.photo_found:
        return Eligibility(False, "photo_missing")
    if not i.in_family_room:
        return Eligibility(False, "not_family_room")
    if not i.uploader_consented:
        return Eligibility(False, "no_consent")
    if i.retro and not i.uploader_retro_consented:
        return Eligibility(False, "no_retro_consent")
    if i.excluded:
        return Eligibility(False, "excluded")
    if i.check_status != CHECK_PHOTO:
        return Eligibility(False, "not_confirmed_photo")
    return Eligibility(True, "ok")


def server_enabled() -> bool:
    return bool(settings.family_memory_enabled)


def _consent_active(row: MemberMemoryConsent | None) -> bool:
    return row is not None and row.consented_at is not None and row.withdrawn_at is None


def _retro_active(row: MemberMemoryConsent | None) -> bool:
    """소급 동의는 기본 동의가 유효할 때만 유효하다."""
    return _consent_active(row) and row.retro_consented_at is not None


def check_photo(db: Session, attachment_id: str, *, retro: bool = False) -> Eligibility:
    """사진 한 장의 분석 자격을 DB 상태로 판정한다(읽기 전용). 이후 단계의 재확인 4지점이 같은 함수를 쓴다."""
    ctx = repo.photo_context(db, attachment_id)
    found = ctx is not None and ctx.kind == "image" and not ctx.message_deleted
    group_id = ctx.group_id if ctx is not None else ""
    uploader = ctx.uploader_id if ctx is not None else ""
    row = repo.get_consent(db, group_id, uploader) if found else None
    return evaluate(
        EligibilityInput(
            server_enabled=server_enabled(),
            family_enabled=repo.family_enabled(db, group_id) if found else False,
            photo_found=found,
            in_family_room=bool(ctx and ctx.room_kind == "family"),
            uploader_consented=_consent_active(row),
            uploader_retro_consented=_retro_active(row),
            excluded=found and repo.is_excluded(db, attachment_id),
            check_status=ctx.check_status if ctx is not None else None,
            retro=retro,
        )
    )


def check_group_photos(
    db: Session, group_id: str
) -> tuple[list[repo.GroupPhoto], dict[str, Eligibility]]:
    """한 가족의 가족 전체방 사진 전체를 **일괄**로 판정한다(`check_photo` 와 같은 `evaluate` 규칙, 고정된 4번의 조회: 사진+판별 상태·가족 설정·동의·제외).
    사진이 몇 장이든 조회 수가 늘지 않는다. 1:1 방·지운 메시지·이미지가 아닌 첨부는 조회에서 이미 빠진다. 읽기 전용."""
    photos = repo.group_photos_with_status(db, group_id)
    server = server_enabled()
    family = repo.family_enabled(db, group_id)
    consents = repo.consents_for_group(db, group_id)
    excluded = repo.excluded_ids(db, group_id)
    result: dict[str, Eligibility] = {}
    for p in photos:
        row = consents.get(p.uploader_id)
        result[p.attachment_id] = evaluate(
            EligibilityInput(
                server_enabled=server,
                family_enabled=family,
                photo_found=True,
                in_family_room=True,
                uploader_consented=_consent_active(row),
                uploader_retro_consented=_retro_active(row),
                excluded=p.attachment_id in excluded,
                check_status=p.check_status,
            )
        )
    return photos, result


# ---------- 상태 ----------
def get_state(db: Session, user: User, group_id: str) -> MemoryStateOut:
    row = repo.get_consent(db, group_id, user.id)
    return MemoryStateOut(
        server_enabled=server_enabled(),
        family_enabled=repo.family_enabled(db, group_id),
        can_manage=repo.member_role(db, group_id, user.id) in MANAGER_ROLES,
        me=MyConsentOut(
            consented=_consent_active(row),
            retro_consented=_retro_active(row),
            consent_version=row.consent_version if _consent_active(row) else None,
        ),
    )


def _require_server_on() -> None:
    if not server_enabled():
        raise ApiError(403, "memory_disabled", "AI 추억 기능이 아직 열려 있지 않아요")


def _require_manager(db: Session, user: User, group_id: str) -> None:
    role = repo.member_role(db, group_id, user.id)
    if role is None:
        raise ApiError(403, "not_member", "이 가족 그룹의 구성원이 아니에요")
    if role not in MANAGER_ROLES:
        raise ApiError(403, "not_manager", "가족 관리자만 할 수 있어요")


# ---------- 가족 활성화 ----------
def set_family_enabled(db: Session, user: User, group_id: str, enabled: bool) -> MemoryStateOut:
    """소유자·관리자만. 켜려면 서버 스위치가 켜져 있어야 한다. 끄면 그 가족의 파생 데이터 정리 훅을 같은 트랜잭션에서 부른다.
    같은 값을 다시 보내도 결과가 같다(정리 재시도 가능)."""
    _require_manager(db, user, group_id)
    if enabled:
        _require_server_on()
    try:
        repo.set_setting(db, group_id, user.id, enabled, datetime.now(UTC))
        if not enabled:
            memory_hooks.family_disabled(db, group_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_state(db, user, group_id)


# ---------- 업로더 동의·철회 ----------
def _withdraw(db: Session, group_id: str, user_id: str, now: datetime) -> None:
    """커밋하지 않는다(부르는 쪽 트랜잭션). 행이 없으면 만들지 않는다. 정리 훅은 이미 철회된 뒤에도 다시 부른다(정리 재시도)."""
    row = repo.get_consent(db, group_id, user_id)
    if row is not None:
        if row.withdrawn_at is None:
            row.withdrawn_at = now
        row.retro_consented_at = None  # 소급 동의도 함께 끝난다
        db.flush()
    memory_hooks.member_withdrawn(db, group_id, user_id)


def set_consent(
    db: Session, user: User, group_id: str, consent: bool, consent_version: int | None = None
) -> MemoryStateOut:
    """본인 동의만 바꾼다. 동의는 서버 스위치가 켜져 있을 때만 새로 받는다. 철회는 항상 가능하고 즉시 효력이 생기며 두 번 보내도 같다.
    동의할 때 `consent_version`(앱이 보여 준 고지문 버전)을 보내면 현재 버전(`CONSENT_VERSION`)과 같아야 한다(다르면 409 `consent_version_mismatch`). 철회에는 버전을 보지 않는다."""
    now = datetime.now(UTC)
    try:
        if consent:
            _require_server_on()
            if consent_version is None and settings.family_memory_consent_version_required:
                raise ApiError(
                    409,
                    "consent_version_required",
                    "동의 안내를 확인한 뒤 다시 동의해 주세요",
                )
            if consent_version is not None and consent_version != CONSENT_VERSION:
                raise ApiError(
                    409,
                    "consent_version_mismatch",
                    "동의 안내가 바뀌었어요. 앱을 새로 고친 뒤 다시 확인해 주세요",
                )
            row = repo.get_consent(db, group_id, user.id)
            if not _consent_active(row):
                if row is None:
                    row = MemberMemoryConsent(group_id=group_id, user_id=user.id)
                    db.add(row)
                row.consent_version = CONSENT_VERSION
                row.consented_at, row.withdrawn_at = now, None
                row.retro_consented_at = None  # 새로 동의해도 소급 동의는 따로 받는다
        else:
            _withdraw(db, group_id, user.id, now)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_state(db, user, group_id)


def set_retro_consent(db: Session, user: User, group_id: str, consent: bool) -> MemoryStateOut:
    """과거 사진 소급 분석 동의(새 업로드 분석 동의와 별개, 기본 꺼짐). 기본 동의가 유효할 때만 켤 수 있다. 끄는 것은 항상 가능하다."""
    row = repo.get_consent(db, group_id, user.id)
    if consent:
        _require_server_on()
        if not _consent_active(row):
            raise ApiError(409, "consent_required", "먼저 AI 분석에 동의해 주세요")
        if row.retro_consented_at is None:
            row.retro_consented_at = datetime.now(UTC)
    elif row is not None:
        row.retro_consented_at = None
    db.commit()
    return get_state(db, user, group_id)


# ---------- 사진별 제외 ----------
def set_exclusion(
    db: Session, user: User, group_id: str, attachment_id: str, excluded: bool
) -> ExclusionOut:
    """업로더 본인만 자기 사진을 AI 분석에서 뺀다(타임라인 노출과 별개, `chat_photo_checks` 는 건드리지 않는다). 항상 가능하다."""
    ctx = repo.photo_context(db, attachment_id)
    if ctx is None or ctx.group_id != group_id or ctx.kind != "image" or ctx.message_deleted:
        raise not_found("사진")
    if ctx.uploader_id != user.id:
        if ctx.room_kind != "family":  # 남의 1:1 방 사진은 있는지도 알려 주지 않는다
            raise not_found("사진")
        raise ApiError(403, "forbidden", "내가 올린 사진만 바꿀 수 있어요")
    try:
        if excluded:
            repo.add_exclusion(db, group_id, user.id, attachment_id, datetime.now(UTC))
            memory_hooks.photo_excluded(
                db, group_id, attachment_id
            )  # 대기·진행 중인 분석 작업을 즉시 막는다
        else:
            repo.remove_exclusion(db, attachment_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ExclusionOut(attachment_id=attachment_id, excluded=excluded)


# ---------- 다른 기능이 알려 주는 사건 ----------
def _feature_ready() -> bool:
    """이 DB 에 이 기능의 표가 아직 없으면(코드가 DB 보다 먼저 배포) 지울 것도 없으니 건너뛴다."""
    return monitor.status().feature_ready("family_memory")


def _on_member_left(db: Session, group_id: str, user_id: str) -> list[Path]:
    """가족을 나가면 그 사람의 AI 분석 동의를 즉시 끝낸다(철회와 같은 정리). 같은 트랜잭션이라 실패하면 가족 나가기도 취소된다."""
    if not _feature_ready():
        return []
    _withdraw(db, group_id, user_id, datetime.now(UTC))
    return []


def _on_attachment_removed(db: Session, group_id: str, attachment_id: str) -> None:
    """채팅 사진이 지워지면 그 사진의 제외 기록도 지운다(첨부 행은 이미 지워진 뒤다)."""
    if not _feature_ready():
        return
    try:
        repo.remove_exclusion(db, attachment_id)
        db.commit()
    except Exception:
        db.rollback()
        raise


member_exit.register(_on_member_left)
memory_hooks.register_attachment_removed(_on_attachment_removed)
