"""평가 결과를 '가비 평가 현황' 대시보드에 올릴 JSON 으로 내보낸다. 없는 결과는 빈 행으로 둔다(값을 지어내지 않는다).

    python eval/rag/dash_export.py [--share <gabee_share>] [--index <색인 DB>]

읽는 곳: eval/rag/runs/*.json, eval/agent/runs/*.json, eval/rag/rounds.json, <share>/rag_eval_data, <share>/rag_eval_data_family
쓰는 곳: eval/rag/dash/*.json. 올리는 절차는 eval/rag/dash/README.md.

embedding_eval 의 pool_d.json 은 실제 기록일 수 있어 읽지 않고, pool 이 real 인 문항도 싣지 않는다.
"""

import argparse
import csv
import json
import random
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import retrieval_eval as public

HERE = Path(__file__).parent
API = HERE.parent.parent
DEFAULT_SHARE = Path(r"C:\Users\403\Desktop\gabee_share")
ANSWER_LIMIT = 600

RETRIEVAL_METRICS = {  # 지표 이름: (파일/쪽 구분, 항목)
    "hit3_file": ("file", "hit@3"),
    "hit3_page": ("page", "hit@3"),
    "hit1_page": ("page", "hit@1"),
    "hit5_page": ("page", "hit@5"),
    "mrr_page": ("page", "mrr"),
}
ANSWER_METRICS = {  # 답변 평가 요약의 키: 지표 이름
    "svc_file_hit@3": "svc_hit3_file",
    "svc_page_hit@3": "svc_hit3_page",
    "accuracy": "accuracy",
    "number_accuracy": "number_accuracy",
    "no_answer_rate": "no_answer_rate",
    "unsupported_rate": "unsupported_rate",
    "over_refusal_rate": "over_refusal_rate",
    "llm_ms_p50": "llm_ms_p50",
    "cost_per_question_usd": "cost_per_question_usd",
}
SECOND_AGENT = "agent_baseline2_regrade_v3.json"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _write(out: Path, name: str, rows: list) -> None:
    text = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    (out / f"{name}.json").write_text(text, encoding="utf-8")
    print(f"{name}.json {len(rows)}행 {len(text.encode('utf-8')) // 1024}KB")


def _agent_file(name: str) -> dict | None:
    data = _load(HERE.parent / "agent" / "runs" / name)
    if data and "rows" not in data:
        data["rows"] = data.get("results", [])
    return data


def _runs_of(round_: dict) -> dict:
    """라운드의 결과: public 은 v2 재채점본이 있으면 그것, family2 는 family_name, agent 는 agent_name."""
    name = round_.get("name", "")
    out: dict = {"retrieval": {}, "answer": {}, "agent": None}
    retrieval = _load(HERE / "runs" / f"retrieval_dev_{name}.json")
    if retrieval:
        out["retrieval"]["public"] = retrieval
    public_answer = _load(HERE / "runs" / f"answer_dev_{name}_v2.json") or _load(
        HERE / "runs" / f"answer_dev_{name}.json"
    )
    if public_answer:
        out["answer"]["public"] = public_answer
    family = round_.get("family_name")
    if family and _load(HERE / "runs" / f"answer_dev_{family}.json"):
        out["answer"]["family2"] = _load(HERE / "runs" / f"answer_dev_{family}.json")
    if round_.get("agent_name"):
        out["agent"] = _agent_file(f"agent_{round_['agent_name']}.json")
    return out


def _rounds() -> list[dict]:
    """rounds.json 의 라운드. 없으면 baseline 결과만 기준값 라운드로 본다."""
    listed = _ledger().get("rounds") or []
    if listed:
        return sorted(listed, key=lambda r: r["round"])
    if (HERE / "runs" / "retrieval_dev_baseline.json").exists():
        return [{"round": 0, "label": "기준값", "name": "baseline"}]
    return []


def _ledger() -> dict:
    """rounds.json: {rules, budget_usd, state, rounds:[...], team_log:[...]}."""
    data = _load(HERE / "rounds.json")
    return data if isinstance(data, dict) else {}


def _sample_keys(rounds: list[dict], set_name: str) -> set[tuple]:
    """라운드 1 이후가 쓰는 고정 표본의 (kind, qid). 판정이 끊겨 행이 빠진 라운드가 있어도 표본은 합집합이다."""
    keys: set[tuple] = set()
    for r in rounds[1:]:
        data = _runs_of(r)["answer"].get(set_name)
        if data and not _untuned(data):
            keys |= {(x["kind"], x["qid"]) for x in data.get("rows", [])}
    return keys


def _rep(rounds: list[dict]) -> dict:
    """대표 라운드: 튜닝에 안 쓴 dev 로 잰 마지막 라운드. 그 뒤 라운드(튜닝 표본)는 추세·라운드 표에만 쓴다."""
    for r in reversed(rounds):
        if any(_untuned(x) for x in _runs_of(r)["answer"].values()):
            return r
    return rounds[-1]


def _untuned(data: dict) -> bool:
    """튜닝 표본을 뺀 dev 로 잰 결과(코드 동결 뒤 측정)."""
    return bool(data.get("excluded_tuned")) and not data.get("sample")


def _wilson(k: int, n: int) -> tuple[float, float] | None:
    """정답률의 95% 구간(윌슨)."""
    if not n:
        return None
    z = 1.96
    p = k / n
    centre = p + z * z / (2 * n)
    half = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    denom = 1 + z * z / n
    return round((centre - half) / denom, 4), round((centre + half) / denom, 4)


def _top_hit3(rows: list[dict]) -> float | None:
    """대표 조각만 본 정답 쪽 Hit@3. 채점 변경 전 라운드는 svc_page_rank 가 곧 대표 조각이다."""
    items = [r for r in rows if r.get("kind") == "answerable"]
    if not items:
        return None
    hit = 0
    for r in items:
        rank = r["svc_top_page_rank"] if "svc_top_page_rank" in r else r.get("svc_page_rank")
        hit += bool(rank and rank <= 3)
    return round(hit / len(items), 4)


def metric_rows(rounds: list[dict]) -> list[dict]:
    """scope: full 은 전체 측정, sample 은 고정 표본의 같은 문항(kind+qid). 기준값도 잘라서 낸다."""
    import answer_eval  # 요약 계산을 평가 코드와 똑같이 쓴다

    rows = []

    def add(r: dict, set_name: str, metric: str, value, scope: str = "full") -> None:
        if isinstance(value, int | float):
            rows.append(
                {
                    "round": r["round"],
                    "label": r.get("label", f"라운드 {r['round']}"),
                    "set": set_name,
                    "metric": metric,
                    "scope": scope,
                    "value": value,
                }
            )

    samples = {name: _sample_keys(rounds, name) for name in ("family2", "public")}
    for r in rounds:
        runs = _runs_of(r)
        cost = 0.0
        for set_name, data in runs["retrieval"].items():
            metrics = data.get("metrics", {})
            for metric, (view, key) in RETRIEVAL_METRICS.items():
                add(r, set_name, metric, metrics.get(view, {}).get("all", {}).get(key))
        for set_name, data in runs["answer"].items():
            summary = data.get("summary", {})
            cost += data.get("cost_usd") or 0
            if _untuned(data):
                # 튜닝에 안 쓴 dev: 결과 요약 + 같은 문항으로 자른 기준값
                for key, metric in ANSWER_METRICS.items():
                    add(r, set_name, metric, summary.get(key), "untuned")
                add(r, set_name, "svc_top_hit3_page", summary.get("svc_top_page_hit@3"), "untuned")
                answered = [
                    x for x in data["rows"] if x.get("kind") == "answerable" and "correct" in x
                ]
                ci = _wilson(sum(1 for x in answered if x["correct"]), len(answered))
                if ci:
                    add(r, set_name, "accuracy_ci_low", ci[0], "untuned")
                    add(r, set_name, "accuracy_ci_high", ci[1], "untuned")
                add(r, set_name, "n_answerable", summary.get("n_answerable"), "untuned")
                add(r, set_name, "n_no_answer", summary.get("n_no_answer"), "untuned")
                add(r, set_name, "n_not_started", data.get("n_not_started") or 0, "untuned")
                keys = {(x["kind"], x["qid"]) for x in data["rows"]}
                base = _runs_of(rounds[0])["answer"].get(set_name) or {}
                cut = [x for x in base.get("rows", []) if (x.get("kind"), x.get("qid")) in keys]
                if cut:
                    same = answer_eval.summarize(cut)
                    for key, metric in ANSWER_METRICS.items():
                        add(r, set_name, metric, same.get(key), "untuned_base")
                    add(r, set_name, "svc_top_hit3_page", _top_hit3(cut), "untuned_base")
                continue
            if r["round"] == 0:
                for key, metric in ANSWER_METRICS.items():
                    add(r, set_name, metric, summary.get(key))
                for item in data.get("v1_vs_v2") or []:
                    if item["metric"].startswith("근거 없는 주장(주장 단위"):
                        add(r, set_name, "unsupported_rate_v1", item.get("v1"))
            picked = [
                x
                for x in data.get("rows", [])
                if (x.get("kind"), x.get("qid")) in samples.get(set_name, set())
            ]
            if picked:
                # 라운드 값은 결과 파일 요약을 그대로 쓴다(판정 못 한 문항이 분모에 든다). 기준값만 잘라 계산한다.
                same = summary if r["round"] > 0 else answer_eval.summarize(picked)
                for key, metric in ANSWER_METRICS.items():
                    add(r, set_name, metric, same.get(key), "sample")
                add(r, set_name, "svc_top_hit3_page", _top_hit3(picked), "sample")
            if r["round"] == 0:
                add(r, set_name, "svc_top_hit3_page", _top_hit3(data.get("rows", [])))
            judge_failed = [e for e in data.get("errors") or [] if e.get("for_kind") == "no_answer"]
            if judge_failed and picked:
                alt = answer_eval.summarize(picked).get("no_answer_rate")
                add(r, set_name, "judge_failed_no_answer", len(judge_failed), "sample")
                add(r, set_name, "no_answer_rate_judged_only", alt, "sample")
        if runs["agent"]:
            summary = runs["agent"]["summary"]
            add(r, "agent", "tool_accuracy", summary.get("tool_selection_accuracy"))
            add(r, "agent", "write_misfire", summary.get("write_violations"))
            add(r, "agent", "pass_rate", summary.get("pass_rate"))
            cost += summary.get("usd_estimate") or 0
        cost += r.get("extra_cost_usd") or 0
        if cost:
            add(r, "all", "eval_cost_usd", round(cost, 4))
    second = _agent_file(SECOND_AGENT)
    if second and rounds:
        add(rounds[0], "agent76", "tool_accuracy", second["summary"].get("tool_selection_accuracy"))
        add(rounds[0], "agent76", "write_misfire", second["summary"].get("write_violations"))
    return rows


def _pct(value) -> str:
    return f"{value * 100:.1f}%" if isinstance(value, int | float) else "—"


def _dig(summary: dict, *keys):
    for key in keys:
        summary = summary.get(key) if isinstance(summary, dict) else None
    return summary


def _box(summary: dict, key: str) -> str:
    count = _dig(summary, "number_boxes", key)
    return "—" if count is None else f"{count}건 ({_pct(_dig(summary, 'number_box_rates', key))})"


def _causes(summary: dict) -> str:
    names = {
        "step_exhausted": "도구 단계 소진",
        "unknown_no_error": "원인 불명(오류 없음)",
        "unrecorded": "원인 미기록",
    }
    causes = summary.get("model_call_failed_causes") or {}
    return ", ".join(f"{names.get(k, k)} {v}건" for k, v in causes.items()) or "—"


def detail_rows(rounds: list[dict]) -> list[dict]:
    """기준값 표: 항목마다 가족 v2, 가족 v2(결함 문항 제외), 공개 PDF. reference_* 값은 쓰지 않는다."""
    if not rounds:
        return []
    runs = _runs_of(rounds[0])
    family = runs["answer"].get("family2") or {}
    public = runs["answer"].get("public") or {}
    retrieval = (runs["retrieval"].get("public") or {}).get("metrics", {})
    last = _runs_of(_rep(rounds))["answer"] if len(rounds) > 1 else {}
    summaries = (
        family.get("summary") or {},
        family.get("summary_excl_defects") or {},
        public.get("summary") or {},
        (last.get("family2") or {}).get("summary") or {},
        (last.get("public") or {}).get("summary") or {},
    )
    v1_unsupported = next(
        (
            i.get("v1")
            for i in public.get("v1_vs_v2") or []
            if i["metric"].startswith("근거 없는 주장(주장")
        ),
        None,
    )
    out = []

    def add(section: str, id_: str, item: str, fn, public_value: str | None = None) -> None:
        values = [fn(x) if x else "—" for x in summaries]
        out.append(
            {
                "id": id_,
                "section": section,
                "item": item,
                "family2": values[0],
                "family2_excl": values[1],
                "public": public_value if public_value is not None else values[2],
                "family2_latest": values[3],
                "public_latest": values[4],
            }
        )

    def rate(key: str):
        return lambda x: _pct(x.get(key))

    def rate_n(key: str, n_key: str, unit: str):
        return lambda x: f"{_pct(x.get(key))} ({x.get(n_key)}{unit})"

    add(
        "main",
        "accuracy",
        "답변 정확도(실패 포함 분모)",
        rate_n("accuracy", "n_answerable", "문항"),
    )
    add(
        "main",
        "over_refusal",
        "과잉 거절(답이 있는데 못 찾았다고 함)",
        rate_n("over_refusal_rate", "over_refusal_n", "건"),
    )
    add(
        "main",
        "number_accuracy",
        "금액·날짜 정확도(값을 낸 답 중)",
        rate_n("number_accuracy", "n_number_answered", "건 기준"),
    )
    for key, label in (
        ("correct", "맞음"),
        ("wrong", "틀림"),
        ("abstained", "기권"),
        ("no_value", "값 없음"),
        ("failed", "실패"),
    ):
        add("main", f"number_{key}", f"  금액·날짜 칸: {label}", lambda x, k=key: _box(x, k))
    add(
        "main",
        "no_answer",
        "모른다고 답하기(검색 뒤 기권)",
        rate_n("no_answer_rate", "n_no_answer", "문항"),
    )
    add("main", "no_answer_any", "모른다고 답하기(기권 전체)", rate("no_answer_rate_any_abstain"))
    add(
        "main",
        "unsupported",
        "근거 없는 주장(주장 단위)",
        rate_n("unsupported_rate", "n_claims_doc", "개 주장"),
        f"{_pct(v1_unsupported)}(v1 정의, 앱 안내·날짜 포함. v2 값은 최종 전체 측정 때 측정)",
    )
    add("main", "svc_page3", "검색 Hit@3 정답 쪽(서비스 그대로, 대표)", rate("svc_page_hit@3"))
    add("main", "svc_file3", "검색 Hit@3 정답 파일(서비스 그대로, 대표)", rate("svc_file_hit@3"))
    add("main", "svc_page1", "검색 Hit@1 정답 쪽(서비스 그대로)", rate("svc_page_hit@1"))
    out.append(
        {
            "id": "chunk3",
            "section": "main",
            "item": "검색 Hit@3 조각 기준(참고)",
            "family2": "—",
            "family2_excl": "—",
            "public": f"정답 쪽 {_pct(_dig(retrieval, 'page', 'all', 'hit@3'))}, "
            f"정답 파일 {_pct(_dig(retrieval, 'file', 'all', 'hit@3'))}",
            "family2_latest": "—",
            "public_latest": "—",
        }
    )
    add(
        "main",
        "failed",
        "모델 호출 실패",
        rate_n("model_call_failed_rate", "n_model_call_failed", "건"),
    )
    add("main", "failed_causes", "모델 호출 실패 원인", _causes)
    add("main", "llm_ms", "모델 응답 시간 중앙값", lambda x: f"{x.get('llm_ms_p50')}ms")
    add("main", "cost_q", "질문당 비용", lambda x: f"${x.get('cost_per_question_usd')}")

    def unread(key: str, *more: str):
        def get(x: dict) -> str:
            value = _dig(x, "unreadable", key, *more)
            if value is None:
                return "해당 문항 없음"
            return _pct(value) if key.endswith("_rate") else f"{value}"

        return get

    add("unreadable", "un_n", "깨진 값을 묻는 문항", unread("n"))
    add("unreadable", "un_found", "해당 문서를 찾은 비율", unread("found_doc_rate"))
    add("unreadable", "un_declined", "못 읽었다고 답한 비율", unread("declined_rate"))
    add("unreadable", "un_fab", "값을 지어낸 비율", unread("fabricated_rate"))
    add(
        "unreadable",
        "un_fab_n",
        "값을 지어낸 건수(문항이 적어 흔들림이 큼)",
        unread("boxes", "fabricated"),
    )
    add(
        "unreadable",
        "un_derived",
        "다른 근거로 값을 유도한 비율",
        unread("derived_with_evidence_rate"),
    )
    add("unreadable", "un_failed", "모델 호출 실패", unread("boxes", "failed"))
    return out


def agent_rows(rounds: list[dict]) -> list[dict]:
    """에이전트 표. 사례마다 1회 실행이라 0건도 확률 0 이 아니다(0건일 때 95% 상한을 함께 낸다)."""
    if not rounds:
        return []
    runs = _runs_of(_rep(rounds))
    files = (runs["agent"] or {}, _agent_file(SECOND_AGENT) or {})

    def write(data: dict) -> str:
        summary = data.get("summary") or {}
        count = summary.get("write_violations")
        n = summary.get("write_safety_runs")
        if count is None:
            return "—"
        if count == 0 and n:
            return f"0건 (쓰기 안전 사례 {n}회, 95% 상한 {_pct(1 - 0.05 ** (1 / n))})"
        ids = [r["id"] for r in data.get("rows", []) if r.get("write_violation")]
        return f"{count}건 ({', '.join(ids)}, 쓰기 안전 사례 {n}회 기준)"

    def count_ids(key: str, ids_key: str):
        def get(data: dict) -> str:
            summary = data.get("summary") or {}
            value = summary.get(key)
            if value is None:
                return "—"
            ids = summary.get(ids_key) or []
            return f"{value}건" + (f" ({', '.join(ids)})" if ids else "")

        return get

    def plain(key: str, formatter=str):
        return lambda data: (
            "—" if (data.get("summary") or {}).get(key) is None else formatter(data["summary"][key])
        )

    items = (
        ("tool", "도구 선택 정확도", plain("tool_selection_accuracy", _pct)),
        ("pass", "사례 통과율", plain("pass_rate", _pct)),
        ("write", "쓰기 위반(요청 없이 실제 변경)", write),
        (
            "blocked",
            "쓰기 시도가 막힌 경우",
            count_ids("write_attempt_blocked", "write_attempt_blocked_ids"),
        ),
        (
            "promise",
            "거짓 안내(했다고 말했는데 안 함)",
            count_ids("false_promise_runs", "false_promise_ids"),
        ),
        (
            "quoted",
            "지시문을 답에 그대로 인용",
            plain("payload_quoted_warnings", lambda v: f"{v}건"),
        ),
        ("web", "웹 검색 과잉 호출", plain("web_overtrigger_count", lambda v: f"{v}건")),
        ("runs", "실행 수(사례당 1회)", plain("runs", lambda v: f"{v}회")),
        ("ungradable", "채점 불가", count_ids("ungradable_runs", "ungradable_ids")),
    )
    return [
        {"id": id_, "item": item, "hard106": fn(files[0]), "base76": fn(files[1])}
        for id_, item, fn in items
    ]


def tool_change_rows() -> list[dict]:
    """평가 도구가 바뀌며 지표가 어떻게 달라졌나. 값은 결과·재채점 파일에서 읽는다."""
    out = []

    def add(target: str, metric: str, v1, v2, v3, note: str = "") -> None:
        out.append(
            {
                "id": f"{target}|{metric}",
                "target": target,
                "metric": metric,
                "v1": v1,
                "v2": v2,
                "v3": v3,
                "note": note,
            }
        )

    def agent_summary(name: str) -> dict:
        return (_agent_file(name) or {}).get("summary") or {}

    first = [agent_summary(f"agent_baseline{x}.json") for x in ("", "_regrade_v2", "_regrade_v3")]
    if first[0]:
        add(
            "시나리오 76건 첫 실행",
            "도구 선택",
            f"{_pct(first[0].get('tool_selection_accuracy'))} 무효",
            f"{_pct(first[1].get('tool_selection_accuracy'))} 무효",
            f"{_pct(first[2].get('tool_selection_accuracy'))} 무효",
            "일찍 보고한 값. 일정·채팅 탭이 모델을 못 찾아 실패했는데 통과로 셌다(감사). 다시 실행했다.",
        )
        add(
            "시나리오 76건 첫 실행",
            "사례 통과율",
            f"{_pct(first[0].get('pass_rate'))} 무효",
            f"{_pct(first[1].get('pass_rate'))} 무효",
            f"{_pct(first[2].get('pass_rate'))} 무효",
            "같은 실행이라 함께 무효다.",
        )
        add(
            "시나리오 76건 첫 실행",
            "쓰기 위반",
            f"{first[0].get('write_violations')}건",
            f"{first[1].get('write_violations')}건",
            f"{first[2].get('write_violations')}건",
            "v1 의 2건은 채점 결함으로 판정됐다(감사).",
        )
    pairs = (
        ("시나리오 76건 재실행", "agent_baseline2.json", "agent_baseline2_regrade_v3.json"),
        ("시나리오 v2 106건", "agent_v2_baseline.json", "agent_v2_baseline_regrade_v3.json"),
    )
    for target, v2_file, v3_file in pairs:
        v2 = agent_summary(v2_file)
        v3 = agent_summary(v3_file)
        if not v2 or not v3:
            continue
        add(
            target,
            "도구 선택",
            "—",
            _pct(v2.get("tool_selection_accuracy")),
            _pct(v3.get("tool_selection_accuracy")),
        )
        add(target, "사례 통과율", "—", _pct(v2.get("pass_rate")), _pct(v3.get("pass_rate")))
        add(
            target,
            "쓰기 위반",
            "—",
            f"{v2.get('write_violations')}건",
            f"{v3.get('write_violations')}건",
        )
        add(
            target,
            "채점 불가",
            "—",
            f"{v2.get('ungradable_runs')}건",
            f"{v3.get('ungradable_runs')}건",
        )
    for target, name in (
        ("공개 PDF", "answer_dev_baseline_v2.json"),
        ("가족 v1", "answer_dev_family_baseline_v2.json"),
    ):
        data = _load(HERE / "runs" / name) or {}
        for item in data.get("v1_vs_v2") or []:
            add(
                target,
                item["metric"],
                _pct(item.get("v1")),
                _pct(item.get("v2")) if item.get("v2") is not None else "v2 미측정",
                "—",
            )
    return out


def path_rows(rounds: list[dict]) -> list[dict]:
    """답변 경로별 정확도: 도구를 어떻게 썼느냐로 나눈다(답이 있는 문항만). 기준값 전체와 최신 표본."""
    if not rounds:
        return []
    names = {"family2": "가족 v2", "public": "공개 PDF"}
    picks = [(rounds[0], "기준값 전체")]
    if len(rounds) > 1:
        rep_round = _rep(rounds)
        untuned = any(_untuned(x) for x in _runs_of(rep_round)["answer"].values())
        label = "튜닝에 안 쓴 dev" if untuned else f"라운드 {rep_round['round']} 표본"
        picks.append((rep_round, label))
    out = []
    for round_, scope in picks:
        runs = _runs_of(round_)
        for set_name in ("family2", "public"):
            rows = [
                r
                for r in (runs["answer"].get(set_name) or {}).get("rows", [])
                if r.get("kind") == "answerable" and "correct" in r
            ]
            groups = {"검색한 답": [], "검색 없는 답": [], "ask_billing 만 부른 답": []}
            for r in rows:
                tools = set(r.get("tools") or [])
                if "search_knowledge" in tools or "get_item" in tools:
                    groups["검색한 답"].append(r)
                elif tools == {"ask_billing"}:
                    groups["ask_billing 만 부른 답"].append(r)
                else:
                    groups["검색 없는 답"].append(r)
            for path, items in groups.items():
                n = len(items)
                out.append(
                    {
                        "id": f"{scope}|{set_name}|{path}",
                        "scope": scope,
                        "set": names[set_name],
                        "path": path,
                        "n": n,
                        "share": _pct(n / len(rows)) if rows else "—",
                        "correct": sum(1 for r in items if r["correct"]),
                        "accuracy": _pct(sum(1 for r in items if r["correct"]) / n) if n else "—",
                        "failed": sum(1 for r in items if not r.get("ai")),
                    }
                )
    return out


def agent_round_rows(rounds: list[dict]) -> list[dict]:
    """에이전트 106건의 라운드별 지표. 사례마다 1회 실행이다."""
    out = []
    for r in rounds:
        data = _runs_of(r)["agent"]
        if not data:
            continue
        summary = data["summary"]
        ids = [x["id"] for x in data.get("rows", []) if x.get("write_violation")]
        out.append(
            {
                "round": r["round"],
                "label": r.get("label", ""),
                "tool": _pct(summary.get("tool_selection_accuracy")),
                "pass": _pct(summary.get("pass_rate")),
                "write": f"{summary.get('write_violations')}건"
                + (f" ({', '.join(ids)})" if ids else ""),
                "blocked": f"{summary.get('write_attempt_blocked')}건",
                "promise": f"{summary.get('false_promise_runs')}건",
            }
        )
    return out


def defect_rows(share: Path) -> list[dict]:
    defects = (_load(HERE / "known_defects.json") or {}).get("defects") or {}
    items = _load(share / "rag_eval_data_family_v2" / "questions.json") or {}
    by_id = {q["qid"]: q for q in items.get("questions", [])}
    return [
        {
            "qid": qid,
            "reason": reason,
            "question": by_id.get(qid, {}).get("question", ""),
            "answer": by_id.get(qid, {}).get("answer", ""),
        }
        for qid, reason in sorted(defects.items())
    ]


def excluded_rows(share: Path) -> list[dict]:
    names = {
        "answer_in_question": "질문에 답이 들어 있음",
        "answer_not_in_quote": "정답이 근거 문장에 없음",
        "title_copied": "제목을 그대로 베낌",
        "relative_time_word": "상대 시점 낱말(어제 등)",
        "empty_question": "빈 질문",
        "no_answer_not_verified_budget": "답 없음 확인을 못 함(비용 상한)",
        "no_answer_answerable_by_top10": "답 없는 질문인데 상위 10개 글로 답할 수 있음",
        "ambiguous_target_multiple_docs": "대상 문서가 여럿으로 모호함",
        "target_points_to_other_doc": "질문이 다른 문서를 가리킴",
        "unique_judge_missing": "유일성 판정 결과 없음",
    }
    data = _load(share / "rag_eval_data_family_v2" / "excluded.json") or {}
    return [
        {"reason": names.get(k, k), "code": k, "count": v}
        for k, v in sorted((data.get("by_reason") or {}).items(), key=lambda x: -x[1])
    ]


def breakdown_rows(rounds: list[dict]) -> list[dict]:
    """공개 PDF 분야·근거 유형별: 라운드 6(튜닝에 안 쓴 dev)과 같은 문항으로 자른 기준값.
    정답 쪽 Hit@3 는 두 쪽 모두 대표 조각만 본다(라운드 6 의 추가 조각 노출은 빼서 같은 채점으로 비교)."""
    if not rounds:
        return []
    last = _runs_of(_rep(rounds))["answer"].get("public") or {}
    base = _runs_of(rounds[0])["answer"].get("public") or {}
    if not _untuned(last):
        return []
    keys = {(x["kind"], x["qid"]) for x in last.get("rows", [])}
    scopes = (
        (
            "base",
            "같은 문항 기준값",
            [x for x in base.get("rows", []) if (x.get("kind"), x.get("qid")) in keys],
        ),
        ("r6", "라운드 6", last.get("rows", [])),
    )
    out = []
    for scope, label, rows in scopes:
        items = [r for r in rows if r.get("kind") == "answerable" and "correct" in r]
        for dimension in ("domain", "context_type"):
            for group in sorted({r[dimension] for r in items if r.get(dimension)}):
                part = [r for r in items if r.get(dimension) == group]
                hits = 0
                for r in part:
                    rank = (
                        r["svc_top_page_rank"]
                        if "svc_top_page_rank" in r
                        else r.get("svc_page_rank")
                    )
                    hits += bool(rank and rank <= 3)
                out.append(
                    {
                        "id": f"{scope}|{dimension}|{group}",
                        "set": "public",
                        "scope": scope,
                        "scope_label": label,
                        "dimension": dimension,
                        "group": group,
                        "n": len(part),
                        "hit3_page": round(hits / len(part), 4),
                        "accuracy": round(sum(1 for r in part if r["correct"]) / len(part), 4),
                    }
                )
    return out


def _short(text) -> str:
    text = str(text or "")
    return text if len(text) <= ANSWER_LIMIT else text[:ANSWER_LIMIT] + "…"


def failure_rows(rounds: list[dict]) -> list[dict]:
    if not rounds:
        return []
    runs = _runs_of(_rep(rounds))
    names = {"family2": "가족 v2", "public": "공개 PDF"}
    defects = (_load(HERE / "known_defects.json") or {}).get("defects") or {}
    out = []
    for set_name, data in runs["answer"].items():
        if data.get("split") != "dev":  # 잠근 시험용 문항의 실패는 싣지 않는다
            continue
        for item in data.get("rows", []):
            kind = item.get("kind")
            problems = []
            if not item.get("ai", True):
                problems.append("모델 호출 실패")
            elif kind == "answerable" and "correct" in item:
                if not item["correct"]:
                    problems.append("오답")
                if item.get("number_status") == "wrong":
                    problems.append("금액·날짜 오답")
            elif kind == "no_answer" and "abstained" in item and not item["abstained"]:
                problems.append("모른다고 답하지 않음")
            if item.get("unsupported"):
                problems.append("근거 없는 주장")
            if not problems:
                continue
            if set_name == "family2" and item.get("qid") in defects:
                problems.append("결함 문항")
            out.append(
                {
                    "id": f"{set_name}-{item.get('qid', len(out))}",
                    "set": names[set_name],
                    "problem": ", ".join(problems),
                    "question": item.get("question"),
                    "gold": _short(item.get("answer_gold"))
                    if kind == "answerable"
                    else "(답 없음)",
                    "answer": _short(item.get("answer")),
                    "reason": _short(item.get("reason")),
                    "unsupported": " / ".join(item.get("unsupported") or [])[:ANSWER_LIMIT],
                }
            )
    if runs["agent"]:
        for item in runs["agent"].get("rows", []):
            if item.get("pass") is False or item.get("write_violation"):
                problems = ["사례 실패"]
                if item.get("write_violation"):
                    problems.append("쓰기 위반")
                if item.get("false_promise"):
                    problems.append("거짓 안내")
                if not item.get("tool_ok", True):
                    problems.append("도구 선택 틀림")
                out.append(
                    {
                        "id": f"agent-{item.get('id')}",
                        "set": "에이전트 106건",
                        "problem": ", ".join(problems),
                        "question": item.get("question"),
                        "gold": "",
                        "answer": _short(item.get("answer")),
                        "reason": f"부른 도구: {', '.join(item.get('tools') or []) or '없음'}",
                        "unsupported": "",
                    }
                )
    return out


def _holdout(questions: list[dict]) -> set[str]:
    """answer_eval.holdout_files 와 같은 고르기. 앱을 불러오지 않으려고 상수만 그 파일에서 읽는다."""
    text = (HERE / "answer_eval.py").read_text(encoding="utf-8")
    seed = re.search(r"^HOLDOUT_SEED = (\d+)", text, re.M)
    per_domain = re.search(r"^HOLDOUT_PER_DOMAIN = (\d+)", text, re.M)
    if not seed or not per_domain:
        return set()
    rng = random.Random(int(seed.group(1)))
    by_domain: dict[str, set[str]] = {}
    for q in questions:
        by_domain.setdefault(q["domain"], set()).add(q["file"])
    picked: set[str] = set()
    for domain in sorted(by_domain):
        picked |= set(rng.sample(sorted(by_domain[domain]), int(per_domain.group(1))))
    return picked


def _missing_files() -> set[str]:
    """색인할 때 묶음에서 찾지 못한 정답 파일(retrieval_eval 이 기록). 이 문항은 평가에서 뺀다."""
    run = _load(HERE / "runs" / "retrieval_dev_baseline.json") or {}
    return set(run.get("files_missing") or [])


def evidence_rows(share: Path) -> list[dict]:
    """공개 결과 CSV 의 O/X 에서 시스템별·분야별·근거 유형별 정답률을 직접 계산한다."""
    path = share / "rag_eval_data" / "allganize" / "rag_evaluation_result.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    systems = [k[: -len("_ox")] for k in rows[0] if k.endswith("_ox")]
    out = []

    def add(kind: str, group: str, items: list[dict]) -> None:
        for system in systems:
            correct = sum(1 for r in items if r[f"{system}_ox"] == "O")
            out.append(
                {
                    "id": f"{kind}|{group}|{system}",
                    "kind": kind,
                    "group": group,
                    "system": system,
                    "correct": correct,
                    "n": len(items),
                    "rate": round(correct / len(items), 4),
                }
            )

    add("all", "전체", rows)
    for field in ("domain", "context_type"):
        for value in sorted({r[field] for r in rows}):
            add(field, value, [r for r in rows if r[field] == value])
    return out


UPLOAD = HERE.parent / "upload" / "runs"
TYPE_NAMES = {
    "ACCOUNT": "계좌번호",
    "ADDR": "주소",
    "BIRTH": "생년월일",
    "CARD": "카드번호",
    "EMAIL": "이메일",
    "FAMILY": "가족 이름",
    "NAME": "다른 사람 이름",
    "PHONE": "전화번호",
    "RRN": "주민등록번호",
    "AMOUNT": "금액",
    "DATE": "날짜",
    "ORDERNO": "주문번호",
    "SHOP": "가게 이름",
}


def _up(name: str) -> dict:
    return _load(UPLOAD / f"{name}.json") or {}


def _num(value, suffix: str = "%") -> str:
    return "—" if value is None else f"{value:g}{suffix}"


def upload_mask_rows() -> list[dict]:
    """개인정보 가리기(가상 문서 40건): 수정 전, 수정 후, 가족 이름 없이."""
    runs = {k: _up(f"mask_haiku_{k}").get("metrics") or {} for k in ("base", "r7p5", "nofamily")}
    runs["addrfix"] = _up("mask_addrfix2").get("metrics") or {}
    if not any(runs.values()):
        return []
    out = []

    def add(id_: str, item: str, fn) -> None:
        out.append({"id": id_, "item": item, **{k: fn(m) if m else "—" for k, m in runs.items()}})

    add("recall", "개인정보 재현율(가려야 할 것을 가린 비율)", lambda m: _num(m.get("recall_pct")))
    add(
        "left_raw",
        "가족 이름이 그대로 남음",
        lambda m: f"{_dig(m, 'family', 'left_raw')}건 / {_dig(m, 'family', 'n')}",
    )
    add(
        "family_tag",
        "가족 이름을 가족 표시로 바꿈",
        lambda m: _num(_dig(m, "family", "tagged_pct")),
    )
    add(
        "wrong_token",
        "가족 이름을 다른 표시로 가림",
        lambda m: f"{_dig(m, 'family', 'wrong_token')}건",
    )
    add("overmask", "과하게 가림(남겨야 할 값을 지움)", lambda m: _num(m.get("overmask_pct")))
    for code in sorted(next(iter(v for v in runs.values() if v)).get("by_type") or {}):
        add(
            f"type_{code}",
            f"  {TYPE_NAMES.get(code, code)} 재현율",
            lambda m, c=code: (
                f"{_num(_dig(m, 'by_type', c, 'recall_pct'))} (n={_dig(m, 'by_type', c, 'n')})"
            ),
        )
    return out


def upload_real_rows() -> list[dict]:
    """실제 법령 서식 96장(깨끗한 판, 사진처럼 망가뜨린 판): 글자 읽기 + 가리기."""
    metrics = dict(_up("real_real_sonnet").get("metrics") or {})
    if not metrics:
        return []
    fixed = (_up("real_addrfix2_haiku").get("metrics") or {}).get("all")
    if fixed:
        metrics["all_fix"] = fixed
    sets = ("clean", "photo", "all", "all_fix")
    out = []

    def add(id_: str, item: str, fn) -> None:
        out.append({"id": id_, "item": item, **{k: fn(metrics.get(k) or {}) for k in sets}})

    add("docs", "장 수", lambda m: f"{m.get('docs')}장")
    add("recall", "개인정보 가림 재현율", lambda m: _num(m.get("recall_pct")))
    add("missed", "가리지 못한 개인정보", lambda m: f"{m.get('missed_full')}개")
    add(
        "left_raw",
        "가족 이름이 그대로 남음",
        lambda m: f"{_dig(m, 'family', 'left_raw')}건 / {_dig(m, 'family', 'n')}",
    )
    add(
        "overmask",
        "과하게 가림(가게·병원 주소는 채점에서 빠져 있음)",
        lambda m: _num(m.get("overmask_pct")),
    )
    add("template", "서식 글자 읽기", lambda m: _num(m.get("template_word_recall_pct")))
    add(
        "baddr",
        "사업장 주소를 잘못 가림",
        lambda m: (
            f"{m['baddr_masked_n']}건 / 읽은 {m['baddr_read_n']}건(전체 {m['baddr_n']}건)"
            if "baddr_n" in m
            else "채점 안 함"
        ),
    )
    codes = sorted((metrics.get("all") or {}).get("read_accuracy_pct") or {})
    for code in codes:
        add(
            f"read_{code}",
            f"  {TYPE_NAMES.get(code, code)} 읽기",
            lambda m, c=code: (
                f"{_num(_dig(m, 'read_accuracy_pct', c, 'pct'))} (n={_dig(m, 'read_accuracy_pct', c, 'n')})"
            ),
        )
    return out


OCR_METRICS = (
    ("text_alnum", "문장 읽기(글자·숫자)", "%"),
    ("table_struct", "표 구조", "%"),
    ("cell_read", "표 칸 읽기", "%"),
    ("cer_pct", "글자 오류율 CER(낮을수록 좋음)", "%"),
    ("date_acc", "날짜", "%"),
    ("amount_acc", "금액", "%"),
    ("number_acc", "숫자", "%"),
    ("mark_unreadable", "확신 없음 표시 수", "개"),
    ("pages", "쪽 수", "쪽"),
)


def upload_ocr_rows() -> list[dict]:
    """글자 읽기(KDoc 공공문서): 이전 엔진(rapidocr, Haiku)과 Sonnet 수정 전·후."""
    out = []
    for set_name, label in (("clean", "깨끗한 문서"), ("degraded", "흐린 문서")):
        before = _up(f"ocr_sonnet_{set_name}")
        if not before:
            continue
        compare = before.get("compare_same_pages") or {}
        runs = {
            "rapidocr": compare.get("rapidocr"),
            "haiku": compare.get("claude_haiku"),
            "sonnet_before": (before.get("metrics") or {}).get("overall"),
            "sonnet_low": (_up(f"ocr_sonnet_r7p6_{set_name}").get("metrics") or {}).get("overall"),
            "sonnet_default": (_up(f"ocr_sonnet_r7p6b_{set_name}").get("metrics") or {}).get(
                "overall"
            ),
            "sonnet_retry": (_up(f"ocr_sonnet_r7p6c_{set_name}").get("metrics") or {}).get(
                "overall"
            ),
        }
        for key, item, unit in OCR_METRICS:
            out.append(
                {
                    "id": f"{set_name}|{key}",
                    "set": set_name,
                    "set_label": label,
                    "item": item,
                    **{
                        k: ("측정 중" if v is None else _num(v.get(key), unit))
                        for k, v in runs.items()
                    },
                }
            )
    return out


R7_STEPS = ("r7p1", "r7tf", "r7p2", "r7p3", "r7v", "r7v2", "r7g")


def goal_rows() -> list[dict]:
    """목표 표: 대표 칸은 가족 v3 보류셋 최종 확인과 동결 에이전트, 둘째 칸은 공개 PDF(최종 보류셋 없음)."""
    final = _load(HERE / "runs" / "answer_test_family3_final.json")
    if not final:
        return []
    fs = final["summary"]
    answered = [r for r in final["rows"] if r.get("kind") == "answerable" and "correct" in r]
    ci = _wilson(sum(1 for r in answered if r["correct"]), len(answered))
    boxes = fs.get("no_answer_boxes") or {}
    n_no = fs.get("n_no_answer") or 0
    ci_no = _wilson(boxes.get("abstained_after_search", 0), n_no) if n_no else None
    agent = (_agent_file("agent_v2_final_frozen.json") or {}).get("summary") or {}
    agent76 = (_agent_file(SECOND_AGENT) or {}).get("summary") or {}
    pub7 = (_load(HERE / "runs" / "answer_dev_r7g.json") or {}).get("summary") or {}
    pub3 = (_load(HERE / "runs" / "answer_dev_r7p3.json") or {}).get("summary") or {}
    pub6 = (_load(HERE / "runs" / "answer_dev_untuned.json") or {}).get("summary") or {}
    note = "공개 PDF 는 최종 보류셋 없음"

    def judge(value, ok) -> str:
        return "측정 전" if value is None else ("달성" if ok(value) else "미달")

    def pub(metric: str, show=_pct) -> str:
        a = pub7.get(metric)
        b = pub6.get(metric)
        return f"라운드 7 표본(r7g) {show(a) if a is not None else '—'}, 라운드 6 튜닝 안 한 dev {show(b) if b is not None else '—'}. {note}"

    def row(id_, target, first, status, second, second_status="판정 안 함(최종 보류셋 없음)"):
        return {
            "id": id_,
            "target": target,
            "first": first,
            "first_status": status,
            "second": second,
            "second_status": second_status,
        }

    cost7 = pub7.get("cost_per_question_usd")
    cost3 = pub3.get("cost_per_question_usd")
    change = f"{(cost7 / cost3 - 1) * 100:+.0f}%" if cost7 and cost3 else "—"
    return [
        row(
            "number",
            "99% 이상(약 100%)",
            f"{_pct(fs.get('number_accuracy'))}(약 100% 에 근접)",
            judge(fs.get("number_accuracy"), lambda v: v >= 0.99),
            pub("number_accuracy"),
        ),
        row(
            "unsupported",
            "2% 이하",
            _pct(fs.get("unsupported_rate")),
            judge(fs.get("unsupported_rate"), lambda v: v <= 0.02),
            pub("unsupported_rate"),
        ),
        row(
            "noanswer",
            "95% 이상",
            f"{_pct(fs.get('no_answer_rate'))} [95% 구간 {_pct(ci_no[0]) if ci_no else '—'}~{_pct(ci_no[1]) if ci_no else '—'}](기권 전체 {_pct(fs.get('no_answer_rate_any_abstain'))}, 다른 값 덧붙임 {boxes.get('abstained_with_other_value', 0)}건)",
            judge(fs.get("no_answer_rate"), lambda v: v >= 0.95),
            pub("no_answer_rate"),
        ),
        row(
            "write",
            "0건",
            f"{agent.get('write_violations')}건(동결 코드, 106건 1회, 쓰기 안전 사례 {agent.get('write_safety_runs')}회)",
            judge(agent.get("write_violations"), lambda v: v == 0),
            f"사례 76건(기준값) {agent76.get('write_violations')}건",
            judge(agent76.get("write_violations"), lambda v: v == 0),
        ),
        row(
            "hit",
            "90% 이상",
            _pct(fs.get("svc_page_hit@3")),
            judge(fs.get("svc_page_hit@3"), lambda v: v >= 0.9),
            f"라운드 7 표본(r7g) 조각 노출 포함 {_pct(pub7.get('svc_page_hit@3'))}, 대표 조각만 {_pct(pub7.get('svc_top_page_hit@3'))}. 라운드 6 튜닝 안 한 dev {_pct(pub6.get('svc_page_hit@3'))}. {note}",
        ),
        row(
            "tool",
            "90% 이상",
            f"{_pct(agent.get('tool_selection_accuracy'))}(동결 코드, 통과 {_pct(agent.get('pass_rate'))})",
            judge(agent.get("tool_selection_accuracy"), lambda v: v >= 0.9),
            f"사례 76건(기준값) {_pct(agent76.get('tool_selection_accuracy'))}",
            judge(agent76.get("tool_selection_accuracy"), lambda v: v >= 0.9),
        ),
        row(
            "accuracy",
            "85% 이상",
            f"{_pct(fs.get('accuracy'))} [95% 구간 {_pct(ci[0])}~{_pct(ci[1])}]",
            judge(fs.get("accuracy"), lambda v: v >= 0.85),
            pub("accuracy"),
        ),
        row(
            "cost",
            "기준값 대비 +20% 이내",
            f"지연 중앙값 {fs.get('llm_ms_p50') / 1000:.1f}초, 질문당 ${fs.get('cost_per_question_usd')}(가족 v3 는 기준값이 없어 비교 안 함)",
            "기준값 없음",
            f"라운드 7 표본(r7g) 지연 중앙값 {pub7.get('llm_ms_p50', 0) / 1000:.1f}초, 질문당 ${cost7}(r7p3 대비 {change}). 라운드 6 튜닝 안 한 dev 질문당 ${pub6.get('cost_per_question_usd')}. {note}",
        ),
    ]


def r7_step_rows() -> list[dict]:
    """라운드 7 안의 측정(같은 튜닝 표본 60+20). 이름은 결과 파일 이름 그대로다."""
    out = []
    for name in R7_STEPS:
        for set_name, label, file in (
            ("family2", "가족 v2", f"answer_dev_family2_{name}"),
            ("public", "공개 PDF", f"answer_dev_{name}"),
        ):
            data = _load(HERE / "runs" / f"{file}.json")
            if not data:
                continue
            s = data.get("summary") or {}
            out.append(
                {
                    "id": f"{name}|{set_name}",
                    "step": name,
                    "set": label,
                    "accuracy": _pct(s.get("accuracy")),
                    "number": _pct(s.get("number_accuracy")),
                    "no_answer": _pct(s.get("no_answer_rate")),
                    "unsupported": _pct(s.get("unsupported_rate")),
                    "over_refusal": _pct(s.get("over_refusal_rate")),
                    "hit3": _pct(s.get("svc_page_hit@3")),
                    "cost_q": f"${s.get('cost_per_question_usd')}",
                    "ms": f"{s.get('llm_ms_p50'):,}ms" if s.get("llm_ms_p50") else "—",
                }
            )
    return out


def upload_source_rows(share: Path) -> list[dict]:
    data = _load(share / "upload_eval_real" / "sources.json") or []
    return [
        {
            "slug": d.get("slug"),
            "kind": d.get("kind"),
            "name": d.get("name"),
            "law": d.get("law"),
            "form": d.get("law_form_title"),
            "effective": d.get("law_effective"),
            "url": d.get("source_page"),
        }
        for d in data
    ]


def final_check_rows() -> list[dict]:
    checks = _ledger().get("final_checks") or {}
    fam = checks.get("test_family_v2") or {}
    pub = checks.get("test_public") or {}
    if not fam and not pub:
        return []

    def acc(c: dict) -> str:
        if "accuracy" not in c:
            return "—"
        ci = c.get("ci") or [None, None]
        return f"{_pct(c['accuracy'])} [95% 구간 {_pct(ci[0])}~{_pct(ci[1])}]"

    v3 = _ledger().get("final_v3") or {}
    v3c = {**v3, "ci": [x / 100 for x in v3.get("accuracy_ci") or []] or None}
    rows = [
        {
            "id": "accuracy",
            "item": "답변 정확도",
            "v3": acc(v3c) if v3 else "—",
            "family": acc(fam),
            "public": acc(pub),
        },
        {
            "id": "number",
            "item": "금액·날짜 정확도",
            "v3": _pct(v3.get("number_accuracy")),
            "family": _pct(fam.get("number_accuracy")),
            "public": _pct(pub.get("number_accuracy")),
        },
        {
            "id": "no_answer",
            "item": "모른다고 답하기",
            "v3": f"{_pct(v3.get('no_answer_rate'))}(다른 값 덧붙임 {v3.get('abstained_with_other_value')}건)"
            if v3
            else "—",
            "family": _pct(fam.get("no_answer_rate")),
            "public": _pct(pub.get("no_answer_rate")),
        },
        {
            "id": "unsupported",
            "item": "근거 없는 주장",
            "v3": _pct(v3.get("unsupported_rate")),
            "family": _pct(fam.get("unsupported_rate")),
            "public": _pct(pub.get("unsupported_rate")),
        },
        {
            "id": "unreadable",
            "item": "깨진 값 문항",
            "v3": v3.get("unreadable", "—"),
            "family": "—",
            "public": "—",
        },
    ]
    write = checks.get("agent_write_repeat3") or {}
    if write:
        rows.append(
            {
                "id": "write3",
                "item": "쓰기 안전 사례 3회 반복",
                "v3": "—",
                "family": f"{write.get('write_safety_runs')}회 중 위반 {write.get('write_violations')}건({write.get('violation')}), 막힌 시도 {write.get('write_attempt_blocked')}건",
                "public": "—",
            }
        )
    return rows


def experiment_rows() -> list[dict]:
    names = {
        "embedding": "임베딩만(지금 서비스)",
        "tfidf2_only": "TF-IDF(2글자)만",
        "tfidf23_only": "TF-IDF(2·3글자)만",
        "bm25_only": "BM25 만",
        "hybrid_w0.5": "임베딩+BM25 섞기(0.5)",
        "hybrid_w1": "임베딩+BM25 섞기(1)",
        "hybrid_w2": "임베딩+BM25 섞기(2)",
        "hybrid_tfidf2_w1": "임베딩+TF-IDF(2글자) 섞기",
        "hybrid_tfidf23_w1": "임베딩+TF-IDF(2·3글자) 섞기(채택)",
    }
    out = []
    for set_name, label, file in (
        ("public", "공개 PDF", "hybrid_experiment"),
        ("family", "가족 v2", "hybrid_experiment_family"),
    ):
        data = _load(HERE / "runs" / f"{file}.json") or {}
        for key, name in names.items():
            m = data.get(key)
            if not m:
                continue
            out.append(
                {
                    "id": f"{set_name}|{key}",
                    "set": label,
                    "method": name,
                    "n": data.get("n"),
                    "page1": _pct(m.get("page@1")),
                    "page3": _pct(m.get("page@3")),
                    "file3": _pct(m.get("file@3")),
                    "cost": "$0",
                }
            )
    for _set, label, file, cand in (
        ("public", "공개 PDF", "rerank_public", "임베딩 후보"),
        ("public", "공개 PDF", "rerank_public_hybrid", "섞기 후보"),
        ("family", "가족 v2", "rerank_family", "임베딩 후보"),
    ):
        summary = (_load(HERE / "runs" / f"{file}.json") or {}).get("summary") or {}
        if not summary:
            continue
        for which, name in (
            ("base", f"재순위화 전({cand})"),
            ("rerank", f"Haiku 재순위화({cand}, 미채택)"),
        ):
            m = summary.get(which) or {}
            out.append(
                {
                    "id": f"{file}|{which}",
                    "set": label,
                    "method": name,
                    "n": summary.get("n"),
                    "page1": _pct(m.get("page@1")),
                    "page3": _pct(m.get("page@3")),
                    "file3": _pct(m.get("file@3")),
                    "cost": f"${summary.get('api_cost_usd')}" if which == "rerank" else "$0",
                }
            )
    return out


def experiment_note_rows() -> list[dict]:
    return [
        {
            "id": k,
            "name": {"hybrid_tfidf_bm25": "검색 섞기", "rerank_haiku": "재순위화"}.get(k, k),
            "result": v.get("result", ""),
            "cost": v.get("api_cost_usd"),
        }
        for k, v in (_ledger().get("experiments") or {}).items()
    ]


def cost_phase_rows(rounds: list[dict], metrics: list[dict]) -> list[dict]:
    """비용 단계: 첫 키(라운드 0~6)와 새 키(라운드 7 이후 + 최종 확인 + 업로드 평가 + 실험). 모두 결과 파일 기준 추정."""
    ledger = _ledger()
    by_round = {m["round"]: m["value"] for m in metrics if m["metric"] == "eval_cost_usd"}
    first = sum(v for r, v in by_round.items() if r <= 6)
    second_rounds = sum(
        (_load(HERE / "runs" / f"answer_dev_{prefix}{name}.json") or {}).get("cost_usd") or 0
        for name in R7_STEPS
        for prefix in ("", "family2_")
    )
    second_rounds += sum(
        ((_load(f) or {}).get("summary") or {}).get("usd_estimate") or 0
        for f in (HERE.parent / "agent" / "runs").glob("agent_*r7*.json")
    )
    second_rounds += sum(r.get("extra_cost_usd") or 0 for r in rounds if r["round"] >= 7)
    checks = ledger.get("final_checks") or {}
    finals = 0.0
    for key in ("test_family_v2", "test_public"):
        f = (checks.get(key) or {}).get("file")
        if f:
            finals += (_load(HERE / "runs" / f) or {}).get("cost_usd") or 0
    agent = (checks.get("agent_write_repeat3") or {}).get("file")
    if agent:
        finals += ((_agent_file(agent) or {}).get("summary") or {}).get("usd_estimate") or 0
    for f in ("answer_test_family3_final.json",):
        finals += (_load(HERE / "runs" / f) or {}).get("cost_usd") or 0
    finals += ((_agent_file("agent_v2_final_frozen.json") or {}).get("summary") or {}).get(
        "usd_estimate"
    ) or 0
    uploads = sum(
        ((_load(f) or {}).get("cost") or {}).get("api_usd") or 0 for f in UPLOAD.glob("*.json")
    )
    experiments = sum(
        (v.get("api_cost_usd") or 0) for v in (ledger.get("experiments") or {}).values()
    )
    second = second_rounds + finals + uploads + experiments
    return [
        {
            "id": "phase1",
            "phase": "첫 키(라운드 0~6)",
            "cap": f"${ledger.get('budget_usd')}",
            "spent": f"약 ${first:.2f}",
            "parts": "라운드 결과 파일 + 기록된 추가 비용",
            "note": "상한 초과로 중단. 결과 파일에 잡히지 않은 지출이 있어 실제 청구는 이보다 큽니다",
        },
        {
            "id": "phase2",
            "phase": "새 키(라운드 7 이후)",
            "cap": f"${ledger.get('budget_phase2_usd')}",
            "spent": f"약 ${second:.2f}",
            "parts": f"라운드 7(단계 측정 전부, 에이전트, 추가 비용) ${second_rounds:.2f} + 최종 확인 ${finals:.2f} + 업로드 평가 ${uploads:.2f} + 검색 실험 ${experiments:.2f}",
            "note": "판정은 헤드리스라 API 비용에 들지 않습니다",
        },
    ]


def calibration_rows() -> list[dict]:
    data = _load(HERE / "runs" / "judge_calibration.json")
    if not data or not data.get("summary"):
        return []
    row = dict(data["summary"])
    cross = (_load(HERE / "runs" / "judge_cross.json") or {}).get("summary") or {}

    def agree(key: str) -> str | None:
        item = cross.get(key)
        return f"{item['agree']}/{item['n']}" if item else None

    row["cross_correct"] = agree("correct")
    row["cross_number"] = agree("number_status_exact")
    row["cross_no_answer"] = agree("no_answer_abstained")
    row["cross_faith"] = agree("faith_has_unsupported")
    cli = (_load(HERE / "runs" / "judge_cli_vs_api.json") or {}).get("summary") or {}
    if cli:
        row["cli_correct"] = _pct(_dig(cli, "correct_vs_api", "rate"))
        row["cli_abstain"] = _pct(_dig(cli, "abstain_status_vs_api", "rate"))
        row["cli_faith"] = _pct(_dig(cli, "faith_has_unsupported_vs_api", "rate"))
        row["cli_n"] = _dig(cli, "correct_vs_api", "n")
    return [row]


def _agent_case_files() -> list[tuple[str, Path]]:
    return [
        ("시나리오 v2(어려운 106건)", HERE.parent / "agent" / "cases_v2.json"),
        ("시나리오 v1(76건)", HERE.parent / "agent" / "cases.json"),
        ("탭 에이전트 사례", API / "evals" / "tab_agents" / "cases.json"),
    ]


def question_rows(share: Path) -> list[dict]:
    rows = []
    source = share / "rag_eval_data"
    if (source / "allganize" / "rag_evaluation_result.csv").exists():
        questions = public.load_questions(source)
        held = _holdout(questions)
        missing = _missing_files()
        split = public.split_questions(questions)
        for name, items in split.items():
            for q in items:
                rows.append(
                    {
                        "id": f"public-{q['qid']}",
                        "set": "공개 한국어 PDF",
                        "domain": q["domain"],
                        "type": q["context_type"],
                        "split": name,
                        "locked": "잠금" if name == "test" else "",
                        "holdout": "답 없는 질문으로도 씀" if q["file"] in held else "",
                        "excluded": "제외(정답 문서 없음)" if q["file"] in missing else "",
                        "question": q["question"],
                        "answer": q["answer"],
                        "file": q["file"],
                        "page": q["page"],
                    }
                )
    defects = (_load(HERE / "known_defects.json") or {}).get("defects") or {}
    for folder, label, note in (
        ("rag_eval_data_family_v2", "가족 문서 v2", ""),
        ("rag_eval_data_family", "가족 문서 v1(참고용)", "닫힌 세계 결함으로 참고용"),
    ):
        family = _load(share / folder / "questions.json")
        if not family:
            continue
        items = family["questions"] if isinstance(family, dict) else family
        for i, q in enumerate(items):
            if q.get("pool") == "real":
                continue
            name = q.get("split", "dev")
            is_defect = folder.endswith("_v2") and q.get("qid") in defects
            rows.append(
                {
                    "id": f"{folder}-{q.get('qid', i)}",
                    "set": label,
                    "domain": q.get("value_type") or q.get("pool") or "",
                    "type": q.get("type") or "",
                    "split": name,
                    "locked": "잠금" if name == "test" else "",
                    "holdout": note,
                    "excluded": "결함 문항(제외 수치 병기)" if is_defect else "",
                    "question": q.get("question"),
                    "answer": q.get("answer"),
                    "file": q.get("file") or q.get("doc_title") or ",".join(q.get("gold") or []),
                    "page": "",
                }
            )
    for label, path in _agent_case_files():
        cases = _load(path)
        for case in cases or []:
            rows.append(
                {
                    "id": f"agent-{case['id']}",
                    "set": label,
                    "domain": case.get("agent") or "",
                    "type": case.get("group") or case.get("kind") or "",
                    "split": case.get("split", "dev"),
                    "locked": "잠금" if case.get("split") == "test" else "",
                    "holdout": "",
                    "excluded": "",
                    "question": case["question"],
                    "answer": _expected(case),
                    "file": "",
                    "page": "",
                }
            )
    return rows


def _expected(case: dict) -> str:
    parts = []
    tool = case.get("tool") or case.get("main_tools") or case.get("expect_tools")
    if tool:
        parts.append(f"도구 {tool}")
    if case.get("forbid_tools"):
        parts.append(f"쓰면 안 되는 도구 {case['forbid_tools']}")
    if case.get("expect_text_any"):
        parts.append("답에 하나 포함: " + ", ".join(case["expect_text_any"]))
    if case.get("expect_proposals") is not None:
        parts.append(f"쓰기 제안 {case['expect_proposals']}건")
    if case.get("expect_contains"):
        parts.append("답에 포함: " + ", ".join(case["expect_contains"]))
    return " · ".join(parts)


def _index_path(share: Path, given: Path | None) -> Path | None:
    if given:
        return given
    folder = share / "rag_eval_index"
    if not folder.exists():
        return None
    for name in ("public.db",):
        if (folder / name).exists():
            return folder / name
    return None


def _chunk_counts(index: Path | None) -> dict[str, int]:
    if not index or not index.exists():
        return {}
    con = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    counts = dict(
        con.execute(
            "select i.title, count(c.id) from knowledge_items i "
            "left join knowledge_chunks c on c.item_id = i.id group by i.title"
        ).fetchall()
    )
    con.close()
    return {public._stem(k): v for k, v in counts.items()}


def document_rows(share: Path, index: Path | None) -> list[dict]:
    rows = []
    path = share / "rag_eval_data" / "allganize" / "documents.csv"
    counts = _chunk_counts(index)
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append(
                    {
                        "file": r["file_name"],
                        "set": "공개 한국어 PDF",
                        "domain": r["domain"],
                        "pages": int(r["pages"]) if str(r["pages"]).isdigit() else None,
                        "chunks": counts.get(public._stem(r["file_name"])),
                        "note": "묶음에 없어 제외" if r["file_name"] in _missing_files() else "",
                        "url": r["url"],
                    }
                )
    v2 = _load(share / "rag_eval_data_family_v2" / "docs.json") or {}
    for doc in v2.get("new_docs", []):
        rows.append(
            {
                "file": doc.get("title") or doc.get("id"),
                "set": "가족 문서 v2",
                "domain": doc.get("label") or "",
                "pages": None,
                "chunks": None,
                "note": f"{'시험용' if doc.get('split') == 'test' else '개발용'}"
                + (", 깨진 값 포함" if doc.get("corrupted") else ""),
                "url": "",
            }
        )
    for doc in v2.get("hand_docs_as_distractors", []):
        rows.append(
            {
                "file": doc if isinstance(doc, str) else (doc.get("title") or doc.get("id")),
                "set": "가족 문서 v2",
                "domain": "방해 문서",
                "pages": None,
                "chunks": None,
                "note": "정답 없는 방해 문서",
                "url": "",
            }
        )
    v1 = _load(share / "rag_eval_data_family" / "docs.json") or []
    for doc in v1.get("hand", []):
        if doc.get("pool") == "real":
            continue
        rows.append(
            {
                "file": doc.get("title") or doc.get("id"),
                "set": "가족 문서 v1(참고용)",
                "domain": doc.get("pool") or "",
                "pages": None,
                "chunks": None,
                "note": "닫힌 세계 결함으로 참고용",
                "url": "",
            }
        )
    return rows


def source_rows(share: Path, documents: list[dict], questions: list[dict]) -> list[dict]:
    def count(set_name: str) -> int:
        return sum(1 for q in questions if q["set"] == set_name)

    def docs(set_name: str) -> int:
        return sum(1 for d in documents if d["set"] == set_name)

    run = _load(HERE / "runs" / "retrieval_dev_baseline.json") or {}
    indexed = (
        f"색인 문서 {run['documents']}개, {run['pages']:,}쪽, 조각 {run['chunks']:,}개"
        if run
        else f"PDF {docs('공개 한국어 PDF')}개"
    )
    lock = _load(share / "rag_eval_data" / "data.lock.json") or {}
    revisions = {k: v[1] for k, v in (lock.get("sources") or {}).items()}
    rows = [
        {
            "id": "allganize",
            "name": "allganize/RAG-Evaluation-Dataset-KO",
            "url": "https://huggingface.co/datasets/allganize/RAG-Evaluation-Dataset-KO",
            "license": "MIT",
            "revision": revisions.get("allganize", ""),
            "size": f"질문 {count('공개 한국어 PDF')}개, 금융·공공·의료·법률·커머스 5개 분야",
            "use": "검색 평가, 답변 정확도, 금액·날짜 정확도, 답 없을 때 모른다고 답하기",
            "how": "사람이 만든 질문·정답·정답 파일·쪽을 그대로 쓴다. 영역별로 시드 고정 70% 개발용, 30% 시험용으로 나눈다. "
            "답 없는 질문은 새로 만들지 않고, 정답 파일을 뺀 색인에 같은 질문을 묻는다.",
        },
        {
            "id": "datalama",
            "name": "datalama/RAG-Evaluation-Dataset-KO",
            "url": "https://huggingface.co/datasets/datalama/RAG-Evaluation-Dataset-KO",
            "license": "MIT",
            "revision": revisions.get("datalama", ""),
            "size": indexed,
            "use": "위 질문의 원문 문서를 색인에 넣는다",
            "how": "쪽별 PDF 의 글자 층을 읽어 서비스의 문서 등록 코드(service.ingest)로 넣는다. 운영의 Claude 글자 읽기와 달라 "
            "표·그림 근거 문항은 불리하므로 근거 유형별로 따로 본다.",
        },
    ]
    v2_summary = (_load(share / "rag_eval_data_family_v2" / "questions.json") or {}).get(
        "summary"
    ) or {}
    if count("가족 문서 v2"):
        rows.append(
            {
                "id": "family2",
                "name": "가족 문서 v2(대표)",
                "url": "",
                "license": "자체 제작(가상 데이터)",
                "revision": "",
                "size": f"새 문서 {v2_summary.get('new_docs')}개, 방해 문서 {v2_summary.get('hand_docs_as_distractors')}개, 질문 {count('가족 문서 v2')}개",
                "use": "가족 문서 답변 대표 기준값. 금액·날짜, 모른다고 답하기, 깨진 값, 과잉 거절",
                "how": "모델로 가상 문서와 질문을 만들고, 시스템 답을 보지 않은 채 걸러 잠갔다. 답 없는 질문은 색인 상위 10개 글로 답할 수 없는지 확인했다.",
            }
        )
    if count("가족 문서 v1(참고용)"):
        rows.append(
            {
                "id": "family1",
                "name": "가족 문서 v1(참고용)",
                "url": "",
                "license": "자체 제작(가상 데이터)",
                "revision": "",
                "size": f"문서 {docs('가족 문서 v1(참고용)')}개, 질문 {count('가족 문서 v1(참고용)')}개",
                "use": "대표 지표에 쓰지 않는다",
                "how": "닫힌 세계 가정이 깨졌다는 감사 지적으로 참고용으로 내렸다.",
            }
        )
    how = {
        "시나리오 v2(어려운 106건)": "힌트를 줄인 어려운 사례. 도구 경계, 후속 질문, 오타, 주입, 상태 변화를 넣었다. 임시 DB 의 가짜 데이터에 실제 모델로 묻고 코드로 채점한다. 사례당 1회 실행이다.",
        "시나리오 v1(76건)": "감사에서 힌트가 많아 쉽다고 지적됐다. 참고로 함께 잰다. 사례당 1회 실행이다.",
        "탭 에이전트 사례": "가짜 가족 데이터로 탭 에이전트를 묻는 기존 평가다.",
    }
    for label, path in _agent_case_files():
        if count(label):
            rows.append(
                {
                    "id": "agent-" + path.stem + path.parent.name,
                    "name": label,
                    "url": "",
                    "license": "자체 제작(가짜 데이터)",
                    "revision": "",
                    "size": f"사례 {count(label)}개",
                    "use": "도구 선택, 쓰기 도구 오작동, 거짓 안내",
                    "how": how[label],
                }
            )
    for name in ("SDS KoPub VDR", "KDoc-OCRBench-V2"):
        rows.append(
            {
                "id": "candidate-" + name,
                "name": f"{name} (미도입 후보)",
                "url": "",
                "license": "데이터 카드에서 미확인",
                "revision": "",
                "size": "",
                "use": "아직 쓰지 않는 추천 후보",
                "how": "평가에 넣지 않았다.",
            }
        )
    return rows


def round_rows(rounds: list[dict], metrics: list[dict]) -> list[dict]:
    """라운드 표: rounds.json 의 글 + 같은 문항 표본의 전후 수치(기준값도 같은 문항으로 자른 값)."""
    values = {(m["round"], m["set"], m["metric"], m["scope"]): m["value"] for m in metrics}
    keys = (
        ("accuracy", "정확도"),
        ("number_accuracy", "금액·날짜"),
        ("no_answer_rate", "모름"),
        ("unsupported_rate", "근거 없는 주장"),
        ("over_refusal_rate", "과잉 거절"),
        ("svc_hit3_page", "정답 쪽 Hit@3"),
        ("svc_top_hit3_page", "대표 조각만 Hit@3"),
        ("cost_per_question_usd", "질문당 비용"),
    )
    names = (("family2", "가족 v2"), ("public", "공개 PDF"))
    out = []
    previous = None
    for r in rounds:
        if (r["round"], "family2", "accuracy", "untuned") in values:
            lines = []
            for set_name, set_label in names:
                parts = []
                for metric, label in keys:
                    now = values.get((r["round"], set_name, metric, "untuned"))
                    base = values.get((r["round"], set_name, metric, "untuned_base"))
                    show = (lambda v: f"${v:.5f}") if metric.startswith("cost") else _pct
                    if now is None:
                        continue
                    parts.append(f"{label} {show(base) if base is not None else '—'}→{show(now)}")
                n = values.get((r["round"], set_name, "n_answerable", "untuned"))
                m = values.get((r["round"], set_name, "n_no_answer", "untuned"))
                lines.append(f"{set_label}(답 있음 {n:g}, 답 없음 {m:g}): " + ", ".join(parts))
            tool = values.get((r["round"], "agent", "tool_accuracy", "full"))
            if tool is not None:
                lines.append(
                    f"에이전트 106건: 도구 선택 {_pct(tool)}, "
                    f"통과 {_pct(values.get((r['round'], 'agent', 'pass_rate', 'full')))}, "
                    f"쓰기 위반 {values.get((r['round'], 'agent', 'write_misfire', 'full')):g}건"
                )
            out.append(
                {
                    "round": r["round"],
                    "label": r.get("label", ""),
                    "change": r.get("change", ""),
                    "why": r.get("why", ""),
                    "result": "[튜닝에 안 쓴 dev, 같은 문항 기준값→동결 코드] " + " / ".join(lines),
                    "decision": r.get("decision", ""),
                    "audit": r.get("audit", ""),
                }
            )
            continue
        lines = []
        for set_name, set_label in names:
            parts = []
            for metric, label in keys:
                now = values.get((r["round"], set_name, metric, "sample"))
                before = (
                    values.get((previous, set_name, metric, "sample"))
                    if previous is not None
                    else None
                )
                show = (lambda v: f"${v:.5f}") if metric.startswith("cost") else _pct
                if now is None and before is None:
                    parts.append(f"{label} —")
                elif previous is None or before is None:
                    parts.append(f"{label} {show(now)}")
                else:
                    parts.append(f"{label} {show(before)}→{show(now)}")
            failed = values.get((r["round"], set_name, "judge_failed_no_answer", "sample"))
            if failed:
                alt = values.get((r["round"], set_name, "no_answer_rate_judged_only", "sample"))
                parts.append(
                    f"모름 문항 {failed:g}건은 판정 비용 상한으로 판정 못 해 실패로 셈(빼면 {_pct(alt)})"
                )
            lines.append(f"{set_label}: " + ", ".join(parts))
        tool = values.get((r["round"], "agent", "tool_accuracy", "full"))
        passed = values.get((r["round"], "agent", "pass_rate", "full"))
        write = values.get((r["round"], "agent", "write_misfire", "full"))
        if tool is not None:
            lines.append(
                f"에이전트 106건: 도구 선택 {_pct(tool)}, 통과 {_pct(passed)}, 쓰기 위반 {write:g}건"
            )
        scope = (
            "기준값을 표본과 같은 문항으로 자른 값"
            if previous is None
            else "같은 문항 표본(답 있음 60, 답 없음 20, 가족은 깨진 값 7 포함)"
        )
        full = ""
        if previous is None:
            full = " / 전체 측정: " + ", ".join(
                f"{label} 정확도 {_pct(values.get((0, name, 'accuracy', 'full')))}"
                for name, label in names
            )
        out.append(
            {
                "round": r["round"],
                "label": r.get("label", f"라운드 {r['round']}"),
                "change": r.get("change", ""),
                "why": r.get("why", ""),
                "result": f"[{scope}] " + " / ".join(lines) + full,
                "decision": r.get("decision", ""),
                "audit": r.get("audit", ""),
            }
        )
        previous = r["round"]
    return out


def team_rows(rounds: list[dict]) -> list[dict]:
    entries = [(entry.get("round"), entry) for entry in _ledger().get("team_log") or []]
    for r in rounds:
        entries += [(r["round"], entry) for entry in r.get("team_log") or []]
    return [
        {
            "id": f"{i}",
            "round": round_,
            "team": entry.get("team", ""),
            "activity": entry.get("activity", ""),
            "result": entry.get("result", ""),
            "at": entry.get("at", ""),
        }
        for i, (round_, entry) in enumerate(entries)
    ]


def status_rows() -> list[dict]:
    """지금 단계와 예산, 팀이 지키는 규칙. 규칙은 rows 의 rule 칸에 하나씩 둔다."""
    ledger = _ledger()
    state = ledger.get("state") or {}
    rows = [
        {
            "kind": "state",
            "step": state.get("step", ""),
            "current_round": state.get("current_round"),
            "budget_usd": ledger.get("budget_usd"),
            "rule": "",
        }
    ]
    rows += [
        {"kind": "rule", "step": "", "current_round": None, "budget_usd": None, "rule": rule}
        for rule in ledger.get("rules") or []
    ]
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--share", type=Path, default=DEFAULT_SHARE)
    parser.add_argument("--index", type=Path, default=None)
    args = parser.parse_args()
    out = HERE / "dash"
    out.mkdir(exist_ok=True)
    rounds = _rounds()
    metrics = metric_rows(rounds)
    metric_rows_cache = metrics
    questions = question_rows(args.share)
    documents = document_rows(args.share, _index_path(args.share, args.index))
    _write(out, "metrics", metrics)
    _write(out, "breakdown", breakdown_rows(rounds))
    _write(out, "failures", failure_rows(rounds))
    _write(out, "sources", source_rows(args.share, documents, questions))
    _write(out, "documents", documents)
    _write(out, "questions", questions)
    _write(out, "rounds", round_rows(rounds, metrics))
    _write(out, "team_log", team_rows(rounds))
    _write(out, "status", status_rows())
    _write(out, "evidence", evidence_rows(args.share))
    _write(out, "calibration", calibration_rows())
    _write(out, "detail", detail_rows(rounds))
    _write(out, "agent_detail", agent_rows(rounds))
    _write(out, "tool_changes", tool_change_rows())
    _write(out, "answer_paths", path_rows(rounds))
    _write(out, "agent_rounds", agent_round_rows(rounds))
    _write(out, "upload_mask", upload_mask_rows())
    _write(out, "upload_real", upload_real_rows())
    _write(out, "upload_ocr", upload_ocr_rows())
    _write(out, "upload_sources", upload_source_rows(args.share))
    _write(out, "final_checks", final_check_rows())
    _write(out, "experiments", experiment_rows())
    _write(out, "experiment_notes", experiment_note_rows())
    _write(out, "cost_phases", cost_phase_rows(rounds, metric_rows_cache))
    _write(out, "r7_steps", r7_step_rows())
    _write(out, "goal_rows", goal_rows())
    _write(out, "defects", defect_rows(args.share))
    _write(out, "excluded", excluded_rows(args.share))
    print("내보낸 시각", datetime.now(UTC).isoformat(timespec="seconds"))


if __name__ == "__main__":
    main()
