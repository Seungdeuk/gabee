"""단계형(E) 판정 규칙과 SigLIP2 ONNX margin 점수기. 모델 파일 없이 도는 시험이 기본이고, 실제 ONNX 모델이 있으면(환경변수
`GABEE_TEST_SIGLIP_ONNX_DIR`) 합성 사진으로 한 번 실제 추론도 해 본다(없으면 건너뜀). 평가 수치와 섞지 않는다."""

import io
import json
import math
import os
from pathlib import Path

import pytest
from PIL import Image

from app.features.ai_assistant.ingest import siglip_margin
from app.features.ai_assistant.ingest.siglip_margin import MarginError, OnnxMarginScorer


def test_the_frozen_thresholds_and_prompts_are_unchanged():
    """평가 동결 설정(exp-1)의 값 그대로: 문서 기준은 평가의 t_rescue=5 를 재사용하고(새로 맞춘 값이 아니다), 문장 14개(문서 6 + 일반 8)."""
    assert siglip_margin.T_DOCUMENT == 5.0
    assert siglip_margin.DOC_PROMPTS == (
        "a photo of a paper document",
        "a photo of a printed form with a table",
        "a photo of a receipt",
        "a photo of an ID card",
        "a photo of a page of text",
        "a scanned document",
    )
    assert siglip_margin.PHOTO_PROMPTS == (
        "a photo of a landscape",
        "a photo of food on a plate",
        "a photo of people outdoors",
        "a photo of a menu board",
        "a photo of street signs",
        "a photo of a poster",
        "a photo of a book cover",
        "a photo of a family",
    )


@pytest.mark.parametrize(
    ("margin", "expected"),
    [
        (8.0, "document"),  # 글자 많은 문서
        (5.01, "document"),
        (5.0, "unsure"),  # 경계: 초과일 때만
        (3.21, "unsure"),  # 평가에서 놓친 글자 적은·평범한 문서(unsure 로 남는다)
        (1.0, "unsure"),
        (-9.0, "unsure"),  # 일반 사진도 photo 가 아니라 unsure(D-13)
    ],
)
def test_the_siglip_only_rule(margin, expected):
    assert siglip_margin.photo_status(margin) == expected


def test_the_siglip_only_rule_never_returns_photo():
    for margin in (-50.0, -1.0, 0.0, 1.0, 3.0, 5.0, 50.0):
        assert siglip_margin.photo_status(margin) in ("document", "unsure")


def test_model_files_status_reports_presence_without_reading(tmp_path):
    assert siglip_margin.model_files_status("") == "not_configured"
    assert siglip_margin.model_files_status(str(tmp_path)) == "missing"
    (tmp_path / siglip_margin.MODEL_FILE).write_bytes(b"x")
    assert (
        siglip_margin.model_files_status(str(tmp_path)) == "missing"
    )  # 두 파일이 모두 있어야 한다
    (tmp_path / siglip_margin.HEAD_FILE).write_text("{}")
    assert siglip_margin.model_files_status(str(tmp_path)) == "present"


def _jpeg(size=(320, 240), color=(235, 235, 235)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="JPEG")
    return out.getvalue()


def test_the_margin_formula_is_doc_max_minus_photo_max_of_scaled_cosines():
    """logit = exp(scale)·cos + bias, margin = max(문서 6) − max(일반 8). 14×768 의 한 축만 켠 단순 임베딩으로 손계산과 비교."""
    dim = siglip_margin.EMBED_DIM
    text = [[1.0 if j == i else 0.0 for j in range(dim)] for i in range(14)]
    image = [0.0] * dim
    image[2] = 0.8  # 문서 3번째 문장과 닮음(cos 0.8)
    image[9] = 0.6  # 일반 4번째 문장과 닮음(cos 0.6)
    scale, bias = math.log(100.0), -10.0
    expected = (100.0 * 0.8 + bias) - (100.0 * 0.6 + bias)
    assert siglip_margin.margin_from_embedding(image, text, scale, bias) == pytest.approx(expected)
    # 편향은 양쪽에서 같이 빠져 margin 에 영향이 없다
    assert siglip_margin.margin_from_embedding(image, text, scale, 7.0) == pytest.approx(expected)


def test_preprocessing_matches_the_original_settings():
    """224×224 로 찌그러뜨려 줄이고 평균·표준편차 0.5 로 정규화한 (1,3,224,224) float32."""
    pixels = OnnxMarginScorer.preprocess(_jpeg((640, 480), (255, 255, 255)))
    assert pixels.shape == (1, 3, 224, 224) and str(pixels.dtype) == "float32"
    assert float(pixels.max()) == pytest.approx(1.0, abs=0.02)  # 흰색 → (1 − 0.5)/0.5 = 1
    black = OnnxMarginScorer.preprocess(_jpeg((100, 300), (0, 0, 0)))
    assert float(black.min()) == pytest.approx(-1.0, abs=0.02)


def test_an_unreadable_image_is_an_error_not_a_verdict():
    with pytest.raises(MarginError, match="InvalidImage"):
        OnnxMarginScorer.preprocess(b"not an image")


def test_an_oversized_image_is_refused_before_decoding(monkeypatch):
    monkeypatch.setattr(siglip_margin, "MAX_PIXELS", 100)
    with pytest.raises(MarginError, match="ImageTooLarge"):
        OnnxMarginScorer.preprocess(_jpeg((320, 240)))


def test_no_model_dir_is_an_error(tmp_path):
    with pytest.raises(MarginError, match="ModelDirMissing"):
        OnnxMarginScorer("").score(_jpeg())


def test_a_missing_model_file_is_an_error(tmp_path):
    with pytest.raises(MarginError, match="ModelFileMissing"):
        OnnxMarginScorer(str(tmp_path)).score(_jpeg())


def _fake_dir(tmp_path: Path, head: dict | None = None, model_bytes: bytes = b"garbage") -> Path:
    (tmp_path / siglip_margin.MODEL_FILE).write_bytes(model_bytes)
    if head is None:
        head = {
            "doc_prompts": list(siglip_margin.DOC_PROMPTS),
            "photo_prompts": list(siglip_margin.PHOTO_PROMPTS),
            "text_embeds": [[0.0] * siglip_margin.EMBED_DIM for _ in range(14)],
            "logit_scale": 4.7,
            "logit_bias": -16.7,
        }
    (tmp_path / siglip_margin.HEAD_FILE).write_text(json.dumps(head), encoding="utf-8")
    return tmp_path


def test_a_corrupt_model_file_is_a_load_error_and_not_retried_at_once(tmp_path):
    scorer = OnnxMarginScorer(str(_fake_dir(tmp_path)))
    with pytest.raises(MarginError, match="^Load"):
        scorer.score(_jpeg())
    (tmp_path / siglip_margin.MODEL_FILE).unlink()  # 다시 시도했다면 ModelFileMissing 이 나왔을 것
    with pytest.raises(MarginError, match="^Load"):
        scorer.score(
            _jpeg()
        )  # 실패 직후에는 같은 오류를 바로 돌려준다(깨진 파일을 사진마다 읽지 않는다)


def test_it_retries_the_load_after_the_cooldown(tmp_path, monkeypatch):
    scorer = OnnxMarginScorer(str(_fake_dir(tmp_path)))
    with pytest.raises(MarginError, match="^Load"):
        scorer.score(_jpeg())
    (tmp_path / siglip_margin.MODEL_FILE).unlink()
    scorer._failed_until = 0.0
    with pytest.raises(MarginError, match="ModelFileMissing"):
        scorer.score(_jpeg())


def test_a_head_with_other_prompts_is_refused(tmp_path):
    head = {
        "doc_prompts": ["a different prompt"] * 6,
        "photo_prompts": list(siglip_margin.PHOTO_PROMPTS),
        "text_embeds": [[0.0] * siglip_margin.EMBED_DIM for _ in range(14)],
        "logit_scale": 4.7,
        "logit_bias": -16.7,
    }
    with pytest.raises(MarginError, match="HeadMismatch"):
        OnnxMarginScorer(str(_fake_dir(tmp_path, head))).score(_jpeg())


def test_a_head_with_the_wrong_shape_is_refused(tmp_path):
    head = {
        "doc_prompts": list(siglip_margin.DOC_PROMPTS),
        "photo_prompts": list(siglip_margin.PHOTO_PROMPTS),
        "text_embeds": [[0.0] * 10 for _ in range(14)],
        "logit_scale": 4.7,
        "logit_bias": -16.7,
    }
    with pytest.raises(MarginError, match="HeadMismatch"):
        OnnxMarginScorer(str(_fake_dir(tmp_path, head))).score(_jpeg())


def test_a_broken_head_file_is_a_load_error(tmp_path):
    folder = _fake_dir(tmp_path)
    (folder / siglip_margin.HEAD_FILE).write_text("{not json", encoding="utf-8")
    with pytest.raises(MarginError, match="^Load"):
        OnnxMarginScorer(str(folder)).score(_jpeg())


def test_a_memory_error_while_loading_is_reported_as_out_of_memory(tmp_path, monkeypatch):
    import onnxruntime as ort

    def boom(*args, **kwargs):
        raise MemoryError

    monkeypatch.setattr(ort, "InferenceSession", boom)
    with pytest.raises(MarginError, match="OutOfMemory"):
        OnnxMarginScorer(str(_fake_dir(tmp_path))).score(_jpeg())


def test_the_shared_scorer_comes_from_the_settings(monkeypatch, tmp_path):
    from app.shared.config import settings

    monkeypatch.setattr(settings, "photo_classify_model_dir", str(tmp_path))
    monkeypatch.setattr(settings, "photo_classify_threads", 3)
    siglip_margin.set_scorer(None)
    try:
        scorer = siglip_margin.get_scorer()
        assert isinstance(scorer, OnnxMarginScorer)
        assert (scorer.model_dir, scorer.threads) == (str(tmp_path), 3)
        assert siglip_margin.get_scorer() is scorer  # 한 번만 만든다
    finally:
        siglip_margin.set_scorer(None)


@pytest.mark.skipif(
    not os.environ.get("GABEE_TEST_SIGLIP_ONNX_DIR"),
    reason="실제 ONNX 모델 폴더(GABEE_TEST_SIGLIP_ONNX_DIR)가 있을 때만",
)
def test_a_real_model_scores_a_synthetic_page_above_a_plain_sky():
    scorer = OnnxMarginScorer(os.environ["GABEE_TEST_SIGLIP_ONNX_DIR"])
    page = Image.new("RGB", (640, 880), (250, 250, 248))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(page)
    for row in range(40):
        draw.rectangle((50, 40 + row * 20, 590 - (row % 5) * 60, 48 + row * 20), fill=(40, 40, 40))
    out = io.BytesIO()
    page.save(out, format="JPEG")
    sky = Image.new("RGB", (640, 480), (120, 170, 230))
    sky_out = io.BytesIO()
    sky.save(sky_out, format="JPEG")
    assert scorer.score(out.getvalue()) > scorer.score(sky_out.getvalue())


def _model_dir(tmp_path):
    (tmp_path / siglip_margin.MODEL_FILE).write_bytes(b"x")
    (tmp_path / siglip_margin.HEAD_FILE).write_text("{}", encoding="utf-8")
    return str(tmp_path)


def test_startup_warns_when_the_switch_is_off_because_document_registration_stops(
    tmp_path, monkeypatch, caplog
):
    """서버는 로그 설정이 없어 WARNING 이상만 남는다. 판별 스위치가 꺼져 있으면(모델이 있어도) 모든 사진이 unsure 가 되어
    문서 사진 자동 등록이 멈추므로 WARNING 으로 알려야 운영에서 잘못된 환경변수를 알아챌 수 있다."""
    from app.shared.config import settings

    monkeypatch.setattr(settings, "photo_classify_model_dir", _model_dir(tmp_path))
    monkeypatch.setattr(settings, "photo_classify_siglip", False)
    with caplog.at_level("WARNING", logger=siglip_margin.logger.name):
        assert siglip_margin.log_model_status() == "present"
    assert any(
        r.levelname == "WARNING" and "PHOTO_CLASSIFY_SIGLIP" in r.getMessage()
        for r in caplog.records
    )


def test_startup_warns_when_the_model_is_missing_even_with_the_switch_off(
    tmp_path, monkeypatch, caplog
):
    from app.shared.config import settings

    monkeypatch.setattr(settings, "photo_classify_model_dir", str(tmp_path))
    monkeypatch.setattr(settings, "photo_classify_siglip", False)
    with caplog.at_level("WARNING", logger=siglip_margin.logger.name):
        assert siglip_margin.log_model_status() == "missing"
    assert any(r.levelname == "WARNING" for r in caplog.records)


def test_startup_is_quiet_when_the_model_is_present_and_the_switch_is_on(
    tmp_path, monkeypatch, caplog
):
    from app.shared.config import settings

    monkeypatch.setattr(settings, "photo_classify_model_dir", _model_dir(tmp_path))
    monkeypatch.setattr(settings, "photo_classify_siglip", True)
    with caplog.at_level("WARNING", logger=siglip_margin.logger.name):
        assert siglip_margin.log_model_status() == "present"
    assert not [r for r in caplog.records if r.levelno >= 30]
