"""주간 가족 뉴스의 재료를 모으는 통로. weekly_news 가 일정·문서함 같은 다른 기능의 데이터를 직접 읽지 않도록,
데이터 주인 기능(schedule·ai_assistant)이 시작할 때 **재료를 읽는 함수**를 여기에 등록하고, weekly_news 는 `collect` 만 부른다
(`shared/chat_share.py`·`shared/chat_library.py` 와 같은 방향). `SourceRecord` 도 기능 폴더가 아니라 여기에 둔다.

- 재료 하나(일정·문서)가 읽히지 않아도 나머지로 뉴스를 만든다: 제공자가 등록되지 않았거나, 주인 기능의 표가 준비되지 않았거나
  (`monitor.status().feature_ready`), 읽다가 예외가 나면 그 재료의 이름만 `unavailable` 에 넣는다. 예외는 종류(클래스 이름)만 기록한다.
- **민감한 주제는 사전에 뺀다(2026-11-11 사용자 결정)**: 의료·금융·법률·신분 같은 주제어가 제목에 든 재료는 개인정보 탐지(NER)와
  상관없이 `collect` 가 제목을 외부로 보내기 전에 버린다(`SENSITIVE_TOPIC_WORDS`). 개인정보 탐지는 이름·전화 같은 식별자를 가릴 뿐
  "항암 치료"·"이혼 상담" 같은 주제는 알아보지 못하기 때문이다. 제외한 개수만 `excluded` 에 담고 제목은 담지 않는다.
- 입력 상한(약속 30·할 일 30·문서 20): 날짜·시간 순으로 앞에서 자르고 `truncated=True` 로 알린다.
- `collect` 를 부르는 쪽은 `group_id`·`user_id` 가 실제 구성원 관계인지 먼저 확인해야 한다(`ensure_group_member`).
  제공자는 받은 값으로 자기 기능의 데이터를 읽을 뿐 구성원 여부는 다시 확인하지 않는다.
- **계약(호출 순서)**: 제공자가 실패하면 `collect` 가 `db.rollback()` 을 부른다. 그러니 커밋하지 않은 쓰기(예: 만드는 중인
  pending 줄)가 있는 세션으로 `collect` 를 부르지 말고, **`collect` 를 먼저 하고 그 뒤에 쓰기·커밋**한다(T26-b 호출 순서).
  세이브포인트로 바꾸지 않은 것은 SQLite·PostgreSQL 동작 차이 위험 때문이다."""

import logging
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.shared.schema import monitor

logger = logging.getLogger(__name__)

SCHEDULE = "schedule"  # 약속(event)·완료한 할 일(todo)
DOCUMENTS = "documents"  # 문서함 기록(document)
EXPECTED = (SCHEDULE, DOCUMENTS)  # 등록돼 있어야 하는 재료. 없으면 unavailable

# 종류별 입력 상한(모듈 상수)
LIMITS = {"event": 30, "todo": 30, "document": 20}

# 제목에 들어 있으면 재료에서 빼는 민감 주제어(신분·서류·의료·금융·법률·가족 민감사). 비교는 공백·보이지 않는 문자·결합 문자를 지우고
# NFKC·소문자로 맞춘 뒤 부분 문자열로 한다. 가족 일정에서 흔한 단어(병원·치과)도 일부러 포함한다: 뉴스가 덜 구체적이어도
# 건강·금융 정보가 외부 AI 로 나가지 않는 쪽을 택했다(문서함 민감 판정 `SENSITIVE_WORDS` 와 같은 방향이지만 일정·할 일 제목까지 적용).
SENSITIVE_TOPIC_WORDS = (
    # 신분·서류
    "가족관계",
    "주민등록",
    "등본",
    "초본",
    "여권",
    "운전면허",
    "신분증",
    "인감",
    "이력서",
    # 의료
    "병원",
    "의원",
    "치과",
    "소아과",
    "내과",
    "외과",
    "안과",
    "피부과",
    "정신과",
    "산부인과",
    "한의원",
    "약국",
    "진료",
    "진단",
    "소견",
    "처방",
    "수술",
    "입원",
    "퇴원",
    "검진",
    "검사결과",
    "항암",
    "치료",
    "접종",
    "mri",
    "임신",
    "출산",
    "의학과",  # 정신건강의학과·재활의학과 등('정신과' 부분 문자열에 안 걸리는 이름)
    "이비인후",
    "비뇨",
    "신경과",
    "의료원",
    "보건소",
    "응급",
    "예방주사",
    "주사맞",
    "백신",
    "심리상담",
    "상담치료",
    "요양",
    "dentist",
    "hospital",
    "clinic",
    "doctor",
    # 금융
    "대출",
    "은행",
    "통장",
    "계좌",
    "보험",
    "연금",
    "세금",
    "채무",
    "파산",
    "투자",
    "주식",
    "코인",
    "적금",
    "청약",
    "월세",
    "전세",
    "이체",
    "카드값",
    "카드대금",
    "카드결제",
    "카드할부",
    # 법률
    "이혼",
    "소송",
    "변호사",
    "법원",
    "고소",
    "재판",
    "합의금",
    "양육권",
    "경찰",
    # 신념
    "종교",
)


def _topic_form(text: str) -> str:
    """주제어 비교용 형태: 공백·보이지 않는 문자(Cf)·결합 문자(Mn·Me)를 지우고 NFKC·소문자로 맞춘다."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(
        c for c in folded if not c.isspace() and unicodedata.category(c) not in ("Cf", "Mn", "Me")
    )


_TOPIC_FORMS = tuple(_topic_form(w) for w in SENSITIVE_TOPIC_WORDS)


def is_sensitive_topic(title: str) -> bool:
    """제목에 민감 주제어가 들어 있는가(재료에서 뺄 대상)."""
    form = _topic_form(title)
    return any(word in form for word in _TOPIC_FORMS)


@dataclass(frozen=True)
class SourceRecord:
    """근거 목록의 재료 한 건. 제목·날짜·시각 말고는 받지 않는다."""

    kind: str  # "event" | "todo" | "document"
    ref: str  # 원본 기록 id(일정·문서). 화면 이동에 쓴다
    title: str
    day: date
    start_time: str | None = None  # "HH:MM"


@dataclass
class Collected:
    records: list[SourceRecord] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)  # 읽지 못한 재료 이름
    truncated: bool = False  # 상한을 넘어 잘렸는가
    excluded: int = 0  # 민감 주제어 때문에 뺀 재료 수(제목은 담지 않는다)


# (db, group_id, user_id, start, end) → 그 주(양끝 포함)의 재료
Provider = Callable[[Session, str, str, date, date], list[SourceRecord]]
_providers: dict[str, tuple[str, Provider]] = {}  # 재료 이름 → (주인 기능, 읽는 함수)


def register_provider(name: str, owner_feature: str, fn: Provider) -> None:
    """name 재료를 읽는 함수를 등록한다(주인 기능이 시작할 때 부른다). owner_feature 는 표 준비 확인에 쓴다."""
    _providers[name] = (owner_feature, fn)


def _read(db: Session, name: str, args: tuple) -> list[SourceRecord] | None:
    """제공자 하나를 읽는다. 쓸 수 없으면 None. 예외가 나면 세션 전체를 `rollback()` 하므로(계약은 모듈 설명)
    커밋하지 않은 쓰기가 있는 세션으로 부르면 안 된다."""
    entry = _providers.get(name)
    if entry is None or not monitor.status().feature_ready(entry[0]):
        return None
    try:
        return list(entry[1](db, *args))
    except Exception as exc:  # noqa: BLE001  재료 하나가 뉴스 전체를 막으면 안 된다(종류만 기록)
        db.rollback()
        logger.warning("weekly source failed name=%s error=%s", name, type(exc).__name__)
        return None


def _order(r: SourceRecord) -> tuple:
    return (r.day, r.start_time or "", r.ref)


def collect(db: Session, group_id: str, user_id: str, start: date, end: date) -> Collected:
    """그 구성원의 그 주(start~end 양끝 포함) 재료를 모은다. 날짜·시간 순이고 종류별 상한을 넘으면 앞에서 자른다.

    제공자 실패 시 `db.rollback()` 을 부르므로, 커밋하지 않은 쓰기가 있는 세션으로 부르지 말고 `collect` 를 먼저 한 뒤 쓰기·커밋한다."""
    out = Collected()
    found: list[SourceRecord] = []
    for name in dict.fromkeys([*EXPECTED, *_providers]):
        records = _read(db, name, (group_id, user_id, start, end))
        if records is None:
            out.unavailable.append(name)
        else:
            found += records
    # 민감 주제는 상한을 적용하기 전에 뺀다(민감한 기록이 상한을 차지해 멀쩡한 기록을 밀어내지 않게)
    safe = [r for r in found if not is_sensitive_topic(r.title)]
    out.excluded = len(found) - len(safe)
    found = safe
    for kind, limit in LIMITS.items():
        mine = sorted((r for r in found if r.kind == kind), key=_order)
        out.truncated = out.truncated or len(mine) > limit
        out.records += mine[:limit]
    out.records.sort(key=_order)
    return out
