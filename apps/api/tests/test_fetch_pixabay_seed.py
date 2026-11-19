"""Pixabay 시드 후보 수집 스크립트: 태그 거르기, 중복·수 제한, 24시간 캐시, 가짜 응답으로 한 바퀴(네트워크 없음)."""

import io
import json

import httpx
from PIL import Image

from scripts import fetch_pixabay_seed as fps


def _jpeg(color=(30, 140, 60), size=(1600, 900)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="JPEG")
    return out.getvalue()


def _hit(pid, tags="apple, fruit, red", url="https://cdn.pixabay.com/a.jpg"):
    return {
        "id": pid,
        "tags": tags,
        "user": "someone",
        "pageURL": f"https://pixabay.com/photos/x-{pid}/",
        "largeImageURL": url,
    }


def test_is_scenery_filters_people_and_text_tags():
    assert fps.is_scenery(_hit(1, "apple, fruit, red"))
    assert not fps.is_scenery(_hit(2, "beach, woman, summer"))
    assert not fps.is_scenery(_hit(3, "street, Sign, city"))
    assert not fps.is_scenery(_hit(4, "dog, People"))
    assert fps.is_scenery(_hit(5, "manhattan skyline"))  # 단어 일부("man")만 닮은 것은 통과


def test_pick_hits_dedupes_and_limits():
    seen = {10}
    hits = [_hit(10), _hit(11), _hit(11), _hit(12, "kid, toy"), _hit(13), _hit(14)]
    got = fps.pick_hits(hits, 2, seen)
    assert [h["id"] for h in got] == [11, 13]
    assert seen == {10, 11, 13}


def test_search_uses_24h_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(fps, "REQUEST_GAP", 0)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        return httpx.Response(200, json={"hits": [_hit(1)]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = fps.search(client, "KEY", "food", 40, tmp_path)
        again = fps.search(client, "KEY", "food", 40, tmp_path)
    assert first == again and len(calls) == 1
    assert calls[0]["category"] == "food" and calls[0]["safesearch"] == "true"
    # 25시간 뒤에는 캐시가 낡아서 다시 요청한다
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fps.search(
            client, "KEY", "food", 40, tmp_path, now=lambda: __import__("time").time() + 25 * 3600
        )
    assert len(calls) == 2


def test_run_makes_files_with_fake_api(tmp_path, monkeypatch):
    monkeypatch.setattr(fps, "REQUEST_GAP", 0)
    image = _jpeg()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "pixabay.com":
            category = request.url.params["category"]
            base = {"food": 100, "animals": 200}.get(category, 300)
            hits = [
                _hit(base + i, "apple, fruit", f"https://cdn.pixabay.com/{base + i}.jpg")
                for i in range(6)
            ]
            hits.append(_hit(base + 99, "woman, portrait", "https://cdn.pixabay.com/bad.jpg"))
            return httpx.Response(200, json={"hits": hits})
        return httpx.Response(200, content=image, headers={"content-type": "image/jpeg"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        found = fps.run(tmp_path, "KEY", 14, client)
    assert 7 <= len(found) <= 14
    assert [c["no"] for c in found] == list(range(1, len(found) + 1))
    assert all(c["license"] == fps.LICENSE and "woman" not in c["tags"] for c in found)
    first = tmp_path / found[0]["file"]
    with Image.open(first) as img:
        assert max(img.size) <= fps.SIDE_PX
    saved = json.loads((tmp_path / "candidates.json").read_text(encoding="utf-8"))
    assert len(saved) == len(found)
    assert (tmp_path / "contact_sheet.jpg").is_file()
    assert not any(
        "KEY" in p.read_text(encoding="utf-8", errors="ignore") for p in tmp_path.glob("*.json")
    )


def test_api_key_from_env_then_dotenv(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('OTHER=1\nPIXABAY_API_KEY="from-file"\n', encoding="utf-8")
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    assert fps.api_key(env) == "from-file"
    monkeypatch.setenv("PIXABAY_API_KEY", "from-env")
    assert fps.api_key(env) == "from-env"
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    import pytest

    with pytest.raises(SystemExit):
        fps.api_key(tmp_path / "missing.env")
