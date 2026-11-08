"""가짜 시나리오의 요약 조각에서 LLM 으로 평가 질문을 만든다(개발용 / 최종 점수용 분리).

    cd apps/api && python -m evals.location.gen_questions --dry-run
    cd apps/api && python -m evals.location.gen_questions --max-calls 100 [--per-chunk 2] [--batch 10]
                    [--kinds span,move,day,place] [--final-ratio 0.3] [--limit-chunks N] [--model 모델]

흐름: 시나리오 → 요약 조각 → 조각을 dev/final 로 나눔 → 조각마다 질문 생성 → (질문, 정답 조각 키) 쌍을 파일로 저장.
- 분리는 질문이 아니라 조각 기준이다. 같은 조각에서 만든 질문은 한쪽에만 들어가 최종 점수가 부풀지 않는다.
  하루 요약 조각은 그날 구간 조각을 요약한 것이라 같은 사람·같은 날을 한 묶음으로 나눈다(scenarios.group_key).
  장소 요약 조각은 여러 날의 방문을 모은 것이라 다른 쪽 조각과 사실이 겹친다(overlaps_other_split 로 표시).
- final 파일은 한 번 만들면 얼려 둔다. 다시 만들려면 --regenerate-final(점수가 달라지므로 이전 점수와 비교하지 않는다).
- LLM 호출 수 = 조각 수 × 조각당 질문 수 ÷ 한 번에 만드는 질문 수(evals/budget.py). 실제 호출은 --max-calls 가 있어야 하고 예상이 넘으면 멈춘다.
- LLM 에는 가짜 시나리오의 요약 문장만 보낸다(실제 위치 데이터 아님)."""

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from evals import budget
from evals.location import scenarios as sc

OUT_DIR = Path(__file__).parent / "data" / "generated"
STYLES = (
    "짧은 구어체(반말 가깝게)",
    "정중한 존댓말",
    "조건을 풀어 쓴 긴 문장",
    "핵심만 던지는 한 줄",
)
SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chunk": {"type": "integer"},
                    "question": {"type": "string"},
                },
                "required": ["chunk", "question"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}
SYSTEM = (
    "너는 가족 위치 기록 검색을 평가할 질문을 만든다. 각 번호의 '기록 문장'을 보고, 그 문장 하나만으로 답할 수 있는 질문을 만든다. "
    "규칙: (1) 질문은 기록 문장의 낱말을 그대로 베끼지 말고 말투와 문장 구조를 바꿔 쓴다. 사람 이름과 장소 이름은 문장에 있는 그대로 쓴다. "
    "(2) 어제·오늘·지난주 같은 상대 날짜는 쓰지 말고 문장에 있는 '월-일'과 요일로 말한다. "
    "(3) 질문에 답을 적지 않는다. (4) 같은 번호의 질문들은 서로 말투나 묻는 방식이 달라야 한다. "
    "(5) 기록 문장에 없는 사실은 묻지 않는다."
)


def build_prompt(batch: list[sc.ChunkDraft], per_chunk: int) -> str:
    lines = [f"[{i}] {c.text}" for i, c in enumerate(batch)]
    styles = ", ".join(STYLES[:per_chunk])
    return (
        f"아래 기록 문장마다 질문을 {per_chunk}개씩 만들어라. 말투 후보: {styles}.\n"
        "출력은 JSON 의 questions 배열이고, 각 항목은 chunk(번호)와 question 이다.\n\n"
        + "\n".join(lines)
    )


def parse_questions(data: dict, batch_size: int, per_chunk: int) -> list[tuple[int, str]]:
    """모델 답에서 (번호, 질문)만 고른다. 범위 밖 번호·너무 짧은 질문·같은 번호의 중복·번호당 초과분은 버린다."""
    seen: dict[int, set[str]] = {}
    out: list[tuple[int, str]] = []
    for item in data.get("questions") or []:
        idx, q = item.get("chunk"), (item.get("question") or "").strip()
        if not isinstance(idx, int) or not 0 <= idx < batch_size or len(q) < 5:
            continue
        got = seen.setdefault(idx, set())
        if q in got or len(got) >= per_chunk:
            continue
        got.add(q)
        out.append((idx, q))
    return out


def eligible(kinds: set[str]) -> list[tuple[str, sc.ChunkDraft]]:
    """[(시나리오 이름, 조각)] 질문을 만들 후보."""
    return [(name, c) for name, s in sc.load_all() for c in sc.chunks_of(s) if c.kind in kinds]


def plan(
    kinds: set[str], final_ratio: float, seed: str, limit: int | None
) -> dict[str, list[tuple[str, sc.ChunkDraft]]]:
    out: dict[str, list[tuple[str, sc.ChunkDraft]]] = {"dev": [], "final": []}
    for name, c in eligible(kinds):
        out[sc.split_of(c, final_ratio, seed)].append((name, c))
    if limit is not None:
        # 앞에서 자르면 첫 시나리오·첫 날짜에 쏠린다. 조각 키의 해시 순서로 골라 시나리오·종류·날짜가 고르게 섞이게 한다
        def order(item: tuple[str, sc.ChunkDraft]) -> str:
            return hashlib.sha1(f"{seed}|{sc.chunk_key(item[1])}".encode()).hexdigest()

        out = {k: sorted(v, key=order)[:limit] for k, v in out.items()}
    return out


def generate(
    items: list[tuple[str, sc.ChunkDraft]],
    split: str,
    per_chunk: int,
    batch: int,
    complete: Callable[..., object],
    model: str | None = None,
) -> tuple[list[dict], int]:
    """조각들에서 질문을 만든다. (질문 목록, 호출 횟수). complete 는 client.complete_json 과 같은 모양(시험에서는 가짜)."""
    chunks_per_call = max(1, batch // per_chunk)
    questions: list[dict] = []
    calls = 0
    for start in range(0, len(items), chunks_per_call):
        group = items[start : start + chunks_per_call]
        result = complete(
            build_prompt([c for _, c in group], per_chunk),
            SCHEMA,
            system=SYSTEM,
            max_tokens=2048,
            model=model,
        )
        calls += 1
        for idx, q in parse_questions(result.data, len(group), per_chunk):
            scenario, c = group[idx]
            key = sc.chunk_key(c)
            questions.append(
                {
                    "id": f"g-{split}-{hashlib.sha1((key + q).encode()).hexdigest()[:8]}",
                    "split": split,
                    "question": q,
                    "scenario": scenario,
                    "gold": {
                        "key": key,
                        "kind": c.kind,
                        "person": c.person_id,
                        "starts_at": c.starts_at.isoformat(timespec="minutes"),
                        "ends_at": c.ends_at.isoformat(timespec="minutes"),
                        "place": c.place,
                        "text": c.text,
                    },
                    "overlaps_other_split": c.kind == "place",
                }
            )
    return sorted(questions, key=lambda x: x["id"]), calls


def write_split(path: Path, split: str, questions: list[dict], meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"split": split, "meta": meta, "questions": questions}
    path.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="가짜 시나리오에서 평가 질문을 만든다(개발용/최종 점수용 분리)"
    )
    ap.add_argument("--per-chunk", type=int, default=2, help=f"조각당 질문 수(최대 {len(STYLES)})")
    ap.add_argument("--batch", type=int, default=10, help="요청 한 번에 만드는 질문 수")
    ap.add_argument("--kinds", default="span,move,day,place", help="질문을 만들 조각 종류(쉼표)")
    ap.add_argument("--final-ratio", type=float, default=0.3, help="최종 점수용으로 보낼 묶음 비율")
    ap.add_argument("--seed", default="gabee-loc-1", help="분리 시드(바꾸면 분리가 달라진다)")
    ap.add_argument("--limit-chunks", type=int, help="분리마다 앞에서 N 개 조각만(시험용)")
    ap.add_argument("--max-calls", type=int, help="호출 상한. 실제 실행에는 필수")
    ap.add_argument("--model", help="질문 생성 모델(기본은 설정값)")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--dry-run", action="store_true", help="조각 수와 예상 호출 수만 보여 준다")
    ap.add_argument(
        "--regenerate-final", action="store_true", help="얼려 둔 final 파일을 다시 만든다"
    )
    args = ap.parse_args(argv)
    if not 1 <= args.per_chunk <= len(STYLES):
        ap.error(f"--per-chunk 는 1~{len(STYLES)}")

    kinds = {k.strip() for k in args.kinds.split(",") if k.strip()}
    planned = plan(kinds, args.final_ratio, args.seed, args.limit_chunks)
    final_path = args.out_dir / "questions_final.json"
    skip_final = final_path.exists() and not args.regenerate_final
    todo = {"dev": planned["dev"], **({} if skip_final else {"final": planned["final"]})}

    print("== 조각 수 (시나리오 합계) ==")
    for split, items in planned.items():
        by_kind = Counter(c.kind for _, c in items)
        print(f"  {split}: {len(items)}개 {dict(by_kind)}")
    if skip_final:
        print(f"  final 은 이미 있어 건너뜁니다(얼려 둠): {final_path}")
    needed = sum(
        budget.question_gen_calls(len(items), args.per_chunk, args.batch) for items in todo.values()
    )
    if args.dry_run:
        budget.guard(
            "질문 생성 = 조각 수 × 조각당 질문 수 ÷ 한 번에 만드는 질문 수", needed, args.max_calls
        )
        return 0
    if args.max_calls is None:
        print(
            "실제 실행에는 --max-calls 가 필요해요(--dry-run 으로 예상 호출 수를 먼저 보세요).",
            file=sys.stderr,
        )
        return 2
    budget.guard("질문 생성", needed, args.max_calls)

    from app.shared.llm import client

    if not client.available():
        print("ANTHROPIC_API_KEY 가 설정되지 않았어요.", file=sys.stderr)
        return 2
    used = 0
    for split, items in todo.items():
        questions, calls = generate(
            items, split, args.per_chunk, args.batch, client.complete_json, args.model
        )
        used += calls
        meta = {
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "model": args.model or "settings.llm_model",
            "per_chunk": args.per_chunk,
            "batch": args.batch,
            "final_ratio": args.final_ratio,
            "seed": args.seed,
            "kinds": sorted(kinds),
            "chunks": len(items),
            "calls": calls,
            "note": "가짜 시나리오에서 만든 질문. 정답은 gold.key 의 조각(바뀌지 않는 키).",
        }
        write_split(args.out_dir / f"questions_{split}.json", split, questions, meta)
        print(f"저장: questions_{split}.json — 질문 {len(questions)}개 (호출 {calls}회)")
    print(f"호출 합계 {used}회")
    return 0


if __name__ == "__main__":
    sys.exit(main())
