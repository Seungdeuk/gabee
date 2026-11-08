"""정산 에이전트 평가의 추가 채점(LLM 을 부르지 않는 순수 함수).

- 도구 인자 정확도: 모델이 도구를 부를 때 넘긴 인자가 사례의 기대 인자(tool_args)와 같은가.
- 금액 충실도: 답에 나온 금액이 질문·도구가 돌려준 값(DB 값)에 있는가. 없으면 지어낸 금액으로 본다.
  한계: 합계·차이처럼 모델이 계산한 금액은 도구 값에 없을 수 있어 '근거 없음'으로 나온다. 합격·불합격이 아니라 목록으로 보여 준다.
  '5만 5천원' 같은 한글 단위 표기는 읽지 못한다('86,000원', '5만원' 모양만 읽는다).
- 쓰기 없음: 사례 한 번을 돌리기 전후로 정산 표의 내용이 그대로인가(변경 요청은 '제안'만 하고 확인 전에는 쓰지 않아야 한다)."""

import hashlib
import json
import re
from typing import Any

from sqlalchemy import Table, select
from sqlalchemy.orm import Session

_WON = re.compile(r"(\d[\d,]*)\s*(만)?\s*원")


def amounts_in(text: str) -> set[int]:
    """글에서 '금액 + 원' 모양을 읽어 정수 원으로 돌려준다('86,000원' → 86000, '5만원' → 50000)."""
    out: set[int] = set()
    for m in _WON.finditer(text or ""):
        value = int(m.group(1).replace(",", "") or 0)
        out.add(value * 10000 if m.group(2) else value)
    return out


def numbers_in(data: Any) -> set[int]:
    """도구 결과(JSON 모양)에 들어 있는 모든 정수(숫자 문자열 포함)."""
    out: set[int] = set()
    if isinstance(data, bool):
        return out
    if isinstance(data, int):
        out.add(data)
    elif isinstance(data, float) and data.is_integer():
        out.add(int(data))
    elif isinstance(data, str):
        out.update(
            int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", data) if x.replace(",", "")
        )
    elif isinstance(data, dict):
        for k, v in data.items():
            out |= numbers_in(k) | numbers_in(v)
    elif isinstance(data, (list, tuple)):
        for v in data:
            out |= numbers_in(v)
    return out


def ungrounded_amounts(answer: str, tool_outputs: list[Any], context_texts: list[str]) -> list[int]:
    """답에 나온 금액 중 도구 결과나 질문·대화·제안 문구에 없는 것(오름차순)."""
    known = numbers_in(tool_outputs)
    for text in context_texts:
        known |= amounts_in(text)
    return sorted(a for a in amounts_in(answer) if a not in known)


def args_ok(case: dict, calls: list[dict]) -> bool | None:
    """기대 인자가 있는 사례에서 모델이 그 도구를 그 인자로 불렀는가. 채점할 인자가 없으면 None."""
    expected = case.get("tool_args") or {}
    tool = case.get("tool")
    if not expected or not tool:
        return None
    return any(
        c.get("name") == tool
        and all(str((c.get("input") or {}).get(k)) == str(v) for k, v in expected.items())
        for c in calls
    )


def db_fingerprint(db: Session, tables: list[Table]) -> str:
    """정산 표들의 내용 전체를 하나의 지문으로. 사례 전후가 같으면 아무것도 쓰이지 않은 것이다."""
    h = hashlib.sha1()
    for t in sorted(tables, key=lambda t: t.name):
        h.update(t.name.encode())
        rows = sorted(repr(tuple(r)) for r in db.execute(select(t)).all())
        h.update(json.dumps(rows, ensure_ascii=False).encode())
    return h.hexdigest()
