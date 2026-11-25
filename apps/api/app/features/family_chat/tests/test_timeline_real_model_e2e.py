"""실제 SigLIP2 ONNX 로 업로드 → 분석 → 타임라인까지 이어서 확인하는 선택 시험(환경변수가 있을 때만 돈다: CI 에는 모델·사진이 없다).

- GABEE_SIGLIP_TEST_DIR: 모델 폴더(siglip2_vision.onnx + head.json)
- GABEE_TIMELINE_E2E_IMAGES: 사진 폴더(하위 `scenes/`, `docs/` 의 이미지, 합성·공개 사진만 쓴다. 실제 가족 사진 금지)
정확도를 평가하지 않는다: 각 사진의 타임라인 노출이 "모델이 낸 margin ≤ 5" 와 일치하는지, 같은 사진의 축소본이 같은 날 한 묶음이 되는지, 제외가 유지되는지만 본다."""

import io
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image

from app.features.ai_assistant.ingest import siglip_margin
from app.features.family_chat import photo_check_service as pcs
from app.features.family_chat import photo_service as ps
from app.features.family_chat import timeline_features as tf
from app.features.family_chat.models import ChatPhotoCheck, MessageAttachment
from app.shared import chat_library, photo_analysis_consent
from app.shared.config import settings
from app.shared.db import SessionLocal

MODEL = os.environ.get("GABEE_SIGLIP_TEST_DIR")
IMAGES = os.environ.get("GABEE_TIMELINE_E2E_IMAGES")
pytestmark = pytest.mark.skipif(
    not (MODEL and IMAGES), reason="실제 모델·사진 폴더 환경변수가 있을 때만 도는 선택 시험"
)
_REAL_SCHEDULE = tf.schedule
DAY = datetime(2026, 11, 21, 3, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _real_pipeline(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "photo_classify_model_dir", MODEL)
    monkeypatch.setattr(chat_library, "_on_photo", None)
    monkeypatch.setattr(
        settings, "timeline_auto_candidates", True
    )  # 자동 후보 동작 자체를 본다(기본 꺼짐, ADR 0026)
    monkeypatch.setattr(
        photo_analysis_consent, "_checker", lambda db, group_id, uploaders: set(uploaders)
    )
    ps.upload_limiter._failures.clear()
    pcs.check_limiter._failures.clear()
    monkeypatch.setattr(tf, "schedule", _REAL_SCHEDULE)
    siglip_margin.set_scorer(None)
    tf._cache.clear()
    tf._inflight.clear()
    yield
    siglip_margin.set_scorer(None)


def _upload(client, headers, data: bytes, name="a.jpg") -> str:
    r = client.post(
        "/family-chat/photos", files={"file": (name, data, "image/jpeg")}, headers=headers
    )
    assert r.status_code == 201, r.text
    att = r.json()["attachment"]["id"]
    # 시험에서는 문서함 판별이 돌지 않아 대기(pending)로 남는다: 판별이 끝나 애매(unsure)가 된 상태로 둔다(타임라인 자동 분석 범위, ADR 0026).
    # 문서 사진을 숨기는 것은 이 시험에서 타임라인의 SigLIP2 margin 규칙이 맡는다(실제 서비스에서는 판별이 먼저 document 로 적어 범위 밖이 된다).
    with SessionLocal() as db:
        row = db.get(ChatPhotoCheck, att)
        row.status, row.source = "unsure", "auto"
        db.commit()
    return att


def _jpeg(path: Path, scale=1.0) -> bytes:
    image = Image.open(path).convert("RGB")
    if scale != 1.0:
        image = image.resize((int(image.width * scale), int(image.height * scale)))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=88)
    return out.getvalue()


def _taken(att, when):
    with SessionLocal() as db:
        db.get(MessageAttachment, att).taken_at = when
        db.commit()


def _run_all(ids):
    for att in ids:
        assert tf.analyze_attachment(att) is True


def test_real_model_pipeline_matches_the_margin_rule_groups_resized_copies_and_keeps_exclusions(
    client, family
):
    a, _, _ = family
    root = Path(IMAGES)
    scenes = sorted((root / "scenes").glob("*"))[:4]
    docs = sorted((root / "docs").glob("*"))[:3]
    assert scenes and docs
    ids = {}
    for i, path in enumerate(scenes + docs):
        att = _upload(client, a, _jpeg(path))
        _taken(att, DAY + timedelta(days=i))  # 사진마다 다른 날(서로 다른 날짜는 합쳐지지 않는다)
        ids[att] = path
    # 첫 장면 사진의 축소본: 같은 날, 같은 사진
    first = scenes[0]
    copy_id = _upload(client, a, _jpeg(first, 0.5))
    _taken(copy_id, DAY + timedelta(minutes=20))
    ids[copy_id] = first
    _run_all(list(ids))

    scorer = siglip_margin.get_scorer()
    expected_visible = {
        att for att in ids if scorer.score(_jpeg(ids[att], 0.5 if att == copy_id else 1.0)) <= 5.0
    }
    body = client.get("/family-chat/timeline/photos", headers=a).json()
    shown = {i["attachment_id"] for i in body["items"]}
    assert shown == expected_visible  # 노출은 모델이 낸 margin ≤ 5 와 정확히 일치한다
    assert body["analyzing"] == 0 and body["analysis_failed"] == 0
    original_id = next(att for att, path in ids.items() if path == first and att != copy_id)
    if {original_id, copy_id} <= shown:
        items = {i["attachment_id"]: i for i in body["items"]}
        assert (
            items[original_id]["batch_id"] == items[copy_id]["batch_id"]
        )  # 같은 날 같은 사진은 한 묶음
        assert items[original_id]["group_kind"] == "similar"
    # 제외하면 다시 나타나지 않는다
    if shown:
        gone = sorted(shown)[0]
        assert client.post(f"/family-chat/photos/{gone}/exclude", headers=a).status_code == 200
        tf._cache.clear()
        again = {
            i["attachment_id"]
            for i in client.get("/family-chat/timeline/photos", headers=a).json()["items"]
        }
        assert gone not in again and again == shown - {gone}
