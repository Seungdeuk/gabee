"""주간 가족 뉴스의 근거 목록 만들기와 문장 검증기(함수 동작은 DB·LLM·네트워크 없는 순수 함수).

흐름: 재료 기록(`SourceRecord`) → `build_sources` 가 불투명한 짧은 id(e1·t1·d1)를 붙여 `Source` 목록을 만든다 →
(나중에 LLM 이) `{"title", "items": [{"text", "source_ids"}]}` 형태의 JSON 후보를 주면 → `validate` 가
엄격하게 걸러 `Validated` 또는 `Failed` 를 돌려준다. 이 모듈의 함수는 LLM·DB·네트워크를 부르지 않는다. import 는
`app.shared.weekly_sources` 의 `SourceRecord` 하나뿐이다(그 모듈은 스키마 점검기를 import 하지만 여기서는 쓰지 않는다).

`Source` 에는 id·종류·원본 참조·제목(label)·날짜·시각만 담는다. 메모·장소·본문·담당자는 담지 않는다.
`Failed.reason` 은 짧은 고정 코드 문자열이고 후보 문장 원문을 담지 않는다(로그에 남겨도 안전).

검증 규칙(문장 단위, 하나라도 어기면 그 문장을 버린다):
1. 인용한 `source_ids` 가 비었거나 문자열 목록이 아니면 버린다.
2. 근거 목록에 없는 id 가 하나라도 있으면 버린다.
3. 문장 속 숫자가 "인용한 근거의 날짜·시각·제목에 들어 있는 숫자"나 "허용 집계 숫자"에 없으면 버린다.
4. `member_names` 에 있는 이름이 문장에 나오는데 인용한 근거의 label 에 없으면 버린다.
5. 비었거나(공백만 포함) `MAX_TEXT` 자를 넘거나 앞서 남은 문장과 같으면 버린다. 남은 문장은 `MAX_ITEMS` 개까지만 쓴다.
제목은 근거를 직접 인용하지 않으므로 "실제로 남은 문장들이 인용한 근거"를 기준으로 3·4 를 적용하고, 실패하면
`FALLBACK_TITLE` 로 바꾼다. 남은 문장이 0개이면 `Failed` 다.

정규화: 문장·제목·구성원 이름·근거 label 은 모두 같은 형태로 바꿔 비교한다. 보이지 않는 문자(유니코드 Cf 범주:
ZWSP·ZWJ·BOM·방향 제어 등과 한글 채움 문자)를 지우고 → NFKC(한글 NFD 분해형도 합쳐진다) → 공백 정리 순이며,
이름은 대소문자도 무시한다. **비교한 정규화 형태를 그대로 저장한다**(검증한 문장과 저장·표시되는 문장이 같다).

한계(단순하고 설명 가능한 규칙을 고른 대가):
- 숫자는 모든 문자 체계의 십진 숫자(`\\d`, Nd 범주: 아랍-인도·데바나가리·전각 포함)를 ASCII 값으로 바꾼 토큰의 값만
  비교한다(앞자리 0 무시). 단위·문맥은 보지 않는다: "11월"의 11 과 "11명"의 11 은 구분하지 못하고, 근거의 날짜·시각·
  제목 숫자나 건수와 우연히 같은 숫자는 통과한다. 특히 작은 숫자는 건수·12시간제 시와 겹쳐 통과할 수 있다
  (단위 접미사 `명·개·번·원·건` 이 바로 붙은 숫자는 날짜·시각과 겹치면 막고 건수·인용 근거 제목의 숫자만 허용하지만,
  건수와 같은 작은 숫자 `2명` 은 집계와 구분할 수 없어 통과한다. 시험 `test_known_limit_small_numbers_*` 가 고정한다). "세 명"·"이틀"처럼 한글로 쓴 수, 한자 숫자(三), 요일·"내일" 같은 상대 표현, "1,000" 의 쉼표(1 과 000 으로
  갈린다)는 검증하지 못한다.
- 시각은 "14:30" 의 시·분과 12시간제 시(2시)를 허용한다. 오전/오후가 맞는지는 보지 않는다.
- 허용 집계는 기본적으로 재료 전체의 종류별 건수와 전체 건수다. 문장이 정말 그 집계를 뜻하는지는 확인하지 못한다.
- 단위 접미사 목록(명·개·번·원·건) 밖의 표현(존칭 `11분`, 나이·횟수 `11살`·`11회`, `11만원`·`11천원`)은 검증하지 못한다. 숫자와 단위 사이에
  공백이 둘 이상이거나 기호가 끼면 단위로 보지 않는다. `11번 버스` 처럼 번호도 단위로 보아 버린다(안전한 쪽의 오탐).
- 이름은 보이지 않는 문자와 결합 문자(Mn·Me)를 지운 뒤 부분 문자열 포함으로 비교한다. 이름 사이에 공백처럼 보이는 문자(점자 공백
  U+2800 등)나 보이는 결합 부호(Mc)를 끼우는 우회는 막지 못한다. 이름이 다른 단어 안에 들어 있으면(예: 구성원 "하나" ↔ "하나로마트") 멀쩡한 문장이
  버려질 수 있고(오탐), 별명·호칭·성 없이 부르는 이름, 구성원 목록에 없는 외부 사람 이름은 막지 못한다.
- 문장이 근거의 내용을 정말 말하는지(의미)는 검증하지 않는다. 존재하는 근거를 인용한 거짓 문장은 통과할 수 있다.
  의미 일치는 평가(Faithfulness)에서 따로 본다.
"""

import re
import unicodedata
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date

# 재료 수집 통로(shared)가 `SourceRecord` 의 주인이다(shared 가 기능 폴더를 import 하지 않으려고 옮겼다)
from app.shared.weekly_sources import SourceRecord

MAX_TEXT = 120
MAX_ITEMS = 6
FALLBACK_TITLE = "이번 주 우리 가족"

KINDS = ("event", "todo", "document")
_ID_PREFIX = {"event": "e", "todo": "t", "document": "d"}

# Failed.reason 으로 쓰는 고정 코드
REASON_BAD_SHAPE = "bad_shape"
REASON_NO_ITEMS = "no_items"
REASON_NO_VALID_ITEMS = "no_valid_items"

# 정규화 전에 이 길이를 넘는 문장·제목은 바로 버린다(보이지 않는 문자로 부풀린 입력의 처리량 상한).
MAX_RAW = 1000
# 후보 문장은 앞에서 이만큼만 본다(처리량 상한). 화면에 쓰는 것은 MAX_ITEMS 개다.
MAX_CANDIDATES = 50

# `\d` 는 모든 문자 체계의 십진 숫자(유니코드 Nd 범주: 아랍-인도·데바나가리·전각 등)를 잡는다.
_DIGITS = re.compile(r"\d+")
# 건수·금액을 뜻하는 단위 접미사가 바로 붙은 숫자(공백 허용). 이런 숫자는 날짜·시각이 아니라 건수나 제목에서 와야 한다.
# 단위 뒤에는 끝·한글 아닌 문자·조사(이가을를은는의과와에도만씩으로라나)만 올 수 있다: "원격"·"명동"·"건강"·"개학"·"번개" 같은
# 단어의 첫 글자와 "번째"는 단위가 아니다. 숫자와 단위 사이는 공백 하나(NBSP 포함)까지만 허용한다.
_COUNT_UNIT = re.compile(
    r"(\d+)[ \u00a0]?(?:명|개|번(?!째)|원|건)(?=$|[^가-힣]|[이가을를은는의과와에도만씩으로라나])"
)
# Cf(서식 문자) 외에 NFKC 로도 없어지지 않는 한글 채움 문자(보이지 않는 Lo 문자)
_FILLERS = frozenset("ᅟᅠㅤﾠ")
# 화면에 보이지 않는 결합 문자(Mn, Default_Ignorable_Code_Point): CGJ·몽골 자유 변이 선택자·변이 선택자(이체자 포함)
_INVISIBLE_MARKS = frozenset(
    ["\u034f", "\u180b", "\u180c", "\u180d", "\u180f"]
    + [chr(c) for c in range(0xFE00, 0xFE10)]
    + [chr(c) for c in range(0xE0100, 0xE01F0)]
)


@dataclass(frozen=True)
class Source:
    """LLM 에 보여 주고 문장이 인용하는 근거. id 는 불투명한 짧은 문자열이다."""

    id: str
    kind: str
    ref: str
    label: str
    date: date
    time: str | None


@dataclass(frozen=True)
class ValidatedItem:
    text: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class Validated:
    title: str
    items: tuple[ValidatedItem, ...]
    used_sources: tuple[Source, ...]  # 남은 문장이 실제로 인용한 근거만(근거 목록 순서)


@dataclass(frozen=True)
class Failed:
    reason: str  # 짧은 고정 코드. 후보 문장·사용자 문장 원문을 담지 않는다


def _strip_invisible(text: str) -> str:
    return "".join(
        c
        for c in text
        if unicodedata.category(c) != "Cf" and c not in _FILLERS and c not in _INVISIBLE_MARKS
    )


def _clean(text: str) -> str:
    """비교하고 저장하는 정규화 형태: 보이지 않는 문자 제거 → NFKC → 공백 정리.

    검증한 문장과 저장·표시하는 문장이 같도록, 비교에 쓴 이 형태를 그대로 저장한다.
    """
    text = unicodedata.normalize("NFKC", _strip_invisible(text))
    return " ".join(_strip_invisible(text).split())


def _fold(text: str) -> str:
    """이름 비교용(저장하지 않는다): `_clean` 에 대소문자 무시와 결합 문자(Mn·Me) 제거를 더한다.

    이름 글자 사이에 결합 악센트 같은 것을 끼워 같은 이름을 다른 문자열로 보이게 하는 우회를 막는다.
    """
    return _no_marks(_clean(text).casefold())


def _no_marks(text: str) -> str:
    """결합 문자(Mn·Me)를 지운 사본. 숫자·이름 비교에만 쓰고 저장하지 않는다."""
    return "".join(c for c in text if unicodedata.category(c) not in ("Mn", "Me"))


def _numbers(text: str) -> set[str]:
    """문장 속 숫자 토큰: 모든 문자 체계의 십진 숫자(`\\d`, Nd 범주)를 ASCII 값으로 바꾸고 앞의 0 을 뗀다."""
    return {_value(tok) for tok in _DIGITS.findall(_no_marks(_clean(text)))}


def _value(token: str) -> str:
    """숫자 토큰의 값(문자열). int 변환이 아니라서 아주 긴 숫자열도 안전하다."""
    return "".join(str(unicodedata.digit(c)) for c in token).lstrip("0") or "0"


def _source_numbers(src: Source) -> set[str]:
    """근거 하나가 뒷받침하는 숫자: 날짜(연·월·일)·시각(시·분, 12시간제 시)·제목 속 숫자."""
    nums = {str(src.date.year), str(src.date.month), str(src.date.day)}
    nums |= _numbers(src.label)
    if src.time:
        nums |= _numbers(src.time)
        hour = _DIGITS.search(_clean(src.time))
        if hour and len(hour.group()) <= 2 and int(_value(hour.group())) <= 23:
            nums.add(str(int(_value(hour.group())) % 12 or 12))
    return nums


def _count_numbers(sources: Iterable[Source]) -> set[str]:
    """재료 전체의 종류별 건수와 전체 건수(0 포함)."""
    sources = list(sources)
    nums = {str(sum(1 for s in sources if s.kind == kind)) for kind in KINDS}
    nums.add(str(len(sources)))
    return nums


def build_sources(records: Iterable[SourceRecord]) -> list[Source]:
    """재료 기록에 id 를 붙여 근거 목록을 만든다.

    정렬은 날짜 → 시간(시간 없는 기록이 먼저) → ref 순이라 입력 순서와 상관없이 같은 입력이면 같은 id·순서다.
    id 는 종류별로 순서대로 붙는다: 약속 e1.., 할 일 t1.., 문서 d1... 같은 (종류, ref) 는 하나만 남긴다.

    Raises:
        ValueError: 알 수 없는 종류.
    """
    items = list(records)
    for r in items:
        if r.kind not in _ID_PREFIX:
            raise ValueError(f"알 수 없는 근거 종류: {r.kind}")
    items.sort(key=lambda r: (r.day, r.start_time or "", r.ref, r.kind, r.title))
    seen: set[tuple[str, str]] = set()
    counters = dict.fromkeys(KINDS, 0)
    out: list[Source] = []
    for r in items:
        if (r.kind, r.ref) in seen:
            continue
        seen.add((r.kind, r.ref))
        counters[r.kind] += 1
        out.append(
            Source(
                id=f"{_ID_PREFIX[r.kind]}{counters[r.kind]}",
                kind=r.kind,
                ref=r.ref,
                label=_clean(r.title),
                date=r.day,
                time=r.start_time,
            )
        )
    return out


def _supported(text: str, cited: list[Source], names: list[str], counts: set[str]) -> bool:
    """규칙 3·4: 문장 속 숫자·이름이 인용 근거로 뒷받침되는가."""
    allowed = set(counts)
    label_numbers: set[str] = set()
    for src in cited:
        allowed |= _source_numbers(src)
        label_numbers |= _numbers(src.label)
    if not _numbers(text) <= allowed:
        return False
    # 단위(명·개·번·원·건)가 붙은 숫자는 날짜·시각과 겹쳐서는 안 되고 건수나 인용 근거의 제목에서 와야 한다
    unit_numbers = {_value(tok) for tok in _COUNT_UNIT.findall(_no_marks(_clean(text)))}
    if not unit_numbers <= (set(counts) | label_numbers):
        return False
    folded_text = _fold(text)
    labels = [_fold(src.label) for src in cited]
    return all(name not in folded_text or any(name in label for label in labels) for name in names)


def _check_item(
    raw: object,
    by_id: dict[str, Source],
    names: list[str],
    counts: set[str],
) -> ValidatedItem | None:
    if not isinstance(raw, dict):
        return None
    text, ids = raw.get("text"), raw.get("source_ids")
    if not isinstance(text, str) or not isinstance(ids, (list, tuple)) or not ids:
        return None
    if not all(isinstance(i, str) and i in by_id for i in ids):
        return None
    if len(text) > MAX_RAW:
        return None
    text = _clean(text)
    if not text or len(text) > MAX_TEXT:
        return None
    unique_ids = tuple(dict.fromkeys(ids))
    if not _supported(text, [by_id[i] for i in unique_ids], names, counts):
        return None
    return ValidatedItem(text=text, source_ids=unique_ids)


def _check_title(raw: object, used: list[Source], names: list[str], counts: set[str]) -> str:
    if not isinstance(raw, str) or len(raw) > MAX_RAW:
        return FALLBACK_TITLE
    title = _clean(raw)
    if not title or len(title) > MAX_TEXT or not _supported(title, used, names, counts):
        return FALLBACK_TITLE
    return title


def validate(
    candidate: object,
    sources: list[Source],
    member_names: Collection[str],
    counts: Collection[int] | None = None,
) -> Validated | Failed:
    """LLM 후보 JSON 을 근거 목록에 맞춰 검증한다.

    Args:
        candidate: `{"title": str, "items": [{"text": str, "source_ids": [str]}]}`. 모양이 다르면 `Failed`.
        sources: `build_sources` 가 만든 근거 목록.
        member_names: 가족 구성원 이름(가명 처리 전 원래 이름이든 가명이든 문장에 나오는 형태와 같아야 한다).
        counts: 추가로 허용할 집계 숫자. 기본 허용은 재료 전체의 종류별 건수와 전체 건수다.

    Returns:
        남은 문장이 있으면 `Validated`, 없으면 `Failed(reason)`. 예외로 알리지 않는다.
    """
    if not isinstance(candidate, dict) or not isinstance(candidate.get("items"), list):
        return Failed(REASON_BAD_SHAPE)
    if not candidate["items"]:
        return Failed(REASON_NO_ITEMS)
    raw_items = candidate["items"][:MAX_CANDIDATES]

    by_id = {s.id: s for s in sources}
    names = [n for n in (_fold(n) for n in member_names) if n]
    # 정수가 아닌 값(문자열·None·실수·bool 등)은 조용히 무시한다
    extra = {str(c) for c in counts or () if isinstance(c, int) and not isinstance(c, bool)}
    allowed_counts = _count_numbers(sources) | extra

    kept: list[ValidatedItem] = []
    seen_texts: set[str] = set()
    for raw in raw_items:
        item = _check_item(raw, by_id, names, allowed_counts)
        if item is None or item.text in seen_texts:
            continue
        seen_texts.add(item.text)
        kept.append(item)
        if len(kept) == MAX_ITEMS:
            break
    if not kept:
        return Failed(REASON_NO_VALID_ITEMS)

    cited_ids = {i for item in kept for i in item.source_ids}
    used = [s for s in sources if s.id in cited_ids]
    title = _check_title(candidate.get("title"), used, names, allowed_counts)
    return Validated(title=title, items=tuple(kept), used_sources=tuple(used))
