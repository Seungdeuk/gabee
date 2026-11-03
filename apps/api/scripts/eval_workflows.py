"""워크플로 검증(NER 이 붙은 서비스): 실제 API 흐름을 임시 SQLite + 가짜 Claude 로 돌려 '최종 요청 본문'에 개인정보가 남는지 점검한다.

- 실제 Claude·외부 API·.env·공용/개인 DB 를 쓰지 않는다. `httpx.post` 를 가짜로 바꿔 나가려는 요청 본문을 전부 캡처한다.
- 서비스 코드(app/)는 고치지 않는다. 모든 이름·번호·주소는 시험용 합성 값이다.
- 실행: apps/api 에서  PYTHONPATH=. python scripts/eval_workflows.py [섹션 ...]
  섹션: A B C D X L LIFE (생략하면 전부)
- 모델 폴더: PRIVACY_NER_MODEL_DIR(기본 apps/api/data/models/ner)
- 결과: WV_OUT(기본: 임시 폴더) 의 WORKFLOW_VERIFY_RESULTS.json (UTF-8)
"""

# ruff: noqa: E741, F841
# (일회성 검증 스크립트: 긴 시나리오 코드라 변수명·미사용 변수 경고는 두고 import 정리·서식만 맞춘다)
from __future__ import annotations

import io
import json
import logging
import math
import os
import re
import shutil
import statistics
import sys
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve()
API_DIR = HERE.parents[1]
sys.path.insert(0, str(API_DIR))

TMP = Path(tempfile.mkdtemp(prefix="wv-eval-"))
MODEL_DIR = os.environ.get("PRIVACY_NER_MODEL_DIR") or str(API_DIR / "data" / "models" / "ner")
OUT = Path(os.environ.get("WV_OUT") or (TMP / "out"))
OUT.mkdir(parents=True, exist_ok=True)

os.environ["DATABASE_URL"] = f"sqlite:///{(TMP / 'wv.db').as_posix()}"
os.environ["DATA_DIR"] = str(TMP)
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["JWT_SECRET"] = "test-only-jwt-secret-not-for-production-0123456789"
os.environ["PRIVACY_NER_MODE"] = "required"
os.environ["PRIVACY_NER_MODEL_DIR"] = MODEL_DIR
for _n in ("MAIL_BACKEND", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"):
    os.environ[_n] = ""

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app as _app_pkg  # noqa: E402
from app.main import app  # noqa: E402
from app.shared import ai_guard  # noqa: E402
from app.shared.config import settings  # noqa: E402
from app.shared.db import SessionLocal  # noqa: E402
from app.shared.privacy import ner  # noqa: E402
from tests.helpers import join_family  # noqa: E402
from tests.security_matrix_support import (  # noqa: E402
    ACCOUNT,
    CARD,
    RRN,
    FakeHttp,
    Family,
    Person,
    Recorded,
    _person,
    example_from_schema,
)

assert "gabee-17a" in str(_app_pkg.__file__), _app_pkg.__file__

SECRET_PW = "Gabee!2024x"
TOKEN_RE = re.compile(r"\[(?:PERSON|ADDR|PHONE|EMAIL)_\d+\]")
ANY_TOKEN_RE = re.compile(r"\[[A-Z]+_\d+\]")

# ----------------------------------------------------------------------------------------------------- 합성 데이터
SPECS = {
    "A": dict(
        label="A",
        names=("한가온", "윤도현", "서하준"),
        outsiders=("박서연", "최지후"),
        addrs=("서울특별시 송파구 올림픽로 300", "경기도 성남시 분당구 판교역로 235"),
        frags=("올림픽로", "판교역로"),
        phone="010-4321-8765",
        email="secret.person@example.com",
        marker="ALPHA7Q",
    ),
    "B": dict(
        label="B",
        names=("오세린", "임태오", "문하랑"),
        outsiders=("장유진", "배건우"),
        addrs=("부산광역시 해운대구 센텀중앙로 79", "대전광역시 유성구 대학로 99"),
        frags=("센텀중앙로", "대학로"),
        phone="010-2468-1357",
        email="b.family@example.org",
        marker="BRAVO7Q",
    ),
}


def raw_values(spec) -> list[str]:
    return [
        *spec["names"],
        *spec["outsiders"],
        *spec["addrs"],
        *spec["frags"],
        spec["phone"],
        spec["phone"].replace("-", ""),
        spec["email"],
    ]


def fragments_of(name: str) -> list[str]:
    """이름의 일부(성+이름 첫 글자 / 이름 두 글자): 가명화 경계가 어긋나 일부만 남는 경우를 잡는다."""
    return [name[:2], name[1:]] if len(name) >= 3 else []


def frag_values(spec) -> list[str]:
    return [f for n in (*spec["names"], *spec["outsiders"]) for f in fragments_of(n)]


def family_messages(spec) -> list[tuple[int, str]]:
    """(발화자 순번 0 소유자/1 구성원/2 셋째, 글자). 마지막 줄에 기대 값이 있다."""
    n0, n1, n2 = spec["names"]
    o0, o1 = spec["outsiders"]
    a0, a1 = spec["addrs"]
    return [
        (0, f"{spec['marker']} 토요일 오후 6시에 {a0} 에서 {o0} 이모랑 저녁 먹자"),
        (1, f"알겠어 {n0}, {o0} 이모 번호는 {spec['phone']} 맞지?"),
        (0, f"응, 메일은 {spec['email']} 이야. {n1} 은 내일 오후 3시에 병원 가야 해"),
        (2, f"{o1} 삼촌도 온대. {a1} 에서 만나서 같이 갈게"),
        (1, f"{n2} 은 학원 끝나고 와"),
        (0, "좋아 다들 토요일에 보자"),
    ]


def expected_for(spec) -> list[tuple[int, str, str]]:
    """(메시지 순번, 원문 값, 종류[PERSON/ADDR/PHONE/EMAIL])."""
    n0, n1, n2 = spec["names"]
    o0, o1 = spec["outsiders"]
    a0, a1 = spec["addrs"]
    return [
        (0, a0, "ADDR"),
        (0, o0, "PERSON"),
        (1, n0, "PERSON"),
        (1, o0, "PERSON"),
        (1, spec["phone"], "PHONE"),
        (2, spec["email"], "EMAIL"),
        (2, n1, "PERSON"),
        (3, o1, "PERSON"),
        (3, a1, "ADDR"),
        (4, n2, "PERSON"),
    ]


HIGH_RISK_TEXT = f"주민번호 {RRN} 이고 카드는 {CARD} 야 계좌 {ACCOUNT} 비밀번호는 {SECRET_PW}"
HIGH_RISK_RAW = (RRN, CARD, "4539 1488", "0343 6467", "123456-04-123456", SECRET_PW)

# ----------------------------------------------------------------------------------------------------- 결과 기록
RESULTS: dict = {
    "meta": {},
    "matrix": [],
    "details": {},
    "latency": {},
    "lifespan": {},
    "findings": [],
    "not_verified": [],
}
_RES_LOCK = threading.Lock()
LOG_LINES: list[tuple[str, str]] = []  # (현재 섹션, 로그 줄)
CUR = {"section": "-"}


class _Capture(logging.Handler):
    def emit(self, record):
        try:
            msg = record.getMessage()
            if record.exc_info:
                msg += "\n" + "".join(traceback.format_exception(*record.exc_info))
        except Exception:  # noqa: BLE001
            msg = str(record.msg)
        LOG_LINES.append((CUR["section"], f"{record.name}:{record.levelname}:{msg}"))


def rec(scn: str, item: int, status: str, evidence: str, note: str = "") -> None:
    """status: PASS / FAIL / PARTIAL / NV(미검증) / NA(해당 없음)."""
    with _RES_LOCK:
        RESULTS["matrix"].append(
            {
                "scenario": scn,
                "item": item,
                "status": status,
                "evidence": evidence[:900],
                "note": note,
            }
        )
    print(f"[{scn}#{item}] {status} {evidence[:160]}")


def finding(severity: str, title: str, repro: str, detail: str = "") -> None:
    with _RES_LOCK:
        RESULTS["findings"].append(
            {"severity": severity, "title": title, "repro": repro, "detail": detail}
        )
    print(f"!! FINDING [{severity}] {title}")


def not_verified(what: str, why: str) -> None:
    RESULTS["not_verified"].append({"what": what, "why": why})


def clip(text: str, n: int = 500) -> str:
    return text if len(text) <= n else text[:n] + "…"


# ----------------------------------------------------------------------------------------------------- 가짜 Claude
class Fake(FakeHttp):
    """FakeHttp + 구조화 출력 응답에 요청 속 토큰을 되돌려 써서 '복원'이 실제로 일어나는지 볼 수 있게 한다."""

    delay: float = 0.0
    sched_intent: str = "register"

    def __call__(self, url, *args, **kwargs):
        resp = super().__call__(url, *args, **kwargs)
        if self.delay:
            time.sleep(self.delay)
        body = kwargs.get("json") or {}
        if resp.status_code != 200 or "tools" in body:
            return resp
        schema = ((body.get("output_config") or {}).get("format") or {}).get("schema")
        if not schema:
            return resp
        custom = self.custom(body, schema)
        if custom is None:
            return resp
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": json.dumps(custom, ensure_ascii=False)}],
                "usage": {"input_tokens": 11, "output_tokens": 7},
                "stop_reason": "end_turn",
                "model": body.get("model", "claude-test"),
            },
            request=resp.request,
        )

    @staticmethod
    def _tomorrow() -> str:
        from datetime import UTC, datetime, timedelta

        return (datetime.now(UTC) + timedelta(hours=9, days=1)).date().isoformat()

    def custom(self, body: dict, schema: dict):
        props = schema.get("properties", {})
        prompt = json.dumps(body.get("messages", []), ensure_ascii=False)
        tokens = list(dict.fromkeys(TOKEN_RE.findall(prompt)))
        persons = [t for t in tokens if t.startswith("[PERSON")]
        addrs = [t for t in tokens if t.startswith("[ADDR")]
        phones = [t for t in tokens if t.startswith("[PHONE")]
        p0 = persons[0] if persons else ""
        a0 = addrs[0] if addrs else ""
        if "summary" in props:
            data = example_from_schema(schema)
            data["summary"] = "요약: " + " ".join(tokens[:12])
            data["schedule_candidates"] = [
                {
                    "title": f"{p0} 와 저녁".strip(),
                    "date": self._tomorrow(),
                    "time": "18:00",
                    "place": a0 or None,
                    "source_message_ids": [],
                }
            ]
            data["todo_candidates"] = [
                {
                    "title": "장보기",
                    "assignee_name": p0 or None,
                    "due": None,
                    "source_message_ids": [],
                }
            ]
            return data
        if "replies" in props:
            return {"replies": [f"{p0} 알겠어요", "좋아요", "그럴게요"]}
        if "topics" in props:
            return {"topics": [f"{p0} 이야기 어때?", "주말 계획은?", "맛집 이야기"]}
        if "intent" in props and "register" in props:
            reg = example_from_schema(props["register"])
            if self.sched_intent == "register":
                reg.update(
                    title=f"{p0} 와 점심".strip(),
                    date=self._tomorrow(),
                    start_time="15:00",
                    end_time="16:00",
                    kind=1,
                    place=a0,
                    memo=(phones[0] if phones else ""),
                    who_ids=[],
                    share_ids=[],
                    date_ambiguous=False,
                )
                return {
                    "intent": "register",
                    "reply": f"{p0} 와 점심 일정을 만들었어요",
                    "event_ids": [],
                    "need_wider": False,
                    "period_start": "",
                    "period_end": "",
                    "keyword": "",
                    "register": reg,
                    "target_id": "",
                    "changes": example_from_schema(props["changes"]),
                    "check_action": "",
                }
            return {
                "intent": "query",
                "reply": f"{p0} 님의 일정은 아직 없어요",
                "event_ids": [],
                "need_wider": False,
                "period_start": "",
                "period_end": "",
                "keyword": "",
                "register": reg,
                "target_id": "",
                "changes": example_from_schema(props["changes"]),
                "check_action": "",
            }
        if "suggestions" in props:
            return {
                "suggestions": [
                    {
                        "title": f"{p0} 병원 예약 확인".strip(),
                        "kind": 1,
                        "date": self._tomorrow(),
                        "place": "",
                    }
                ]
            }
        return None


FAKE = Fake()


# ----------------------------------------------------------------------------------------------------- 보조
@contextmanager
def patched(**kv):
    old = {k: getattr(settings, k) for k in kv}
    for k, v in kv.items():
        setattr(settings, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(settings, k, v)


def set_ner(mode: str, model_dir: str | None = None) -> None:
    settings.privacy_ner_mode = mode
    settings.privacy_ner_model_dir = model_dir if model_dir is not None else MODEL_DIR
    ner.reset()


def make_family(api, spec) -> Family:
    owner = _person(api, spec["names"][0], "parent")
    g = api.post(
        "/family-group/groups", json={"name": f"{spec['label']} 가족"}, headers=owner.headers
    ).json()
    member = _person(api, spec["names"][1], "child")
    third = _person(api, spec["names"][2], "child")
    join_family(api, owner.headers, g["invite_code"], member.headers)
    join_family(api, owner.headers, g["invite_code"], third.headers)
    fam = Family(owner, member, third, g["id"], g["invite_code"], spec["marker"])
    r = api.put("/family-chat/ai/settings", json={"enabled": True}, headers=owner.headers)
    assert r.status_code == 200, r.text
    return fam


def post_msg(api, who: Person, text: str, room_id: str | None = None) -> dict:
    body = {"text": text}
    if room_id:
        body["room_id"] = room_id
    r = api.post("/family-chat/messages", json=body, headers=who.headers)
    assert r.status_code == 201, r.text
    return r.json()


def seed_chat(api, fam: Family, spec, with_high_risk: bool = False) -> list[int]:
    people = (fam.owner, fam.member, fam.third)
    ids = [post_msg(api, people[i], text)["id"] for i, text in family_messages(spec)]
    if with_high_risk:
        ids.append(post_msg(api, fam.member, HIGH_RISK_TEXT)["id"])
    return ids


def payload_lines(r: Recorded) -> list[dict]:
    msgs = r.body.get("messages") or []
    content = msgs[0].get("content") if msgs else ""
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    out = []
    for line in content.splitlines():
        if line.startswith('{"id"'):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def leaks(text: str, values) -> list[str]:
    return [v for v in values if v and v in text]


def err_clean(text: str, extra=()) -> list[str]:
    """오류 응답에 있으면 안 되는 것(경로·내부 용어·개인정보)."""
    bad = [
        MODEL_DIR,
        str(TMP),
        "koelectra",
        ".onnx",
        "Traceback",
        "C:\\",
        "C:/",
        "model_card",
        "sha256",
        "ModelIntegrity",
        "RuntimeError",
        "FileNotFound",
        "onnxruntime",
        *extra,
    ]
    return [b for b in bad if b and b in text]


def sec(name: str) -> None:
    CUR["section"] = name
    print(f"\n===== 섹션 {name} =====")


def disable_limits():
    """한도·쿨다운·미리보기 속도 제한을 끈다(이 하니스가 같은 가족으로 수십 번 부르기 때문). 가드 자체는 이 평가의 대상이 아니다."""
    settings.ai_request_cooldown_seconds = 0
    settings.ai_result_cache_ttl_seconds = 0
    settings.ai_max_concurrent_requests_per_group = 32
    settings.ai_analysis_max_chars = 12000
    settings.chat_include_sensitive = True
    settings.anthropic_api_key = "test-key"
    settings.allow_legacy_token_auth = True
    ai_guard._check_cooldown = lambda *a, **k: None
    ai_guard._check_daily_limits = lambda *a, **k: None
    from app.features.family_chat import ai_service

    ai_service.PREVIEW_LIMIT = 10**9


def now_ms() -> float:
    return time.perf_counter() * 1000.0


# ============================================================================================ 시나리오 A
def scenario_a(api, fams):
    sec("A")
    spec = SPECS["A"]
    fam = fams["A"]
    ids = seed_chat(api, fam, spec, with_high_risk=True)
    expected = expected_for(spec)
    h = fam.owner.headers
    detail = {}

    for mode in ("required", "off"):
        set_ner(mode)
        if mode == "required":
            assert ner.ner_status()["active"], "NER 가 켜져 있지 않음"
        FAKE.reset()
        pv = api.post("/family-chat/ai/preview", json={}, headers=h)
        calls_pv = len(FAKE.calls)
        FAKE.reset()
        an = api.post("/family-chat/ai/analysis", json={}, headers=h)
        an_calls = FAKE.anthropic
        FAKE.reset()
        rp = api.post("/family-chat/ai/replies", json={}, headers=h)
        rp_calls = FAKE.anthropic
        FAKE.reset()
        tp = api.post("/family-chat/ai/topics", json={}, headers=h)
        tp_calls = FAKE.anthropic
        d = {
            "preview_status": pv.status_code,
            "preview_llm_calls": calls_pv,
            "analysis_status": an.status_code,
            "analysis_calls": len(an_calls),
            "replies_status": rp.status_code,
            "replies_calls": len(rp_calls),
            "topics_status": tp.status_code,
            "topics_calls": len(tp_calls),
        }
        detail[mode] = d
        if not (an.status_code == 200 and len(an_calls) == 1):
            rec("A", 1, "FAIL", f"[{mode}] 분석 흐름 실패 status={an.status_code} {an.text[:200]}")
            continue
        # 원문 잔류 / 정확도
        pay = {"analysis": an_calls[0], "replies": rp_calls[0], "topics": tp_calls[0]}
        lines_by_id = {ln["id"]: ln for ln in payload_lines(an_calls[0])}
        rows = []
        for idx, value, kind in expected:
            mid = ids[idx]
            ln = lines_by_id.get(mid)
            text = ln["text"] if ln else ""
            replaced = value not in text
            frag = kind == "PERSON" and any(f in text for f in fragments_of(value))
            tok = re.search(rf"\[{kind}_\d+\]", text) is not None and not frag
            rows.append(
                {
                    "msg": idx,
                    "kind": kind,
                    "replaced": replaced,
                    "right_token": tok,
                    "fragment_left": frag,
                }
            )
        spoken = {
            "owner": any(fam.owner.name in ln["name"] for ln in lines_by_id.values()),
        }
        speaker_leak = [
            ln["name"] for ln in lines_by_id.values() if any(n in ln["name"] for n in spec["names"])
        ]
        by_kind = {}
        for r in rows:
            k = r["kind"]
            by_kind.setdefault(k, [0, 0, 0])
            by_kind[k][0] += 1
            by_kind[k][1] += int(r["replaced"])
            by_kind[k][2] += int(r["replaced"] and r["right_token"])
        d["accuracy_by_kind"] = {
            k: {"n": v[0], "replaced": v[1], "right_token": v[2]} for k, v in by_kind.items()
        }
        d["speaker_name_leak"] = speaker_leak
        # 같은 사람 -> 같은 토큰
        p_tokens = {}
        for idx in (0, 1):  # o0 박서연 이모: 메시지 0 과 1
            t = re.findall(r"\[PERSON_\d+\]", lines_by_id[ids[idx]]["text"])
            p_tokens[idx] = t
        d["same_person_tokens_msg0_msg1"] = p_tokens
        d["raw_left"] = {k: leaks(v.text, raw_values(spec)) for k, v in pay.items()}
        d["fragment_left"] = {k: leaks(v.text, frag_values(spec)) for k, v in pay.items()}
        d["high_risk_left"] = {k: leaks(v.text, HIGH_RISK_RAW) for k, v in pay.items()}
        d["date_time_kept"] = {
            "토요일": "토요일" in an_calls[0].text,
            "오후 6시": "오후 6시" in an_calls[0].text,
            "내일 오후 3시": "내일 오후 3시" in an_calls[0].text,
        }
        d["payload_excerpt"] = [
            clip(json.dumps(ln, ensure_ascii=False), 220) for ln in list(lines_by_id.values())[:7]
        ]

        # 요청 본문에 매핑표가 없는가(항목 8)
        pt = an_calls[0].text
        mapping_like = re.findall(r"\[[A-Z]+_\d+\]\s*(?:=|:|->|→|=>)\s*\S", pt)
        d["mapping_like"] = mapping_like
        d["body_keys"] = sorted(an_calls[0].body.keys())

        if mode == "required":
            # 미리보기와 실제 일치(항목 9)
            pvj = pv.json()
            same = {}
            for feat, call in pay.items():
                pl = payload_lines(call)
                if feat == "analysis":
                    prev = [(x["id"], x["speaker"], x["text"], x["blocked"]) for x in pvj["lines"]]
                    act = [(x["id"], x["name"], x["text"], x["time"] == "") for x in pl]
                    same[feat] = prev == act
                else:
                    prev_by = {x["id"]: (x["speaker"], x["text"]) for x in pvj["lines"]}
                    act = [(x["id"], x["name"], x["text"]) for x in pl]
                    same[feat] = all(prev_by.get(i) == (n, t) for i, n, t in act) and len(act) > 0
            d["preview_matches_payload"] = same
            d["preview_masked_counts"] = pvj["masked"]
            d["preview_blocked"] = pvj["blocked_messages"]
            d["preview_resp_raw_left"] = leaks(pv.text, raw_values(spec) + list(HIGH_RISK_RAW))
            d["preview_resp_has_token_mapping"] = bool(
                re.findall(r"\[[A-Z]+_\d+\]\s*(?:=|->|→)", pv.text)
            )
            # 승인 후 새 메시지가 오면 실제 전송은 승인본과 달라질 수 있다
            newm = post_msg(
                api, fam.owner, f"{spec['marker']} 추가 {spec['outsiders'][0]} 이모 도착했대"
            )
            FAKE.reset()
            an2 = api.post("/family-chat/ai/analysis", json={}, headers=h)
            pl2 = payload_lines(FAKE.anthropic[0])
            ids_prev = {x["id"] for x in pvj["lines"]}
            ids_act = {x["id"] for x in pl2}
            d["new_message_after_preview"] = {
                "status": an2.status_code,
                "ids_in_payload_not_in_approved_preview": sorted(ids_act - ids_prev),
            }
            # 응답 복원(사용자 화면)
            aj = an.json()
            shown = json.dumps(aj, ensure_ascii=False)
            d["response_restored"] = {
                "has_owner_name": spec["names"][0] in aj["summary"]
                or any(n in aj["summary"] for n in spec["names"] + spec["outsiders"]),
                "summary": aj["summary"],
                "schedule_candidates": aj["schedule_candidates"],
                "todo_candidates": aj["todo_candidates"],
                "leftover_tokens": ANY_TOKEN_RE.findall(shown),
                "no_mapping_field": all(
                    k not in aj for k in ("mapping", "tokens", "pseudonym_map")
                ),
                "meta_privacy": aj["meta"].get("privacy"),
            }
            d["response_other_leak"] = leaks(shown, ["ALPHA7Q"] + list(HIGH_RISK_RAW))
        else:
            d["high_risk_left_off"] = {k: leaks(v.text, HIGH_RISK_RAW) for k, v in pay.items()}

    # ---- 항목 판정
    req = detail.get("required", {})
    off = detail.get("off", {})
    if req:
        raw_left = {k: v for k, v in req["raw_left"].items() if v}
        frag_left = {k: v for k, v in req["fragment_left"].items() if v}
        st1 = "FAIL" if raw_left else ("PARTIAL" if frag_left else "PASS")
        rec(
            "A",
            1,
            st1,
            f"required: 분석·답장·주제 본문 원문 전체 잔류={raw_left or '없음'}; 이름 일부(조각) 잔류={frag_left or '없음'} (값 {len(raw_values(spec))}개 + 이름 조각 검사)",
            f"off(규칙만) 잔류={ {k: v for k, v in off.get('raw_left', {}).items() if v} }",
        )
        if frag_left:
            finding(
                "중간",
                "NER 가 이름 경계를 어긋나게 잡아 이름 일부(성+첫 글자)가 Claude 로 나감",
                "시나리오 A: '박서연 이모랑 저녁 먹자' -> 전송 본문 '박서[PERSON_2]랑'(탐지 구간이 '연 이모'). 이름 전체 검사는 통과하지만 '박서' 가 남는다. 복원 시 '연 이모' 로 돌아가 사용자 화면은 정상. 재현: PRIVACY_NER_MODE=required 로 위 문장을 가족 채팅에 넣고 /family-chat/ai/analysis 호출 후 캡처된 본문 확인(eval_workflows.py A).",
                json.dumps(frag_left, ensure_ascii=False),
            )
        hr = {k: v for k, v in req["high_risk_left"].items() if v}
        rec(
            "A",
            2,
            "PASS" if not hr else "FAIL",
            f"고위험(주민번호·카드·계좌·비밀번호) 잔류={hr or '없음'}; 미리보기 차단 메시지={req['preview_blocked']}건",
        )
        acc = req["accuracy_by_kind"]
        tot = sum(v["n"] for v in acc.values())
        okc = sum(v["right_token"] for v in acc.values())
        spk = req["speaker_name_leak"]
        status = "PASS" if okc == tot and not spk else ("PARTIAL" if okc >= tot * 0.8 else "FAIL")
        rec(
            "A",
            3,
            status,
            f"기대 토큰 일치 {okc}/{tot} ({acc}); 발화자 이름 노출={spk or '없음'}; 같은 사람 토큰 일치={req['same_person_tokens_msg0_msg1']}",
            f"off 일치: { {k: (v['right_token'], v['n']) for k, v in off.get('accuracy_by_kind', {}).items()} }",
        )
        rec("A", 4, "NA", "가족 간 혼합은 시나리오 X 에서 검증")
        mp = req["mapping_like"]
        rec(
            "A",
            8,
            "PASS" if not mp and not req["preview_resp_has_token_mapping"] else "FAIL",
            f"본문 최상위 키={req['body_keys']}, 토큰=원문 대응 패턴={mp or '없음'}, 미리보기 응답 원문={req['preview_resp_raw_left'] or '없음'}",
        )
        pm = req["preview_matches_payload"]
        rec(
            "A",
            9,
            "PASS" if all(pm.values()) else "FAIL",
            f"미리보기(id·발화자·글자·차단) vs 실제 전송: {pm}. 승인 뒤 새 메시지 도착 시 승인본에 없던 id 가 실제 전송에 포함: {req['new_message_after_preview']['ids_in_payload_not_in_approved_preview']}",
            "미리보기에는 승인 결합 토큰/해시가 없다(재요청 시 다시 계산)",
        )
        if req["new_message_after_preview"]["ids_in_payload_not_in_approved_preview"]:
            finding(
                "낮음/설계",
                "미리보기 승인과 실제 전송이 결합돼 있지 않음",
                "POST /family-chat/ai/preview 후 새 메시지를 보내고 POST /family-chat/ai/analysis 호출 -> 승인본에 없는 메시지(id)가 Claude 로 전송됨(새 메시지도 같은 가명화 적용). 미리보기 응답에는 해시·만료 토큰이 없다.",
            )
        rr = req["response_restored"]
        ok_restore = (
            rr["has_owner_name"]
            and not rr["leftover_tokens"]
            and rr["no_mapping_field"]
            and not req["response_other_leak"]
        )
        rec(
            "A",
            0,
            "PASS" if ok_restore else "FAIL",
            f"사용자 화면 복원: summary={rr['summary']!r}, 후보={rr['schedule_candidates']}, 남은 토큰={rr['leftover_tokens']}",
            "항목 0 = 시나리오 고유(복원)",
        )
    if off:
        detail["off_hr"] = off.get("high_risk_left_off")
    RESULTS["details"]["A"] = detail
    # 항목 7 (응답 본문) 은 로그 섹션에서 일괄
    return detail


# ============================================================================================ 시나리오 B
def today_plus(days: int) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) + timedelta(hours=9, days=days)).date().isoformat()


def clear_suggestions():
    from sqlalchemy import delete

    from app.features.schedule.models import EventSuggestion

    with SessionLocal() as db:
        db.execute(delete(EventSuggestion))
        db.commit()


def scenario_b(api, fams):
    sec("B")
    spec = SPECS["A"]
    fam = fams["A"]
    h = fam.owner.headers
    o0, o1 = spec["outsiders"]
    a0, a1 = spec["addrs"]
    set_ner("required")
    d = {}
    # 일정 목록에 개인정보가 든 제목(규칙 마스킹 경로) 두 개
    t1 = f"{o0} 이모 병원 {spec['phone']}"
    t2 = f"{o1} 삼촌 댁 {a1}"
    for title, day in ((t1, 3), (t2, 4)):
        r = api.post(
            "/schedule/events",
            json={"title": title, "start_date": today_plus(day), "start_time": "10:00"},
            headers=h,
        )
        assert r.status_code == 201, r.text
    # B1 등록 초안
    text = f"{spec['marker']} 내일 오후 3시에 {o0} 이모랑 {a0} 에서 점심, 연락처 {spec['phone']}"
    FAKE.reset()
    FAKE.sched_intent = "register"
    r = api.post("/schedule/agent", json={"text": text, "channel": "personal"}, headers=h)
    calls = FAKE.anthropic
    d["b1"] = {"status": r.status_code, "calls": len(calls)}
    if r.status_code != 200 or len(calls) != 1:
        rec(
            "B",
            1,
            "FAIL",
            f"등록 초안 흐름 실패 status={r.status_code} calls={len(calls)} {r.text[:200]}",
        )
        RESULTS["details"]["B"] = d
        return
    pay = calls[0]
    pt = pay.text
    user_values = [
        o0,
        spec["phone"],
        spec["phone"].replace("-", ""),
        a0,
        "올림픽로",
        *fragments_of(o0),
    ]
    d["b1"]["user_text_leaks"] = leaks(pt, user_values)
    d["b1"]["member_name_leaks"] = leaks(pt, list(spec["names"]))
    d["b1"]["date_time_kept"] = {k: (k in pt) for k in ("내일 오후 3시", "[지금]")}
    prompt = pay.body["messages"][0]["content"]
    d["b1"]["prompt_user_excerpt"] = clip(
        next((ln for ln in prompt.splitlines() if "ALPHA7Q" in ln), ""), 300
    )
    rj = r.json()
    d["b1"]["response"] = {"intent": rj["intent"], "text": rj["text"], "cards": rj["cards"]}
    ev = api.get("/schedule/events", headers=h)
    evs = ev.json() if ev.status_code == 200 else []
    mine = [e for e in evs if "점심" in e["title"]]
    d["b1"]["stored"] = [
        {
            "title": e["title"],
            "place": e.get("place"),
            "memo": e.get("memo") or e.get("note"),
            "start_time": e.get("start_time"),
        }
        for e in mine
    ]
    stored_text = json.dumps(d["b1"]["stored"], ensure_ascii=False)
    d["b1"]["stored_leftover_tokens"] = ANY_TOKEN_RE.findall(stored_text)
    # 일정 목록 줄(기간 없는 질문): 제목의 이름·주소·전화가 어떻게 나가는지
    FAKE.reset()
    FAKE.sched_intent = "query"
    api.post(
        "/schedule/agent",
        json={"text": "등록된 일정 전부 알려줘", "channel": "personal"},
        headers=h,
    )
    list_pay = " ".join(c.text for c in FAKE.anthropic)
    list_prompt = FAKE.anthropic[0].body["messages"][0]["content"] if FAKE.anthropic else ""
    d["b1"]["event_title_leaks"] = leaks(
        list_pay, [o0, o1, a1, "판교역로", spec["phone"], *fragments_of(o0), *fragments_of(o1)]
    )
    d["b1"]["event_list_excerpt"] = [clip(ln, 160) for ln in list_prompt.splitlines() if "|" in ln][
        :8
    ]
    FAKE.sched_intent = "register"
    # B2 되묻기 초안(draft) 경로
    draft = {
        "title": f"{o1} 삼촌 모임",
        "date": today_plus(2),
        "start_time": "",
        "end_time": "",
        "kind": 1,
        "place": a1,
        "memo": f"전화 {spec['phone']}",
        "who_ids": [],
        "share_ids": [],
        "asks": 1,
    }
    FAKE.reset()
    r2 = api.post(
        "/schedule/agent",
        json={"text": f"{spec['marker']} 저녁 7시로 해줘", "channel": "personal", "draft": draft},
        headers=h,
    )
    c2 = FAKE.anthropic
    d["b2"] = {
        "status": r2.status_code,
        "calls": len(c2),
        "leaks": leaks(c2[0].text, [a1, "판교역로", *fragments_of(o1)]) if c2 else None,
        "draft_block_excerpt": clip(
            next(
                (
                    ln
                    for ln in (c2[0].body["messages"][0]["content"] if c2 else "").splitlines()
                    if ln.startswith("제목:")
                ),
                "",
            ),
            200,
        ),
    }
    # B3 고위험 입력(주민번호·카드·계좌·비밀번호)
    hr_rows = {}
    for label, sentence in (
        ("rrn", f"주민번호 {RRN} 일정 알려줘"),
        ("card", f"카드 {CARD} 일정 알려줘"),
        ("account", f"계좌 {ACCOUNT} 일정 알려줘"),
        ("password", f"비밀번호는 {SECRET_PW} 이니까 일정 알려줘"),
    ):
        FAKE.reset()
        rr = api.post("/schedule/agent", json={"text": sentence, "channel": "personal"}, headers=h)
        hr_rows[label] = {
            "status": rr.status_code,
            "code": rr.json().get("code") if rr.status_code >= 400 else None,
            "calls": len(FAKE.anthropic),
            "raw_in_payload": leaks(" ".join(c.text for c in FAKE.anthropic), HIGH_RISK_RAW),
        }
    d["b3_high_risk"] = hr_rows
    # 일정 제목에 고위험 값
    for title in (f"신분 {RRN}", f"계좌 {ACCOUNT}", f"비밀번호 {SECRET_PW}"):
        api.post("/schedule/events", json={"title": title, "start_date": today_plus(5)}, headers=h)
    FAKE.reset()
    api.post(
        "/schedule/agent", json={"text": "다음 주 일정 알려줘", "channel": "personal"}, headers=h
    )
    ev_pay = " ".join(c.text for c in FAKE.anthropic)
    d["b3_event_title_high_risk_in_payload"] = leaks(ev_pay, HIGH_RISK_RAW)
    # B4 조회(query) + B5 추천(suggestions, 규칙 마스킹만)
    FAKE.reset()
    FAKE.sched_intent = "query"
    rq = api.post(
        "/schedule/agent",
        json={"text": f"{o0} 이모 일정 언제야 {a0}", "channel": "personal"},
        headers=h,
    )
    d["b4_query"] = {
        "status": rq.status_code,
        "calls": len(FAKE.anthropic),
        "leaks": leaks(
            " ".join(c.text for c in FAKE.anthropic), [o0, a0, "올림픽로", *fragments_of(o0)]
        ),
        "answer": rq.json().get("text") if rq.status_code == 200 else rq.text[:200],
    }
    FAKE.sched_intent = "register"
    clear_suggestions()
    FAKE.reset()
    rs = api.get("/schedule/suggestions", headers=h)
    d["b5_suggest"] = {
        "status": rs.status_code,
        "calls": len(FAKE.anthropic),
        "leaks_names_addr_phone": leaks(
            " ".join(c.text for c in FAKE.anthropic),
            [o0, o1, a1, "판교역로", spec["phone"], *fragments_of(o0), *fragments_of(o1)],
        ),
        "ner_connected": False,
    }
    # ---- 판정
    b1 = d["b1"]
    rec(
        "B",
        1,
        "FAIL" if b1["user_text_leaks"] else ("PARTIAL" if b1["event_title_leaks"] else "PASS"),
        f"사용자 문장 경로 잔류={b1['user_text_leaks'] or '없음'}; 일정 제목(규칙 마스킹) 경로 잔류={b1['event_title_leaks'] or '없음'}; 추천(suggest) 경로 잔류={d['b5_suggest']['leaks_names_addr_phone'] or '없음'}",
        "일정 제목·추천은 NER 미연결(mask_text 규칙)",
    )
    if b1["event_title_leaks"]:
        finding(
            "중간",
            "일정 목록 제목(event_line)의 이름·주소는 NER 가 아닌 규칙 마스킹(mask_text)만 적용돼 Claude 로 나감(에이전트가 등록한 일정은 복원된 실명이 제목으로 저장돼 이후 호출마다 실명이 나감)",
            f"POST /schedule/events title='{t1}' / '{t2}' 등록 후 POST /schedule/agent. 캡처 본문의 일정 목록 줄: {b1['event_list_excerpt'][:3]}",
            json.dumps(b1["event_title_leaks"], ensure_ascii=False),
        )
    if d["b5_suggest"]["leaks_names_addr_phone"]:
        finding(
            "중간",
            "GET /schedule/suggestions(일정 추천)는 규칙 마스킹만 사용, NER·required 차단 없음",
            "일정 제목에 이름·주소가 든 일정이 있는 상태에서 GET /schedule/suggestions -> 캡처 본문에 이름 잔류",
            json.dumps(d["b5_suggest"]["leaks_names_addr_phone"], ensure_ascii=False),
        )
    hr = d["b3_high_risk"]
    hr_ok = all(
        v["status"] == 400 and v["calls"] == 0 and not v["raw_in_payload"] for v in hr.values()
    )
    ev_hr_left = d["b3_event_title_high_risk_in_payload"]
    rec(
        "B",
        2,
        "PASS" if hr_ok and not ev_hr_left else "FAIL",
        f"입력 문장 고위험: {hr}; 일정 제목에 든 고위험의 전송본문 잔류={ev_hr_left or '없음'}",
    )
    if not hr_ok:
        bad = {k: v for k, v in hr.items() if not (v["status"] == 400 and v["calls"] == 0)}
        finding(
            "높음",
            "일정 에이전트: 일부 고위험 입력(비밀번호 등)이 차단되지 않고 외부로 전송",
            f"POST /schedule/agent text='비밀번호는 {SECRET_PW} 이니까 일정 알려줘' 등. 결과: {bad}",
        )
    if ev_hr_left:
        finding(
            "높음",
            "일정 제목에 든 고위험 값이 일정 목록 줄로 Claude 에 전송됨",
            "POST /schedule/events title='비밀번호 ...' 후 POST /schedule/agent 로 아무 문장이나 보냄 -> 본문의 일정 목록",
            json.dumps(ev_hr_left, ensure_ascii=False),
        )
    ok_tokens = {
        "이모 이름": o0 not in pt and not any(f in pt for f in fragments_of(o0)),
        "주소": a0 not in pt and "올림픽로" not in pt,
        "전화": spec["phone"] not in pt,
        "날짜·시간 유지": all(b1["date_time_kept"].values()),
    }
    rec(
        "B",
        3,
        "PASS" if all(ok_tokens.values()) else "FAIL",
        f"{ok_tokens}; 전송된 사용자 문장 줄: {b1['prompt_user_excerpt']!r}",
    )
    rec("B", 4, "NA", "시나리오 X 에서 검증")
    mapping = re.findall(r"\[[A-Z]+_\d+\]\s*(?:=|->|→)", pt)
    rec(
        "B",
        8,
        "PASS" if not mapping else "FAIL",
        f"대응표 패턴={mapping or '없음'}; 본문 키={sorted(pay.body)}",
    )
    rec(
        "B",
        9,
        "NA",
        "일정 에이전트에는 미리보기·승인 단계가 없다(등록 확인 카드만 있음 — 전송 본문 미리보기는 제공되지 않음)",
    )
    wf_ok = (
        b1["response"]["intent"] == "register"
        and not b1["stored_leftover_tokens"]
        and any("점심" in x["title"] for x in b1["stored"])
    )
    rec(
        "B",
        0,
        "PASS" if wf_ok else "FAIL",
        f"등록 결과 응답={b1['response']['text']!r}, 저장된 일정={b1['stored']}, 남은 토큰={b1['stored_leftover_tokens']}; draft 경로 status={d['b2']['status']} calls={d['b2']['calls']} 잔류={d['b2']['leaks']}; query 경로 status={d['b4_query']['status']} 잔류={d['b4_query']['leaks']}",
    )
    RESULTS["details"]["B"] = d


# ============================================================================================ 시나리오 C
SPECS["C"] = dict(
    label="C",
    names=("정하윤", "고민재", "남서윤"),
    outsiders=("홍길순", "이도윤"),
    addrs=("서울특별시 마포구 월드컵북로 396", "인천광역시 연수구 컨벤시아대로 165"),
    frags=("월드컵북로", "컨벤시아대로"),
    phone="010-9988-7766",
    email="doyoon.lee@example.com",
    marker="CHARLIE7Q",
)


def big_jpeg() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (900, 700), (240, 240, 240)).save(out, format="JPEG")
    return out.getvalue()


def doc_payload(api, h, plan_query="보험", message="보험 문서 찾아줘") -> list[Recorded]:
    FAKE.reset()
    FAKE.tool_plan = [("search_knowledge", {"query": plan_query})]
    r = api.post("/ai-assistant/chat", json={"message": message}, headers=h)
    assert r.status_code == 200, (r.status_code, r.text[:200])
    return FAKE.anthropic


def scenario_c(api, fams):
    sec("C")
    from app.features.ai_assistant import files as ai_files
    from app.features.ai_assistant.ingest.converters import OcrLine

    spec = SPECS["C"]
    fam = make_family(api, spec)
    h = fam.owner.headers
    o0, o1 = spec["outsiders"]
    a0, a1 = spec["addrs"]
    lines = [
        f"성명 {o1}",
        f"주민등록번호 {RRN}",
        f"전화 {spec['phone']}",
        f"주소 {a0}",
        f"이메일 {spec['email']}",
        f"담당자 {o0}",
        f"계좌 {ACCOUNT}",
        f"보험 증권 안내 {spec['marker']}",
        f"보험금 수령인 {spec['names'][2]} 님 {a1}",
        f"비밀번호 {SECRET_PW}",
    ]

    class FakeOcr:
        def read(self, image):
            return [OcrLine(t, 0.97) for t in lines]

    ai_files.processors.ocr = FakeOcr()
    d = {}
    watch = [
        o0,
        o1,
        spec["names"][2],
        spec["phone"],
        spec["email"],
        a0,
        a1,
        "월드컵북로",
        "컨벤시아대로",
        *HIGH_RISK_RAW,
    ]
    body_md = ""
    try:
        r = api.post(
            "/ai-assistant/files", files={"file": ("scan.jpg", big_jpeg(), "image/jpeg")}, headers=h
        )
        d["upload_status"] = r.status_code
        item_id = r.json()["id"]
        it = api.get(f"/ai-assistant/knowledge/items/{item_id}", headers=h)
        item = it.json() if it.status_code == 200 else {}
        body_md = item.get("body_md", "")
        d["stored_item"] = {k: item.get(k) for k in ("kind_label", "sensitivity", "title")}
        d["stored_body_excerpt"] = clip(body_md, 700)
    finally:
        ai_files.processors.ocr = None
    stored_left = leaks(body_md, watch)
    d["stored_left"] = stored_left
    # 문서 QA 경로(채팅 도구) — include_sensitive True/False
    for inc in (True, False):
        with patched(chat_include_sensitive=inc):
            calls = doc_payload(api, h)
            txt = " ".join(c.text for c in calls)
            d[f"chat_include_{inc}"] = {
                "calls": len(calls),
                "marker_in_payload": spec["marker"] in txt,
                "raw_left": leaks(txt, watch),
                "tool_result_excerpt": clip(
                    next((c.text for c in calls if "tool_result" in c.text), ""), 900
                ),
            }
    # 일부러 sensitive 로 표시한 문서(API 직접 입력) — 민감 문서 포함 설정
    sens_marker = "ZZSENSC"
    rr = api.post(
        "/ai-assistant/knowledge/items",
        json={"kind_label": "보험", "title": "주민번호 문서", "body_md": f"보험 주민번호 {RRN}"},
        headers=h,
    )
    d["items_api_with_rrn"] = {"status": rr.status_code, "code": rr.json().get("code")}
    body = f"{sens_marker} 보험 보장 내용 담당자 {spec['phone']} 메일 {spec['email']}"
    sr = api.post(
        "/ai-assistant/knowledge/items",
        json={
            "kind_label": "보험",
            "title": "민감 보험 문서",
            "body_md": body,
            "sensitivity": "sensitive",
        },
        headers=h,
    )
    d["sens_item_status"] = sr.status_code
    for inc in (True, False):
        with patched(chat_include_sensitive=inc):
            calls = doc_payload(api, h, plan_query="보험", message="보험 보장 내용 찾아줘")
            txt = " ".join(c.text for c in calls)
            d[f"sens_include_{inc}"] = {
                "marker_in_payload": sens_marker in txt,
                "raw_left": leaks(txt, [spec["phone"], spec["email"]]),
                "tool_result_excerpt": clip(
                    next((c.text for c in calls if "tool_result" in c.text), "")[-900:], 900
                ),
            }
    # 문서 QA (knowledge/ask)
    FAKE.reset()
    ra = api.post(
        "/ai-assistant/knowledge/ask", json={"question": "보험 증권 내용 알려줘"}, headers=h
    )
    txt = " ".join(c.text for c in FAKE.anthropic)
    d["knowledge_ask"] = {
        "status": ra.status_code,
        "calls": len(FAKE.anthropic),
        "raw_left": leaks(txt, watch),
    }
    # ---- 판정
    ci = d["chat_include_True"]
    rl = ci["raw_left"]
    rec(
        "C",
        1,
        "PASS" if not rl else "FAIL",
        f"OCR 문서가 문서 QA(채팅 검색 도구)로 갈 때 Claude 본문 원문 잔류={rl or '없음'}; knowledge/ask 잔류={d['knowledge_ask']['raw_left'] or '없음'}; 저장 본문 잔류={stored_left or '없음'}",
        "문서 경로는 NER 미적용(규칙 mask_text 만). 증명서 OCR 자체는 다른 에이전트 담당",
    )
    names_left = [
        v for v in rl if v in (o0, o1, spec["names"][2], a0, a1, "월드컵북로", "컨벤시아대로")
    ]
    if names_left:
        finding(
            "중간",
            "문서(OCR) 경로: 라벨 없는 이름·주소가 규칙 마스킹으로 가려지지 않고 Claude 에 전송(NER 미적용)",
            f"가짜 OCR 글자로 사진 업로드(POST /ai-assistant/files) 후 POST /ai-assistant/chat(tool search_knowledge). 캡처 본문 잔류: {names_left}. 도구 결과 발췌: {ci['tool_result_excerpt'][:300]}",
        )
    hr_left = [v for v in rl if v in HIGH_RISK_RAW]
    rec(
        "C",
        2,
        "PASS" if not hr_left else "FAIL",
        f"OCR 고위험(주민번호·계좌·비밀번호) 전송본문 잔류={hr_left or '없음'}",
    )
    if hr_left:
        finding("높음", "문서(OCR) 경로로 고위험 값이 Claude 본문에 남음", f"잔류: {hr_left}")
    t, f = d["sens_include_True"], d["sens_include_False"]
    ok5 = t["marker_in_payload"] and not f["marker_in_payload"]
    rec(
        "C",
        5,
        "PASS" if ok5 else "FAIL",
        f"CHAT_INCLUDE_SENSITIVE=true: 민감 문서 근거 포함={t['marker_in_payload']}(설정상 기대 true), false: 포함={f['marker_in_payload']}(기대 false); 포함 시 원문 잔류={t['raw_left'] or '없음'}",
    )
    if t["raw_left"]:
        finding(
            "중간",
            "POST /ai-assistant/knowledge/items 로 직접 넣은 문서의 개인정보 원문이 채팅 도구 결과로 Claude 에 전송(기존 보안 시험의 알려진 결함과 같은 현상)",
            "문서 입력 API 에 전화·이메일·주민번호가 든 body_md 를 넣고 /ai-assistant/chat 로 검색. (고위험 가드는 /ai-assistant/chat 입력에만 적용)",
            json.dumps(t["raw_left"], ensure_ascii=False),
        )
    rec(
        "C",
        6,
        "PASS" if not rl else "FAIL",
        f"가짜 OCR 글자 10줄(성명·주민번호·전화·주소·이메일·담당자·계좌·수령인·비밀번호) 중 최종 본문 잔류={rl or '없음'}; 보관본문 잔류={stored_left or '없음'}",
        "라벨 없는 이름은 규칙이 못 가림" if names_left else "",
    )
    mp = re.findall(r"\[[A-Z]+_\d+\]\s*(?:=|->|→)", ci["tool_result_excerpt"])
    rec(
        "C",
        8,
        "PASS" if not mp else "FAIL",
        f"대응표 패턴={mp or '없음'}(문서 경로는 가명화 토큰을 쓰지 않음)",
    )
    rec("C", 9, "NA", "문서 QA 경로에는 미리보기·승인이 없다")
    rec("C", 4, "NA", "시나리오 X 에서 검증")
    RESULTS["details"]["C"] = d


# ============================================================================================ 시나리오 D
def build_entries(api, fam, spec):
    h = fam.owner.headers
    o0, o1 = spec["outsiders"]
    a0 = spec["addrs"][0]
    phone = spec["phone"]

    def analysis():
        return api.post("/family-chat/ai/analysis", json={}, headers=h)

    def replies():
        return api.post("/family-chat/ai/replies", json={}, headers=h)

    def topics():
        return api.post("/family-chat/ai/topics", json={}, headers=h)

    def preview():
        return api.post("/family-chat/ai/preview", json={}, headers=h)

    def schedule_agent():
        FAKE.sched_intent = "register"
        text = f"내일 오후 3시에 {o0} 이모랑 {a0} 에서 점심 {phone}"
        return api.post("/schedule/agent", json={"text": text, "channel": "personal"}, headers=h)

    def schedule_suggest():
        clear_suggestions()
        return api.get("/schedule/suggestions", headers=h)

    def assistant_chat():
        return api.post(
            "/ai-assistant/chat",
            json={"message": f"{o0} 이모랑 {a0} 에서 만나기로 했어. 연락처 {phone}"},
            headers=h,
        )

    def knowledge_ask():
        return api.post(
            "/ai-assistant/knowledge/ask",
            json={"question": f"{o0} 이모 {a0} 문서 알려줘"},
            headers=h,
        )

    def billing_agent():
        return api.post(
            "/billing/agent/chat",
            json={"message": f"{o0} 이모한테 {phone} 로 보낸 돈 알려줘"},
            headers=h,
        )

    def care_agent():
        return api.post(
            "/care/agent/chat", json={"message": f"{o0} 이모 {a0} 근처 돌봄 알려줘"}, headers=h
        )

    def main_to_family_agent():
        FAKE.tool_plan = [
            ("ask_family_chat", {"question": "토요일 약속 알려줘"}),
            ("search_messages", {"query": "토요일"}),
        ]
        return api.post(
            "/ai-assistant/chat", json={"message": f"{o0} 이모랑 한 토요일 약속 알려줘"}, headers=h
        )

    return {
        "family_analysis": (analysis, True),
        "family_replies": (replies, True),
        "family_topics": (topics, True),
        "family_preview": (preview, True),
        "schedule_agent": (schedule_agent, True),
        "schedule_suggestions": (schedule_suggest, False),
        "assistant_chat": (assistant_chat, False),
        "knowledge_ask": (knowledge_ask, False),
        "billing_agent": (billing_agent, False),
        "care_agent": (care_agent, False),
        "main_chat_to_family_agent": (main_to_family_agent, "partial"),
    }


@contextmanager
def engine_patch(kind: str | None):
    """kind: None / 'infer_error' / 'timeout' — 로드된 엔진의 추론을 실패시킨다(메시지에 합성 이름·경로를 넣어 오류 응답·로그 누출도 본다)."""
    if kind is None:
        yield
        return
    orig = ner.NerEngine.analyze_many

    def boom(self, texts, deadline=None, *a, **k):
        if kind == "timeout":
            raise ner.NerTimeout()
        raise RuntimeError(
            f"추론 실패 박서연 010-4321-8765 C:\\secret\\model\\x.onnx {texts[0][:20] if texts else ''}"
        )

    ner.NerEngine.analyze_many = boom
    try:
        yield
    finally:
        ner.NerEngine.analyze_many = orig


def make_tampered_dir() -> Path:
    dst = TMP / "tampered"
    if dst.exists():
        return dst
    dst.mkdir()
    for name in ("model.onnx", "tokenizer.json", "labels.json", "model_card.json"):
        shutil.copy2(Path(MODEL_DIR) / name, dst / name)
    path = dst / "model.onnx"
    data = bytearray(path.read_bytes())
    data[1000] ^= 0x01  # 한 바이트만 바꾼다(sha256 불일치)
    path.write_bytes(bytes(data))
    return dst


def run_config(api, fam, spec, label, mode, model_dir, patch_kind=None):
    CUR["section"] = f"D:{label}"
    set_ner(mode, model_dir)
    rows = {}
    with engine_patch(patch_kind):
        if mode != "off" and patch_kind is not None:
            # 추론 실패 유형은 엔진이 먼저 로드돼 있어야 의미가 있다
            ner.ner_status()
        for name, (fn, connected) in build_entries(api, fam, spec).items():
            FAKE.reset()
            FAKE.sched_intent = "register"
            try:
                r = fn()
                status, text = r.status_code, r.text
                try:
                    code = r.json().get("code") if status >= 400 else None
                except ValueError:
                    code = None
            except Exception as e:  # noqa: BLE001
                status, text, code = -1, f"{type(e).__name__}", None
            pay = " ".join(c.text for c in FAKE.anthropic)
            rows[name] = {
                "connected": connected,
                "status": status,
                "code": code,
                "calls": len(FAKE.anthropic),
                "unmasked_outsiders": leaks(
                    pay,
                    [*spec["outsiders"], *[f for n in spec["outsiders"] for f in fragments_of(n)]],
                ),
                "member_names_in_payload": leaks(pay, spec["names"]),
                "addr_phone_in_payload": leaks(pay, [*spec["addrs"], spec["phone"]]),
                "high_risk_in_payload": leaks(pay, HIGH_RISK_RAW),
                "body_dirty": err_clean(
                    text, extra=[*spec["outsiders"], *spec["names"], spec["phone"], "박서연"]
                )
                if status >= 400
                else [],
                "body": clip(text, 160) if status >= 400 else "",
            }
    rows["_ner_status"] = ner.ner_status() if mode != "off" else {"mode": "off"}
    return rows


def scenario_d(api, fams):
    sec("D")
    spec = SPECS["A"]
    fam = make_family(api, spec)
    seed_chat(api, fam, spec, with_high_risk=True)
    tampered = make_tampered_dir()
    nomodel = TMP / "nomodel"
    nomodel.mkdir(exist_ok=True)
    cfgs = [
        ("required/ok", "required", MODEL_DIR, None),
        ("required/missing", "required", str(nomodel), None),
        ("required/tampered", "required", str(tampered), None),
        ("required/infer_error", "required", MODEL_DIR, "infer_error"),
        ("required/timeout", "required", MODEL_DIR, "timeout"),
        ("auto/ok", "auto", MODEL_DIR, None),
        ("auto/missing", "auto", str(nomodel), None),
        ("auto/tampered", "auto", str(tampered), None),
        ("auto/infer_error", "auto", MODEL_DIR, "infer_error"),
        ("off/ok", "off", MODEL_DIR, None),
        ("off/missing", "off", str(nomodel), None),
    ]
    table = {}
    for label, mode, mdir, kind in cfgs:
        table[label] = run_config(api, fam, spec, label, mode, mdir, kind)
        print(
            label,
            {
                k: (v["status"], v["calls"])
                for k, v in table[label].items()
                if not k.startswith("_")
            },
        )
    # 권한 실패(required + 정상 모델): 가족 없는 사용자 / 잘못된 토큰 / 토큰 없음 -> Claude 호출 0
    set_ner("required")
    CUR["section"] = "D:auth"
    loner = _person(api, "혼자", "child")
    auth_rows = {}
    for who, hdr in (
        ("no_family_user", loner.headers),
        ("bad_token", {"X-Gyeot-Token": "nope"}),
        ("no_token", {}),
    ):
        for name, (method, path, body) in {
            "family_analysis": ("POST", "/family-chat/ai/analysis", {}),
            "family_preview": ("POST", "/family-chat/ai/preview", {}),
            "schedule_agent": (
                "POST",
                "/schedule/agent",
                {"text": "내일 일정", "channel": "personal"},
            ),
            "assistant_chat": ("POST", "/ai-assistant/chat", {"message": "안녕"}),
            "billing_agent": ("POST", "/billing/agent/chat", {"message": "안녕"}),
        }.items():
            FAKE.reset()
            r = api.request(method, path, json=body, headers=hdr)
            auth_rows[f"{who}:{name}"] = {
                "status": r.status_code,
                "code": (
                    r.json().get("code")
                    if r.headers.get("content-type", "").startswith("application/json")
                    and isinstance(r.json(), dict)
                    else None
                ),
                "calls": len(FAKE.anthropic),
            }
    # NER 이 모델 파일 없음/변조여도 권한 실패가 먼저(401/403)인지: required + missing
    set_ner("required", str(nomodel))
    FAKE.reset()
    r = api.post("/family-chat/ai/analysis", json={}, headers={"X-Gyeot-Token": "nope"})
    auth_rows["required_missing:bad_token:family_analysis"] = {
        "status": r.status_code,
        "calls": len(FAKE.anthropic),
    }
    set_ner("required")
    table["_auth"] = auth_rows
    RESULTS["details"]["D"] = table

    # ---- 판정
    connected = [n for n, (_, c) in build_entries(api, fam, spec).items() if c is True]
    unconnected = [n for n, (_, c) in build_entries(api, fam, spec).items() if c is False]
    partial_entries = ["main_chat_to_family_agent"]
    bad_closed = []
    ok_closed = []
    for label in (
        "required/missing",
        "required/tampered",
        "required/infer_error",
        "required/timeout",
    ):
        for n in connected:
            row = table[label][n]
            good = (
                row["status"] == 503 and row["code"] == "privacy_unavailable" and row["calls"] == 0
            )
            (ok_closed if good else bad_closed).append(
                (label, n, row["status"], row["code"], row["calls"])
            )
    rec(
        "D",
        10,
        "PASS" if not bad_closed else "FAIL",
        f"required + 모델 없음/변조/추론오류/시간초과 x NER 연결 입구 {connected}: 정상 차단(503 privacy_unavailable, Claude 호출 0) {len(ok_closed)}건, 위반 {bad_closed or '없음'}",
    )
    # 일부 연결(메인 채팅 -> 가족 채팅 에이전트): 첫 호출이 사용자 질문과 함께 나간다
    mp = {
        l: table[l]["main_chat_to_family_agent"]
        for l in ("required/missing", "required/tampered", "required/infer_error")
    }
    rec(
        "D",
        10,
        "PARTIAL",
        f"메인 채팅 -> 가족 채팅 에이전트 경로(required+NER 실패): { ({l: (v['status'], v['code'], v['calls']) for l, v in mp.items()}) }. 도구 단계에서 차단되지만 그 전에 오케스트레이터 호출이 mask_text 규칙만 거친 사용자 질문과 함께 이미 나간다(호출 수 참조)",
    )
    finding(
        "낮음",
        "메인 AI 채팅 -> 탭 에이전트 도구 호출에서 required 의 503 privacy_unavailable 이 삼켜져 사용자에게 200 으로 보임",
        f"모델 폴더를 비우고 PRIVACY_NER_MODE=required 로 POST /ai-assistant/chat(첫 응답이 ask_family_chat 도구 호출). 결과 status={mp['required/missing']['status']} Claude 호출={mp['required/missing']['calls']}회. 원인: knowledge/rag_chat.py 의 `except (ValueError, ApiError, TypeError)` 가 PrivacyUnavailable(ApiError 하위)을 도구 오류로 처리. 가족 대화 데이터는 전송되지 않지만(에이전트가 실행되지 않음) 사용자는 보호 엔진 장애를 알 수 없고 오케스트레이터에 질문(규칙 마스킹만)이 이미 나간다.",
    )
    raw_unconn = {
        n: sorted(
            set(
                table["required/ok"][n]["addr_phone_in_payload"]
                + table["required/ok"][n]["unmasked_outsiders"]
            )
        )
        for n in unconnected
        if table["required/ok"][n]["addr_phone_in_payload"]
        or table["required/ok"][n]["unmasked_outsiders"]
    }
    if raw_unconn:
        finding(
            "높음",
            "NER(가명화 게이트웨이) 미연결 AI 입구에서 사용자가 입력한 이름·주소·전화 원문이 Claude 본문에 그대로 나감(정상 모델·required 에서도)",
            f"required + 정상 NER 에서 POST /ai-assistant/chat, /ai-assistant/knowledge/ask, /billing/agent/chat, /care/agent/chat 에 '박서연 이모랑 서울특별시 송파구 올림픽로 300 에서 만나기로 했어. 연락처 010-4321-8765' 류 문장을 보내고 캡처. 입구별 잔류: {raw_unconn}. 정산·돌봄 에이전트 시스템 프롬프트에는 요청자 실명도 포함(member_names_in_payload). 기존 tests/test_security_matrix.py 의 known_defect 와 같은 현상.",
        )
    un = {
        n: {
            l: (table[l][n]["status"], table[l][n]["calls"])
            for l in ("required/missing", "required/tampered")
        }
        for n in unconnected
    }
    called = [n for n in unconnected if table["required/missing"][n]["calls"] > 0]
    if called:
        rec(
            "D",
            10,
            "PARTIAL",
            f"NER 미연결 입구는 required+모델 없음에서도 Claude 를 호출한다(규칙 마스킹만): {un}",
            "설계상 NER 를 쓰지 않는 경로 — required 가 보호를 보장하지 못하는 범위",
        )
        finding(
            "중간",
            "PRIVACY_NER_MODE=required 가 일부 AI 입구에서는 fail-closed 가 아님(NER 미연결 경로)",
            f"모델 폴더를 비우고 required 로 실행 -> 다음 입구는 503 없이 Claude 호출: {called} (일정 추천 GET /schedule/suggestions, AI 비서 채팅/문서질문, 정산·돌봄 에이전트). 이름·주소는 규칙 마스킹(mask_text)만 거치고 NER 보호가 없다.",
        )
    # auto/off 동작
    auto_rows = {}
    for label in ("auto/missing", "auto/tampered", "auto/infer_error"):
        for n in connected:
            row = table[label][n]
            exp_calls = 0 if n == "family_preview" else 1
            auto_rows[(label, n)] = row["status"] == 200 and row["calls"] == exp_calls
    auto_ok = all(auto_rows.values())
    leaks_auto = sorted(
        {
            x
            for l in ("auto/missing", "auto/tampered", "auto/infer_error")
            for n in connected
            for x in table[l][n]["unmasked_outsiders"]
        }
    )
    member_leak = sorted(
        {
            x
            for l in ("auto/missing", "auto/tampered", "auto/infer_error")
            for n in connected
            for x in table[l][n]["member_names_in_payload"]
        }
    )
    rec(
        "D",
        1,
        "PARTIAL" if auto_ok and leaks_auto else ("PASS" if auto_ok else "FAIL"),
        f"auto + NER 실패: 연결 입구 동작(200, 호출 1회/미리보기 0회)={'모두 정상' if auto_ok else {k: v for k, v in auto_rows.items() if not v}}; 비구성원 이름·조각 잔류={leaks_auto or '없음'}(규칙만으로는 사전에 없는 이름을 못 가림); 구성원 이름 잔류={member_leak or '없음'}(대상 입구: 일정 에이전트의 일정 목록 제목 경로 — 에이전트가 등록하면 복원된 실명이 제목으로 저장되고 이후 호출에서 규칙 마스킹만 거쳐 나감)",
        "auto 는 의도된 열화(경고 1회) — 이름 보호 수준이 NER 정상 때보다 낮다",
    )
    off_ok = all(
        table["off/ok"][n]["status"] == 200
        and table["off/ok"][n]["calls"] == (0 if n == "family_preview" else 1)
        for n in connected
    )
    leaks_off = sorted({x for n in connected for x in table["off/ok"][n]["unmasked_outsiders"]})
    rec(
        "D",
        0,
        "PASS" if off_ok and auto_ok else "FAIL",
        f"off: 연결 입구 정상(이전과 동일 규칙 동작)={off_ok}, 비구성원 이름 잔류={leaks_off or '없음'}; required+정상 모델: { {n: (table['required/ok'][n]['status'], table['required/ok'][n]['calls']) for n in connected} }",
    )
    hr_left = sorted(
        {
            x
            for l, rows in table.items()
            if not l.startswith("_")
            for n, r_ in rows.items()
            if not n.startswith("_")
            for x in r_["high_risk_in_payload"]
        }
    )
    rec(
        "D",
        2,
        "PASS" if not hr_left else "FAIL",
        f"모든 모드·실패 유형에서 고위험(주민번호·카드·계좌·비밀번호) 전송본문 잔류={hr_left or '없음'}(가족 대화 7번 메시지는 차단 자리표시)",
    )
    dirty = [
        (l, n, r_["body_dirty"])
        for l, rows in table.items()
        if not l.startswith("_")
        for n, r_ in rows.items()
        if not n.startswith("_") and r_["body_dirty"]
    ]
    rec(
        "D",
        7,
        "PASS" if not dirty else "FAIL",
        f"실패 응답 본문(경로·내부 용어·합성 개인정보) 노출={dirty or '없음'}; 예: {table['required/tampered']['family_analysis']['body']}",
    )
    auth_bad = {k: v for k, v in auth_rows.items() if v["calls"] != 0 or v["status"] == 503}
    rec(
        "D",
        4,
        "PASS" if not auth_bad else "FAIL",
        f"권한 실패(가족 없음·잘못된 토큰·토큰 없음) x 5 입구: Claude 호출 0, 상태 { {k: v['status'] for k, v in auth_rows.items()} }; 위반={auth_bad or '없음'}",
    )
    # 변조 모델: 실제로 sha256 불일치로 막혔는지 확인
    rec(
        "D",
        10,
        "PASS"
        if table["required/tampered"]["family_analysis"]["status"] == 503
        and table["auto/tampered"]["family_analysis"]["status"] == 200
        else "FAIL",
        "모델 파일 한 바이트 변조(sha256 불일치): required 503 차단 / auto 규칙만으로 계속 동작",
    )


# ============================================================================================ 시나리오 X (가족 간 격리·동시 요청)
def scenario_x(api, fams):
    sec("X")
    set_ner("required")
    assert ner.ner_status()["active"]
    sa, sb = SPECS["A"], SPECS["B"]
    fa = make_family(api, sa)
    fb = make_family(api, sb)
    seed_chat(api, fa, sa)
    seed_chat(api, fb, sb)
    d = {}
    # B 의 1:1 방·일정
    room_b = api.post(
        "/family-chat/rooms/direct", json={"user_id": fb.member.id}, headers=fb.owner.headers
    ).json()
    dm_b = post_msg(api, fb.owner, f"{sb['marker']} 비밀 1대1 {sb['outsiders'][0]}", room_b["id"])
    ev_b = api.post(
        "/schedule/events",
        json={"title": f"{sb['marker']} {sb['outsiders'][1]} 일정", "start_date": today_plus(2)},
        headers=fb.owner.headers,
    ).json()
    api.post(
        "/schedule/events",
        json={"title": f"{sa['marker']} 우리집 행사", "start_date": today_plus(2)},
        headers=fa.owner.headers,
    )
    ha = fa.owner.headers
    cross = {}
    r = api.get("/family-chat/messages", params={"room_id": room_b["id"]}, headers=ha)
    cross["A_reads_B_room"] = (r.status_code, bool(leaks(r.text, [sb["marker"], *sb["outsiders"]])))
    r = api.post(
        "/family-chat/messages", json={"text": "침입", "room_id": room_b["id"]}, headers=ha
    )
    cross["A_posts_B_room"] = (r.status_code, bool(leaks(r.text, [sb["marker"]])))
    r = api.get("/family-chat/rooms", headers=ha)
    cross["A_room_list_has_B_room"] = (r.status_code, room_b["id"] in r.text)
    r = api.get(f"/schedule/events/{ev_b['id']}/sharing", headers=ha)
    cross["A_reads_B_event_sharing"] = (r.status_code, bool(leaks(r.text, [sb["marker"]])))
    r = api.patch(f"/schedule/events/{ev_b['id']}", json={"title": "해킹"}, headers=ha)
    cross["A_patches_B_event"] = (r.status_code, "해킹" in r.text)
    r = api.post(
        "/schedule/agent/confirm",
        json={"action": {"type": "delete", "event_id": ev_b["id"]}},
        headers=ha,
    )
    cross["A_agent_deletes_B_event"] = (r.status_code, False)
    still = api.get("/schedule/events", headers=fb.owner.headers).json()
    cross["B_event_still_exists_unchanged"] = any(
        e["id"] == ev_b["id"] and "해킹" not in e["title"] for e in still
    )
    FAKE.reset()
    r = api.post(
        "/family-chat/ai/analysis", json={"after_id": dm_b["id"] - 1, "limit": 200}, headers=ha
    )
    pa = " ".join(c.text for c in FAKE.anthropic)
    cross["A_analysis_with_B_message_id_as_after_id"] = (
        r.status_code,
        bool(
            leaks(
                pa + r.text,
                [
                    sb["marker"],
                    *sb["names"],
                    *sb["outsiders"],
                    *sb["addrs"],
                    sb["phone"],
                    sb["email"],
                ],
            )
        ),
    )
    FAKE.reset()
    r = api.post("/family-chat/ai/analysis", json={"group_id": fb.group_id}, headers=ha)
    pa2 = " ".join(c.text for c in FAKE.anthropic)
    cross["A_analysis_body_group_id_B"] = (
        r.status_code,
        bool(leaks(pa2 + r.text, [sb["marker"], *sb["names"], *sb["outsiders"]])),
    )
    FAKE.reset()
    FAKE.sched_intent = "query"
    r = api.post(
        "/schedule/agent", json={"text": "등록된 일정 전부 알려줘", "channel": "family"}, headers=ha
    )
    pa3 = " ".join(c.text for c in FAKE.anthropic)
    cross["A_schedule_agent_sees_B_events"] = (
        r.status_code,
        bool(leaks(pa3 + r.text, [sb["marker"], *sb["outsiders"]])),
    )
    FAKE.sched_intent = "register"
    d["cross_access"] = cross
    denied = (
        "A_reads_B_room",
        "A_posts_B_room",
        "A_reads_B_event_sharing",
        "A_patches_B_event",
        "A_agent_deletes_B_event",
    )
    cross_bad = {
        k: v
        for k, v in cross.items()
        if (isinstance(v, tuple) and (v[1] or (k in denied and v[0] == 200)))
        or (k == "B_event_still_exists_unchanged" and v is not True)
    }
    # --- 동시 요청
    ops = ["analysis", "replies", "topics", "preview", "schedule"]
    plan = []
    for i in range(120):
        plan.append(("A" if i % 2 == 0 else "B", ops[(i // 2) % len(ops)], i))
    fam_of = {"A": (fa, sa), "B": (fb, sb)}
    results = []
    gate = threading.Barrier(16)

    def work(item):
        key, op, i = item
        fam, spec = fam_of[key]
        h = fam.owner.headers
        try:
            if i < 16:
                gate.wait(timeout=20)
        except threading.BrokenBarrierError:
            pass
        if op == "schedule":
            text = f"{spec['marker']} 내일 오후 3시에 {spec['outsiders'][0]} 이모랑 {spec['addrs'][0]} 에서 점심 {spec['phone']}"
            r = api.post("/schedule/agent", json={"text": text, "channel": "personal"}, headers=h)
        else:
            r = api.post(f"/family-chat/ai/{op}", json={}, headers=h)
        return {"fam": key, "op": op, "status": r.status_code, "text": r.text}

    FAKE.reset()
    FAKE.sched_intent = "register"
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=16) as ex:
        results = list(ex.map(work, plan))
    d["concurrent_seconds"] = round(time.perf_counter() - t0, 2)
    other = {"A": sb, "B": sa}
    own = {"A": sa, "B": sb}
    mixes, bad_status, unrestored, missing_own = [], [], [], []
    for res in results:
        spec_o = other[res["fam"]]
        foreign = leaks(
            res["text"],
            [
                spec_o["marker"],
                *spec_o["names"],
                *spec_o["outsiders"],
                *spec_o["addrs"],
                spec_o["phone"],
                spec_o["email"],
            ],
        )
        if foreign:
            mixes.append((res["fam"], res["op"], foreign))
        if res["status"] != 200:
            bad_status.append((res["fam"], res["op"], res["status"], res["text"][:120]))
            continue
        if res["op"] in ("analysis", "replies", "topics") and ANY_TOKEN_RE.findall(res["text"]):
            unrestored.append((res["fam"], res["op"], ANY_TOKEN_RE.findall(res["text"])))
        if res["op"] in ("analysis", "replies", "topics"):
            if not leaks(
                res["text"], list(own[res["fam"]]["names"]) + list(own[res["fam"]]["outsiders"])
            ):
                missing_own.append((res["fam"], res["op"]))
    # 전송 본문 쪽: 각 호출은 정확히 한 가족의 표식만 가져야 한다
    pay_mix, pay_nomark = [], []
    for c in FAKE.anthropic:
        has_a = sa["marker"] in c.text
        has_b = sb["marker"] in c.text
        if has_a and has_b:
            pay_mix.append("두 표식")
            continue
        if not (has_a or has_b):
            pay_nomark.append(clip(c.text, 80))
            continue
        spec_o = sb if has_a else sa
        f = leaks(
            c.text,
            [
                *spec_o["names"],
                *spec_o["outsiders"],
                *spec_o["addrs"],
                spec_o["phone"],
                spec_o["email"],
            ],
        )
        if f:
            pay_mix.append(f)
    # 일정(등록) 저장값: 각 가족 일정에 상대 가족 이름 없음 + 토큰 잔류 없음
    ev_a = api.get("/schedule/events", headers=fa.owner.headers).json()
    ev_b2 = api.get("/schedule/events", headers=fb.owner.headers).json()
    ev_leaks = [
        e["title"]
        for e in ev_a
        if leaks(json.dumps(e, ensure_ascii=False), [*sb["names"], *sb["outsiders"], sb["marker"]])
    ] + [
        e["title"]
        for e in ev_b2
        if leaks(json.dumps(e, ensure_ascii=False), [*sa["names"], *sa["outsiders"], sa["marker"]])
    ]
    ev_tok = [
        e["title"] for e in ev_a + ev_b2 if ANY_TOKEN_RE.findall(json.dumps(e, ensure_ascii=False))
    ]
    d["concurrent"] = {
        "requests": len(results),
        "threads": 16,
        "status_counts": {
            str(s): sum(1 for r_ in results if r_["status"] == s)
            for s in sorted({r_["status"] for r_ in results})
        },
        "response_foreign_data": mixes,
        "payload_mix": pay_mix,
        "payload_without_marker": pay_nomark,
        "anthropic_calls": len(FAKE.anthropic),
        "unrestored_tokens_in_responses": unrestored,
        "responses_missing_own_names": missing_own,
        "stored_events_with_foreign_data": ev_leaks,
        "stored_events_with_tokens": ev_tok,
        "non200": bad_status[:8],
    }
    # ---- 판정
    ok4 = not mixes and not pay_mix and not ev_leaks and not cross_bad
    rec(
        "X",
        4,
        "PASS" if ok4 else "FAIL",
        f"동시 {len(results)}건/16스레드({d['concurrent_seconds']}s) 상태={d['concurrent']['status_counts']}: 응답 내 타 가족 데이터={mixes or '없음'}, 전송본문 혼합={pay_mix or '없음'}, 표식 없는 호출={len(pay_nomark)}, 저장 일정 혼합={ev_leaks or '없음'}, 복원 안 된 토큰={unrestored or '없음'}, 자기 이름 복원 누락={missing_own or '없음'}; 교차 접근 시도={ {k: v for k, v in cross.items()} }",
        "토큰 번호가 두 가족에서 같아도([PERSON_1]) 각자 자기 이름으로만 복원됐는지는 '자기 이름 복원 누락/타 가족 데이터' 로 확인",
    )
    rec(
        "X",
        8,
        "PASS"
        if not re.findall(r"\[[A-Z]+_\d+\]\s*(?:=|->|→)", " ".join(c.text for c in FAKE.anthropic))
        else "FAIL",
        f"동시 요청 {len(FAKE.anthropic)}개 전송본문 전체에서 토큰=원문 대응 패턴 검색",
    )
    non200 = [x for x in bad_status if x[2] != 200]
    rec(
        "X",
        0,
        "PASS" if not non200 else "FAIL",
        f"동시 요청 정상 응답 {len(results) - len(non200)}/{len(results)}; 비정상={non200[:5] or '없음'}",
    )
    if mixes or pay_mix:
        finding("높음", "가족 간 가명화 혼합 의심", f"scenario X: {mixes[:3]} {pay_mix[:3]}")
    RESULTS["details"]["X"] = d


# ============================================================================================ 지연 / 시작 시 미리 로드
def pct(values, q):
    v = sorted(values)
    k = max(0, math.ceil(q * len(v)) - 1)
    return v[k]


def stats(values):
    return {
        "n": len(values),
        "mean_ms": round(statistics.fmean(values), 2),
        "median_ms": round(statistics.median(values), 2),
        "p95_ms": round(pct(values, 0.95), 2),
        "min_ms": round(min(values), 2),
        "max_ms": round(max(values), 2),
        "first_ms": round(values[0], 2),
    }


def latency(api, fams):
    sec("L")
    spec = SPECS["A"]
    o0 = spec["outsiders"][0]
    a0 = spec["addrs"][0]
    N = 30

    def series(label, mode, cold_cache=False):
        set_ner(mode)
        if mode != "off":
            t = now_ms()
            ner.ner_status()  # 엔진을 먼저 올려 둔다(미리 로드된 상태)
            load_ms = now_ms() - t
        else:
            load_ms = 0.0
        fam = make_family(api, spec)
        seed_chat(api, fam, spec)
        h = fam.owner.headers
        times = {"analysis": [], "preview": [], "schedule": []}
        for i in range(N):
            post_msg(
                api,
                fam.member,
                f"{spec['marker']} 추가 {i}번째 {spec['outsiders'][1]} 삼촌 얘기 장보러 가자",
            )
            for op in ("analysis", "preview", "schedule"):
                if cold_cache:
                    with ner._cache_lock:
                        ner._cache.clear()
                FAKE.reset()
                FAKE.sched_intent = "register"
                t = now_ms()
                if op == "schedule":
                    text = f"{spec['marker']} 내일 오후 3시에 {o0} 이모랑 {a0} 에서 점심 {i}번째"
                    r = api.post(
                        "/schedule/agent", json={"text": text, "channel": "personal"}, headers=h
                    )
                else:
                    r = api.post(f"/family-chat/ai/{op}", json={}, headers=h)
                dt = now_ms() - t
                assert r.status_code == 200, (label, op, r.status_code, r.text[:100])
                times[op].append(dt)
        return {"engine_load_ms": round(load_ms, 1), **{op: stats(v) for op, v in times.items()}}

    # 워밍업(임포트·DB·라우팅 비용을 첫 측정에서 빼기 위해)
    set_ner("off")
    wf = make_family(api, spec)
    seed_chat(api, wf, spec)
    for _ in range(3):
        api.post("/family-chat/ai/analysis", json={}, headers=wf.owner.headers)
    out = {}
    out["off_1"] = series("off_1", "off")
    out["on_warm_cache"] = series("on_warm", "required")
    out["on_cold_cache"] = series("on_cold", "required", cold_cache=True)
    out["off_2"] = series("off_2", "off")
    # 첫 요청: 미리 로드 전/후
    first = {}
    for label, pre in (("no_preload", False), ("after_preload", True)):
        set_ner("off")
        fam = make_family(api, spec)
        seed_chat(api, fam, spec)
        set_ner("required")  # ner.reset(): 엔진 없음
        pre_ms = 0.0
        if pre:
            t = now_ms()
            th = ner.start_preload()
            th.join(60)
            pre_ms = now_ms() - t
        FAKE.reset()
        t = now_ms()
        r = api.post("/family-chat/ai/analysis", json={}, headers=fam.owner.headers)
        first[label] = {
            "status": r.status_code,
            "first_request_ms": round(now_ms() - t, 1),
            "preload_ms": round(pre_ms, 1),
        }
        t = now_ms()
        api.post("/family-chat/ai/analysis", json={}, headers=fam.owner.headers)
        first[label]["second_request_ms_same_text"] = round(now_ms() - t, 1)
    out["first_request"] = first
    base = {}
    for op in ("analysis", "preview", "schedule"):
        base[op] = round((out["off_1"][op]["mean_ms"] + out["off_2"][op]["mean_ms"]) / 2, 2)
        base[op + "_p95"] = round((out["off_1"][op]["p95_ms"] + out["off_2"][op]["p95_ms"]) / 2, 2)
    out["baseline_off_mean"] = base
    inc = {}
    for key in ("on_warm_cache", "on_cold_cache"):
        inc[key] = {
            op: {
                "mean_increase_ms": round(out[key][op]["mean_ms"] - base[op], 2),
                "p95_increase_ms": round(out[key][op]["p95_ms"] - base[op + "_p95"], 2),
                "ratio": round(out[key][op]["mean_ms"] / base[op], 2) if base[op] else None,
            }
            for op in ("analysis", "preview", "schedule")
        }
    out["increase_vs_off"] = inc
    out["note"] = (
        "가짜 Claude(지연 0) 기준: 서버 처리(가명화 포함) 종단 지연. 실제 Claude 응답 시간(수 초)은 포함되지 않는다."
    )
    RESULTS["latency"] = out
    rec(
        "L",
        0,
        "PASS",
        f"지연 측정 완료: analysis 평균 off {base['analysis']}ms -> on(warm) {out['on_warm_cache']['analysis']['mean_ms']}ms / on(cold cache) {out['on_cold_cache']['analysis']['mean_ms']}ms",
    )


def lifespan_logs(api, fams):
    sec("LIFE")
    nomodel = TMP / "nomodel"
    nomodel.mkdir(exist_ok=True)
    tampered = make_tampered_dir()
    out = {}
    cfgs = [
        ("required/ok", "required", MODEL_DIR),
        ("auto/ok", "auto", MODEL_DIR),
        ("required/missing", "required", str(nomodel)),
        ("auto/missing", "auto", str(nomodel)),
        ("required/tampered", "required", str(tampered)),
        ("auto/tampered", "auto", str(tampered)),
        ("off/ok", "off", MODEL_DIR),
    ]
    forbidden = [
        MODEL_DIR,
        str(TMP),
        "C:\\",
        "C:/",
        "Users",
        "koelectra",
        "sha256",
        "박서연",
        "010-",
    ]
    for label, mode, mdir in cfgs:
        settings.privacy_ner_mode = mode
        settings.privacy_ner_model_dir = mdir
        ner.reset()
        start = len(LOG_LINES)
        CUR["section"] = f"LIFE:{label}"
        t0 = time.perf_counter()
        with TestClient(app, raise_server_exceptions=False) as c2:
            threads = [t for t in threading.enumerate() if t.name == "privacy-ner-preload"]
            started_preload = bool(threads) or mode == "off"
            for t in threads:
                t.join(60)
            elapsed = time.perf_counter() - t0
            health = c2.get("/health").status_code
            status = ner.ner_status()
        lines = [m for sec_, m in LOG_LINES[start:] if m.startswith("app.shared.privacy")]
        bad = [(m[:100], f) for m in lines for f in forbidden if f in m]
        out[label] = {
            "server_started_health": health,
            "preload_thread_seen_or_off": started_preload,
            "seconds_until_preload_done": round(elapsed, 2),
            "ner_status_after": status,
            "log_lines": [clip(m, 220) for m in lines],
            "forbidden_hits": bad,
        }
        print(label, health, status, lines)
    RESULTS["lifespan"] = out
    all_ok = all(
        v["server_started_health"] == 200 and not v["forbidden_hits"] for v in out.values()
    )
    rec(
        "LIFE",
        7,
        "PASS" if all_ok else "FAIL",
        "lifespan 로그: "
        + "; ".join(
            f"{k}: {len(v['log_lines'])}줄, health {v['server_started_health']}, active={v['ner_status_after'].get('active')}, 금지어 {len(v['forbidden_hits'])}"
            for k, v in out.items()
        ),
        "성공 로그에는 모델 파일 이름(model.onnx)·지문(12자리)·스레드 수만, 실패 로그에는 예외 종류만",
    )
    set_ner("required")


def final_log_scan():
    spec_all = [SPECS[k] for k in SPECS]
    watch = []
    for sp in spec_all:
        watch += [
            *sp["names"],
            *sp["outsiders"],
            *sp["addrs"],
            *sp["frags"],
            sp["phone"],
            sp["email"],
        ]
    watch += [*HIGH_RISK_RAW, "박서연", "secret.person"]
    by_sec = {}
    hits = []
    for sec_, m in LOG_LINES:
        by_sec[sec_] = by_sec.get(sec_, 0) + 1
        f = [w for w in watch if w in m]
        if f:
            hits.append((sec_, f, m[:160]))
    RESULTS["details"]["log_scan"] = {
        "total_lines": len(LOG_LINES),
        "by_section": by_sec,
        "hits": hits[:20],
    }
    rec(
        "ALL",
        7,
        "PASS" if not hits else "FAIL",
        f"전 시나리오 로그 {len(LOG_LINES)}줄(root DEBUG 핸들러) 중 합성 개인정보(이름·전화·이메일·주소·고위험) 포함={len(hits)}건 {hits[:3] or ''}",
        "예외 메시지에 합성 이름·전화·경로를 넣은 추론 실패(infer_error)에서도 로그는 예외 종류만 기록",
    )


# ============================================================================================ 보고서
ITEM_NAMES = {
    0: "워크플로 동작(복원·정상 응답)",
    1: "개인정보 원문 잔류(이름·전화·이메일·주소)",
    2: "고위험 잔류(주민번호·카드·계좌·비밀번호)",
    3: "이름·주소 가명화 정확도",
    4: "가족 간 혼합·접근 차단",
    5: "민감 문서 근거 포함(CHAT_INCLUDE_SENSITIVE)",
    6: "OCR 글자 가림 누락",
    7: "로그·오류 응답 개인정보",
    8: "요청별 매핑표 외부 전달",
    9: "승인 미리보기 = 실제 페이로드",
    10: "탐지 모델 실패 시 외부 전송 중단",
}
ORDER = {"PASS": 0, "NA": 1, "NV": 2, "PARTIAL": 3, "FAIL": 4}
KO = {"PASS": "통과", "FAIL": "실패", "PARTIAL": "부분", "NV": "미검증", "NA": "해당없음"}


def aggregate(statuses):
    real = [s for s in statuses if s != "NA"]
    if not real:
        return "NA"
    if "FAIL" in real:
        return "FAIL"
    if "PARTIAL" in real:
        return "PARTIAL"
    if all(s == "PASS" for s in real):
        return "PASS"
    return "NV"


def write_report():
    m = RESULTS["matrix"]
    scns = ["A", "B", "C", "D", "X", "ALL", "LIFE"]
    lines = ["# 워크플로 검증 보고서 (NER 연결 서비스)\n"]
    meta = RESULTS["meta"]
    lines.append(
        f"- 실행: {meta.get('started')} ~ {meta.get('finished')} / 코드 경로 `{meta.get('app_file')}` / Python {meta.get('python')}\n"
        f"- NER: `{meta.get('model_dir_name')}` 상태 {meta.get('ner_status')}\n"
        "- 방식: 임시 SQLite + FastAPI TestClient + 가짜 Claude(`httpx.post` 가로채기, 요청 본문 캡처). 실제 Claude·.env·공용/개인 DB 미사용, 합성 데이터만.\n"
    )
    lines.append("## 1. 시나리오 x 항목 결과표\n")
    lines.append("| # | 항목 | " + " | ".join(scns) + " | 총괄 |")
    lines.append("|---|---|" + "|".join(["---"] * len(scns)) + "|---|")
    for i in range(0, 11):
        cells, allst = [], []
        for sc in scns:
            sts = [e["status"] for e in m if e["scenario"] == sc and e["item"] == i]
            if not sts:
                cells.append("-")
                continue
            agg = aggregate(sts)
            allst += sts
            cells.append(KO[agg])
        lines.append(
            f"| {i} | {ITEM_NAMES[i]} | " + " | ".join(cells) + f" | **{KO[aggregate(allst)]}** |"
        )
    lines.append(
        "\n(0번은 시나리오 고유 워크플로 동작 확인이라 10개 항목 밖이다. A 정상 흐름·B·D·X 포함. `ALL` 은 전 시나리오 로그 일괄 검사, `LIFE` 는 서버 시작 로그.)\n"
    )
    lines.append("## 2. 항목별 근거(캡처 본문 기준)\n")
    for e in m:
        lines.append(
            f"- **[{e['scenario']}#{e['item']}] {KO[e['status']]}** — {e['evidence']}"
            + (f" _(비고: {e['note']})_" if e["note"] else "")
        )
    lines.append("\n## 3. 발견된 문제\n")
    if not RESULTS["findings"]:
        lines.append("없음")
    seen = set()
    for f in RESULTS["findings"]:
        if f["title"] in seen:
            continue
        seen.add(f["title"])
        lines.append(
            f"### [{f['severity']}] {f['title']}\n- 재현: {f['repro']}\n"
            + (f"- 상세: {f['detail']}\n" if f["detail"] else "")
        )
    lat = RESULTS.get("latency")
    if lat:
        lines.append("\n## 4. 종단 지연(가짜 Claude, 같은 시나리오 30회)\n")
        lines.append(
            "| 요청 | 설정 | 평균(ms) | 중앙값 | P95 | 최소 | 최대 | 첫 요청 | 평균 증가(vs off) | P95 증가 |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        base = lat["baseline_off_mean"]
        for op in ("analysis", "preview", "schedule"):
            for key, name in (
                ("off_1", "off(1차)"),
                ("off_2", "off(2차)"),
                ("on_warm_cache", "required 엔진 로드됨"),
                ("on_cold_cache", "required 캐시 비움(매번 추론)"),
            ):
                s = lat[key][op]
                inc = lat["increase_vs_off"].get(key, {}).get(op, {})
                lines.append(
                    f"| {op} | {name} | {s['mean_ms']} | {s['median_ms']} | {s['p95_ms']} | {s['min_ms']} | {s['max_ms']} | {s['first_ms']} | "
                    + (
                        f"+{inc['mean_increase_ms']} ({inc['ratio']}배) | +{inc['p95_increase_ms']}"
                        if inc
                        else "-"
                    )
                    + " |"
                )
        fr = lat["first_request"]
        lines.append(
            f"\n첫 요청(가족 분석): 미리 로드 없음 {fr['no_preload']['first_request_ms']}ms (그 다음 같은 요청 {fr['no_preload']['second_request_ms_same_text']}ms) / "
            f"미리 로드 후 {fr['after_preload']['first_request_ms']}ms (미리 로드 자체 {fr['after_preload']['preload_ms']}ms). 엔진 로드 시간 {lat['on_warm_cache']['engine_load_ms']}ms.\n"
        )
        lines.append(f"_{lat['note']}_\n")
    life = RESULTS.get("lifespan")
    if life:
        lines.append("\n## 5. 서버 시작 시 미리 로드(lifespan)\n")
        lines.append(
            "| 설정 | health | 미리 로드 완료까지(s) | 이후 NER 상태 | 로그 | 금지어(경로·개인정보) |"
        )
        lines.append("|---|---|---|---|---|---|")
        for k, v in life.items():
            lines.append(
                f"| {k} | {v['server_started_health']} | {v['seconds_until_preload_done']} | {v['ner_status_after']} | {' / '.join(v['log_lines']) or '(없음)'} | {len(v['forbidden_hits'])} |"
            )
    lines.append("\n## 6. 확인하지 못한 것\n")
    for nv in RESULTS["not_verified"]:
        lines.append(f"- {nv['what']} — {nv['why']}")
    lines.append(
        "\n## 7. 재현\n```\ncd apps/api\nPYTHONPATH=. python scripts/eval_workflows.py            # 전체\nPYTHONPATH=. python scripts/eval_workflows.py A B C      # 일부 섹션\n```\n환경: PRIVACY_NER_MODEL_DIR=<모델 폴더>, 결과 폴더는 WV_OUT.\n"
    )
    (OUT / "WORKFLOW_VERIFY_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


# ============================================================================================ main
def main(argv):
    wanted = set(argv) or {"A", "B", "C", "D", "X", "L", "LIFE"}
    h = _Capture()
    h.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(h)
    logging.getLogger().setLevel(logging.DEBUG)
    real_post = httpx.post
    httpx.post = FAKE  # 실제 외부 호출 차단
    try:
        disable_limits()
        RESULTS["meta"] = {
            "app_file": str(_app_pkg.__file__),
            "python": sys.version.split()[0],
            "model_dir_name": Path(MODEL_DIR).name,
            "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with TestClient(app, raise_server_exceptions=False) as api:
            set_ner("required")
            RESULTS["meta"]["ner_status"] = ner.ner_status()
            fams = {}
            for key in ("A", "B"):
                fams[key] = make_family(api, SPECS[key])
            ctx = {"api": api, "fams": fams}
            for name, fn in SECTIONS:
                if name in wanted:
                    try:
                        fn(api, fams)
                    except Exception as e:  # noqa: BLE001
                        traceback.print_exc()
                        RESULTS["details"].setdefault("errors", []).append(
                            {"section": name, "error": f"{type(e).__name__}: {e}"[:400]}
                        )
            del ctx
    finally:
        httpx.post = real_post
        logging.getLogger().removeHandler(h)
    finish()


SECTIONS = [
    (k, globals()[fn])
    for k, fn in (
        ("A", "scenario_a"),
        ("B", "scenario_b"),
        ("C", "scenario_c"),
        ("D", "scenario_d"),
        ("X", "scenario_x"),
        ("L", "latency"),
        ("LIFE", "lifespan_logs"),
    )
    if fn in globals()
]


def finish():
    RESULTS["meta"]["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if LOG_LINES:
        final_log_scan()
    RESULTS["not_verified"] = RESULTS["not_verified"] or default_not_verified()
    write_report()
    (OUT / "WORKFLOW_VERIFY_RESULTS.json").write_text(
        json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("saved", OUT / "WORKFLOW_VERIFY_RESULTS.json")


def default_not_verified():
    return [
        {
            "what": "실제 Claude 응답에 따른 동작(토큰을 바꿔 쓰거나 새 토큰을 만드는 경우)",
            "why": "가짜 응답이 요청 속 토큰을 그대로 되돌려 쓰는 경우만 시험함(위조 토큰 방어는 기존 단위 시험 범위)",
        },
        {"what": "PostgreSQL·운영 환경(Docker/Caddy)", "why": "임시 SQLite + TestClient 만 사용"},
        {
            "what": "증명서(OCR) 이미지 인식 정확도",
            "why": "이번에 제외(다른 에이전트 담당). 가짜 OCR 글자로 가림만 확인함",
        },
        {
            "what": "NER 동시 추론 대기 초과(QUEUE_WAIT 8s)·시간 상한 10s 실제 초과",
            "why": "시간 초과는 NerTimeout 을 직접 일으켜 모의했고 실제 대기 초과는 만들지 않음",
        },
        {
            "what": "가족 대화 사진(photos)·위치·돌봄/정산 도구 결과의 이름 가명화",
            "why": "탭 에이전트 도구 결과 경로는 입구 호출 수·입력 문장만 확인(기존 보안 시험이 결함으로 표시함)",
        },
        {
            "what": "다른 PC·다른 모델 버전에서의 정확도",
            "why": "koelectra-small-v2b 한 가지만 사용, 합성 이름 몇 개 기준이라 통계적 정확도가 아님",
        },
        {
            "what": "앱(모바일) 화면에서의 승인 UX",
            "why": "서버 API 응답만 확인(미리보기 응답과 실제 전송 본문 비교)",
        },
    ]


if __name__ == "__main__":
    main(sys.argv[1:])
