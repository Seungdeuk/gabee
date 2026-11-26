"""검색 품질 실행기(결정론적, 실모델 0회). 합성 월드에서 실제 `search_service.search` 결과를 지표로 바꾼다.

운영 검색 로직·Tool 응답 형태는 건드리지 않는다. 에이전트의 `search_messages` 와 같은 호출(가족 전체방만, `limit` 기본 10·최대 20)을 그대로 따라 하고
(`tests/search_quality/test_tool_parity.py` 가 도구 결과와 같은지 본다), 결과의 id 는 합성 월드의 키 대응표로 gold 와 맞춘다.

- 분당 검색 30회 제한(`search_service.search_limiter`)은 호출마다 비워 측정이 제한에 왜곡되지 않게 한다(합성 환경 안에서만, 운영 값은 그대로).
- 상위 20건(`Hit@20`)과 200건 내부 진단은 원인 분류에만 쓰고 품질 지표에는 넣지 않는다. 200건은 도구가 낼 수 없는 값이라 저장소 함수를 직접 부른다.
- 평가 전에 `validate.require` 로 gold·범위·핵심 사실을 확인하고, 어긋나면 `DatasetInvalid` 로 중단한다(점수를 내지 않는다).
"""

import subprocess
from pathlib import Path

from sqlalchemy.orm import Session

from app.features.family_chat import agent, search_service
from app.features.family_chat import search_repository as srepo
from app.features.family_group.models import User
from app.shared.db import SessionLocal

from . import attribution, case_specs, data, metrics, validate
from .world import World

METRICS_VERSION = "v1"
DEFAULT_LIMIT = 10  # 도구의 기본 limit (agent.search_messages 의 `_int(args, "limit", 10, ...)`)
MAX_LIMIT = agent.MAX_RESULTS  # 도구의 최대 limit
DEEP_LIMIT = 200  # 내부 진단 전용


def git_sha() -> str:
    try:
        root = Path(__file__).resolve().parents[3]
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10
        )
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


class Searcher:
    """에이전트 `search_messages` 와 같은 경로로 검색한다(가족 전체방만)."""

    def __init__(self, db: Session, user: User, world: World):
        self.db, self.user, self.world = db, user, world
        self.family = next(
            r for r in srepo.accessible_rooms(db, world.group_id, user.id) if r.kind == "family"
        )

    def agent_ids(self, words: list[str], limit: int = DEFAULT_LIMIT) -> list[int]:
        """도구와 같은 호출: 가족 전체방, 낱말은 공백으로 이은 한 검색어."""
        search_service.search_limiter.reset()
        out = search_service.search(
            self.db,
            self.user,
            self.world.group_id,
            " ".join(words),
            room_id=self.family.id,
            limit=limit,
        )
        return [item.id for item in out.items]

    def deep_ids(self, words: list[str]) -> list[int]:
        """내부 진단: 같은 조건에서 한도만 200건. 품질 지표에는 쓰지 않는다."""
        unique = list(dict.fromkeys(" ".join(words).split()))
        rows = srepo.search(self.db, self.world.group_id, [self.family], unique, DEEP_LIMIT, None)
        return [m.id for m, _ in rows]

    def ui_ids(self, words: list[str]) -> list[int]:
        """대화 검색 화면(GET /family-chat/search 와 같은 서비스): 내가 속한 1:1 방도 포함한다. 에이전트 결과와 혼동하지 않게 대조용으로만 쓴다."""
        search_service.search_limiter.reset()
        out = search_service.search(
            self.db, self.user, self.world.group_id, " ".join(words), room_id=None, limit=MAX_LIMIT
        )
        return [item.id for item in out.items]


def _keys(world: World, ids: list[int]) -> list[str]:
    return [world.key_of(i) for i in ids]


def _evaluate_set(case: dict, name: str, words: list[str], search: Searcher, world: World) -> dict:
    gold, acc, forb = case["gold"], case["acceptable"], set(case["forbidden"])
    scope = data.family_scope_keys()
    top = _keys(world, search.agent_ids(words))
    top20 = _keys(world, search.agent_ids(words, MAX_LIMIT))
    deep = _keys(world, search.deep_ids(words))
    ideal_deep = _keys(world, search.deep_ids(case["queries"]["ideal"]))
    row = {
        "query_set": name,
        "query": " ".join(words),
        "retrieved": top,
        "violations": [k for k in top if k not in scope or k in forb],
        "diagnostic": {"retrieved_at_20": top20, "deep_count": len(deep)},
    }
    row |= metrics.case_metrics(top, gold, acc)
    if gold:
        first20 = next((i for i, k in enumerate(top20, 1) if k in set(gold)), None)
        row["diagnostic"]["hit_at_20"] = 1.0 if first20 else 0.0
        card_keys = {m.key for m in data.MESSAGES if m.card}
        misses = [k for k in gold if k not in top]
        causes = {
            k: attribution.classify_miss(
                gold_key=k,
                query_set=name,
                in_deep=k in deep,
                in_ideal_deep=k in ideal_deep,
                card_keys=card_keys if case["card"] else set(),
                lexical_gap=case["lexical_gap"],
                needs_history=bool(case["history"]),
            )
            for k in misses
        }
        row["missed"] = causes
        unique = sorted(set(causes.values()))
        row["cause"] = "" if not unique else unique[0] if len(unique) == 1 else "mixed"
    else:
        row["cause"] = ""
    row["expected_cause"] = case["expected_cause"].get(name, "")
    row["matches_expectation"] = row["cause"] == row["expected_cause"]
    return row


def _group(rows: list[dict]) -> dict:
    """gold 가 있는 행들의 지표 묶음. 전체와, 알려진 한계 사례를 뺀 하위집단을 나란히 낸다(전체를 대체하지 않는다)."""
    with_gold = [r for r in rows if "hit" in r]
    rest = [r for r in with_gold if not r["known_limitation"]]
    return {
        "all": metrics.aggregate(with_gold),
        "excluding_known_limitations": metrics.aggregate(rest),
    }


def _causes(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in rows:
        for cause in r.get("missed", {}).values():
            counts[cause] = counts.get(cause, 0) + 1
    return dict(sorted(counts.items()))


def run(world: World, run_id: str = "local") -> dict:
    """평가를 실행해 보고서(JSON 으로 저장 가능한 dict)를 돌려준다. 정합 검사에 실패하면 `DatasetInvalid`."""
    problems = case_specs.check_pins()
    if problems:
        raise validate.DatasetInvalid("핀 검사 실패: " + "; ".join(problems))
    cases = case_specs.load()
    validate.require(cases)
    if set(world.ids) != {m.key for m in data.MESSAGES}:
        raise validate.DatasetInvalid("월드의 메시지 키가 선언과 다르다")
    pins = case_specs.build_pins()
    rows: list[dict] = []
    ui_probe: list[dict] = []
    with SessionLocal() as db:
        user = db.get(User, world.user_ids[data.REQUESTER])
        search = Searcher(db, user, world)
        for case in cases:
            for name, words in case["queries"].items():
                if not words:  # 에이전트 검색어 슬롯: 이번 단계에서는 비어 있다
                    continue
                row = _evaluate_set(case, name, words, search, world)
                row |= {
                    "case": case["id"],
                    "category": case["category"],
                    "known_limitation": case["known_limitation"],
                    "gold": case["gold"],
                }
                rows.append(row)
            if case["forbidden"]:
                ui = _keys(world, search.ui_ids(case["queries"]["ideal"]))
                ui_probe.append({"case": case["id"], "ui_search_returns": ui})

    def sets(name: str) -> list[dict]:
        return [r for r in rows if r["query_set"] == name]

    report = {
        "run_id": run_id,
        "git_sha": git_sha(),
        "model_calls": 0,
        "metrics_version": METRICS_VERSION,
        "limits": {"default": DEFAULT_LIMIT, "max": MAX_LIMIT, "deep_diagnostic_only": DEEP_LIMIT},
        "dataset": {
            "case_count": pins["case_count"],
            "cases_sha256": pins["cases_sha256"],
            "world_sha256": pins["world_sha256"],
        },
        "ordering": "최신순(id 내림차순). 관련도 순위가 아니다.",
        "query_sets": {},
        "cases": rows,
        "ui_scope_probe": ui_probe,
    }
    for name in ("ideal", "naive"):
        selected = sets(name)
        group = _group(selected)
        group["no_answer"] = metrics.no_answer(
            [
                {"returned": r["returned"], "violations": len(r["violations"])}
                for r in selected
                if "hit" not in r
            ]
        )
        group["miss_causes"] = _causes(selected)
        group["hit_at_20_diagnostic"] = _mean_diag(selected)
        report["query_sets"][name] = group
    diag = sets("no_history")
    report["query_sets"]["no_history_diagnostic"] = {
        "all": metrics.aggregate([r for r in diag if "hit" in r]),
        "miss_causes": _causes(diag),
    }
    report["security_violations"] = sum(len(r["violations"]) for r in rows)
    report["expectation_mismatches"] = [
        {
            "case": r["case"],
            "query_set": r["query_set"],
            "expected": r["expected_cause"],
            "actual": r["cause"],
        }
        for r in rows
        if not r["matches_expectation"]
    ]
    return report


def _mean_diag(rows: list[dict]) -> float | None:
    values = [r["diagnostic"]["hit_at_20"] for r in rows if "hit_at_20" in r["diagnostic"]]
    return sum(values) / len(values) if values else None
