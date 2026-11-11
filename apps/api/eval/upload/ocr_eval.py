"""업로드 글자 읽기(OCR) 평가: 서비스의 읽기 함수를 그대로 불러 KDoc 공공문서 쪽을 읽히고 채점한다.

    PYTHONPATH=. python eval/upload/ocr_eval.py --name sonnet_clean --max-usd 2 [--n 50] [--seed 7] [--set clean|degraded] [--input image|pdf]
    PYTHONPATH=. python eval/upload/ocr_eval.py --name sonnet_clean --max-usd 2 --rescore    # 호출 없이 저장된 결과만 다시 채점

- 데이터·정답·채점기: gabee_share/OCR_평가데이터_KDoc (읽기만 한다). 채점은 그 폴더의 score_ocr.py 를 그대로 불러 쓴다.
- 읽기: image 는 서비스의 llm_ingest.ocr_image(= doc_ai.read_image), pdf 는 doc_ai.read_pdf. 모델은 서비스 설정 ingest_ocr_model.
- 추가 지표(이 파일에서 계산): 문자 오류율(CER), 숫자·금액·날짜 정확도, 표 보존, [판독불가]/[?] 표시율.
  CER 정답은 디지털 PDF 의 글자층이다. cer_pct 는 글자층을 30자 안팎 조각으로 모아 각 조각이 읽은 글 어디에든 가장 가깝게 들어 있는 편집거리를 합친 값(읽는 순서 무시),
  cer_global_pct 는 쪽 전체를 한 줄로 맞춘 편집거리(순서가 다르면 크게 나온다)다. 자세한 한계는 README.
- 점수를 보고 평가 데이터나 채점 기준을 고치지 않는다. 쪽마다 중간 저장하고, 같은 --name 으로 다시 돌리면 끝난 쪽은 건너뛴다."""

import argparse
import collections
import glob
import importlib.util
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import common

sys.dont_write_bytecode = True  # 데이터 폴더에 __pycache__ 를 만들지 않는다
import numpy as np  # noqa: E402

DEFAULT_DATA = glob.glob("C:/Users/403/Desktop/gabee_share/OCR_*KDoc")
MARKS = ("[판독불가]", "[?]")
HTML_TAG_OR_MD = re.compile(r"[^0-9A-Za-z가-힣]")
DATE_RE = re.compile(r"(\d{4})\s*(?:년|\.|-|/)\s*(\d{1,2})\s*(?:월|\.|-|/)\s*(\d{1,2})")
THOUSANDS = re.compile(
    r"(?<=\d),(?=\d{3}(?!\d))"
)  # 1,234 -> 1234: 천 단위 쉼표 차이로 틀리게 세지 않는다
AMOUNT_RE = re.compile(
    r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?\s*원"
)  # 쉼표 묶음이거나 '원'이 붙은 숫자
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
CHUNK_MIN = 30  # 순서 무시 CER 의 정답 조각 길이(글자층 줄을 이만큼 모아 한 조각으로)


def load_scorer(data_dir: Path):
    spec = importlib.util.spec_from_file_location("score_ocr", data_dir / "score_ocr.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def edit_distance(a: str, b: str) -> int:
    """글자 단위 편집거리(전체 대 전체). 한 줄씩 numpy 로 계산한다."""
    if not a:
        return len(b)
    if not b:
        return len(a)
    h = np.frombuffer(b.encode("utf-32-le"), dtype=np.uint32)
    idx = np.arange(len(h) + 1)
    prev = idx.astype(np.int32)
    for i, ch in enumerate(a, 1):
        cost = (h != ord(ch)).astype(np.int32)
        tmp = np.empty(len(h) + 1, dtype=np.int32)
        tmp[0] = i
        tmp[1:] = np.minimum(prev[:-1] + cost, prev[1:] + 1)
        prev = np.minimum.accumulate(tmp - idx) + idx
    return int(prev[-1])


def reference_text(pdf_path: Path) -> str:
    """디지털 PDF 한 쪽의 글자층(정답)."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        page = doc[0]
        textpage = page.get_textpage()
        text = textpage.get_text_range()
        textpage.close()
        page.close()
        return text
    finally:
        doc.close()


def strip_header_footer(ref: str, tests: list[dict]) -> str:
    """OCR 에게 적지 말라고 한 쪽 번호·머리말이 정답에 남아 CER 이 부풀지 않게, 채점기의 '없어야 함' 글을 정답 앞뒤 창에서 걷는다."""
    flat = re.sub(r"\s+", "", ref)
    for t in tests:
        if t["type"] != "absent":
            continue
        needle = re.sub(r"\s+", "", t["text"])
        if not needle:
            continue
        if t.get("first_n"):
            head = flat[: t["first_n"]]
            if needle in head:
                flat = flat[: head.find(needle)] + flat[head.find(needle) + len(needle) :]
        elif t.get("last_n"):
            start = max(0, len(flat) - t["last_n"])
            tail = flat[start:]
            if needle in tail:
                k = start + tail.rfind(needle)
                flat = flat[:k] + flat[k + len(needle) :]
    return flat


def normalize_for_cer(text: str) -> str:
    """서식(표 기호·마크다운)·문장부호·공백을 걷고 한글·숫자·영문만 남긴다."""
    return HTML_TAG_OR_MD.sub("", text or "")


def numeric_tokens(text: str) -> dict[str, collections.Counter]:
    """날짜·금액(쉼표로 묶였거나 '원'이 붙은 숫자)·기타 숫자 토큰을 종류별로 센다(먼저 잡힌 글자는 뒤 종류에서 뺀다. 기타 숫자의 천 단위 쉼표는 지운다)."""
    out = {
        "date": collections.Counter(),
        "amount": collections.Counter(),
        "number": collections.Counter(),
    }
    for m in DATE_RE.finditer(text):
        y, mo, d = m.groups()
        out["date"][f"{y}{int(mo):02d}{int(d):02d}"] += 1
    rest = DATE_RE.sub(" ", text)
    for m in AMOUNT_RE.finditer(rest):
        out["amount"][re.sub(r"[^\d.]", "", m.group(0))] += 1
    rest = THOUSANDS.sub("", AMOUNT_RE.sub(" ", rest))
    for m in NUMBER_RE.finditer(rest):
        out["number"][m.group(0)] += 1
    return out


def ref_chunks(ref_raw: str, tests: list[dict], scorer) -> list[str]:
    """정답 글자층을 줄 단위로 모아 CHUNK_MIN 글자 안팎의 조각으로 만든다(머리말·꼬리말로 지정된 글 제외)."""
    absent = [
        normalize_for_cer(t["text"]) for t in tests if t["type"] == "absent" and t["text"].strip()
    ]
    chunks, buf = [], ""
    for line in re.split(r"[\r\n]+", ref_raw):
        piece = normalize_for_cer(line)
        if not piece or piece in absent:
            continue
        buf += piece
        if len(buf) >= CHUNK_MIN:
            chunks.append(buf)
            buf = ""
    if buf:
        if chunks:
            chunks[-1] += buf
        elif len(buf) >= 4:
            chunks.append(buf)
    return chunks


def page_metrics(scorer, hyp: str, ref_raw: str, tests: list[dict]) -> dict:
    """한 쪽의 지표 원자료(합산해서 쓴다)."""
    res = dict(scorer.score(hyp, tests))
    ref_n, hyp_n = normalize_for_cer(strip_header_footer(ref_raw, tests)), normalize_for_cer(hyp)
    res["cerg_chars"] = len(ref_n)
    res["cerg_edits"] = edit_distance(ref_n, hyp_n)
    chunks = ref_chunks(ref_raw, tests, scorer)
    res["cer_chars"] = sum(len(c) for c in chunks)
    res["cer_edits"] = sum(min(scorer.min_dist(c, hyp_n), len(c)) for c in chunks)
    ref_tok, hyp_tok = numeric_tokens(ref_raw), numeric_tokens(hyp)
    for kind in ("date", "amount", "number"):
        matched = sum((ref_tok[kind] & hyp_tok[kind]).values())
        res[f"{kind}_ref"] = sum(ref_tok[kind].values())
        res[f"{kind}_hit"] = matched
        res[f"{kind}_hyp"] = sum(hyp_tok[kind].values())
    tables = scorer.md_tables(hyp) + scorer.html_tables(hyp)
    res["has_table_tests"] = int(res.get("table_n", 0) > 0)
    res["table_emitted"] = int(res.get("table_n", 0) > 0 and bool(tables))
    res["mark_unreadable"] = hyp.count(MARKS[0])
    res["mark_doubt"] = hyp.count(MARKS[1])
    res["pages_with_mark"] = int(any(m in hyp for m in MARKS))
    res["out_chars"] = len(hyp)
    res["pages"] = 1
    return res


def summarize(rows: list[dict]) -> dict:
    """쪽별 원자료를 합쳐 비율 지표로 만든다."""
    agg: collections.Counter = collections.Counter()
    for r in rows:
        agg.update(r)

    def pct(a: str, b: str) -> float | None:
        return round(100 * agg[a] / agg[b], 1) if agg[b] else None

    return {
        "pages": agg["pages"],
        "text_strict": pct("text_strict", "text_n"),
        "text_alnum": pct("text_alnum", "text_n"),
        "text_lenient": pct("text_lenient", "text_n"),
        "table_struct": pct("table_struct", "table_n"),
        "cell_read": pct("cell_read", "table_n"),
        "table_struct_given_cell": pct("table_struct", "cell_read"),
        "table_emitted_pages": pct("table_emitted", "has_table_tests"),
        "header_footer_pass": pct("hf_pass", "hf_n"),
        "cer_pct": pct("cer_edits", "cer_chars"),
        "cer_global_pct": pct("cerg_edits", "cerg_chars"),
        "date_acc": pct("date_hit", "date_ref"),
        "amount_acc": pct("amount_hit", "amount_ref"),
        "number_acc": pct("number_hit", "number_ref"),
        "number_extra_pct": round(
            100
            * sum(agg[f"{k}_hyp"] - agg[f"{k}_hit"] for k in ("date", "amount", "number"))
            / max(1, sum(agg[f"{k}_hyp"] for k in ("date", "amount", "number"))),
            1,
        ),
        "date_n": agg["date_ref"],
        "amount_n": agg["amount_ref"],
        "number_n": agg["number_ref"],
        "mark_per_1000_chars": round(
            1000 * (agg["mark_unreadable"] + agg["mark_doubt"]) / max(1, agg["out_chars"]), 2
        ),
        "mark_unreadable": agg["mark_unreadable"],
        "mark_doubt": agg["mark_doubt"],
        "pages_with_mark_pct": pct("pages_with_mark", "pages"),
    }


def stratified_sample(index: list[dict], n: int, seed: int, pool_degraded: bool) -> list[dict]:
    """문서 종류별로 같은 수(나머지는 시드로 고른 종류에 하나씩 더) 시드 고정으로 뽑는다."""
    rng = random.Random(seed)
    pool = [x for x in index if x.get("degraded")] if pool_degraded else list(index)
    cats = sorted({x["category"] for x in pool})
    n = min(n, len(pool))
    quota = {c: n // len(cats) for c in cats}
    for c in rng.sample(cats, n - sum(quota.values())):
        quota[c] += 1
    picked: list[dict] = []
    for c in cats:
        members = sorted((x for x in pool if x["category"] == c), key=lambda x: x["name"])
        picked += rng.sample(members, min(quota[c], len(members)))
    return sorted(picked, key=lambda x: x["name"])


def read_page(args, item: dict, data_dir: Path, ocr_image, doc_ai) -> dict:
    """서비스 읽기 함수로 한 쪽을 읽는다. 결과 행(글, 걸린 초, 토큰)."""
    started = time.time()
    if args.input == "pdf":
        out = doc_ai.read_pdf((data_dir / "kdoc" / "pdfs" / item["pdf"]).read_bytes())
    else:
        from PIL import Image

        with Image.open(data_dir / "images" / args.set / f"{item['name']}.jpg") as image:
            out = ocr_image(image)
    return {
        "text": out.text,
        "truncated": out.truncated,
        "in": out.input_tokens,
        "out": out.output_tokens,
        "sec": round(time.time() - started, 1),
    }


def compare_rows(scorer, data_dir: Path, tests, by_name, refs, names, args) -> dict:
    """같은 쪽에 대해 reference_results 의 이전 엔진 결과를 같은 지표로 채점한다(호출 없음)."""
    out = {}
    for engine in ("rapidocr", "claude_haiku", "claude_sonnet"):
        folder = data_dir / "reference_results" / engine / args.set
        if not folder.is_dir():
            continue
        rows = []
        for name in names:
            f = folder / f"{name}.json"
            if f.exists():
                text = common.load_json(f)["text"]
                rows.append(page_metrics(scorer, text, refs[name], tests[by_name[name]["pdf"]]))
        if rows:
            out[engine] = summarize(rows)
    return out


def print_table(rows: dict[str, dict]) -> None:
    cols = [
        ("text_strict", "문장엄격"),
        ("text_alnum", "문장부호무시"),
        ("table_struct", "표구조"),
        ("cell_read", "칸글자"),
        ("header_footer_pass", "머리꼬리말"),
        ("cer_pct", "CER%"),
        ("date_acc", "날짜"),
        ("amount_acc", "금액"),
        ("number_acc", "숫자"),
        ("mark_per_1000_chars", "표시/천자"),
    ]
    print("엔진".ljust(22) + "쪽".rjust(4) + "".join(c[1].rjust(10) for c in cols))
    for engine, s in rows.items():
        cells = "".join(str("-" if s[k] is None else s[k]).rjust(10) for k, _ in cols)
        print(engine.ljust(22) + str(s["pages"]).rjust(4) + cells)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--name", required=True, help="결과 파일 이름: runs/ocr_<이름>.json")
    ap.add_argument(
        "--max-usd",
        type=float,
        required=True,
        help="누적 API 비용 상한(닿으면 새 쪽을 시작하지 않는다)",
    )
    ap.add_argument("--n", type=int, default=50, help="표본 쪽 수(종류별 층화)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--set", choices=["clean", "degraded"], default="clean")
    ap.add_argument("--input", choices=["image", "pdf"], default="image")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--data", default=DEFAULT_DATA[0] if DEFAULT_DATA else "")
    ap.add_argument("--rescore", action="store_true", help="API 호출 없이 저장된 결과만 다시 채점")
    args = ap.parse_args()

    data_dir = Path(args.data)
    scorer = load_scorer(data_dir)
    import json

    index = json.loads((data_dir / "index.json").read_text(encoding="utf-8"))
    by_name = {x["name"]: x for x in index}
    tests = scorer.load_tests({x["pdf"] for x in index})
    sample = stratified_sample(index, args.n, args.seed, args.set == "degraded")
    names = [x["name"] for x in sample]

    common.prepare_service_import()
    from app.features.ai_assistant.ingest import llm_ingest
    from app.shared.config import settings
    from app.shared.llm import doc_ai

    model = settings.ingest_ocr_model
    price_in, price_out = common.price_of(model)
    path = common.RUNS / f"ocr_{args.name}.json"
    meta = {
        "model": model,
        "price_per_mtok": {"in": price_in, "out": price_out},
        "seed": args.seed,
        "n": len(names),
        "set": args.set,
        "input": args.input,
        "ocr_system_prompt_from": "app/shared/llm/doc_ai.py OCR_SYSTEM",
    }
    run = {"meta": meta, "pages": {}}
    if path.exists():
        prev = common.load_json(path)
        if any(prev["meta"].get(k) != meta[k] for k in ("model", "seed", "n", "set", "input")):
            raise SystemExit(
                f"{path.name} 의 설정(모델·시드·표본·입력)이 달라요. 다른 --name 을 쓰세요."
            )
        run = prev
    run["meta"]["updated"] = datetime.now().isoformat(timespec="seconds")
    pages = run["pages"]
    budget = common.Budget(args.max_usd, sum(p.get("usd", 0) for p in pages.values()))

    todo = [x for x in sample if x["name"] not in pages or "error" in pages[x["name"]]]
    if args.rescore:
        todo = []
    print(
        f"표본 {len(names)}쪽 (종류별 {dict(collections.Counter(x['category'] for x in sample))}), 남은 {len(todo)}쪽, 모델 {model}"
    )

    stopped = False

    def work(item: dict) -> None:
        nonlocal stopped
        if budget.exhausted():
            stopped = True
            return
        try:
            row = read_page(args, item, data_dir, llm_ingest.ocr_image, doc_ai)
            row["usd"] = round(common.cost_of(model, row["in"], row["out"]), 5)
            budget.add(row["usd"])
        except (
            Exception
        ) as exc:  # 한 쪽 실패가 전체를 멈추지 않게. 종류만 적는다(내용·키는 적지 않는다)
            row = {"error": type(exc).__name__, "usd": 0.0}
        pages[item["name"]] = row
        common.save_json(path, run)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, todo))

    done = [n for n in names if n in pages and "error" not in pages[n]]
    refs = {n: reference_text(data_dir / "kdoc" / "pdfs" / by_name[n]["pdf"]) for n in done}
    rows_by_cat: dict[str, list[dict]] = collections.defaultdict(list)
    all_rows = []
    for n in done:
        r = page_metrics(scorer, pages[n]["text"], refs[n], tests[by_name[n]["pdf"]])
        rows_by_cat[by_name[n]["category"]].append(r)
        all_rows.append(r)
    run["metrics"] = {
        "overall": summarize(all_rows) if all_rows else {},
        "by_category": {c: summarize(v) for c, v in sorted(rows_by_cat.items())},
    }
    run["compare_same_pages"] = compare_rows(scorer, data_dir, tests, by_name, refs, done, args)
    run["cost"] = {
        "api_usd": round(sum(p.get("usd", 0) for p in pages.values()), 4),
        "input_tokens": sum(p.get("in", 0) for p in pages.values()),
        "output_tokens": sum(p.get("out", 0) for p in pages.values()),
        "max_usd": args.max_usd,
        "stopped_by_budget": stopped,
        "pages_done": len(done),
        "pages_failed": [n for n in names if n in pages and "error" in pages[n]],
        "pages_not_started": [n for n in names if n not in pages],
        "avg_sec_per_page": round(
            sum(p.get("sec", 0) for p in pages.values()) / max(1, len(done)), 1
        ),
    }
    common.save_json(path, run)

    print(
        f"\n완료 {len(done)}쪽, 실패 {len(run['cost']['pages_failed'])}, 미시작 {len(run['cost']['pages_not_started'])}"
    )
    print(
        f"API 비용 ${run['cost']['api_usd']} (상한 ${args.max_usd}), 쪽당 {run['cost']['avg_sec_per_page']}초"
    )
    table = (
        {f"이번({model.split('-', 1)[-1]})": run["metrics"]["overall"], **run["compare_same_pages"]}
        if all_rows
        else {}
    )
    if table:
        print_table(table)
        for cat, s in run["metrics"]["by_category"].items():
            print(
                f"  [{cat}] 쪽 {s['pages']} 문장부호무시 {s['text_alnum']} 표구조 {s['table_struct']} CER {s['cer_pct']}"
            )
    print(f"저장: {path}")


if __name__ == "__main__":
    main()
