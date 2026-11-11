"""가족 문서 RAG 평가셋 만들기: 사람이 쓴 가짜 문서(hand_docs)에서 질문을 만들고, 방해 문서와 함께 색인을 만든다.

가짜 문서만 쓴다(실제 가족 데이터 금지). 공용·개인 DB 는 쓰지 않고, 색인은 SQLite 파일 하나다.
업로드 LLM(OCR·가리기)은 부르지 않는다: service.ingest 에 문서 글을 그대로 넣는다. LLM 은 질문 만들기와 no_answer 검증에만 쓴다.

    PYTHONPATH=. python eval/rag/prepare_family.py                # 기본 경로에 만들고 data.lock.json 을 남긴다
    PYTHONPATH=. python eval/rag/prepare_family.py --limit 3 --out <임시 폴더> --index <임시 .db>   # 시험용

pool_d.json(실제 파이프라인 기록)은 읽지 않는다. 시드를 고정해 다시 돌려도 같은 문서를 고른다.
data.lock.json 이 이미 있으면 덮어쓰지 않는다(평가셋은 만든 뒤 고치지 않는다).
"""

import argparse
import hashlib
import json
import os
import random
import re
import sys
import uuid
from collections import Counter
from pathlib import Path

SEED = 20261109
SOURCE = Path(r"C:\Users\403\Desktop\gabee_share\embedding_eval")
OUT = Path(r"C:\Users\403\Desktop\gabee_share\rag_eval_data_family")
INDEX = Path(r"C:\Users\403\Desktop\gabee_share\rag_eval_index\family.db")
DISTRACTORS = 150
DEV_SHARE = 0.7
COST_CAP_USD = 2.5  # 상한 $3 보다 낮은 안전선: 넘으면 멈춘다
UNREAD_MARK = "[읽지 못한 부분]"

FAMILY_SYSTEM_EXTRA = (
    "\n- 문서에 금액·날짜·수량 같은 숫자 값이 있으면 easy 와 paraphrase 중 적어도 하나는 그 값을 물으세요"
    "(예: '이번 달 전기요금 얼마 나왔어?', '자동차보험 만기가 언제야?'). 숫자 값이 없는 문서는 문서에 있는 다른 사실을 물으세요.\n"
    f"- {UNREAD_MARK} 로 표시됐거나 글자가 깨져 읽기 어려운 값은 묻지 마세요."
)

JUDGE_SYSTEM = (
    "아래 질문과, 문서에서 가져온 글 조각들이 있습니다. 조각들에 적힌 내용만으로 질문에 답할 수 있는지 판단하세요. "
    '질문의 대상(어떤 문서·사람·달)과 묻는 사실이 모두 조각 안에 있어야 답할 수 있는 것입니다. 설명 없이 JSON 한 줄만 출력하세요: {"answerable": true} 또는 {"answerable": false}'
)

# 값이 깨진 것으로 보는 기준(질문을 만들기 전에 정한 규칙이고, 결과를 보고 바꾸지 않는다)
ALLOWED_PUNCT = set(" \t\n·※~…-_/:;,.!?'\"()[]{}<>%+=*&#@|•→“”‘’")
UNITS = {"kwh", "gb", "mb", "kg", "km"}
UNCERTAIN_WORDS = ("불확실", "일부만 확인", "읽기 어려", "흐림", "판독")


def noisy(text: str) -> bool:
    """글자가 깨졌거나 값이 이상해 보이면 True. 한글 완성형·ASCII·흔한 부호 밖의 글자, 숫자와 영문이 섞인 낱말,
    천 단위 쉼표가 어긋난 숫자, 읽지 못한 부분·불확실 표시를 깨짐으로 본다."""
    if UNREAD_MARK in text or any(w in text for w in UNCERTAIN_WORDS):
        return True
    for ch in text:
        if "\uac00" <= ch <= "\ud7a3" or ch.isascii() or ch in ALLOWED_PUNCT:
            continue
        return True
    for token in text.split():
        core = re.sub(r"[가-힣]+", "", token)
        letters = re.sub(r"[^A-Za-z]", "", core)
        if re.search(r"\d", core) and letters and letters.lower() not in UNITS:
            return True
        for num in re.findall(r"\d[\d,]*", core):
            if "," in num and not re.fullmatch(r"\d{1,3}(,\d{3})+", num):
                return True
    return False


def value_type(quote: str, answer: str) -> str:
    """정답이 금액·날짜·그 밖의 숫자·글 중 무엇인지(통계용)."""
    text = f"{answer} {quote}" if not answer else answer
    if re.search(r"\d[\d,]*\s*(원|만원|천원)|\d,\d{3}", text):
        return "amount"
    if re.search(r"\d{4}\s*년|\d{1,2}\s*월|\d{1,2}\s*일|\d{4}-\d{2}", text):
        return "date"
    if re.search(r"\d", text):
        return "number"
    return "text"


def parse_doc(text: str) -> tuple[str, str]:
    """(제목, 분류). '# 제목' 줄과 '분류: ' 줄에서 읽는다."""
    title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), "")
    label = next((ln[3:].strip() for ln in text.splitlines() if ln.startswith("분류:")), "문서")
    return title[:190] or "제목 없음", label or "문서"


def pick_docs(source: Path, limit: int | None) -> tuple[list[dict], list[dict]]:
    """(정답 문서, 방해 문서). 시드 고정. pool_d.json 은 열지 않는다."""
    big = json.loads((source / "ft_data_big.json").read_text(encoding="utf-8"))
    hand = [{"id": d["id"], "text": d["text"]} for d in big["hand_docs"]]
    pool = sorted(
        ({"id": d["id"], "text": d["text"]} for d in big["docs"] if d.get("lang") == "ko"),
        key=lambda d: d["id"],
    )
    distractors = random.Random(SEED).sample(pool, DISTRACTORS)
    if limit:
        hand = hand[:limit]
        distractors = distractors[: limit * 2]
    return hand, distractors


def split_docs(ids: list[str]) -> dict[str, str]:
    """문서 단위 70/30. 시드가 고정이라 다시 돌려도 같다."""
    ids = sorted(ids)
    random.Random(SEED).shuffle(ids)
    cut = round(len(ids) * DEV_SHARE)
    return {i: ("dev" if k < cut else "test") for k, i in enumerate(ids)}


def build_index(index: Path, docs: list[dict]) -> tuple[str, str, dict[str, str]]:
    """색인 파일을 새로 만든다. (group_id, 임베더 이름, {문서 id: 색인의 item id}). ingest 를 그대로 쓴다."""
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app.features.ai_assistant.knowledge import service
    from app.features.ai_assistant.knowledge.embedding import get_embedder
    from app.features.family_group.models import User
    from app.main import app
    from app.shared.db import SessionLocal, init_db
    from tests.helpers import signup

    init_db()
    client = TestClient(app)
    headers = signup(client, "평가", "parent")
    group = client.post("/family-group/groups", json={"name": "평가"}, headers=headers).json()
    ids: dict[str, str] = {}
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.name == "평가"))
        for i, doc in enumerate(docs):
            title, label = parse_doc(doc["text"])
            item_id = uuid.uuid5(uuid.NAMESPACE_URL, f"gabee-family-eval/{doc['id']}").hex
            service.ingest(
                db,
                group["id"],
                uid,
                kind_label=label,
                title=title,
                body_md=doc["text"],
                item_id=item_id,
            )
            ids[doc["id"]] = item_id
            if (i + 1) % 25 == 0:
                print(f"색인 {i + 1}/{len(docs)}", flush=True)
    return group["id"], get_embedder().name, ids


class Cost:
    """실제 사용 토큰으로 계산한 비용."""

    def __init__(self, price_in: float, price_out: float) -> None:
        self.tin = self.tout = self.calls = 0
        self.price = (price_in, price_out)

    def add(self, tokens_in: int, tokens_out: int) -> None:
        self.tin += tokens_in
        self.tout += tokens_out
        self.calls += 1
        if self.usd > COST_CAP_USD:
            raise SystemExit(f"비용 안전선 ${COST_CAP_USD} 초과, 멈춤")

    @property
    def usd(self) -> float:
        return self.tin * self.price[0] + self.tout * self.price[1]


def answerable_by_top10(question: str, group_id: str, embedder_name: str, cost: Cost) -> bool:
    """색인 전체에서 상위 10개 조각을 가져와 Claude 에게 답할 수 있는지 묻는다."""
    from app.features.ai_assistant.knowledge import repository as repo
    from app.features.ai_assistant.knowledge.embedding import get_embedder
    from app.shared.db import SessionLocal
    from app.shared.llm import transport
    from eval.rag.generate_questions import MODEL, _json_of

    embedder = get_embedder()
    assert embedder.name == embedder_name
    with SessionLocal() as db:
        rows = repo.search_chunks(
            db, group_id, embedder.name, embedder.embed_query(question), None, None, None, True
        )[:10]
    pieces = "\n\n".join(
        f"[조각 {i}]\n{chunk.text}" for i, (chunk, _item, _s) in enumerate(rows, 1)
    )
    reply = transport.post_messages(
        {
            "model": MODEL,
            "max_tokens": 300,
            "system": JUDGE_SYSTEM,
            "messages": [
                {
                    "role": "user",
                    "content": f"<question>{question}</question>\n<chunks>\n{pieces}\n</chunks>",
                }
            ],
        },
        timeout=120.0,
        retry=True,
    )
    cost.add(*transport.usage_of(reply))
    text = "".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text")
    return bool(_json_of(text).get("answerable"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--index", type=Path, default=INDEX)
    parser.add_argument("--limit", type=int, default=0, help="시험용: 정답 문서 수를 줄인다")
    args = parser.parse_args()
    if (args.out / "data.lock.json").exists():
        raise SystemExit("data.lock.json 이 이미 있어요. 평가셋은 만든 뒤 고치지 않습니다.")
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.unlink(missing_ok=True)
    os.environ["DATABASE_URL"] = (
        f"sqlite:///{args.index.as_posix()}"  # 앱 코드를 불러오기 전에 정한다
    )
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    from app.shared.llm import transport
    from eval.rag import generate_questions as gen

    hand, distractors = pick_docs(args.source, args.limit or None)
    split_of = split_docs([d["id"] for d in hand])
    group_id, embedder_name, item_ids = build_index(args.index, hand + distractors)
    titles = {d["id"]: parse_doc(d["text"])[0] for d in hand}
    cost = Cost(gen.PRICE_IN, gen.PRICE_OUT)
    system = gen.SYSTEM + FAMILY_SYSTEM_EXTRA

    excluded = Counter()
    kept: list[dict] = []
    failed_docs = 0
    for doc in hand:
        try:
            made, tin, tout = gen.ask({**doc, "pool": "hand"}, system)
        except (ValueError, transport.LLMUnavailable) as exc:
            failed_docs += 1
            print(f"실패 {doc['id']}: {type(exc).__name__}", flush=True)
            continue
        cost.add(tin, tout)
        for q in made:
            kind = q["type"]
            if not q["valid"]:
                excluded[f"valid=false:{kind}"] += 1
                continue
            if kind == "no_answer":
                src = q["source_doc"]
                if noisy(q["question"]):
                    excluded["noisy:no_answer"] += 1
                    continue
                try:
                    leaked = answerable_by_top10(q["question"], group_id, embedder_name, cost)
                except ValueError:  # 판정 응답을 읽지 못한 질문은 안전하게 뺀다
                    excluded["no_answer_judge_unparsable"] += 1
                    continue
                if leaked:
                    excluded["no_answer_answerable_by_top10"] += 1
                    continue
                kept.append({**q, "doc": src})
                continue
            digits = re.sub(r"\D", "", q["answer"])
            if noisy(q["question"]) or noisy(q["quote"]) or noisy(q["answer"]):
                excluded[f"noisy_value:{kind}"] += 1
                continue
            if digits and digits not in re.sub(r"\D", "", q["quote"]):
                excluded[f"answer_not_in_quote:{kind}"] += 1
                continue
            kept.append({**q, "doc": q["gold"][0]})
        print(f"{doc['id']} 완료 ${cost.usd:.3f}", flush=True)

    kept.sort(key=lambda q: (q["doc"], q["type"]))
    questions = []
    for i, q in enumerate(kept, 1):
        no_answer = q["type"] == "no_answer"
        questions.append(
            {
                "qid": f"f{i:03d}",
                "domain": "family",
                "question": q["question"],
                "answer": q["answer"],
                "file": titles[q["doc"]],
                "page": "",
                "context_type": "family",
                "kind": "no_answer" if no_answer else "answerable",
                "type": q["type"],
                "item_id": None if no_answer else item_ids[q["doc"]],
                "split": split_of[q["doc"]],
                "quote": q["quote"],
                "value_type": None if no_answer else value_type(q["quote"], q["answer"]),
                "source_doc": q["doc"],
            }
        )
    dup_titles = sorted(t for t, n in Counter(titles.values()).items() if n > 1)
    summary = {
        "model": gen.MODEL,
        "seed": SEED,
        "hand_docs": len(hand),
        "distractor_docs": len(distractors),
        "indexed_items": len(item_ids),
        "embedder": embedder_name,
        "failed_docs": failed_docs,
        "questions": len(questions),
        "by_kind": dict(Counter(q["kind"] for q in questions)),
        "by_type": dict(Counter(q["type"] for q in questions)),
        "by_split": dict(Counter(q["split"] for q in questions)),
        "by_kind_split": dict(Counter(f"{q['kind']}/{q['split']}" for q in questions)),
        "by_value_type": dict(Counter(q["value_type"] for q in questions if q["value_type"])),
        "docs_by_split": dict(Counter(split_of.values())),
        "excluded": dict(excluded),
        "duplicate_titles": dup_titles,
        "llm_calls": cost.calls,
        "tokens_in": cost.tin,
        "tokens_out": cost.tout,
        "cost_usd": round(cost.usd, 4),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    files = {
        "questions.json": {"questions": questions, "summary": summary},
        "docs.json": {
            "hand": [
                {"id": d["id"], "title": titles[d["id"]], "split": split_of[d["id"]]} for d in hand
            ],
            "distractors": [d["id"] for d in distractors],
        },
    }
    lock = {}
    for name, data in files.items():
        (args.out / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        lock[name] = hashlib.sha256((args.out / name).read_bytes()).hexdigest()
    (args.out / "data.lock.json").write_text(
        json.dumps({"seed": SEED, "sha256": lock}, indent=1), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
