"""시드 후보 사진마다 AI 로 탐정단 질문·보기·정답·확대 위치 초안을 만들어 사람이 확인할 파일로 떨군다.

사용법 (apps/api 에서):
    python -m scripts.draft_photo_seed <후보 폴더> [--workers 4]

입력: `fetch_pixabay_seed.py` 가 만든 폴더(`candidates.json`, `img/NNN.jpg`).
출력(같은 폴더): `seed.json`(쓸 수 있다고 한 사진만, `seed_photo_rec.py` 형식), `review.md`(표), `review.html`(사진·확대 위치 상자·질문·보기를 한 화면에서 확인).
AI 에는 Pixabay 공개 사진만 보낸다(`content_question`, 사진 한 장당 한 번·규칙에 안 맞으면 한 번 더). 가족 정보는 없다.
"""

import argparse
import html
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.features.ai_assistant.ingest.photo_judge import to_judge_jpeg
from app.features.play.photo_rec_ai import (
    ContentFailed,
    ContentResult,
    content_question,
    validate_content,
)
from app.shared.llm import client as llm

ZOOM = 8  # 시드 문제의 기본 확대 배율(출제자가 고칠 수 있다)
KIND_CONTENT = 3


def answers_ask(answers: dict, cand: dict):
    """AI 를 부르는 대신 미리 써 둔 답(`{"001": {usable, question, options, answer_index, box_x, box_y}}`)을 쓰는 `ask`.
    서버가 내용 질문에 쓰는 규칙(`validate_content`)으로 똑같이 검증하고, 규칙에 안 맞거나 항목이 없으면 `ContentFailed`."""

    def ask(_jpeg: bytes) -> ContentResult:
        valid = validate_content(answers.get(f"{cand['no']:03d}"))
        if valid is None:
            raise ContentFailed("답 파일의 항목이 없거나 규칙에 안 맞음", 0, 0, 0)
        return ContentResult(**valid, input_tokens=0, output_tokens=0, model="manual")

    return ask


def draft_one(folder: Path, cand: dict, ask=content_question) -> dict:
    """후보 한 장의 초안. {cand 정보, status: ok|unusable|failed, question, options, answer_index, box_x, box_y, tokens}."""
    base = {**cand, "status": "failed", "tokens": 0}
    try:
        result = ask(to_judge_jpeg((folder / cand["file"]).read_bytes()))
    except ContentFailed as exc:
        return {**base, "tokens": exc.input_tokens + exc.output_tokens, "reason": "규칙에 안 맞음"}
    except llm.LLMUnavailable as exc:
        return {**base, "reason": f"AI 호출 실패: {exc}"}
    tokens = result.input_tokens + result.output_tokens
    if not result.usable:
        return {**base, "status": "unusable", "tokens": tokens}
    return {
        **base,
        "status": "ok",
        "tokens": tokens,
        "question": result.question,
        "options": result.options,
        "answer_index": result.answer_index,
        "box_x": result.box_x,
        "box_y": result.box_y,
    }


def _num(d: dict) -> str:
    """검수표에 보이는 번호. 같은 사진으로 문제를 둘 만들 때는 `tag`(예: 025b)로 구분한다."""
    return d.get("tag") or f"{d['no']:03d}"


def to_seed(drafts: list[dict]) -> list[dict]:
    """쓸 수 있다고 한 초안만 `seed_photo_rec.py` 가 읽는 항목으로 바꾼다."""
    return [
        {
            "key": _num(d),
            "image": d["file"],
            "kind": KIND_CONTENT,
            "question": d["question"],
            "options": d["options"],
            "answer_index": d["answer_index"],
            "box_x": d["box_x"],
            "box_y": d["box_y"],
            "zoom": ZOOM,
        }
        for d in drafts
        if d["status"] == "ok"
    ]


_STATUS = {"ok": "사용 가능", "unusable": "제외 추천(AI가 쓰지 말라고 함)", "failed": "AI 실패"}


def review_md(drafts: list[dict]) -> str:
    lines = [
        "| 번호 | 파일 | 분류 | AI 판정 | 질문 | 보기(정답 ✔) | 확대 위치 | 태그 | 승인 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for d in drafts:
        opts = " / ".join(
            f"{'✔' if i == d.get('answer_index') else ''}{o}"
            for i, o in enumerate(d.get("options", []))
        )
        box = f"({d['box_x']:.2f}, {d['box_y']:.2f})" if d["status"] == "ok" else ""
        lines.append(
            f"| {_num(d)} | {d['file']} | {d['category']} | {_STATUS[d['status']]} | "
            f"{d.get('question', '')} | {opts} | {box} | {d.get('tags', '')[:60]} |  |"
        )
    return "\n".join(lines) + "\n"


def review_html(drafts: list[dict]) -> str:
    """사진(확대 위치를 붉은 상자로 표시)과 질문·보기를 나란히 보여 주는 한 장짜리 확인용 페이지."""
    rows = []
    for d in drafts:
        esc = html.escape
        box = ""
        if d["status"] == "ok":
            w = 100 / ZOOM
            left = min(max((d["box_x"] * 100) - w / 2, 0), 100 - w)
            top = min(max((d["box_y"] * 100) - w / 2, 0), 100 - w)
            box = f'<div class="box" style="left:{left:.1f}%;top:{top:.1f}%;width:{w:.1f}%;height:{w:.1f}%"></div>'
        opts = "".join(
            f'<li class="{"ans" if i == d.get("answer_index") else ""}">{esc(o)}</li>'
            for i, o in enumerate(d.get("options", []))
        )
        rows.append(
            f'<tr class="{d["status"]}"><td>{_num(d)}<br><small>{esc(d["category"])} {esc(d.get("label", ""))}</small></td>'
            f'<td><div class="ph"><img src="{esc(d["file"])}" width="320">{box}</div></td>'
            f"<td><b>{esc(d.get('question', ''))}</b><ol>{opts}</ol>"
            f"<small>{esc(_STATUS[d['status']])} · {esc(d.get('reason', ''))}<br>{esc(d.get('note', ''))}<br>{esc(d.get('tags', ''))}<br>"
            f'<a href="{esc(d.get("page_url", ""))}">{esc(d.get("user", ""))}</a></small></td></tr>'
        )
    style = (
        "body{font-family:sans-serif;margin:16px}table{border-collapse:collapse}td{border:1px solid #ccc;"
        "padding:8px;vertical-align:top}.ph{position:relative;display:inline-block}.box{position:absolute;"
        "border:3px solid #e33;box-sizing:border-box}li.ans{font-weight:bold;color:#0a7a2f}"
        "tr.unusable,tr.failed{background:#fdeeee}"
    )
    return (
        f'<!doctype html><meta charset="utf-8"><title>시드 검수</title><style>{style}</style>'
        "<h2>탐정단 흔한 사진 시드 검수</h2><p>붉은 상자 = 확대되는 위치(8배), 굵은 초록 = 정답. "
        "번호로 승인·수정·제외를 알려 주세요.</p><table>" + "".join(rows) + "</table>"
    )


def run(
    folder: Path, workers: int = 4, ask=content_question, answers: dict | None = None
) -> list[dict]:
    cands = json.loads((folder / "candidates.json").read_text(encoding="utf-8"))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        drafts = list(
            pool.map(
                lambda c: draft_one(
                    folder, c, answers_ask(answers, c) if answers is not None else ask
                ),
                cands,
            )
        )
    (folder / "seed.json").write_text(
        json.dumps(to_seed(drafts), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (folder / "review.md").write_text(review_md(drafts), encoding="utf-8")
    (folder / "review.html").write_text(review_html(drafts), encoding="utf-8")
    return drafts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path, help="fetch_pixabay_seed.py 가 만든 후보 폴더")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--answers",
        type=Path,
        nargs="+",
        help="AI 를 부르지 않고 미리 써 둔 답 JSON 파일(여러 개 가능, 번호 '001' → 질문·보기·정답·확대 위치)",
    )
    args = parser.parse_args(argv)
    answers = None
    if args.answers:
        answers = {}
        for path in args.answers:
            answers.update(json.loads(path.read_text(encoding="utf-8")))
    drafts = run(args.folder, args.workers, answers=answers)
    counts = {s: sum(d["status"] == s for d in drafts) for s in _STATUS}
    tokens = sum(d["tokens"] for d in drafts)
    print(f"초안 {len(drafts)}장: {counts}, 토큰 합계 {tokens} → {args.folder}\\review.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
