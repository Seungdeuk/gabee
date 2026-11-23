"""업로드 → 전처리(가짜 OCR·가짜 모델) → knowledge 저장 → 검색·채팅 흐름. 모델이나 인터넷 없이 돈다."""

import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from app.features.ai_assistant import files
from app.features.ai_assistant.ingest.converters import OcrLine
from app.shared.config import settings
from tests.helpers import allow_ai


class FakeOcr:
    def __init__(self, lines=()):
        self.lines = [OcrLine(t, c) for t, c in lines]

    def read(self, image):
        return list(self.lines)


def png(color=(120, 160, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (400, 300), color).save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def pipeline():
    old = files.processors
    files.processors = files.Processors(ocr=FakeOcr())
    yield files.processors
    files.processors = old


@pytest.fixture
def family(client, family, monkeypatch):
    """사진 속 글자는 Claude 로만 읽으므로(로컬 OCR 없음) 사진을 문서함에 저장·등록하려면 가족 AI 동의가 있어야 한다: 이 모듈의 가족은 동의한 상태로 둔다."""
    allow_ai(client, family[0], monkeypatch)
    return family


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


def _plain_photo(client, a, color=(10, 90, 200)):
    return upload(client, a, png(color), "sea.png")


def test_photo_without_text_asks_for_a_description(client, family, pipeline):
    a, _, _ = family
    up = _plain_photo(client, a)
    st = client.get(f"/ai-assistant/files/{up['id']}", headers=a).json()
    assert st["status"] == "analyzed" and st["kind_label"] == "사진"
    assert st["needs_description"] is True
    item = client.get(f"/ai-assistant/knowledge/items/{up['id']}", headers=a).json()
    assert item["needs_description"] is True and "- 설명:" not in item["body_md"]
    listed = client.get("/ai-assistant/knowledge/items", headers=a).json()
    assert [i["needs_description"] for i in listed if i["id"] == up["id"]] == [True]


def test_saving_a_description_makes_the_photo_searchable(client, family, pipeline):
    a, _, _ = family
    up = _plain_photo(client, a)
    url = f"/ai-assistant/files/{up['id']}/description"
    r = client.post(url, json={"text": "  제주 바닷가에서 찍은 가족 사진  "}, headers=a)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["needs_description"] is False and out["status"] == "analyzed"
    assert out["description"] == "제주 바닷가에서 찍은 가족 사진"
    assert out["title"] == "제주 바닷가에서 찍은 가족 사진"  # 기본 제목이었으므로 설명으로 바뀐다
    item = client.get(f"/ai-assistant/knowledge/items/{up['id']}", headers=a).json()
    assert "- 설명: 제주 바닷가에서 찍은 가족 사진" in item["body_md"]
    assert item["needs_description"] is False
    hits = client.post(
        "/ai-assistant/knowledge/search", json={"query": "제주 바닷가 사진"}, headers=a
    ).json()["hits"]
    assert hits and hits[0]["item_id"] == up["id"]

    # 다시 달면 덮어쓰고, 줄은 하나만 남는다
    r = client.post(url, json={"text": "설악산 단풍"}, headers=a)
    assert r.status_code == 200
    body = client.get(f"/ai-assistant/knowledge/items/{up['id']}", headers=a).json()["body_md"]
    assert body.count("- 설명:") == 1 and "설악산 단풍" in body and "제주" not in body


def test_description_is_masked_before_saving(client, family, pipeline):
    a, _, _ = family
    up = _plain_photo(client, a, (3, 3, 3))
    r = client.post(
        f"/ai-assistant/files/{up['id']}/description",
        json={"text": "주민번호 900101-1234567 적힌 서류"},
        headers=a,
    )
    assert r.status_code == 200
    body = client.get(f"/ai-assistant/knowledge/items/{up['id']}", headers=a).json()["body_md"]
    assert "900101-1234567" not in body


def test_description_is_refused_for_other_family_missing_and_non_photo(client, family, pipeline):
    from tests.helpers import signup

    a, _, _ = family
    photo = _plain_photo(client, a)
    pipeline.ocr = FakeOcr([("동대문마트", 0.95), ("합계 34,950원", 0.93)])
    receipt = upload(client, a, png((8, 8, 80)), "r.png")
    stranger = signup(client, "철수")
    client.post("/family-group/groups", json={"name": "남의 가족"}, headers=stranger)
    url = f"/ai-assistant/files/{photo['id']}/description"
    assert client.post(url, json={"text": "내 사진"}, headers=stranger).status_code == 404
    assert client.post(url, json={"text": "내 사진"}).status_code in (401, 403)
    missing = client.post("/ai-assistant/files/nope/description", json={"text": "x"}, headers=a)
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"
    r = client.post(
        f"/ai-assistant/files/{receipt['id']}/description", json={"text": "영수증"}, headers=a
    )
    assert r.status_code == 409 and r.json()["code"] == "not_a_photo"
    other = client.get(f"/ai-assistant/knowledge/items/{photo['id']}", headers=a).json()
    assert "- 설명:" not in other["body_md"]  # 거절된 요청은 아무것도 바꾸지 않는다


def test_description_length_is_validated(client, family, pipeline):
    a, _, _ = family
    up = _plain_photo(client, a)
    url = f"/ai-assistant/files/{up['id']}/description"
    assert client.post(url, json={"text": "가" * 201}, headers=a).status_code == 422
    assert client.post(url, json={"text": ""}, headers=a).status_code == 422
    assert client.post(url, json={"text": "   "}, headers=a).status_code == 422
    assert client.post(url, json={"text": "가" * 200}, headers=a).status_code == 200


def test_text_photos_do_not_need_a_description(client, family, pipeline, monkeypatch):
    from app.features.ai_assistant.ingest import doc_classifier
    from app.features.ai_assistant.ingest.doc_classifier import Prediction

    # 분류기 파일(data/models/doc-classifier)은 저장소에 없다. CI 처럼 파일이 없으면 분류가 "확인 필요"가 되어
    # 상태가 달라지므로, 진짜 분류기에 기대지 않게 확신하는 가짜를 끼운다(이 시험이 보는 것은 설명 필요 여부).
    monkeypatch.setattr(doc_classifier, "predict", lambda text: Prediction("학교 가정통신문", 0.93))
    a, _, _ = family
    pipeline.ocr = FakeOcr([("가정통신문", 0.95), ("현장체험학습 안내", 0.9)])
    up = upload(client, a, png((9, 9, 9)))
    st = client.get(f"/ai-assistant/files/{up['id']}", headers=a).json()
    assert st["status"] == "analyzed" and st["needs_description"] is False


def test_sensitive_documents_reach_the_chat_model_only_masked_unless_excluded(
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
    allow_ai(client, a, monkeypatch)
    monkeypatch.setattr(settings, "chat_include_sensitive", True)  # 기본값은 false — 켠 가족만
    client.post("/ai-assistant/chat", json={"message": "처방전 약 알려줘"}, headers=a)
    assert "소염진통제" in seen[1]  # 켜면: 가려진 글자가 Claude 에게 간다
    assert "900101-2345678" not in seen[1] and "김영희" not in seen[1]

    seen.clear()
    monkeypatch.setattr(settings, "chat_include_sensitive", False)
    monkeypatch.setattr(settings, "ai_max_calls_per_user_per_day", 100)
    client.post("/ai-assistant/chat", json={"message": "처방전 약 알려줘"}, headers=a)
    assert "소염진통제" not in seen[1]  # 끄면 민감 기록은 가지 않는다


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


def test_a_file_stuck_in_received_is_reported_as_failed(client, family, pipeline):
    """처리 도중 서버가 꺼져 상태가 received 로 남은 파일은 오래되면 실패로 알려 준다."""
    from datetime import UTC, datetime, timedelta

    from app.features.ai_assistant.models import Photo
    from app.shared.db import SessionLocal

    a, _, group = family
    with SessionLocal() as db:
        db.add(
            Photo(
                id="stuck0000001",
                group_id=group["id"],
                uploaded_by="u",
                filename="x.png",
                content_type="image/png",
                size=1,
                status="received",
                created_at=datetime.now(UTC) - timedelta(minutes=30),
            )
        )
        db.commit()
    st = client.get("/ai-assistant/files/stuck0000001", headers=a).json()
    assert st["status"] == "failed" and st["message"]


def test_original_file_comes_back_byte_identical_for_the_same_family(client, family, pipeline):
    a, b, _ = family
    data = png((33, 44, 55))
    up = upload(client, a, data, "원본.png")
    r = client.get(f"/ai-assistant/files/{up['id']}/original", headers=b)  # 같은 가족 다른 구성원
    assert r.status_code == 200 and r.content == data
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "private, no-store"
    assert r.headers["content-disposition"].startswith("inline")


def test_original_file_is_hidden_from_other_families_and_strangers(client, family, pipeline):
    from tests.helpers import signup

    a, _, _ = family
    up = upload(client, a, png((1, 1, 1)))
    stranger = signup(client, "철수")
    client.post("/family-group/groups", json={"name": "남의 가족"}, headers=stranger)
    url = f"/ai-assistant/files/{up['id']}/original"
    assert client.get(url, headers=stranger).status_code == 404
    assert client.get(url).status_code in (401, 403)
    assert client.get("/ai-assistant/files/nope/original", headers=a).status_code == 404


def test_original_file_refuses_a_source_path_pointing_at_another_group(client, family, pipeline):
    from app.features.ai_assistant.knowledge.models import KnowledgeItem
    from app.shared.db import SessionLocal

    a, _, _ = family
    up = upload(client, a, png((9, 8, 7)))
    with SessionLocal() as db:
        item = db.get(KnowledgeItem, up["id"])
        item.source_path = "othergroup00/../" + item.source_path
        db.commit()
    assert client.get(f"/ai-assistant/files/{up['id']}/original", headers=a).status_code == 404


def test_receipt_title_skips_a_leading_phone_line(client, family, pipeline):
    a, _, _ = family
    pipeline.ocr = FakeOcr(
        [("전화 02-555-0123", 0.9), ("하나로마트 동대문점", 0.95), ("합계 9,900원", 0.93)]
    )
    up = upload(client, a, png((7, 7, 7)), "r.png")
    st = client.get(f"/ai-assistant/files/{up['id']}", headers=a).json()
    assert st["title"] == "하나로마트 동대문점"


def _blurry_upload(client, a, pipeline):
    pipeline.ocr = FakeOcr([("동대문마트", 0.5), ("합계 34,950원", 0.5)])  # 글자가 흐려 확인 필요
    up = upload(client, a, png((4, 5, 6)), "blur.png")
    item = client.get(f"/ai-assistant/knowledge/items/{up['id']}", headers=a).json()
    assert item["needs_review"] is True
    return up["id"]


def test_blurry_files_are_listed_as_needing_review_and_editing_clears_it(client, family, pipeline):
    a, _, _ = family
    fid = _blurry_upload(client, a, pipeline)
    listed = client.get("/ai-assistant/knowledge/items", headers=a).json()
    assert [i["needs_review"] for i in listed if i["id"] == fid] == [True]

    detail = client.get(f"/ai-assistant/knowledge/items/{fid}", headers=a).json()
    fixed = detail["body_md"].replace("34,950", "43,950")
    r = client.patch(
        f"/ai-assistant/knowledge/items/{fid}",
        json={"title": "하나로마트 영수증", "body_md": fixed},
        headers=a,
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["needs_review"] is False and out["title"] == "하나로마트 영수증"
    assert "43,950" in out["body_md"] and "34,950" not in out["body_md"]
    assert out["body_md"].startswith("# 하나로마트 영수증")
    assert client.get(f"/ai-assistant/files/{fid}", headers=a).json()["status"] == "analyzed"
    hits = client.post(
        "/ai-assistant/knowledge/search", json={"query": "43,950원 합계"}, headers=a
    ).json()["hits"]
    assert hits and hits[0]["item_id"] == fid


def test_confirming_without_changes_clears_the_review_mark(client, family, pipeline):
    a, _, _ = family
    fid = _blurry_upload(client, a, pipeline)
    r = client.patch(f"/ai-assistant/knowledge/items/{fid}", json={}, headers=a)
    assert r.status_code == 200 and r.json()["needs_review"] is False
    assert client.get(f"/ai-assistant/files/{fid}", headers=a).json()["status"] == "analyzed"


def test_edited_text_is_masked_again_and_empty_text_is_refused(client, family, pipeline):
    a, _, _ = family
    fid = _blurry_upload(client, a, pipeline)
    url = f"/ai-assistant/knowledge/items/{fid}"
    r = client.patch(
        url,
        json={"body_md": "# 메모\n분류: 영수증\n주민번호 900101-1234567 전화 010-1234-5678"},
        headers=a,
    )
    assert r.status_code == 200
    body = r.json()["body_md"]
    assert "900101-1234567" not in body and "010-1234-5678" not in body
    assert client.patch(url, json={"body_md": ""}, headers=a).status_code == 422


def test_other_family_cannot_edit_a_record(client, family, pipeline):
    from tests.helpers import signup

    a, _, _ = family
    fid = _blurry_upload(client, a, pipeline)
    stranger = signup(client, "철수")
    client.post("/family-group/groups", json={"name": "남의 가족"}, headers=stranger)
    url = f"/ai-assistant/knowledge/items/{fid}"
    assert client.patch(url, json={"title": "해킹"}, headers=stranger).status_code == 404
    assert client.patch(url, json={"title": "익명"}).status_code in (401, 403)
    assert client.get(url, headers=a).json()["title"] != "해킹"


def _pdf_bytes(pages: int) -> bytes:
    from PIL import Image

    imgs = [Image.new("RGB", (300, 400), (200 - i * 20, 220, 240)) for i in range(pages)]
    out = io.BytesIO()
    imgs[0].save(out, "PDF", save_all=True, append_images=imgs[1:])
    return out.getvalue()


def test_original_pdf_is_served_as_page_images_for_the_same_family(client, family, pipeline):
    a, b, _ = family
    up = upload(client, a, _pdf_bytes(3), "scan.pdf", "application/pdf")
    base = f"/ai-assistant/files/{up['id']}/original/pages"
    assert client.get(base, headers=b).json() == {"count": 3}
    page = client.get(f"{base}/2", headers=b)
    assert page.status_code == 200 and page.headers["content-type"] == "image/jpeg"
    assert page.content[:2] == b"\xff\xd8"
    assert client.get(f"{base}/4", headers=a).status_code == 404  # 없는 쪽
    assert client.get(f"{base}/0", headers=a).status_code == 404


def test_original_pdf_pages_are_hidden_from_others_and_non_pdf(client, family, pipeline):
    from tests.helpers import signup

    a, _, _ = family
    pdf = upload(client, a, _pdf_bytes(1), "p.pdf", "application/pdf")
    photo = upload(client, a, png((1, 2, 3)), "p.png")
    stranger = signup(client, "철수")
    client.post("/family-group/groups", json={"name": "남의 가족"}, headers=stranger)
    pages = f"/ai-assistant/files/{pdf['id']}/original/pages"
    assert client.get(pages, headers=stranger).status_code == 404
    assert client.get(f"{pages}/1", headers=stranger).status_code == 404
    assert client.get(pages).status_code in (401, 403)
    assert (
        client.get(f"/ai-assistant/files/{photo['id']}/original/pages", headers=a).status_code
        == 404
    )


def test_the_same_file_uploaded_twice_is_one_source(client, family, pipeline, monkeypatch):
    from app.features.ai_assistant.knowledge import rag_chat

    a, _, _ = family
    pipeline.ocr = FakeOcr([("동대문마트", 0.95), ("합계 34,950원", 0.93)])
    data = png((9, 9, 200))
    first = upload(client, a, data, "r1.png")
    second = upload(client, a, data, "r2.png")  # 같은 파일을 한 번 더
    assert first["id"] != second["id"]
    state = {"calls": 0, "refs": []}

    def fake_post(body):
        state["calls"] += 1
        if state["calls"] == 1:
            call = {
                "type": "tool_use",
                "id": "t",
                "name": "search_knowledge",
                "input": {"query": "마트 합계"},
            }
            return {"content": [call]}
        results = json.loads(body["messages"][-1]["content"][0]["content"])["results"]
        state["refs"] = [r["ref"] for r in results]
        refs = "".join(f"[{r}]" for r in state["refs"])
        return {"content": [{"type": "text", "text": f"합계는 34,950원이에요 {refs}"}]}

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)
    allow_ai(client, a, monkeypatch)
    out = client.post("/ai-assistant/chat", json={"message": "마트 합계 얼마야?"}, headers=a).json()
    assert len(state["refs"]) == 1  # Claude 에게도 같은 파일은 한 번만 간다
    assert len(out["sources"]) == 1 and "[1][1]" not in out["reply"]


def _raw_files(group_id: str) -> list[Path]:
    root = Path(settings.data_dir) / "raw" / group_id
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


def test_deleting_a_record_removes_text_search_and_original(client, family, pipeline):
    a, _, group = family
    pipeline.ocr = FakeOcr([("동대문마트", 0.95), ("합계 34,950원", 0.93)])
    up = upload(client, a, png((77, 7, 7)), "del.png")
    assert _raw_files(group["id"])  # 원본과 화면용 사본이 있다
    r = client.delete(f"/ai-assistant/knowledge/items/{up['id']}", headers=a)
    assert r.status_code == 204
    assert client.get(f"/ai-assistant/knowledge/items/{up['id']}", headers=a).status_code == 404
    assert client.get(f"/ai-assistant/files/{up['id']}", headers=a).status_code == 404
    assert client.get(f"/ai-assistant/files/{up['id']}/original", headers=a).status_code == 404
    assert [i["id"] for i in client.get("/ai-assistant/knowledge/items", headers=a).json()] == []
    hits = client.post(
        "/ai-assistant/knowledge/search", json={"query": "마트 합계"}, headers=a
    ).json()["hits"]
    assert hits == []
    assert _raw_files(group["id"]) == []  # 서버에 둔 원본도 지워졌다
    assert client.delete(f"/ai-assistant/knowledge/items/{up['id']}", headers=a).status_code == 404


def test_original_stays_while_another_record_uses_the_same_file(client, family, pipeline):
    a, _, group = family
    data = png((1, 77, 7))
    first = upload(client, a, data, "x1.png")
    second = upload(client, a, data, "x2.png")  # 같은 파일을 한 번 더
    assert (
        client.delete(f"/ai-assistant/knowledge/items/{first['id']}", headers=a).status_code == 204
    )
    assert _raw_files(group["id"])  # 두 번째 기록이 아직 쓰는 원본은 그대로
    assert client.get(f"/ai-assistant/files/{second['id']}/original", headers=a).status_code == 200
    assert (
        client.delete(f"/ai-assistant/knowledge/items/{second['id']}", headers=a).status_code == 204
    )
    assert _raw_files(group["id"]) == []


def test_other_family_cannot_delete_a_record(client, family, pipeline):
    from tests.helpers import signup

    a, _, _ = family
    up = upload(client, a, png((7, 7, 77)), "keep.png")
    stranger = signup(client, "철수")
    client.post("/family-group/groups", json={"name": "남의 가족"}, headers=stranger)
    url = f"/ai-assistant/knowledge/items/{up['id']}"
    assert client.delete(url, headers=stranger).status_code == 404
    assert client.delete(url).status_code in (401, 403)
    assert client.get(url, headers=a).status_code == 200
    assert client.get(f"/ai-assistant/files/{up['id']}/original", headers=a).status_code == 200


def test_blurry_lines_are_marked_asked_about_and_cleared_when_confirmed(client, family, pipeline):
    a, _, _ = family
    pipeline.ocr = FakeOcr(
        [("하나로마트 동대문점", 0.95), ("우유 2,95O원", 0.55), ("합계 9,900원", 0.93)]
    )
    up = upload(client, a, png((5, 50, 5)), "doubt.png")
    status = client.get(f"/ai-assistant/files/{up['id']}", headers=a).json()
    assert status["status"] == "needs_review"
    assert status["doubts"] == ["우유 2,95O원"]  # 흐린 줄만 물어본다
    assert status["title"] == "하나로마트 동대문점"  # 제목에는 표시가 섞이지 않는다
    body = client.get(f"/ai-assistant/knowledge/items/{up['id']}", headers=a).json()["body_md"]
    assert "우유 2,95O원 [불확실]" in body and "합계 9,900원 [불확실]" not in body

    # 사용자가 줄을 고쳐서 저장하면 표시가 사라지고 확인 필요도 사라진다
    fixed = body.replace("우유 2,95O원 [불확실]", "우유 2,950원")
    r = client.patch(
        f"/ai-assistant/knowledge/items/{up['id']}", json={"body_md": fixed}, headers=a
    ).json()
    assert (
        "[불확실]" not in r["body_md"] and "2,950원" in r["body_md"] and r["needs_review"] is False
    )
    after = client.get(f"/ai-assistant/files/{up['id']}", headers=a).json()
    assert after["status"] == "analyzed" and after["doubts"] == []


def test_confirming_without_changes_also_clears_the_doubt_marks(client, family, pipeline):
    a, _, _ = family
    pipeline.ocr = FakeOcr([("가게 이름", 0.95), ("합계 1,000원", 0.4)])
    up = upload(client, a, png((50, 5, 5)), "doubt2.png")
    assert client.get(f"/ai-assistant/files/{up['id']}", headers=a).json()["doubts"]
    r = client.patch(f"/ai-assistant/knowledge/items/{up['id']}", json={}, headers=a).json()
    assert "[불확실]" not in r["body_md"] and "합계 1,000원" in r["body_md"]


def test_raw_store_refuses_paths_that_leave_the_group_folder(tmp_path):
    from app.features.ai_assistant.ingest.raw_store import LocalRawStore

    store = LocalRawStore(tmp_path)
    other = tmp_path / "g2" / "ab"
    other.mkdir(parents=True)
    victim = other / "x.png"
    victim.write_bytes(b"secret")
    mine = tmp_path / "g1" / "ab"
    mine.mkdir(parents=True)
    ok = mine / "y.png"
    ok.write_bytes(b"mine")

    bad = [
        "g1/../g2/ab/x.png",
        "g1/ab/../../g2/ab/x.png",
        "g1/./../g2/ab/x.png",
        str(victim),
        "/g2/ab/x.png",
        "g1\\..\\g2\\ab\\x.png",
        "g1/ab/x.png\x00",
        "g1//../g2/ab/x.png",
        "g2/ab/x.png",
        "g1",
        "g1/",
        "",
        "  ",
    ]
    for ref in bad:
        with pytest.raises(ValueError):
            store.get_for_group("g1", ref)
        with pytest.raises(ValueError):
            store.delete_for_group("g1", ref)
    assert victim.read_bytes() == b"secret"
    with pytest.raises(OSError):
        store.get_for_group("g1", "g1/%2e%2e/g2/ab/x.png")
    assert store.get_for_group("g1", "g1/ab/y.png") == b"mine"
    store.delete_for_group("g1", "g1/ab/y.png")
    assert not ok.exists() and victim.exists()


def test_forged_source_path_cannot_delete_another_familys_original(
    client, family, pipeline, monkeypatch
):
    from tests.helpers import signup

    a, _, group = family
    stranger = signup(client, "철수")
    other_group = client.post(
        "/family-group/groups", json={"name": "남의 가족"}, headers=stranger
    ).json()
    allow_ai(client, stranger, monkeypatch)  # 사진 업로드는 그 가족의 AI 동의가 있어야 한다
    theirs = upload(client, stranger, png((200, 1, 1)), "theirs.png")
    their_files = _raw_files(other_group["id"])
    assert their_files
    their_item = client.get(
        f"/ai-assistant/knowledge/items/{theirs['id']}", headers=stranger
    ).json()
    victim_path = their_item["source_path"]

    # 클라이언트가 보낸 source_path 는 무시된다
    forged = f"{group['id']}/../{victim_path}"
    r = client.post(
        "/ai-assistant/knowledge/items",
        json={"kind_label": "메모", "title": "위조", "body_md": "내용", "source_path": forged},
        headers=a,
    )
    assert r.status_code == 201 and r.json()["source_path"] is None
    assert (
        client.delete(f"/ai-assistant/knowledge/items/{r.json()['id']}", headers=a).status_code
        == 204
    )

    # DB 에 이미 위조 경로가 들어 있어도(예전 데이터) 지울 때 남의 원본은 남는다
    from app.features.ai_assistant.knowledge.models import KnowledgeItem
    from app.shared.db import SessionLocal

    mine = upload(client, a, png((9, 9, 9)), "mine.png")
    with SessionLocal() as db:
        db.get(KnowledgeItem, mine["id"]).source_path = forged
        db.commit()
    assert client.get(f"/ai-assistant/files/{mine['id']}/original", headers=a).status_code == 404
    assert (
        client.delete(f"/ai-assistant/knowledge/items/{mine['id']}", headers=a).status_code == 204
    )
    assert sorted(_raw_files(other_group["id"])) == sorted(their_files)
    assert (
        client.get(f"/ai-assistant/files/{theirs['id']}/original", headers=stranger).status_code
        == 200
    )


class FlakyOcr(FakeOcr):
    """앞의 몇 번은 Claude 연결이 안 되는 것처럼 실패하고 그 뒤로는 읽는다."""

    def __init__(self, lines, fail_times):
        super().__init__(lines)
        self.fail_times, self.calls = fail_times, 0

    def read(self, image):
        from app.shared.llm.transport import LLMUnavailable

        self.calls += 1
        if self.calls <= self.fail_times:
            raise LLMUnavailable("test")
        return super().read(image)


def test_file_failed_by_llm_outage_is_retried_and_saved(client, family, pipeline, monkeypatch):
    a, _, _ = family
    monkeypatch.setattr(settings, "ingest_retry_max", 2)
    pipeline.ocr = FlakyOcr([("동대문마트", 0.95), ("합계 34,950원", 0.93)], fail_times=2)
    up = upload(client, a, png(), "영수증.png")
    st = client.get(f"/ai-assistant/files/{up['id']}", headers=a).json()
    assert st["status"] in ("analyzed", "needs_review")
    assert pipeline.ocr.calls == 3  # 처음 1번 + 다시 2번


def test_file_stays_failed_when_retries_run_out(client, family, pipeline, monkeypatch):
    a, _, _ = family
    monkeypatch.setattr(settings, "ingest_retry_max", 1)
    pipeline.ocr = FlakyOcr([("동대문마트", 0.95)], fail_times=99)
    up = upload(client, a, png(), "영수증.png")
    st = client.get(f"/ai-assistant/files/{up['id']}", headers=a).json()
    assert st["status"] == "failed"
    assert pipeline.ocr.calls == 2  # 처음 1번 + 다시 1번


def test_broken_file_is_not_retried(client, family, pipeline, monkeypatch):
    a, _, _ = family
    monkeypatch.setattr(settings, "ingest_retry_max", 2)
    pipeline.ocr = FlakyOcr([("x", 0.9)], fail_times=0)
    up = upload(
        client, a, bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + b"broken", "깨짐.png"
    )
    st = client.get(f"/ai-assistant/files/{up['id']}", headers=a).json()
    assert st["status"] == "failed"
    assert pipeline.ocr.calls == 0  # 열 수 없는 파일은 읽기까지 가지 못하고 다시 하지도 않는다


def test_retry_can_be_turned_off(client, family, pipeline, monkeypatch):
    a, _, _ = family
    monkeypatch.setattr(settings, "ingest_retry_max", 0)
    pipeline.ocr = FlakyOcr([("동대문마트", 0.95)], fail_times=1)
    up = upload(client, a, png(), "영수증.png")
    st = client.get(f"/ai-assistant/files/{up['id']}", headers=a).json()
    assert st["status"] == "failed" and pipeline.ocr.calls == 1
