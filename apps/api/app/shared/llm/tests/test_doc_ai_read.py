"""글자 읽기: 출력 상한에서 잘린 쪽만 사고를 줄여 한 번 더 읽는다."""

from app.shared.llm import doc_ai


def _reply(text: str, stop: str) -> dict:
    return {
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def test_read_retries_with_low_effort_only_when_truncated(monkeypatch):
    calls: list[str | None] = []

    def fake_call(model, system, content, tool, max_tokens, timeout, effort=None):
        calls.append(effort)
        return _reply(
            "잘린 글" if effort is None else "끝까지 읽은 긴 글",
            "max_tokens" if effort is None else "end_turn",
        )

    monkeypatch.setattr(doc_ai, "_call", fake_call)
    out = doc_ai._read({"type": "text", "text": "x"}, "옮겨 적으세요")
    assert calls == [None, "low"]
    assert out.text == "끝까지 읽은 긴 글"
    assert out.truncated is False
    assert (out.input_tokens, out.output_tokens) == (20, 10)


def test_read_once_when_not_truncated(monkeypatch):
    calls: list[str | None] = []

    def fake_call(model, system, content, tool, max_tokens, timeout, effort=None):
        calls.append(effort)
        return _reply("다 읽음", "end_turn")

    monkeypatch.setattr(doc_ai, "_call", fake_call)
    out = doc_ai._read({"type": "text", "text": "x"}, "옮겨 적으세요")
    assert calls == [None]
    assert out.text == "다 읽음"


def test_pdf_page_asks_for_figure_notes_but_photo_does_not(monkeypatch):
    """PDF 쪽에는 그림 설명 규칙이 붙고, 사진 업로드에는 붙지 않는다(일반 사진이 문서로 저장되면 안 된다)."""
    systems: list[str] = []

    def fake_call(model, system, content, tool, max_tokens, timeout, effort=None):
        systems.append(system)
        return _reply("글", "end_turn")

    monkeypatch.setattr(doc_ai, "_call", fake_call)
    doc_ai.read_pdf(b"%PDF-")
    doc_ai.read_image(b"\xff\xd8")
    assert "[그림:" in systems[0]
    assert "[그림:" not in systems[1]
    assert systems[1] == doc_ai.OCR_SYSTEM
