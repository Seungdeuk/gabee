"""AI 추억 동의·철회·사진별 제외·자격 판정(PR1). docs/requirements/auto-memory-consent.md 의 시험 항목을 따른다.
이미지 분석·카드는 이 단계에 없으므로 여기서는 동의 기록, 자격 판정, 정리 훅만 본다."""

import io
import logging

import pytest
from PIL import Image
from sqlalchemy import func, select, update

from app.features.family_chat.models import ChatPhotoCheck
from app.features.family_group.models import GroupMember
from app.features.family_memory import service
from app.features.family_memory.models import (
    FamilyMemorySetting,
    MemberMemoryConsent,
    PhotoAnalysisExclusion,
)
from app.shared import memory_hooks
from app.shared.config import settings
from app.shared.db import SessionLocal
from tests.helpers import join_family, signup

BASE = "/family-memory"
PHOTOS = "/family-chat/photos"
MSG = "/family-chat/messages"
DIRECT_ROOM = "/family-chat/rooms/direct"
LEAVE = "/family-group/groups/me/leave"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "family_memory_enabled", True)  # 서버 스위치는 시험마다 명시한다
    # 시험이 끝나면 등록한 임시 훅을 걷는다
    saved = (
        list(memory_hooks._member_withdrawn),
        list(memory_hooks._family_disabled),
        list(memory_hooks._attachment_removed),
    )
    yield
    memory_hooks._member_withdrawn[:] = saved[0]
    memory_hooks._family_disabled[:] = saved[1]
    memory_hooks._attachment_removed[:] = saved[2]


def _uid(client, headers):
    return client.get("/family-group/me", headers=headers).json()["id"]


def _photo(client, headers, room_id=None):
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(out, format="JPEG")
    r = client.post(
        PHOTOS,
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        data={"room_id": room_id} if room_id else None,
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["attachment"]["id"], r.json()["id"]


def _set_check(attachment_id, status):
    """업로더가 일반 사진으로 확인한 상태를 시험용으로 만든다(D-13: 자동 판별은 photo 를 못 만든다)."""
    with SessionLocal() as db:
        db.execute(
            update(ChatPhotoCheck)
            .where(ChatPhotoCheck.attachment_id == attachment_id)
            .values(status=status)
        )
        db.commit()


def _check_status(attachment_id):
    with SessionLocal() as db:
        return db.scalar(
            select(ChatPhotoCheck.status).where(ChatPhotoCheck.attachment_id == attachment_id)
        )


def _eligibility(attachment_id, **kw):
    with SessionLocal() as db:
        return service.check_photo(db, attachment_id, **kw)


def _count(model):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model))


def _enable_all(client, owner, uploader):
    assert client.put(f"{BASE}/settings", json={"enabled": True}, headers=owner).status_code == 200
    assert (
        client.put(f"{BASE}/consent", json={"consent": True}, headers=uploader).status_code == 200
    )


# ---------- 기본 꺼짐 ----------
def test_default_everything_off(client, family):
    a, b, _ = family
    state = client.get(f"{BASE}/settings", headers=b).json()
    assert state["family_enabled"] is False
    assert state["me"] == {"consented": False, "retro_consented": False, "consent_version": None}
    assert state["can_manage"] is False
    assert client.get(f"{BASE}/settings", headers=a).json()["can_manage"] is True


def test_server_switch_off_blocks_enable_and_consent(client, family, monkeypatch):
    a, b, _ = family
    monkeypatch.setattr(settings, "family_memory_enabled", False)
    assert client.get(f"{BASE}/settings", headers=a).json()["server_enabled"] is False
    r = client.put(f"{BASE}/settings", json={"enabled": True}, headers=a)
    assert (r.status_code, r.json()["code"]) == (403, "memory_disabled")
    r = client.put(f"{BASE}/consent", json={"consent": True}, headers=b)
    assert (r.status_code, r.json()["code"]) == (403, "memory_disabled")
    assert _count(FamilyMemorySetting) == 0 and _count(MemberMemoryConsent) == 0


def test_server_switch_off_blocks_eligibility_even_when_all_on(client, family, monkeypatch):
    a, b, _ = family
    attachment_id, _ = _photo(client, b)
    _enable_all(client, a, b)
    _set_check(attachment_id, "photo")
    assert _eligibility(attachment_id).eligible is True
    monkeypatch.setattr(settings, "family_memory_enabled", False)
    result = _eligibility(attachment_id)
    assert (result.eligible, result.reason) == (False, "server_off")


# ---------- 권한 ----------
def test_member_cannot_change_family_setting_but_admin_can(client, family):
    a, b, group = family
    r = client.put(f"{BASE}/settings", json={"enabled": True}, headers=b)
    assert (r.status_code, r.json()["code"]) == (403, "not_manager")
    with SessionLocal() as db:
        db.execute(
            update(GroupMember)
            .where(GroupMember.group_id == group["id"], GroupMember.user_id == _uid(client, b))
            .values(role="admin")
        )
        db.commit()
    assert client.put(f"{BASE}/settings", json={"enabled": True}, headers=b).status_code == 200
    assert client.get(f"{BASE}/settings", headers=a).json()["family_enabled"] is True


def test_other_family_is_isolated(client, family, other_family):
    a, b, _ = family
    _enable_all(client, a, b)
    outsider = other_family
    state = client.get(f"{BASE}/settings", headers=outsider).json()
    assert state["family_enabled"] is False and state["me"]["consented"] is False
    # 남의 가족 설정을 바꿔도 우리 가족에 영향이 없다
    assert (
        client.put(f"{BASE}/settings", json={"enabled": False}, headers=outsider).status_code == 200
    )
    assert client.get(f"{BASE}/settings", headers=a).json()["family_enabled"] is True
    # 남의 사진은 제외 설정을 못 한다(있는지도 알려 주지 않는다)
    attachment_id, _ = _photo(client, b)
    r = client.put(
        f"{BASE}/photos/{attachment_id}/exclusion", json={"excluded": True}, headers=outsider
    )
    assert r.status_code == 404
    assert _count(PhotoAnalysisExclusion) == 0


def test_requires_login_and_group(client):
    assert client.get(f"{BASE}/settings").status_code == 401
    lone = signup(client, "혼자")  # 가족이 없다
    assert client.get(f"{BASE}/settings", headers=lone).status_code == 400


# ---------- 동의·철회·소급 ----------
def test_new_member_is_not_consented_and_consent_is_per_uploader(client, family):
    a, b, _ = family
    assert client.put(f"{BASE}/settings", json={"enabled": True}, headers=a).status_code == 200
    assert client.get(f"{BASE}/settings", headers=b).json()["me"]["consented"] is False
    client.put(f"{BASE}/consent", json={"consent": True}, headers=b)
    assert client.get(f"{BASE}/settings", headers=b).json()["me"]["consented"] is True
    assert (
        client.get(f"{BASE}/settings", headers=a).json()["me"]["consented"] is False
    )  # 소유자는 별개


def test_withdraw_is_immediate_and_idempotent(client, family):
    a, b, _ = family
    attachment_id, _ = _photo(client, b)
    _enable_all(client, a, b)
    _set_check(attachment_id, "photo")
    assert _eligibility(attachment_id).eligible is True
    first = client.put(f"{BASE}/consent", json={"consent": False}, headers=b)
    assert first.status_code == 200 and first.json()["me"]["consented"] is False
    assert _eligibility(attachment_id).reason == "no_consent"  # 같은 요청 직후부터 자격 없음
    second = client.put(f"{BASE}/consent", json={"consent": False}, headers=b)
    assert second.status_code == 200 and second.json() == first.json()
    # 철회한 뒤에도 다른 사람에게는 영향이 없다
    assert client.put(f"{BASE}/consent", json={"consent": True}, headers=a).status_code == 200


def test_withdraw_without_any_consent_row_creates_nothing(client, family):
    _, b, _ = family
    assert client.put(f"{BASE}/consent", json={"consent": False}, headers=b).status_code == 200
    assert _count(MemberMemoryConsent) == 0


def test_retro_consent_is_separate_and_needs_base_consent(client, family):
    a, b, _ = family
    attachment_id, _ = _photo(client, b)
    r = client.put(f"{BASE}/consent/retro", json={"consent": True}, headers=b)
    assert (r.status_code, r.json()["code"]) == (409, "consent_required")
    _enable_all(client, a, b)
    _set_check(attachment_id, "photo")
    assert client.get(f"{BASE}/settings", headers=b).json()["me"]["retro_consented"] is False
    assert _eligibility(attachment_id, retro=True).reason == "no_retro_consent"
    assert _eligibility(attachment_id).eligible is True  # 새 업로드 분석은 소급 동의와 무관
    client.put(f"{BASE}/consent/retro", json={"consent": True}, headers=b)
    assert _eligibility(attachment_id, retro=True).eligible is True
    # 기본 동의를 철회하면 소급 동의도 함께 끝나고, 다시 동의해도 소급은 따로 받는다
    client.put(f"{BASE}/consent", json={"consent": False}, headers=b)
    client.put(f"{BASE}/consent", json={"consent": True}, headers=b)
    assert client.get(f"{BASE}/settings", headers=b).json()["me"]["retro_consented"] is False


def test_family_disable_calls_cleanup_hook_and_is_repeatable(client, family):
    a, _, group = family
    calls = []
    memory_hooks.register_family_disabled(lambda db, group_id: calls.append(group_id))
    assert client.put(f"{BASE}/settings", json={"enabled": True}, headers=a).status_code == 200
    assert calls == []
    for _ in range(2):  # 같은 요청을 다시 보내도 정리가 다시 불리고 결과는 같다
        r = client.put(f"{BASE}/settings", json={"enabled": False}, headers=a)
        assert r.status_code == 200 and r.json()["family_enabled"] is False
    assert calls == [group["id"], group["id"]]


# ---------- 사진별 제외 ----------
def test_only_uploader_can_exclude_own_photo(client, family):
    a, b, _ = family
    attachment_id, _ = _photo(client, b)
    url = f"{BASE}/photos/{attachment_id}/exclusion"
    r = client.put(url, json={"excluded": True}, headers=a)  # 가족 전체방 사진: 남의 것은 403
    assert (r.status_code, r.json()["code"]) == (403, "forbidden")
    assert _count(PhotoAnalysisExclusion) == 0
    assert client.put(url, json={"excluded": True}, headers=b).json() == {
        "attachment_id": attachment_id,
        "excluded": True,
    }
    assert client.put(url, json={"excluded": True}, headers=b).status_code == 200  # 두 번째도 같다
    assert _count(PhotoAnalysisExclusion) == 1
    assert client.put(url, json={"excluded": False}, headers=a).status_code == 403
    assert client.put(url, json={"excluded": False}, headers=b).status_code == 200
    assert _count(PhotoAnalysisExclusion) == 0
    assert (
        client.put(f"{BASE}/photos/nope/exclusion", json={"excluded": True}, headers=b).status_code
        == 404
    )


def test_exclusion_does_not_touch_timeline_state(client, family):
    a, b, _ = family
    attachment_id, _ = _photo(client, b)
    _set_check(attachment_id, "photo")
    client.put(f"{BASE}/photos/{attachment_id}/exclusion", json={"excluded": True}, headers=b)
    assert _check_status(attachment_id) == "photo"  # 타임라인 제외와 별개


def test_exclusion_is_available_even_when_server_switch_is_off(client, family, monkeypatch):
    _, b, _ = family
    attachment_id, _ = _photo(client, b)
    monkeypatch.setattr(settings, "family_memory_enabled", False)
    r = client.put(f"{BASE}/photos/{attachment_id}/exclusion", json={"excluded": True}, headers=b)
    assert r.status_code == 200


# ---------- 자격 판정 ----------
def test_eligibility_matrix(client, family):
    a, b, _ = family
    attachment_id, _ = _photo(client, b)
    url = f"{BASE}/photos/{attachment_id}/exclusion"

    assert _eligibility(attachment_id).reason == "family_off"  # 가족 미활성
    client.put(f"{BASE}/settings", json={"enabled": True}, headers=a)
    assert _eligibility(attachment_id).reason == "no_consent"  # 업로더 미동의(신규 구성원 기본)
    client.put(f"{BASE}/consent", json={"consent": True}, headers=b)
    assert _eligibility(attachment_id).reason == "not_confirmed_photo"  # 자동 판별 전(pending)
    for status in ("pending", "document", "unsure", "failed", "excluded"):
        _set_check(attachment_id, status)
        assert _eligibility(attachment_id).eligible is False, status  # E0: photo 만 자격
    _set_check(attachment_id, "photo")
    assert _eligibility(attachment_id).eligible is True
    client.put(url, json={"excluded": True}, headers=b)
    assert _eligibility(attachment_id).reason == "excluded"
    client.put(url, json={"excluded": False}, headers=b)
    client.put(f"{BASE}/settings", json={"enabled": False}, headers=a)
    assert _eligibility(attachment_id).reason == "family_off"
    assert _eligibility("does-not-exist").eligible is False  # 모르는 사진도 자격 없음(fail-closed)


def test_direct_room_photo_is_never_eligible(client, family):
    a, b, _ = family
    _enable_all(client, a, b)
    room = client.post(DIRECT_ROOM, json={"user_id": _uid(client, a)}, headers=b).json()
    attachment_id, _ = _photo(client, b, room_id=room["id"])
    assert _eligibility(attachment_id).reason == "not_family_room"
    # 1:1 방 사진은 업로더가 아닌 상대가 제외 설정을 해도 있는 사진인지 알려 주지 않는다(404)
    url = f"{BASE}/photos/{attachment_id}/exclusion"
    assert client.put(url, json={"excluded": True}, headers=a).status_code == 404


def test_eligibility_does_not_write_check_state_or_ai_settings(client, family):
    a, b, _ = family
    attachment_id, _ = _photo(client, b)
    _enable_all(client, a, b)
    _set_check(attachment_id, "unsure")
    _eligibility(attachment_id)
    assert _check_status(attachment_id) == "unsure"  # D-13: 읽기만 한다
    with SessionLocal() as db:
        from app.shared.ai_usage import AiGroupSetting

        assert db.scalar(select(func.count()).select_from(AiGroupSetting)) == 0


def test_memory_switch_and_chat_ai_consent_are_independent(client, family):
    a, _, group = family
    assert (
        client.put("/family-chat/ai/settings", json={"enabled": True}, headers=a).status_code == 200
    )
    assert client.get(f"{BASE}/settings", headers=a).json()["family_enabled"] is False
    client.put(f"{BASE}/settings", json={"enabled": True}, headers=a)
    client.put("/family-chat/ai/settings", json={"enabled": False}, headers=a)
    assert client.get(f"{BASE}/settings", headers=a).json()["family_enabled"] is True


# ---------- 정리 훅: 철회·나가기·사진 삭제·가족 삭제 ----------
def test_withdraw_cleanup_failure_rolls_back_the_withdrawal(client, family):
    a, b, group = family
    _enable_all(client, a, b)

    def boom(db, group_id, user_id):
        raise RuntimeError("cleanup failed")

    memory_hooks.register_member_withdrawn(boom)
    with SessionLocal() as db:
        user = db.get(
            __import__("app.features.family_group.models", fromlist=["User"]).User, _uid(client, b)
        )
        with pytest.raises(RuntimeError):
            service.set_consent(db, user, group["id"], False)
    with SessionLocal() as db:
        row = db.get(MemberMemoryConsent, (group["id"], _uid(client, b)))
        assert row.withdrawn_at is None  # 철회가 반쯤 적용된 상태를 남기지 않는다


def test_leaving_family_withdraws_consent_and_rejoin_starts_unconsented(client, family):
    a, b, group = family
    _enable_all(client, a, b)
    client.put(f"{BASE}/consent", json={"consent": True}, headers=a)
    b_id = _uid(client, b)
    calls = []
    memory_hooks.register_member_withdrawn(lambda db, g, u: calls.append((g, u)))
    assert client.post(LEAVE, headers=b).status_code in (200, 204)
    assert (group["id"], b_id) in calls
    with SessionLocal() as db:
        row = db.get(MemberMemoryConsent, (group["id"], b_id))
        assert row.withdrawn_at is not None and row.retro_consented_at is None
        assert db.get(MemberMemoryConsent, (group["id"], _uid(client, a))).withdrawn_at is None
    assert join_family(client, a, group["invite_code"], b).status_code == 200
    assert client.get(f"{BASE}/settings", headers=b).json()["me"]["consented"] is False


def test_leave_is_rolled_back_when_cleanup_fails(client, family):
    a, b, group = family
    _enable_all(client, a, b)

    def boom(db, group_id, user_id):
        raise RuntimeError("cleanup failed")

    memory_hooks.register_member_withdrawn(boom)
    with pytest.raises(RuntimeError):
        client.post(LEAVE, headers=b)
    with SessionLocal() as db:
        assert db.get(GroupMember, (group["id"], _uid(client, b))) is not None  # 나가기도 취소됨
        assert db.get(MemberMemoryConsent, (group["id"], _uid(client, b))).withdrawn_at is None


def test_deleting_photo_removes_exclusion_and_survives_hook_failure(client, family):
    a, b, _ = family
    attachment_id, message_id = _photo(client, b)
    client.put(f"{BASE}/photos/{attachment_id}/exclusion", json={"excluded": True}, headers=b)
    assert _count(PhotoAnalysisExclusion) == 1
    assert client.delete(f"{MSG}/{message_id}", headers=b).status_code == 200
    assert _count(PhotoAnalysisExclusion) == 0

    def boom(db, group_id, attachment_id):
        raise RuntimeError("cleanup failed")

    memory_hooks.register_attachment_removed(boom)
    other_attachment, other_message = _photo(client, b)
    assert (
        client.delete(f"{MSG}/{other_message}", headers=b).status_code == 200
    )  # 훅이 실패해도 삭제 성공


def test_photo_delete_works_when_no_hook_is_registered(client, family, monkeypatch):
    _, b, _ = family
    monkeypatch.setattr(memory_hooks, "_attachment_removed", [])
    _, message_id = _photo(client, b)
    assert client.delete(f"{MSG}/{message_id}", headers=b).status_code == 200


def test_family_purge_removes_memory_rows(client):
    owner = signup(client, "혼자지기")
    client.post("/family-group/groups", json={"name": "우리"}, headers=owner)
    attachment_id, _ = _photo(client, owner)
    _enable_all(client, owner, owner)
    client.put(f"{BASE}/photos/{attachment_id}/exclusion", json={"excluded": True}, headers=owner)
    assert (
        _count(FamilyMemorySetting),
        _count(MemberMemoryConsent),
        _count(PhotoAnalysisExclusion),
    ) == (1, 1, 1)
    assert client.post(LEAVE, headers=owner).status_code in (
        200,
        204,
    )  # 혼자 남은 소유자: 가족 삭제
    assert (
        _count(FamilyMemorySetting),
        _count(MemberMemoryConsent),
        _count(PhotoAnalysisExclusion),
    ) == (0, 0, 0)


# ---------- 로그 ----------
def test_logs_do_not_contain_ids_or_photo_details(client, family, caplog):
    a, b, _ = family
    caplog.set_level(logging.DEBUG)
    attachment_id, _ = _photo(client, b)
    _enable_all(client, a, b)
    client.put(f"{BASE}/photos/{attachment_id}/exclusion", json={"excluded": True}, headers=b)
    client.put(f"{BASE}/consent", json={"consent": False}, headers=b)
    _eligibility(attachment_id)
    # 테스트 클라이언트(httpx)가 찍는 요청 URL 은 서버 로그가 아니므로 제외하고, 앱(app.*) 로거의 기록만 본다
    text = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("app."))
    assert attachment_id not in text and _uid(client, b) not in text
