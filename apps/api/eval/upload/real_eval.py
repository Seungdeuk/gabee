"""실제 문서 양식 + 가상 개인정보 이미지 평가: 서비스 업로드 경로(사진 읽기 → 개인정보 가리기)를 그대로 불러 채점한다.

    cd apps/api
    PYTHONIOENCODING=utf8 PYTHONPATH=. python eval/upload/real_eval.py --name sonnet_real --max-usd 5 [--set clean|photo|both] [--limit 2] [--no-family] [--rescore] [--reuse-ocr runs/real_x.json]

서비스 경로(app/features/ai_assistant/ingest/service.py `_from_image_llm` 과 같은 순서):
  converters.prepare_image(바이트) → llm_ingest.ocr_image(Claude 로 읽기) → service._mask(글, family)(Claude 로 가리기, 설정에 따라 규칙 가리기)
서비스 코드는 고치지 않고 doc_ai.find_pii 만 감싸 토큰을 센다. 비용은 응답의 실제 토큰 수 × 단가(common.PRICES, 모르는 모델이면 멈춤).
평가 데이터는 build_real_set.py 가 만든 gabee_share/upload_eval_real/ (data.lock.json 의 sha256 이 다르면 멈춘다).

지표(전부 코드)
- 읽기 정확도: 써 넣은 값이 읽은 글에 있나. 금액=숫자 토큰(쉼표 무시), 날짜=연·월·일 순서(구분 문자·앞 0 무시), 주문·접수번호=숫자열, 상호·이름·주소=공백 무시 포함 여부.
- 개인정보 재현율: 읽은 값(read ok)이든 못 읽은 값이든 가린 글에 남지 않은 비율(`recall_pct`), 읽은 값만 본 비율(`recall_given_read_pct`). 종류별, 가족 이름은 따로(가족 표시로 바뀌었나).
- 과하게 가림: 읽는 데 성공한 지킬 값(금액·날짜·상호·번호)이 가린 글에서 사라진 비율.
- 사업장 주소 가림(`baddr_masked_n`): 채점에서 제외한 사업장 주소(BADDR)가 가린 글에서 사라진 수. 과하게 가림 %에 들어가지 않는 별도 칸이다(4차 감사: "과하게 가림 0%"는 이 칸을 빼고 낸 값이었다).
- 참고: 양식 글자층의 한글 낱말(2자 이상)이 읽은 글에 나온 비율(`template_word_recall_pct`).
"""

import argparse
import collections
import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import common
import mask_eval

DATA_DIR = Path("C:/Users/403/Desktop/gabee_share/upload_eval_real")
_acc = threading.local()
_save_lock = threading.Lock()  # 여러 일꾼이 같은 결과 파일을 동시에 바꾸지 않게
NUM_RE = re.compile(r"\d[\d,]*\d|\d")


# ---------- 데이터 잠금 ----------
def load_locked(data_dir: Path) -> dict:
    lock_path = data_dir / "data.lock.json"
    if not lock_path.exists():
        raise SystemExit(
            "data.lock.json 이 없어요. 먼저: python eval/upload/build_real_set.py build"
        )
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    for rel, digest in lock["sha256"].items():
        path = data_dir / rel
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise SystemExit(
                f"{rel} 이 잠근 sha256 과 달라요(정답·이미지가 바뀐 것 같아요). 평가를 멈춥니다."
            )
    return json.loads((data_dir / "truth.json").read_text(encoding="utf-8"))


# ---------- 채점 ----------
def _ws(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _date_in(norm: str, text: str) -> bool:
    year, month, day = norm[:4], int(norm[4:6]), int(norm[6:8])
    return re.search(rf"(?<!\d){year}\D{{0,4}}0?{month}\D{{0,4}}0?{day}(?!\d)", text) is not None


def present(item: dict, text: str) -> str:
    """값이 글에 있나. 'full' | 'partial' | 'none' (partial 은 이름의 이름 부분, 주소의 도로명+번호만 남은 경우)."""
    kind, value = item["type"], item["value"]
    flat = _ws(text)
    if kind == "AMOUNT":
        tokens = {t.replace(",", "") for t in NUM_RE.findall(text)}
        return "full" if item["norm"] in tokens else "none"
    if kind in ("DATE", "BIRTH"):
        return "full" if _date_in(item["norm"], text) else "none"
    if kind in ("RRN", "CARD", "ACCOUNT", "PHONE", "ORDERNO"):
        return "full" if _digits(value) in _digits(text) else "none"
    if _ws(value) in flat:
        return "full"
    if kind in ("NAME", "FAMILY"):
        given = item.get("given", value[1:])
        return "partial" if len(given) >= 2 and given in flat else "none"
    if kind == "ADDR":
        return "partial" if _ws(item["core"]) in flat else "none"
    return "none"


def score_doc(doc: dict, ocr_text: str, masked: str) -> dict:
    out: dict = {"read": {}, "leak": {}, "keep": {}, "family": collections.Counter()}
    for item in doc["pii"]:
        read = present(item, ocr_text) == "full"
        left = present(item, masked)
        row = out["read"].setdefault(item["type"], {"n": 0, "ok": 0})
        row["n"] += 1
        row["ok"] += read
        row = out["leak"].setdefault(
            item["type"],
            {"n": 0, "full": 0, "partial": 0, "read": 0, "read_full": 0, "read_partial": 0},
        )
        row["n"] += 1
        row["full"] += left == "full"
        row["partial"] += left == "partial"
        if read:
            row["read"] += 1
            row["read_full"] += left == "full"
            row["read_partial"] += left == "partial"
        if item["type"] == "FAMILY":
            tag = f"[가족:{item['family_uid']}]"
            fam = out["family"]
            fam["n"] += 1
            if left != "none":
                fam["left_raw"] += 1
            elif tag in masked:
                fam["tagged"] += 1
            else:
                fam["wrong_token"] += 1
    for item in doc["keep"]:
        read = present(item, ocr_text) == "full"
        kept = present(item, masked) == "full"
        row = out["read"].setdefault(item["type"], {"n": 0, "ok": 0})
        row["n"] += 1
        row["ok"] += read
        row = out["keep"].setdefault(item["type"], {"read": 0, "removed": 0})
        if read:
            row["read"] += 1
            row["removed"] += not kept
    # 사업장 주소(BADDR): 채점에서 제외된 값이지만 가려지면 과하게 가린 것이다(별도 칸). 읽은 것 중 가린 글에서 사라진 수
    baddr = out.setdefault("baddr", {"n": 0, "read": 0, "masked": 0})
    for item in doc.get("ignored", []):
        if item["type"] != "BADDR":
            continue
        baddr["n"] += 1
        if _ws(item["value"]) in _ws(ocr_text):
            baddr["read"] += 1
            baddr["masked"] += _ws(item["value"]) not in _ws(masked)
    words = {w for w in re.findall(r"[가-힣]{2,}", doc["template_text"])}
    flat = _ws(ocr_text)
    out["template"] = {"n": len(words), "found": sum(w in flat for w in words)}
    out["family"] = dict(out["family"])
    return out


def summarize(rows: list[dict]) -> dict:
    read: dict = collections.defaultdict(collections.Counter)
    leak: dict = collections.defaultdict(collections.Counter)
    keep: dict = collections.defaultdict(collections.Counter)
    fam: collections.Counter = collections.Counter()
    tpl = collections.Counter()
    baddr = collections.Counter()
    for r in rows:
        baddr.update(r.get("baddr", {}))
        for k, v in r["read"].items():
            read[k].update(v)
        for k, v in r["leak"].items():
            leak[k].update(v)
        for k, v in r["keep"].items():
            keep[k].update(v)
        fam.update(r["family"])
        tpl.update(r["template"])
    pii_n = sum(v["n"] for v in leak.values())
    missed = sum(v["full"] + v["partial"] for v in leak.values())
    read_n = sum(v["read"] for v in leak.values())
    read_missed = sum(v["read_full"] + v["read_partial"] for v in leak.values())
    pct = lambda a, b: round(100 * a / max(1, b), 1)  # noqa: E731
    keep_read = sum(v["read"] for v in keep.values())
    keep_removed = sum(v["removed"] for v in keep.values())
    return {
        "docs": len(rows),
        "read_accuracy_pct": {
            k: {"n": v["n"], "ok": v["ok"], "pct": pct(v["ok"], v["n"])}
            for k, v in sorted(read.items())
        },
        "pii_n": pii_n,
        "pii_read_ok": read_n,
        "recall_pct": pct(pii_n - missed, pii_n),
        "recall_given_read_pct": pct(read_n - read_missed, read_n),
        "missed_full": sum(v["full"] for v in leak.values()),
        "missed_partial": sum(v["partial"] for v in leak.values()),
        "recall_by_type": {
            k: {
                "n": v["n"],
                "read_ok": v["read"],
                "missed": v["full"] + v["partial"],
                "recall_pct": pct(v["n"] - v["full"] - v["partial"], v["n"]),
                "recall_given_read_pct": pct(
                    v["read"] - v["read_full"] - v["read_partial"], v["read"]
                ),
            }
            for k, v in sorted(leak.items())
        },
        "family": {
            "n": fam["n"],
            "tagged_ok": fam["tagged"],
            "left_raw": fam["left_raw"],
            "wrong_token": fam["wrong_token"],
            "tagged_pct": pct(fam["tagged"], fam["n"]),
        },
        "keep_read_n": keep_read,
        "overmask_pct": pct(keep_removed, keep_read),
        "overmask_by_type": {
            k: {"read": v["read"], "removed": v["removed"]} for k, v in sorted(keep.items())
        },
        "template_word_recall_pct": pct(tpl["found"], tpl["n"]),
        # 사업장 주소(BADDR, 채점 제외 값)를 가린 수: overmask_pct 에 들어가지 않는 과하게 가림
        "baddr_n": baddr["n"],
        "baddr_read_n": baddr["read"],
        "baddr_masked_n": baddr["masked"],
    }


# ---------- 실행 ----------
def pick_jobs(docs: list[dict], sets: list[str], limit: int) -> list[tuple[dict, str]]:
    jobs = [(d, s) for d in docs for s in sets]
    if limit and limit < len(jobs):
        step = len(jobs) / limit
        jobs = [jobs[int(i * step)] for i in range(limit)]
    return jobs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--name", required=True, help="결과 파일 이름: runs/real_<이름>.json")
    ap.add_argument(
        "--max-usd",
        type=float,
        required=True,
        help="누적 API 비용 상한(닿으면 새 이미지를 시작하지 않는다)",
    )
    ap.add_argument("--set", choices=["clean", "photo", "both"], default="both")
    ap.add_argument(
        "--limit", type=int, default=0, help="이 수만큼만(고르게 뽑음, 시범용). 0 이면 전부"
    )
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--no-family", action="store_true", help="family 인자를 넘기지 않는다")
    ap.add_argument("--rescore", action="store_true", help="호출 없이 저장된 결과만 다시 채점")
    ap.add_argument(
        "--reuse-ocr",
        type=Path,
        help="이 결과 파일(runs/real_*.json)에 저장된 읽은 글을 쓰고 읽기 호출은 건너뛴다(가리기만 다시 잰다). 다른 --name 을 쓰세요",
    )
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = ap.parse_args()

    truth = load_locked(args.data_dir)
    sets = ["clean", "photo"] if args.set == "both" else [args.set]
    jobs = pick_jobs(truth["docs"], sets, args.limit)
    sha = hashlib.sha256((args.data_dir / "truth.json").read_bytes()).hexdigest()

    common.prepare_service_import()
    from app.features.ai_assistant.family_names import FamilyTagger, Member
    from app.features.ai_assistant.ingest import converters, llm_ingest, service
    from app.shared.config import settings
    from app.shared.llm import doc_ai

    ocr_model = settings.ingest_ocr_model or settings.llm_model
    mask_model = settings.ingest_mask_model or settings.llm_model
    ocr_price, mask_price = common.price_of(ocr_model), common.price_of(mask_model)
    real_find = doc_ai.find_pii

    def counted_find(text, candidates=None):
        found = real_find(text, candidates)
        acc = getattr(_acc, "v", None)
        if acc is not None:
            acc[0] += found.input_tokens
            acc[1] += found.output_tokens
        return found

    doc_ai.find_pii = counted_find  # 서비스 코드는 그대로, 가리기 토큰만 센다

    reused: dict = {}
    if args.reuse_ocr:
        reused = common.load_json(args.reuse_ocr)["items"]
    meta = {
        "reuse_ocr": args.reuse_ocr.name if args.reuse_ocr else None,
        "ocr_model": ocr_model,
        "mask_model": mask_model,
        "price_per_mtok": {"ocr": ocr_price, "mask": mask_price},
        "ingest_llm_mask": settings.ingest_llm_mask,
        "truth_sha256": sha,
        "family_arg": not args.no_family,
        "sets": sets,
        "jobs": len(jobs),
    }
    path = common.RUNS / f"real_{args.name}.json"
    run: dict = {"meta": meta, "items": {}}
    if path.exists():
        prev = common.load_json(path)
        keys = (
            "ocr_model",
            "mask_model",
            "truth_sha256",
            "family_arg",
            "sets",
            "jobs",
            "ingest_llm_mask",
            "reuse_ocr",
        )
        if any(prev["meta"].get(k) != meta[k] for k in keys):
            raise SystemExit(
                f"{path.name} 의 설정(모델·데이터·family·세트·개수)이 달라요. 다른 --name 을 쓰세요."
            )
        run = prev
    run["meta"]["updated"] = datetime.now().isoformat(timespec="seconds")
    done = run["items"]
    budget = common.Budget(args.max_usd, sum(d.get("usd", 0) for d in done.values()))
    members = [Member(uid, name) for uid, name in mask_eval.FAMILY]
    key_of = lambda d, s: f"{d['id']}|{s}"  # noqa: E731
    todo = [(d, s) for d, s in jobs if key_of(d, s) not in done or "error" in done[key_of(d, s)]]
    if args.rescore:
        todo = []
    print(
        f"이미지 {len(jobs)}장, 남은 {len(todo)}장, 읽기 {ocr_model}, 가리기 {mask_model}, family {'없음' if args.no_family else '4명'}"
    )
    stopped = False

    def work(job: tuple[dict, str]) -> None:
        nonlocal stopped
        doc, kind = job
        if budget.exhausted():
            stopped = True
            return
        _acc.v = [0, 0]
        started = time.time()
        row: dict = {}
        try:
            if args.reuse_ocr:  # 저장된 읽은 글을 그대로 쓴다(읽기 호출·비용 없음)
                old = reused.get(key_of(doc, kind), {})
                if "ocr_text" not in old:
                    raise KeyError("ocr_text")
                ocr_text = old["ocr_text"]
                row.update(ocr_text=ocr_text, truncated=old.get("truncated"), usd_ocr=0.0)
            else:
                image = converters.prepare_image((args.data_dir / doc[kind]).read_bytes())
                out = llm_ingest.ocr_image(image)
                ocr_text = out.text
                row.update(
                    ocr_text=out.text,
                    ocr_in=out.input_tokens,
                    ocr_out=out.output_tokens,
                    truncated=out.truncated,
                )
                row["usd_ocr"] = common.cost_of(ocr_model, out.input_tokens, out.output_tokens)
                budget.add(row["usd_ocr"])  # 읽기 비용은 가리기가 실패해도 센다
            family = None if args.no_family else FamilyTagger(members)
            masked, privacy = service._mask(ocr_text, family)
            row.update(masked=masked, counts=dict(privacy.masked), sensitive=privacy.sensitive)
        except Exception as exc:  # 종류만 적는다(문서 내용은 로그에 남기지 않는다)
            row["error"] = type(exc).__name__
        row["mask_in"], row["mask_out"] = _acc.v
        row["usd_mask"] = common.cost_of(mask_model, *_acc.v)
        budget.add(row["usd_mask"])
        row["usd"] = round(row.get("usd_ocr", 0) + row["usd_mask"], 6)
        row["sec"] = round(time.time() - started, 1)
        with _save_lock:
            done[key_of(doc, kind)] = row
            common.save_json(path, run)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, todo))

    ok = [(d, s) for d, s in jobs if key_of(d, s) in done and "error" not in done[key_of(d, s)]]
    scored = {
        key_of(d, s): score_doc(d, done[key_of(d, s)]["ocr_text"], done[key_of(d, s)]["masked"])
        for d, s in ok
    }
    by_set = {s: [scored[key_of(d, s2)] for d, s2 in ok if s2 == s] for s in sets}
    run["metrics"] = {"all": summarize(list(scored.values())) if scored else {}}
    for s, rows in by_set.items():
        run["metrics"][s] = summarize(rows) if rows else {}
    run["cost"] = {
        "api_usd": round(sum(d.get("usd", 0) for d in done.values()), 5),
        "ocr_input_tokens": sum(d.get("ocr_in", 0) for d in done.values()),
        "ocr_output_tokens": sum(d.get("ocr_out", 0) for d in done.values()),
        "mask_input_tokens": sum(d.get("mask_in", 0) for d in done.values()),
        "mask_output_tokens": sum(d.get("mask_out", 0) for d in done.values()),
        "max_usd": args.max_usd,
        "stopped_by_budget": stopped,
        "images_done": len(ok),
        "images_failed": [k for k, v in done.items() if "error" in v],
        "images_not_started": [key_of(d, s) for d, s in jobs if key_of(d, s) not in done],
    }
    common.save_json(path, run)

    cost = run["cost"]
    print(
        f"\n완료 {len(ok)}장, 실패 {len(cost['images_failed'])}, 미시작 {len(cost['images_not_started'])}, API 비용 ${cost['api_usd']} (상한 ${args.max_usd})"
    )
    for name, m in run["metrics"].items():
        if not m:
            continue
        print(f"\n[{name}] 문서 {m['docs']}")
        reads = ", ".join(
            "{} {}%({}/{})".format(k, v["pct"], v["ok"], v["n"])
            for k, v in m["read_accuracy_pct"].items()
        )
        print(f"  읽기 정확도 {reads}")
        print(
            f"  개인정보 재현율 {m['recall_pct']}% (읽은 값만 {m['recall_given_read_pct']}%), 놓침 전부 {m['missed_full']} / 일부 {m['missed_partial']} / 심은 값 {m['pii_n']}"
        )
        for k, v in m["recall_by_type"].items():
            print(
                f"    {k:8s} n={v['n']:3d} 읽음 {v['read_ok']:3d} 재현율 {v['recall_pct']}% (읽은 값만 {v['recall_given_read_pct']}%)"
            )
        print(f"  가족 이름 {m['family']}")
        print(
            f"  과하게 가림 {m['overmask_pct']}% / 읽은 지킬 값 {m['keep_read_n']}  {m['overmask_by_type']}"
        )
        print(
            f"  사업장 주소 가림 {m['baddr_masked_n']} / 읽은 사업장 주소 {m['baddr_read_n']} (정답 {m['baddr_n']})"
        )
        print(f"  양식 글자 재현 {m['template_word_recall_pct']}%")
    print(f"저장: {path}")


if __name__ == "__main__":
    main()
