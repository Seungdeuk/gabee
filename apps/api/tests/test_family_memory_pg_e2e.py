"""AI 추억 동의·설정 표 3개(family_memory_settings, member_memory_consents, photo_analysis_exclusions)와 서비스 흐름을
PostgreSQL 16(최신 Alembic head)에서 검증한다 — 서버 기본값, 실제 외래키 CASCADE, 철회·가족 나가기·사진 삭제·가족 삭제 정리.

Docker 가 필요하므로 GABEE_PG16_E2E=1 일 때만 실행한다. 이 시험이 띄운 임시 컨테이너(메모리 768MB·CPU 1개·데이터는 메모리 위 tmpfs)만 쓰며
공용 DB·개인 DB·MVP DB 에는 접속하지 않는다. 일반 시험(SQLite)이 보지 못하는 PostgreSQL 쪽 동작(기본값·CASCADE·부분 실패)을 본다.
"""

import io
import os
import secrets
import time

import psycopg
import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.features.family_memory import service
from app.shared.config import settings
from tests import test_signup_pg_e2e as _base
from tests.test_join_pg_e2e import account
from tests.test_schema_gate_pg_e2e import IMAGE, admin, docker, url

rows = _base.rows
pg_client = _base.pg_client  # 이 모듈의 pg16 픽스처(아래, 자원 제한 포함)를 이름으로 찾아 쓴다

pytestmark = pytest.mark.skipif(
    os.environ.get("GABEE_PG16_E2E") != "1", reason="GABEE_PG16_E2E=1 일 때만 실행(Docker 필요)"
)

P = "/family-group"
M = "/family-memory"


@pytest.fixture(scope="module")
def pg16():
    """다른 PG e2e 시험의 픽스처와 같지만 자원을 제한한다(메모리 768MB, CPU 1개, 데이터는 tmpfs 라 볼륨이 남지 않는다)."""
    name, password = f"gabee-memory-e2e-{secrets.token_hex(3)}", secrets.token_urlsafe(12)
    env = {**os.environ, "POSTGRES_PASSWORD": password}
    docker(
        "run", "-d", "--rm", "--name", name,
        "--memory", "768m", "--cpus", "1",
        "--tmpfs", "/var/lib/postgresql/data:rw,size=256m",
        "-e", "POSTGRES_PASSWORD", "-p", "127.0.0.1::5432", IMAGE,
        env=env,
    )  # fmt: skip
    try:
        for _ in range(60):
            ready = docker(
                "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres", check=False
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        time.sleep(2)
        port = int(
            docker("port", name, "5432/tcp").stdout.strip().splitlines()[0].rsplit(":", 1)[1]
        )
        yield {"port": port, "password": password}
    finally:
        docker("rm", "-f", name, check=False)


@pytest.fixture(autouse=True)
def _settings(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "family_memory_enabled", True)


def _family(client):
    owner = account(client, "owner_kim")
    group = client.post(f"{P}/groups", json={"name": "우리 가족"}, headers=owner).json()
    guest = account(client, "guest_lee")
    req = client.post(f"{P}/groups/join", json={"code": group["invite_code"]}, headers=guest).json()
    if req["status"] == "pending":
        r = client.post(f"{P}/groups/join-requests/{req['id']}/approve", headers=owner)
        assert r.status_code == 200, r.text
    return owner, guest, group


def _me(client, headers):
    me = client.get(f"{P}/me", headers=headers).json()
    return me["id"], me["active_group_id"]


def _photo(client, headers):
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(out, format="JPEG")
    r = client.post(
        "/family-chat/photos",
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["attachment"]["id"], r.json()["id"]


def _count(pg, table):
    return rows(pg, f"SELECT count(*) FROM {table}")[0][0]


def _eligibility(pg, attachment_id):
    engine = create_engine(url(pg))
    try:
        with sessionmaker(bind=engine)() as db:
            return service.check_photo(db, attachment_id)
    finally:
        engine.dispose()


def test_alembic_head_and_server_defaults_on_postgres(pg_client):
    _, pg = pg_client
    from tests.test_schema_gate_pg_e2e import HEAD  # 코드의 head 리비전

    assert rows(pg, "SELECT version_num FROM alembic_version") == [(HEAD,)]
    client, _ = pg_client
    owner, _, group = _family(client)
    _, gid = _me(client, owner)
    # enabled 를 생략하고 넣으면 서버 기본값 false(행이 있어도 기본은 꺼짐)
    with admin(pg) as conn:
        conn.execute(
            "INSERT INTO family_memory_settings (group_id, updated_at) VALUES (%s, now())", (gid,)
        )
    assert rows(pg, "SELECT enabled FROM family_memory_settings WHERE group_id=%s", gid) == [
        (False,)
    ]
    assert group["id"] == gid


def test_consent_flow_withdraw_exclusion_and_eligibility_on_postgres(pg_client):
    client, pg = pg_client
    owner, guest, _ = _family(client)
    guest_id, gid = _me(client, guest)
    attachment_id, _ = _photo(client, guest)

    assert _eligibility(pg, attachment_id).reason == "family_off"
    assert (
        client.put(f"{M}/settings", json={"enabled": True}, headers=guest).status_code == 403
    )  # member
    assert client.put(f"{M}/settings", json={"enabled": True}, headers=owner).status_code == 200
    assert _eligibility(pg, attachment_id).reason == "no_consent"
    assert client.put(f"{M}/consent", json={"consent": True}, headers=guest).status_code == 200
    with admin(
        pg
    ) as conn:  # 업로더가 일반 사진으로 확인한 상태(D-13: 자동 판별은 photo 를 못 만든다)
        conn.execute(
            "UPDATE chat_photo_checks SET status='photo' WHERE attachment_id=%s", (attachment_id,)
        )
    assert _eligibility(pg, attachment_id).eligible is True

    # 사진별 제외: 업로더 본인만. 다른 구성원은 403, 제외하면 자격 없음, 판별 상태는 그대로
    url_ex = f"{M}/photos/{attachment_id}/exclusion"
    assert client.put(url_ex, json={"excluded": True}, headers=owner).status_code == 403
    assert client.put(url_ex, json={"excluded": True}, headers=guest).status_code == 200
    assert _eligibility(pg, attachment_id).reason == "excluded"
    assert rows(
        pg, "SELECT status FROM chat_photo_checks WHERE attachment_id=%s", attachment_id
    ) == [("photo",)]
    assert client.put(url_ex, json={"excluded": False}, headers=guest).status_code == 200

    # 철회는 즉시 효력, 두 번 보내도 같다(withdrawn_at 은 처음 철회한 시각이 유지된다)
    assert (
        client.put(f"{M}/consent/retro", json={"consent": True}, headers=guest).status_code == 200
    )
    assert client.put(f"{M}/consent", json={"consent": False}, headers=guest).status_code == 200
    first = rows(
        pg,
        "SELECT withdrawn_at, retro_consented_at FROM member_memory_consents WHERE user_id=%s",
        guest_id,
    )
    assert client.put(f"{M}/consent", json={"consent": False}, headers=guest).status_code == 200
    assert (
        rows(
            pg,
            "SELECT withdrawn_at, retro_consented_at FROM member_memory_consents WHERE user_id=%s",
            guest_id,
        )
        == first
    )
    assert first[0][0] is not None and first[0][1] is None  # 소급 동의도 함께 끝남
    assert _eligibility(pg, attachment_id).reason == "no_consent"
    assert _count(pg, "ai_group_settings") == 0  # 대화 분석 동의 표를 건드리지 않는다
    assert gid


def test_photo_delete_removes_exclusion_and_attachment_cascade_on_postgres(pg_client):
    client, pg = pg_client
    _, guest, _ = _family(client)
    attachment_id, message_id = _photo(client, guest)
    assert (
        client.put(
            f"{M}/photos/{attachment_id}/exclusion", json={"excluded": True}, headers=guest
        ).status_code
        == 200
    )
    assert _count(pg, "photo_analysis_exclusions") == 1
    assert client.delete(f"/family-chat/messages/{message_id}", headers=guest).status_code == 200
    assert _count(pg, "photo_analysis_exclusions") == 0

    # 훅과 별개로 DB 가 첨부 삭제를 따라간다(ON DELETE CASCADE)
    other_id, _ = _photo(client, guest)
    client.put(f"{M}/photos/{other_id}/exclusion", json={"excluded": True}, headers=guest)
    assert _count(pg, "photo_analysis_exclusions") == 1
    with admin(pg) as conn:
        conn.execute("DELETE FROM message_attachments WHERE id=%s", (other_id,))
    assert _count(pg, "photo_analysis_exclusions") == 0


def test_leaving_family_withdraws_consent_and_purge_deletes_all_rows_on_postgres(pg_client):
    client, pg = pg_client
    owner, guest, _ = _family(client)
    guest_id, gid = _me(client, guest)
    owner_id, _ = _me(client, owner)
    attachment_id, _ = _photo(client, guest)
    client.put(f"{M}/settings", json={"enabled": True}, headers=owner)
    client.put(f"{M}/consent", json={"consent": True}, headers=guest)
    client.put(f"{M}/consent", json={"consent": True}, headers=owner)
    client.put(f"{M}/photos/{attachment_id}/exclusion", json={"excluded": True}, headers=guest)

    assert client.post(f"{P}/groups/me/leave", headers=guest).status_code == 204
    assert rows(
        pg, "SELECT withdrawn_at IS NOT NULL FROM member_memory_consents WHERE user_id=%s", guest_id
    ) == [(True,)]
    assert rows(
        pg, "SELECT withdrawn_at IS NULL FROM member_memory_consents WHERE user_id=%s", owner_id
    ) == [(True,)]

    # 혼자 남은 소유자가 나가면 가족과 함께 세 표의 행이 모두 지워진다(group_purge)
    assert client.post(f"{P}/groups/me/leave", headers=owner).status_code == 204
    for table in ("family_memory_settings", "member_memory_consents", "photo_analysis_exclusions"):
        assert _count(pg, table) == 0, table
    assert rows(pg, "SELECT count(*) FROM groups WHERE id=%s", gid) == [(0,)]


def test_failed_cleanup_does_not_roll_back_withdrawal_or_leave_on_postgres(pg_client):
    """PR6 안전성: 정리가 **실제 DB 오류**로 실패해도(PostgreSQL 은 오류가 나면 트랜잭션이 중단되므로 SAVEPOINT 가 필요하다) 철회·가족 나가기는 수락돼 유지된다."""
    from sqlalchemy import text

    from app.shared import memory_hooks

    client, pg = pg_client
    owner, guest, _ = _family(client)
    guest_id, _ = _me(client, guest)
    client.put(f"{M}/settings", json={"enabled": True}, headers=owner)
    client.put(f"{M}/consent", json={"consent": True}, headers=guest)

    def db_error(db, group_id, user_id):
        db.execute(text("SELECT * FROM no_such_table_for_cleanup"))  # 진짜 DB 오류

    saved = list(memory_hooks._member_withdrawn)
    memory_hooks.register_member_withdrawn(db_error)
    try:
        assert client.put(f"{M}/consent", json={"consent": False}, headers=guest).status_code == 200
        assert rows(
            pg,
            "SELECT withdrawn_at IS NOT NULL FROM member_memory_consents WHERE user_id=%s",
            guest_id,
        ) == [(True,)]  # 철회가 유지된다
        assert (
            client.post(f"{P}/groups/me/leave", headers=guest).status_code == 204
        )  # 나가기도 성공
    finally:
        memory_hooks._member_withdrawn[:] = saved
    assert rows(pg, "SELECT count(*) FROM group_members WHERE user_id=%s", guest_id) == [(0,)]


def _eligible_photos(client, pg, count):
    """가족 활성화·업로더 동의·확인된 일반 사진 `count` 장(D-13: 확인 상태는 관리자 연결로 만든다)."""
    owner, _, _ = _family(client)
    assert client.put(f"{M}/settings", json={"enabled": True}, headers=owner).status_code == 200
    assert client.put(f"{M}/consent", json={"consent": True}, headers=owner).status_code == 200
    ids = [_photo(client, owner)[0] for _ in range(count)]
    with admin(pg) as conn:
        for att in ids:
            conn.execute(
                "UPDATE chat_photo_checks SET status='photo' WHERE attachment_id=%s", (att,)
            )
    return owner, ids


def _sessions(pg, n):
    engines = [create_engine(url(pg)) for _ in range(n)]
    return engines, [sessionmaker(bind=e)() for e in engines]


def test_job_table_defaults_unique_and_cascade_on_postgres(pg_client):
    from app.features.family_memory import job_service as js

    client, pg = pg_client
    _, ids = _eligible_photos(client, pg, 2)
    engines, (db,) = _sessions(pg, 1)
    try:
        first = js.enqueue(db, ids[0])
        again = js.enqueue(db, ids[0])
    finally:
        db.close()
        engines[0].dispose()
    assert (first.outcome, again.outcome) == ("queued", "exists")
    assert rows(
        pg, "SELECT status, attempts, max_attempts, lease_until FROM family_memory_jobs"
    ) == [("queued", 0, 3, None)]
    with pytest.raises(psycopg.errors.UniqueViolation):  # 같은 사진·종류는 DB 가 한 줄만 허용한다
        with admin(pg) as conn:
            conn.execute(
                "INSERT INTO family_memory_jobs (id, group_id, attachment_id, user_id, kind, run_after,"
                " created_at, updated_at) SELECT 'dup', group_id, attachment_id, user_id, kind, now(),"
                " now(), now() FROM family_memory_jobs"
            )
    with admin(pg) as conn:  # 첨부를 지우면 DB 가 작업도 따라 지운다(ON DELETE CASCADE)
        conn.execute("DELETE FROM message_attachments WHERE id=%s", (ids[0],))
    assert _count(pg, "family_memory_jobs") == 0


def test_concurrent_workers_never_claim_the_same_job_on_postgres(pg_client):
    """여러 워커가 동시에 선점해도 FOR UPDATE SKIP LOCKED 로 작업마다 정확히 한 워커만 가져간다(시도 횟수도 1)."""
    import threading

    from app.features.family_memory import job_service as js

    client, pg = pg_client
    _, ids = _eligible_photos(client, pg, 8)
    engines, sessions = _sessions(pg, 1)
    try:
        for att in ids:
            assert js.enqueue(sessions[0], att).outcome == "queued"
    finally:
        sessions[0].close()
        engines[0].dispose()

    workers = 6
    barrier = threading.Barrier(workers)
    taken: list[tuple[str, str]] = []
    lock = threading.Lock()

    def run(n: int) -> None:
        engine = create_engine(url(pg))
        try:
            barrier.wait()
            while True:
                with sessionmaker(bind=engine)() as db:
                    job = js.claim(db, f"w{n}", [js.KIND_PHOTO])
                if job is None:
                    return
                with lock:
                    taken.append((job.id, f"w{n}"))
        finally:
            engine.dispose()

    threads = [threading.Thread(target=run, args=(n,)) for n in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    job_ids = [j for j, _ in taken]
    assert len(job_ids) == len(set(job_ids)) == 8  # 중복 선점 없음·누락 없음
    assert rows(pg, "SELECT DISTINCT attempts, status FROM family_memory_jobs") == [(1, "running")]


def test_a_row_locked_by_another_worker_is_skipped_not_waited_on_postgres(pg_client):
    from app.features.family_memory import job_repository as jobs
    from app.features.family_memory import job_service as js

    client, pg = pg_client
    _, ids = _eligible_photos(client, pg, 2)
    engines, (setup, holder, other) = _sessions(pg, 3)
    try:
        for att in ids:
            js.enqueue(setup, att)
        locked = jobs.next_candidate(holder, [js.KIND_PHOTO], js._now())  # 첫 작업을 잠근 채 둔다
        assert locked is not None
        claimed = js.claim(
            other, "w2", [js.KIND_PHOTO]
        )  # 기다리지 않고 건너뛰어 다른 작업을 가져온다
        assert claimed is not None and claimed.id != locked.id
        holder.rollback()
        assert (
            js.claim(other, "w2", [js.KIND_PHOTO]).id == locked.id
        )  # 잠금이 풀리면 가져갈 수 있다
    finally:
        for db in (setup, holder, other):
            db.close()
        for e in engines:
            e.dispose()


def test_withdrawal_and_leave_cancel_jobs_in_the_same_transaction_on_postgres(pg_client):
    from app.features.family_memory import job_service as js

    client, pg = pg_client
    owner, ids = _eligible_photos(client, pg, 1)
    engines, (db,) = _sessions(pg, 1)
    try:
        assert js.enqueue(db, ids[0]).outcome == "queued"
    finally:
        db.close()
        engines[0].dispose()
    assert client.put(f"{M}/consent", json={"consent": False}, headers=owner).status_code == 200
    assert rows(pg, "SELECT status, cancel_reason FROM family_memory_jobs") == [
        ("canceled", "withdrawn")
    ]


def test_embedding_is_saved_through_the_gate_and_removed_by_cascade_on_postgres(
    pg_client, monkeypatch
):
    from app.features.family_memory import analysis, worker
    from app.features.family_memory import job_service as js

    monkeypatch.setattr(settings, "family_memory_encoder", "fake")
    analysis.reset_encoder()
    saved = dict(worker._handlers)
    client, pg = pg_client
    _, ids = _eligible_photos(client, pg, 1)
    engines, (db,) = _sessions(pg, 1)
    try:
        assert js.enqueue(db, ids[0], analysis.KIND_EMBEDDING).outcome == "queued"
    finally:
        db.close()
        engines[0].dispose()
    try:
        analysis.register_handlers()
        engine = create_engine(url(pg))
        try:
            with sessionmaker(bind=engine)() as s:
                job = js.claim(s, "w1", [analysis.KIND_EMBEDDING])
            result = analysis.run(job)
            with sessionmaker(bind=engine)() as s:
                assert js.complete(s, job, "w1", result, analysis.save) == "done"
        finally:
            engine.dispose()
    finally:
        worker._handlers.clear()
        worker._handlers.update(saved)
        analysis.reset_encoder()
    assert rows(pg, "SELECT model_id, dim, octet_length(vector) FROM photo_embeddings") == [
        ("fake-gray4x4", 16, 64)
    ]
    with admin(pg) as conn:  # 첨부를 지우면 DB 가 임베딩도 따라 지운다(ON DELETE CASCADE)
        conn.execute("DELETE FROM message_attachments WHERE id=%s", (ids[0],))
    assert _count(pg, "photo_embeddings") == 0


def test_withdrawal_waits_for_an_in_flight_save_then_removes_the_embedding_on_postgres(
    pg_client, monkeypatch
):
    """저장 중(작업 줄 잠금)에 철회가 들어오면 철회는 저장이 끝날 때까지 기다렸다가 그 임베딩을 지운다(철회 뒤에 남는 파생 데이터가 없다)."""
    import threading
    import time

    from app.features.family_memory import analysis
    from app.features.family_memory import job_repository as jobs
    from app.features.family_memory import job_service as js

    monkeypatch.setattr(settings, "family_memory_encoder", "fake")
    analysis.reset_encoder()
    client, pg = pg_client
    owner, ids = _eligible_photos(client, pg, 1)
    engines, (setup, saver) = _sessions(pg, 2)
    try:
        js.enqueue(setup, ids[0], analysis.KIND_EMBEDDING)
        job = js.claim(setup, "w1", [analysis.KIND_EMBEDDING])
        result = analysis.run(job)
        row = jobs.lock_running(saver, job.id, "w1")  # 저장 트랜잭션이 작업 줄을 잡고 있다
        assert row is not None
        analysis.save(saver, job, result)  # 아직 커밋하지 않았다

        status = {}

        def withdraw():
            r = client.put(f"{M}/consent", json={"consent": False}, headers=owner)
            status["code"] = r.status_code

        t = threading.Thread(target=withdraw)
        t.start()
        time.sleep(1.5)
        assert t.is_alive()  # 철회가 작업 줄 잠금 때문에 기다린다
        row.status = jobs.DONE  # 저장 트랜잭션이 끝난다
        saver.commit()
        t.join(timeout=20)
        assert status["code"] == 200
    finally:
        for s in (setup, saver):
            s.close()
        for e in engines:
            e.dispose()
        analysis.reset_encoder()
    assert _count(pg, "photo_embeddings") == 0  # 저장이 먼저 끝났어도 철회가 지웠다
    assert (
        _count(pg, "family_memory_jobs") == 0
    )  # 끝난 작업 줄도 지워 재동의 뒤 다시 등록할 수 있다
    assert rows(pg, "SELECT withdrawn_at IS NOT NULL FROM member_memory_consents") == [(True,)]


def test_table_constraints_on_postgres(pg_client):
    _, pg = pg_client
    assert psycopg  # 제약 위반은 psycopg 예외로 확인한다
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with admin(pg) as conn:
            conn.execute(
                "INSERT INTO member_memory_consents (group_id, user_id, consent_version)"
                " VALUES ('nope', 'nope', 1)"
            )


def test_candidates_tables_defaults_cascade_and_concurrent_refresh_on_postgres(
    pg_client, monkeypatch
):
    """새 표의 기본값·CASCADE 와, 같은 가족을 동시에 새로 고쳐도 후보가 한 벌만 남는지(PG)."""
    import threading
    from datetime import UTC, datetime, timedelta

    from app.features.family_memory import candidate_service, discovery, encoder
    from app.features.family_memory import embedding_repository as emb

    monkeypatch.setattr(settings, "family_memory_candidates_api_enabled", True)
    # 이 시험의 사진은 모두 같은 합성 이미지라 파일 해시로는 중복이 된다: 화질·해시 값 없이(중복 판정은 임베딩으로) 본다
    monkeypatch.setattr(discovery, "photo_stats", lambda attachment_id: None)
    client, pg = pg_client
    owner, ids = _eligible_photos(client, pg, 4)
    owner_id, gid = _me(client, owner)
    # 촬영 시각이 같은 날 5분 간격이 되도록 맞추고(없으면 그룹이 만들어지지 않는다) 합성 임베딩을 넣는다
    base = datetime(2024, 5, 1, 10, 0, tzinfo=UTC)
    with admin(pg) as conn:
        for i, att in enumerate(ids):
            conn.execute(
                "UPDATE message_attachments SET taken_at=%s WHERE id=%s",
                (base + timedelta(minutes=5 * i), att),
            )
    engine = create_engine(url(pg))
    try:
        with sessionmaker(bind=engine)() as s:
            for i, att in enumerate(ids):
                vec = [1.0, 0.6 * i] + [
                    0.0
                ] * 30  # 서로 다른 장면 방향(코사인 0.85 안팎: 중복이 아니다)
                norm = sum(v * v for v in vec) ** 0.5
                emb.upsert(s, gid, att, owner_id, "siglip2-base-patch16-224", "t", 32,
                           encoder.pack([v / norm for v in vec]), datetime.now(UTC))  # fmt: skip
            s.commit()
        outcomes, errors = [], []
        barrier = threading.Barrier(3)

        def refresh():
            e = create_engine(url(pg))
            try:
                barrier.wait()
                with sessionmaker(bind=e)() as s:
                    outcomes.append(candidate_service.refresh(s, gid))
            except Exception as exc:  # noqa: BLE001
                errors.append(type(exc).__name__)
            finally:
                e.dispose()

        threads = [threading.Thread(target=refresh) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        engine.dispose()
    # 동시에 새로 고치면 일부는 IntegrityError 로 실패할 수 있지만(먼저 끝난 쪽이 맞다) 후보는 한 벌뿐이다
    assert set(errors) <= {"IntegrityError"}
    assert _count(pg, "memory_candidates") == 1 and _count(pg, "memory_candidate_photos") == 4
    assert rows(pg, "SELECT status, algorithm_version FROM memory_candidates") == [
        ("private", "memgrp-1")
    ]
    with admin(pg) as conn:  # 첨부를 지우면 DB 가 사진 줄을 따라 지운다(ON DELETE CASCADE)
        conn.execute("DELETE FROM message_attachments WHERE id=%s", (ids[0],))
    assert _count(pg, "memory_candidate_photos") == 3
    items = client.get(f"{M}/candidates", headers=owner).json()["items"]
    assert len(items) == 1 and items[0]["photo_count"] == 3 and ids[0] not in str(items)
    with admin(pg) as conn:
        conn.execute("DELETE FROM message_attachments WHERE id=%s", (ids[1],))
    assert (
        client.get(f"{M}/candidates", headers=owner).json()["items"] == []
    )  # 2장면만 남아 숨겨진다
