"""업로드 → 전처리(가짜 OCR·가짜 모델) → knowledge 저장 → 검색·채팅 흐름. 모델이나 인터넷 없이 돈다."""

import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image

from app.features.ai_assistant import files
from app.features.ai_assistant.ingest.converters import OcrLine
from app.features.ai_assistant.ingest.schemas import Caption
from app.shared.config import settings


class FakeOcr:
    def __init__(self, lines=()):
        self.lines = [OcrLine(t, c) for t, c in lines]

    def read(self, image):
        return list(self.lines)


class FakeCaptioner:
    def __init__(
        self,
        caption=Caption(
            description="푸른 바다와 모래사장이 보이는 풍경", keywords=["바다", "해변"]
        ),
    ):
        self.caption = caption
        self.calls = 0

    def describe(self, image):
        self.calls += 1
        return self.caption


def png(color=(120, 160, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (400, 300), color).save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def pipeline():
    old = files.processors
    files.processors = files.Processors(
        ocr=FakeOcr(),
        llm=lambda *a, **k: {
            "doc_type": "학교 가정통신문",
            "is_document": True,
            "tags": ["학교"],
            "confidence": 0.9,
        },
        captioner=FakeCaptioner(),
        default_captioner=False,
    )
    yield files.processors
    files.processors = old


def upload(client, headers, data, name="a.png", ctype="image/png"):
    r = client.post("/ai-assistant/files", files={"file": (name, data, ctype)}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_receipt_photo_is_read_masked_saved_and_findable(client, family, pipeline):
    a, _, group = family
    pipeline.ocr = FakeOcr(
        [
            ("동대문마트", 0.95),
            ("2026-10-15", 0.92),
            ("합계 34,950원", 0.93),
            ("영수증 주민 900101-1234567", 0.9),
        ]
    )
    data = png()
    up = upload(client, a, data, "영수증.png")
    assert up["status"] == "received"
    # 테스트 클라이언트는 응답 뒤 백그라운드 작업이 끝나야 돌아온다
    st = client.get(f"/ai-assistant/files/{up['id']}", headers=a).json()
    assert st["status"] == "analyzed" and st["kind_label"] == "영수증"
    item = client.get(f"/ai-assistant/knowledge/items/{up['id']}", headers=a).json()
    assert "34,950" in item["body_md"]
    assert (
        "900101-1234567" not in item["body_md"] and "******-*******" in item["body_md"]
    )  # 주민번호는 가려져 저장
    hits = client.post(
        "/ai-assistant/knowledge/search", json={"query": "마트 영수증 합계"}, headers=a
    ).json()["hits"]
    assert hits and hits[0]["item_id"] == up["id"]
    # 원본은 그대로(바이트 동일) 원본 폴더에 있다
    sha = hashlib.sha256(data).hexdigest()
    raw = Path(settings.data_dir) / "raw" / group["id"] / sha[:2] / f"{sha}.png"
    assert raw.read_bytes() == data and item["source_path"] == f"{group['id']}/{sha[:2]}/{sha}.png"


def test_photo_without_text_gets_a_description_and_is_found_by_it(client, family, pipeline):
    a, _, _ = family
    up = upload(client, a, png((10, 90, 200)), "sea.png")
    st = client.get(f"/ai-assistant/files/{up['id']}", headers=a).json()
    assert st["status"] == "analyzed" and st["kind_label"] == "사진"
    assert "푸른 바다" in st["description"]
    hits = client.post(
        "/ai-assistant/knowledge/search", json={"query": "바다 사진"}, headers=a
    ).json()["hits"]
    assert hits[0]["item_id"] == up["id"]
    body = client.get(f"/ai-assistant/knowledge/items/{up['id']}", headers=a).json()["body_md"]
    assert "자동 설명" in body and "틀릴 수 있어요" in body  # 자동으로 만든 설명임을 남긴다
    assert pipeline.captioner.calls == 1


def test_text_photos_do_not_call_the_caption_model(client, family, pipeline):
    a, _, _ = family
    pipeline.ocr = FakeOcr([("가정통신문", 0.95), ("현장체험학습 안내", 0.9)])
    up = upload(client, a, png((9, 9, 9)))
    assert client.get(f"/ai-assistant/files/{up['id']}", headers=a).json()["status"] == "analyzed"
    assert pipeline.captioner.calls == 0


def test_sensitive_documents_are_hidden_from_the_chat_model_by_default(
    client, family, pipeline, monkeypatch
):
    from app.features.ai_assistant.knowledge import rag_chat

    a, _, _ = family
    pipeline.ocr = FakeOcr(
        [
            ("처방전", 0.95),
            ("환자 김영희", 0.9),
            ("조제약 소염진통제", 0.9),
            ("주민 900101-2345678", 0.9),
        ]
    )
    up = upload(client, a, png((5, 5, 5)), "rx.png")
    st = client.get(f"/ai-assistant/files/{up['id']}", headers=a).json()
    assert st["status"] in ("analyzed", "needs_review")
    item = client.get(f"/ai-assistant/knowledge/items/{up['id']}", headers=a).json()
    assert item["sensitivity"] == "sensitive" and "900101-2345678" not in item["body_md"]

    seen = []

    def fake_post(body):
        if len(seen) == 0:
            seen.append(1)
            call = {
                "type": "tool_use",
                "id": "t",
                "name": "search_knowledge",
                "input": {"query": "처방전 약"},
            }
            return {"content": [call]}
        seen.append(body["messages"][-1]["content"][0]["content"])
        return {"content": [{"type": "text", "text": "확인했어요."}]}

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)
    client.post("/ai-assistant/chat", json={"message": "처방전 약 알려줘"}, headers=a)
    assert "소염진통제" not in seen[1]  # 기본값: 민감 기록 내용은 Claude 에게 가지 않는다

    seen.clear()
    monkeypatch.setattr(settings, "chat_include_sensitive", True)
    client.post("/ai-assistant/chat", json={"message": "처방전 약 알려줘"}, headers=a)
    assert "소염진통제" in seen[1]


def test_broken_and_empty_uploads_fail_cleanly(client, family, pipeline):
    a, b, _ = family
    assert (
        client.post(
            "/ai-assistant/files", files={"file": ("e.txt", b"", "text/plain")}, headers=a
        ).json()["code"]
        == "empty_file"
    )
    up = upload(client, a, b"\xff\xd8\xff" + b"garbage" * 10, "broken.jpg", "image/jpeg")
    st = client.get(f"/ai-assistant/files/{up['id']}", headers=a).json()
    assert st["status"] == "failed" and st["message"]
    assert (
        client.get(f"/ai-assistant/knowledge/items/{up['id']}", headers=a).status_code == 404
    )  # 저장된 기록 없음
    assert (
        client.get(f"/ai-assistant/files/{up['id']}", headers=b).status_code == 200
    )  # 같은 가족은 본다


def test_other_family_cannot_see_the_file_or_record(client, family, pipeline):
    from tests.helpers import signup

    a, _, _ = family
    up = upload(client, a, png((1, 2, 3)))
    stranger = signup(client, "철수")
    client.post("/family-group/groups", json={"name": "남의 가족"}, headers=stranger)
    assert client.get(f"/ai-assistant/files/{up['id']}", headers=stranger).status_code == 404
    assert (
        client.get(f"/ai-assistant/knowledge/items/{up['id']}", headers=stranger).status_code == 404
    )
    hits = client.post(
        "/ai-assistant/knowledge/search", json={"query": "사진"}, headers=stranger
    ).json()["hits"]
    assert hits == []


def test_document_upload_converts_to_text(client, family, pipeline):
    a, _, _ = family
    up = upload(
        client,
        a,
        "# 제주 여행 계획\n\n- 11월 2일 출발\n- 렌터카 예약\n".encode(),
        "plan.md",
        "text/markdown",
    )
    st = client.get(f"/ai-assistant/files/{up['id']}", headers=a).json()
    assert st["status"] in ("analyzed", "needs_review")
    hits = client.post(
        "/ai-assistant/knowledge/search", json={"query": "제주 렌터카"}, headers=a
    ).json()["hits"]
    assert hits[0]["item_id"] == up["id"]
