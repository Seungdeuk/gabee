"""프로필 사진 업로드·조회·삭제(PR B). 사진 파일은 tmp_path 를 DATA_DIR 로 지정해 실제 data 폴더를 건드리지 않는다."""

import io
import re
import threading
import time

import pytest
from PIL import Image
from sqlalchemy import select

from app.features.family_group import photo_repository, photo_service
from app.features.family_group.models import GroupMember, User
from app.shared.config import settings
from app.shared.db import SessionLocal

from .test_family_profile import family
from .test_join_approval import P, account, create_group


@pytest.fixture(autouse=True)
def _photo_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    photo_service.upload_limiter.reset()
    yield
    photo_service.upload_limiter.reset()


def image_bytes(fmt="JPEG", size=(600, 300), mode="RGB", exif=None) -> bytes:
    img = Image.new(mode, size, (200, 80, 40) if mode == "RGB" else (200, 80, 40, 128))
    out = io.BytesIO()
    kwargs = {"exif": exif} if exif is not None else {}
    img.save(out, format=fmt, **kwargs)
    return out.getvalue()


def gps_exif() -> Image.Exif:
    exif = Image.Exif()
    exif[0x0112] = 6  # 오른쪽으로 90도 회전해서 보는 사진
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (37.0, 33.0, 59.0)
    gps[3], gps[4] = "E", (126.0, 58.0, 40.0)
    return exif


def upload(client, headers, data, name="me.jpg", ctype="image/jpeg"):
    return client.post(f"{P}/me/photo", files={"file": (name, data, ctype)}, headers=headers)


def stored(tmp_path, user_id):
    """DB 에 적힌 경로의 실제 파일(사진이 없으면 존재하지 않는 경로)."""
    with SessionLocal() as db:
        path = db.get(User, user_id).profile_photo_path
    return tmp_path / (path or f"profile_photos/{user_id}_none.jpg")


def get_photo(client, headers, user_id, extra=None):
    return client.get(f"{P}/users/{user_id}/photo", headers={**headers, **(extra or {})})


def members(client, headers):
    return client.get(f"{P}/groups/me", headers=headers).json()["members"]


def test_upload_formats_become_square_512_jpeg(client, tmp_path):
    h, uid = account(client, "photo_a", "가")
    for fmt, size, name, ctype in (
        ("JPEG", (1200, 800), "a.jpg", "image/jpeg"),
        ("PNG", (300, 700), "a.png", "image/png"),
        ("WEBP", (640, 640), "a.webp", "image/webp"),
    ):
        r = upload(client, h, image_bytes(fmt, size), name, ctype)
        assert r.status_code == 200, r.text
        body = r.json()
        assert re.fullmatch(rf"/family-group/users/{uid}/photo\?v=\d+", body["photo_url"])
        assert body["photo_updated_at"]
        with Image.open(stored(tmp_path, uid)) as img:
            assert img.format == "JPEG"
            assert img.width == img.height <= 512
        assert not list((tmp_path / "profile_photos").glob("*.tmp"))  # 임시 파일이 남지 않는다
        photo_service.upload_limiter.reset()


def test_small_image_is_cropped_square_without_upscaling(client, tmp_path):
    h, uid = account(client, "photo_s", "작")
    assert (
        upload(client, h, image_bytes("PNG", (200, 100)), "s.png", "image/png").status_code == 200
    )
    with Image.open(stored(tmp_path, uid)) as img:
        assert img.size == (100, 100)


def test_png_with_alpha_is_flattened(client, tmp_path):
    h, uid = account(client, "photo_alpha", "투")
    r = upload(client, h, image_bytes("PNG", (100, 100), mode="RGBA"), "a.png", "image/png")
    assert r.status_code == 200, r.text
    with Image.open(stored(tmp_path, uid)) as img:
        assert img.mode == "RGB"


def test_exif_gps_is_removed(client, tmp_path):
    h, uid = account(client, "photo_gps", "위")
    source = image_bytes("JPEG", (800, 400), exif=gps_exif())
    with Image.open(io.BytesIO(source)) as src:  # 시험 전제: 원본에는 GPS 가 실제로 있다
        assert src.getexif().get_ifd(0x8825)
    assert upload(client, h, source).status_code == 200
    raw = stored(tmp_path, uid).read_bytes()
    assert b"Exif" not in raw[:64]
    with Image.open(io.BytesIO(raw)) as out:
        assert not out.getexif()
        assert "exif" not in out.info
        assert not out.getexif().get_ifd(0x8825)


def test_too_large_is_413(client, tmp_path):
    h, uid = account(client, "photo_big", "큰")
    r = upload(client, h, b"\xff\xd8" + b"0" * (2 * 1024 * 1024))
    assert r.status_code == 413
    assert r.json()["code"] == "photo_too_large"
    assert not stored(tmp_path, uid).exists()


def test_not_an_image_is_400(client, tmp_path):
    h, uid = account(client, "photo_fake", "가짜")
    r = upload(client, h, "이건 그림이 아니에요".encode(), "evil.jpg", "image/jpeg")
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_image"
    assert not stored(tmp_path, uid).exists()


def test_truncated_image_and_other_formats_are_400(client):
    h, _ = account(client, "photo_bad", "깨짐")
    good = image_bytes("JPEG")
    assert upload(client, h, good[: len(good) // 3]).json()["code"] == "invalid_image"
    gif = io.BytesIO()
    Image.new("RGB", (10, 10)).save(gif, format="GIF")
    r = upload(client, h, gif.getvalue(), "a.gif", "image/gif")
    assert (r.status_code, r.json()["code"]) == (400, "invalid_image")


def test_huge_dimensions_are_rejected(client):
    h, _ = account(client, "photo_dim", "폭탄")
    r = upload(client, h, image_bytes("PNG", (8001, 8)), "b.png", "image/png")
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_image"


def test_requires_login(client):
    assert upload(client, {}, image_bytes()).status_code == 401
    assert client.delete(f"{P}/me/photo").status_code == 401
    assert client.get(f"{P}/users/abc/photo").status_code == 401


def test_family_member_can_view_with_cache_headers(client):
    owner, owner_id, (jimin, jimin_id), _, _ = family(client)
    assert upload(client, jimin, image_bytes()).status_code == 200
    r = get_photo(client, owner, jimin_id)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"].startswith("private, max-age=")
    with Image.open(io.BytesIO(r.content)) as img:
        assert img.format == "JPEG"
    # 본인도 볼 수 있다
    assert get_photo(client, jimin, jimin_id).status_code == 200
    # ETag 가 같으면 304
    again = get_photo(client, owner, jimin_id, {"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304
    assert again.headers["etag"] == r.headers["etag"]


def test_other_family_and_unknown_user_get_404(client):
    owner, owner_id, (jimin, jimin_id), _, _ = family(client)
    assert upload(client, jimin, image_bytes()).status_code == 200
    stranger, _ = account(client, "stranger_x", "남")
    create_group(client, stranger, "남의 가족")
    assert get_photo(client, stranger, jimin_id).status_code == 404
    loner, _ = account(client, "loner_y", "혼자")  # 가족이 없는 사용자
    assert get_photo(client, loner, jimin_id).status_code == 404
    assert get_photo(client, owner, "nobody12345").status_code == 404
    assert get_photo(client, owner, "..%2F..%2Fgabee").status_code == 404
    # 사진이 없는 같은 가족 구성원도 404(같은 응답)
    assert get_photo(client, owner, owner_id).status_code == 404


def test_replace_overwrites_file_and_changes_version(client, tmp_path):
    h, uid = account(client, "photo_rep", "교체")
    first = upload(client, h, image_bytes("JPEG", (400, 400))).json()
    first_file = stored(tmp_path, uid)
    first_bytes = first_file.read_bytes()
    time.sleep(0.01)  # 버전(밀리초)이 달라지게
    second = upload(client, h, image_bytes("PNG", (300, 300)), "b.png", "image/png").json()
    assert stored(tmp_path, uid).read_bytes() != first_bytes
    assert not first_file.exists()  # 커밋 성공 뒤 이전 버전 파일이 지워진다
    assert second["photo_updated_at"] >= first["photo_updated_at"]
    assert len(list((tmp_path / "profile_photos").iterdir())) == 1
    me = client.get(f"{P}/me", headers=h)
    assert me.status_code == 200
    assert me.json()["photo_url"] == second["photo_url"]


def test_delete_removes_file_and_view_is_404(client, tmp_path):
    owner, owner_id, (jimin, jimin_id), _, _ = family(client)
    upload(client, jimin, image_bytes())
    path = stored(tmp_path, jimin_id)
    assert path.exists()
    assert client.delete(f"{P}/me/photo", headers=jimin).status_code == 204
    assert not path.exists()
    assert get_photo(client, owner, jimin_id).status_code == 404
    with SessionLocal() as db:
        user = db.scalars(select(User).where(User.id == jimin_id)).one()
        assert user.profile_photo_path is None and user.profile_photo_updated_at is None
    assert client.delete(f"{P}/me/photo", headers=jimin).status_code == 204  # 없어도 204


def test_member_list_contains_photo_url(client):
    owner, owner_id, (jimin, jimin_id), _, _ = family(client)
    assert all(m["photo_url"] is None for m in members(client, owner))
    url = upload(client, jimin, image_bytes()).json()["photo_url"]
    by_id = {m["id"]: m for m in members(client, owner)}
    assert by_id[jimin_id]["photo_url"] == url
    assert by_id[owner_id]["photo_url"] is None
    assert client.get(url, headers=owner).status_code == 200  # 응답의 경로를 그대로 쓸 수 있다


def test_upload_rate_limit(client):
    h, _ = account(client, "photo_rate", "빈번")
    for _ in range(photo_service.UPLOAD_LIMIT):
        assert upload(client, h, image_bytes("JPEG", (50, 50))).status_code == 200
    r = upload(client, h, image_bytes("JPEG", (50, 50)))
    assert r.status_code == 429
    assert r.json()["code"] == "too_many_uploads"
    assert int(r.headers["retry-after"]) >= 1


def test_file_path_ignores_user_input(client, tmp_path):
    h, uid = account(client, "photo_path", "경로")
    r = upload(client, h, image_bytes(), name="../../evil.jpg")
    assert r.status_code == 200
    files = [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()]
    assert len(files) == 1 and re.fullmatch(rf"profile_photos/{uid}_\d+\.jpg", files[0])
    with SessionLocal() as db:
        assert db.get(User, uid).profile_photo_path == files[0]


# ---- 메모리·본문 크기 방어 ----


def solid_png(size) -> bytes:
    out = io.BytesIO()
    Image.new("L", size, 128).save(out, format="PNG")  # 단색이라 압축되면 아주 작다
    return out.getvalue()


def test_huge_pixel_count_rejected_before_decode(client, tmp_path, monkeypatch):
    h, uid = account(client, "photo_px", "화소")
    data = solid_png((8000, 8000))
    assert len(data) < photo_service.MAX_BYTES  # 2MB 검사는 통과하는 크기
    original_load = Image.Image.load

    def no_load(self, *a, **k):  # 거절은 픽셀을 읽기 전에 일어나야 한다
        raise AssertionError("decoded")

    monkeypatch.setattr(Image.Image, "load", no_load)
    try:
        r = upload(client, h, data, "b.png", "image/png")
    finally:
        monkeypatch.setattr(Image.Image, "load", original_load)
    assert r.status_code == 400 and r.json()["code"] == "invalid_image"
    assert not stored(tmp_path, uid).exists()


def test_pixel_limit_boundary(client):
    h, _ = account(client, "photo_edge", "경계")
    ok = solid_png((4000, 4000))  # 정확히 한도(1600만)
    assert upload(client, h, ok, "a.png", "image/png").status_code == 200
    photo_service.upload_limiter.reset()
    over = solid_png((4001, 4000))
    assert upload(client, h, over, "a.png", "image/png").status_code == 400


def test_large_jpeg_is_reduced_on_decode(client, tmp_path):
    h, uid = account(client, "photo_jpg", "큰제이펙")
    out = io.BytesIO()
    Image.new("RGB", (4000, 3000), (10, 200, 30)).save(out, format="JPEG")
    assert upload(client, h, out.getvalue()).status_code == 200
    with Image.open(stored(tmp_path, uid)) as img:
        assert img.size == (512, 512)


def test_busy_returns_503_without_waiting(client, tmp_path):
    h, uid = account(client, "photo_busy", "붐빔")
    held = [
        photo_service._slots.acquire(blocking=False) for _ in range(photo_service.MAX_CONCURRENT)
    ]
    try:
        r = upload(client, h, image_bytes())
    finally:
        for ok in held:
            if ok:
                photo_service._slots.release()
    assert r.status_code == 503 and r.json()["code"] == "photo_busy"
    assert not stored(tmp_path, uid).exists()
    assert upload(client, h, image_bytes()).status_code == 200  # 자리가 나면 다시 된다


def test_content_length_over_limit_rejected_before_auth(client):
    big = b"0" * (3 * 1024 * 1024)
    r = client.post(f"{P}/me/photo", files={"file": ("a.jpg", big, "image/jpeg")})  # 인증 없음
    assert r.status_code == 413 and r.json()["code"] == "photo_too_large"
    h, _ = account(client, "photo_cl", "본문")
    r = client.post(f"{P}/me/photo", files={"file": ("a.jpg", big, "image/jpeg")}, headers=h)
    assert r.status_code == 413
    small = client.post(f"{P}/me/photo", files={"file": ("a.jpg", b"x", "image/jpeg")})
    assert small.status_code == 401  # 작은 본문은 평소처럼 인증에서 거절


def test_chunked_body_over_limit_rejected(client):
    def body():
        for _ in range(40):
            yield b"0" * (100 * 1024)  # Content-Length 없는 chunked

    r = client.post(
        f"{P}/me/photo", content=body(), headers={"content-type": "multipart/form-data; boundary=x"}
    )
    assert r.status_code == 413


def test_other_paths_are_not_limited(client):
    h, _ = account(client, "photo_other", "다른")
    r = client.post(f"{P}/me/photox", content=b"0" * (3 * 1024 * 1024), headers=h)
    assert r.status_code != 413


# ---- 업로드·삭제 직렬화, 파일과 DB 일치 ----


def test_failed_commit_cleans_new_file_and_keeps_old(client, tmp_path, monkeypatch):
    from sqlalchemy.orm import Session

    h, uid = account(client, "photo_fail", "실패")
    assert upload(client, h, image_bytes("JPEG", (300, 300))).status_code == 200
    old = stored(tmp_path, uid)
    old_bytes = old.read_bytes()
    time.sleep(0.01)
    real_commit = Session.commit

    def boom(self):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(Session, "commit", boom)
    photo_service.upload_limiter.reset()
    try:
        with pytest.raises(RuntimeError):
            upload(client, h, image_bytes("PNG", (200, 200)), "b.png", "image/png")
    finally:
        monkeypatch.setattr(Session, "commit", real_commit)
    files = sorted((tmp_path / "profile_photos").iterdir())
    assert files == [old] and old.read_bytes() == old_bytes
    assert stored(tmp_path, uid) == old


def test_concurrent_uploads_and_deletes_leave_file_and_db_consistent(client, tmp_path):
    h, uid = account(client, "photo_race", "경합")
    errors = []

    def worker(i):
        try:
            photo_service.upload_limiter.reset()
            if i % 3 == 2:
                client.delete(f"{P}/me/photo", headers=h)
            else:
                upload(client, h, image_bytes("JPEG", (100 + i, 100 + i)))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(9)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    with SessionLocal() as db:
        path = db.get(User, uid).profile_photo_path
    directory = tmp_path / "profile_photos"
    files = [p.name for p in directory.iterdir()] if directory.exists() else []
    assert files == ([path.split("/")[1]] if path else [])


def test_lock_user_returns_row(client):
    _, uid = account(client, "photo_lock", "잠금")
    with SessionLocal() as db:
        assert photo_repository.lock_user(db, uid).id == uid
        assert photo_repository.lock_user(db, "nobody") is None


def test_exif_rotation_moves_pixels(client, tmp_path):
    h, uid = account(client, "photo_rot", "회전")
    img = Image.new("RGB", (400, 200), (255, 255, 255))
    img.paste((255, 0, 0), (0, 0, 200, 200))  # 왼쪽 반쪽만 빨강
    exif = Image.Exif()
    exif[0x0112] = 6  # 시계 방향 90도로 보여준다 -> 왼쪽이 위쪽으로 간다
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=95, exif=exif)
    assert upload(client, h, out.getvalue()).status_code == 200
    with Image.open(stored(tmp_path, uid)) as res:
        res = res.convert("RGB")
        w = res.width
        top, bottom = res.getpixel((w // 2, 5)), res.getpixel((w // 2, w - 6))
    assert top[0] > 200 and top[1] < 80  # 위쪽이 빨강
    assert bottom[1] > 200  # 아래쪽은 흰색


def test_photo_404_after_leaving_family(client):
    owner, owner_id, (jimin, jimin_id), _, _ = family(client)
    assert upload(client, jimin, image_bytes()).status_code == 200
    assert get_photo(client, owner, jimin_id).status_code == 200
    with SessionLocal() as db:  # 가족을 떠난 상태(구성원 행 삭제)
        for row in db.scalars(select(GroupMember).where(GroupMember.user_id == jimin_id)):
            db.delete(row)
        db.commit()
    assert get_photo(client, owner, jimin_id).status_code == 404
