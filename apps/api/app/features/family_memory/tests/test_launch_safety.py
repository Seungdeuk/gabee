"""출시 준비 안전장치(PR9): 동의 버전 우회 방지 스위치, 앱·서버 동의 버전 일치, 대조 정리의 지속 실패 감지(ERROR 로그·상태), 읽기 전용 점검 CLI.
고지문(T31)은 미확정이라 실제 동의 수집은 켜지지 않는다 — 여기서는 확정 뒤에 켤 스위치가 올바르게 막는지만 본다."""

import io
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import update

from app.features.family_memory import embedding_repository as emb
from app.features.family_memory import reconcile, reconcile_check, service, worker
from app.features.family_memory.models import MemberMemoryConsent
from app.shared.config import settings
from app.shared.db import SessionLocal

BASE = "/family-memory"
REPO = Path(__file__).resolve().parents[6]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "family_memory_enabled", True)
    worker.reconcile_health.__init__()  # 시험마다 상태를 비운다


def _gid(client, headers):
    return client.get("/family-group/groups/me", headers=headers).json()["id"]


def _uid(client, headers):
    return client.get("/family-group/me", headers=headers).json()["id"]


# ---------- 동의 버전 ----------
def test_app_and_server_agree_on_the_consent_notice_version():
    source = (
        REPO / "apps" / "mobile" / "src" / "features" / "family-memory" / "consent.js"
    ).read_text(encoding="utf-8")
    match = re.search(r"export const REQUIRED_CONSENT_VERSION = (\d+);", source)
    assert (
        match and int(match.group(1)) == service.CONSENT_VERSION
    )  # 둘 중 하나만 올리면 이 시험이 깨진다
    assert re.search(
        r"export const MEMORY_NOTICE_FINAL = false;", source
    )  # 고지문 확정 전: 앱이 동의를 받지 않는다


def test_consent_version_required_switch_blocks_a_missing_or_wrong_version(
    client, family, monkeypatch
):
    a, b, _ = family
    assert settings.family_memory_consent_version_required is False  # 기본 꺼짐: 기존 호출 호환
    assert client.put(f"{BASE}/settings", json={"enabled": True}, headers=a).status_code == 200
    monkeypatch.setattr(settings, "family_memory_consent_version_required", True)
    missing = client.put(f"{BASE}/consent", json={"consent": True}, headers=a)
    assert missing.status_code == 409 and missing.json()["code"] == "consent_version_required"
    wrong = client.put(f"{BASE}/consent", json={"consent": True, "consent_version": 99}, headers=a)
    assert wrong.status_code == 409 and wrong.json()["code"] == "consent_version_mismatch"
    assert (
        client.get(f"{BASE}/settings", headers=a).json()["me"]["consented"] is False
    )  # 우회 시도는 동의를 기록하지 않는다
    ok = client.put(
        f"{BASE}/consent",
        json={"consent": True, "consent_version": service.CONSENT_VERSION},
        headers=a,
    )
    assert ok.status_code == 200 and ok.json()["me"]["consent_version"] == service.CONSENT_VERSION
    # 소급 동의는 기본 동의가 있을 때만(별개), 철회는 버전을 요구하지 않는다
    assert client.put(f"{BASE}/consent/retro", json={"consent": True}, headers=b).status_code == 409
    assert client.put(f"{BASE}/consent/retro", json={"consent": True}, headers=a).status_code == 200
    assert client.put(f"{BASE}/consent", json={"consent": False}, headers=a).status_code == 200
    state = client.get(f"{BASE}/settings", headers=a).json()["me"]
    assert state == {
        "consented": False,
        "retro_consented": False,
        "consent_version": None,
    }  # 철회가 소급 동의도 함께 끝낸다


# ---------- 대조 정리 지속 실패 감지 ----------
def test_reconcile_failures_are_counted_and_logged_as_error_after_the_threshold(
    monkeypatch, caplog
):
    def boom(db, now=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(reconcile, "reconcile", boom)
    levels = []
    with caplog.at_level(logging.WARNING):
        for _ in range(worker.RECONCILE_ALERT_AFTER + 1):
            assert worker.reconcile_derived() == 0
            levels.append(caplog.records[-1].levelno)
    assert levels[: worker.RECONCILE_ALERT_AFTER - 1] == [logging.WARNING] * (
        worker.RECONCILE_ALERT_AFTER - 1
    )
    assert (
        levels[worker.RECONCILE_ALERT_AFTER - 1 :] == [logging.ERROR] * 2
    )  # 연속 실패가 기준 이상이면 ERROR
    assert worker.reconcile_health.consecutive_failures == worker.RECONCILE_ALERT_AFTER + 1
    assert worker.reconcile_health.last_error == "RuntimeError"
    assert "family memory reconcile failed error=RuntimeError consecutive=" in caplog.text
    assert "db down" not in caplog.text  # 예외 메시지(내용)는 남기지 않고 종류만


def test_reconcile_success_resets_the_failure_count_and_reports_leftovers(client, family, caplog):
    a, _, _ = family
    _insert_leftover_embedding(client, a)  # 동의 없이 남은 임베딩(즉시 정리가 못 지운 것)
    worker.reconcile_health.failed("RuntimeError")
    worker.reconcile_health.failed("RuntimeError")
    with caplog.at_level(logging.WARNING):
        assert worker.reconcile_derived() == 1  # 뒤늦게라도 지우고
    assert (
        worker.reconcile_health.consecutive_failures == 0
        and worker.reconcile_health.last_error is None
    )
    assert (
        worker.reconcile_health.last_ok_at is not None and worker.reconcile_health.last_deleted == 1
    )
    assert (
        "family memory reconcile removed leftovers count=1" in caplog.text
    )  # 남았던 것이 있었다는 사실을 남긴다(개수만)
    assert worker.reconcile_derived() == 0  # 다시 돌려도 0(멱등)


# ---------- 점검 CLI ----------
def _insert_leftover_embedding(client, headers):
    """동의가 없는 사람의 임베딩이 남은 상태(정리 실패 뒤)를 만든다: 사진 한 장을 올리고 임베딩 줄을 넣은 뒤 동의를 철회 상태로 둔다."""
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (40, 30), (10, 20, 30)).save(out, format="JPEG")
    r = client.post(
        "/family-chat/photos",
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    att = r.json()["attachment"]["id"]
    with SessionLocal() as db:
        emb.upsert(
            db,
            _gid(client, headers),
            att,
            _uid(client, headers),
            "m",
            "v",
            2,
            b"\x00" * 8,
            datetime.now(UTC),
        )
        db.commit()
    return att


def test_reconcile_check_exit_codes_and_output_hold_only_counts(
    client, family, capsys, monkeypatch
):
    a, _, _ = family
    assert reconcile_check.main() == reconcile_check.EXIT_OK  # 아무것도 없으면 0
    assert json.loads(capsys.readouterr().out) == {
        "ok": True, "pending": 0, "embeddings": 0, "candidate_photos": 0, "active_jobs": 0, "done_jobs": 0,
    }  # fmt: skip
    att = _insert_leftover_embedding(client, a)  # 가족 설정·동의가 없는 사람의 임베딩이 남았다
    assert reconcile_check.main() == reconcile_check.EXIT_PENDING
    out = capsys.readouterr().out
    body = json.loads(out)
    assert body["ok"] is False and body["embeddings"] == 1 and body["pending"] == 1
    assert (
        att not in out and _uid(client, a) not in out and "chat_photos" not in out
    )  # 개수만 낸다(id·경로 없음)
    with SessionLocal() as db:  # 읽기 전용: 점검이 아무것도 지우지 않았다
        assert emb.count(db) == 1
    with SessionLocal() as db:
        assert reconcile.reconcile(db).embeddings == 1  # 지우는 일은 대조 정리가 한다
        db.commit()
    assert reconcile_check.main() == reconcile_check.EXIT_OK
    capsys.readouterr()

    class Broken:
        def __enter__(self):
            raise RuntimeError("db unreachable password=secret")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(reconcile_check, "SessionLocal", lambda: Broken())
    assert reconcile_check.main() == reconcile_check.EXIT_ERROR  # 연결 실패는 2
    err = capsys.readouterr().out
    assert json.loads(err) == {"ok": False, "error": "RuntimeError"} and "secret" not in err


def test_reconcile_check_does_not_count_data_of_users_who_still_consent(client, family, capsys):
    a, _, _ = family
    assert client.put(f"{BASE}/settings", json={"enabled": True}, headers=a).status_code == 200
    assert client.put(f"{BASE}/consent", json={"consent": True}, headers=a).status_code == 200
    _insert_leftover_embedding(client, a)
    assert reconcile_check.main() == reconcile_check.EXIT_OK  # 동의가 유효하면 남은 것이 아니다
    capsys.readouterr()
    with SessionLocal() as db:
        db.execute(update(MemberMemoryConsent).values(withdrawn_at=datetime.now(UTC)))
        db.commit()
    assert reconcile_check.main() == reconcile_check.EXIT_PENDING
