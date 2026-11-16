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
from dataclasses import dataclass, replace
from datetime import date

# 재료 수집 통로(shared)가 `SourceRecord` 의 주인이다(shared 가 기능 폴더를 import 하지 않으려고 옮겼다)
from app.shared.weekly_sources import SourceRecord

MAX_TEXT = 120
MAX_ITEMS = 6
FALLBACK_TITLE = "이번 주 우리 가족"

# 기사 모드(헤드라인·메인·단신). 기사는 재료 수보다 많을 수 없고 최대 MAX_ARTICLES 개다(메인 1 + 단신 최대 4).
MAX_ARTICLES = 5
MAX_HEADLINE = 20
# 분류는 모델이 정하지 않는다: 인용한 근거의 종류가 하나면 그 종류의 이름, 섞이면 MIXED_CATEGORY.
CATEGORY_BY_KIND = {"event": "일정", "todo": "할 일", "document": "문서"}
MIXED_CATEGORY = "가족 소식"

# 약속(event)은 실제로 있었는지 알 수 없다(참석·완료 정보가 없다). 약속을 인용한 문장·헤드라인이 활동이 이루어진 것처럼 쓰면 버린다.
# 어간 부분 문자열로 거른다(활용형을 한꺼번에 잡으려고). 근거 제목에 있는 말은 제목을 그대로 인용한 것이므로 먼저 지우고 본다.
# 한계: 목록 밖의 우회 표현은 막지 못한다(의미 일치는 평가에서 따로 본다). 완료한 할 일(todo)만 인용한 문장은 해당 없다.
ACTIVITY_STEMS = (
    "다녀",
    "다녔",
    "참석",
    "참가",
    "참여",
    "방문",
    "들렀",
    "들러",
    "갔",
    "왔",
    "마쳤",
    "마친",
    "마무리",
    "끝났",
    "끝난",
    "끝냈",
    "완료",
    "진행됐",
    "진행되었",
    "진행된",
    "열렸",
    "열린",
    "치렀",
    "치른",
    "만났",
    "만난",
    "함께했",
    "함께 했",
    "함께한",
    "즐겼",
    "즐긴",
    "즐거",
    "보냈",
    "보낸",
    "성공",
    "관람",
    "해냈",
    "먹었",
    "받았",
    "가졌",
    "가셨",
    "오셨",
    "보셨",
    "봤",
    "들었",
    # 감정·분위기: 재료에 없는 정보다
    "행복",
    "기뻤",
    "기쁜",
    "뿌듯",
    "신났",
    "설렜",
    "재미있",
    "웃었",
    "웃음",
)
# 약속을 인용한 문장(본문)은 일정을 일정으로 말하는 표현이 하나는 있어야 한다. 금지 어간 목록 밖의 우회 표현으로 활동을 말하는 문장을
# 막으려는 허용 목록이다(헤드라인은 명사구라 해당 없다). 프롬프트가 쓰라고 안내한 표현과 같다.
SCHEDULE_WORDS = ("있었", "잡혀", "예정", "등록", "공유")
# 묶은 기사나 헤드라인이 사건 사이의 관계·원인·결과·순서를 말하는 표현. 재료에는 그런 정보가 없으므로 지어낸 것이다.
RELATION_WORDS = (
    "때문",
    "덕분",
    "덕에",
    "덕택",
    "그래서",
    "따라서",
    "그러자",
    "그러면서",
    "그러다",
    "곧이어",
    "결과",
    "바람에",
    "인해",
    "탓",
    "이후",
    "직후",
    "뒤에",
    "한 뒤",
    "끝나고",
    "나서",
    "위해",
    "이어서",
    "에 이어",
    "이어진",
    "이어졌",
    "계기",
    "힘입",
    "영향",
    "비롯",
    "앞서",
    "뒤이",
    "잇따",
    "연이어",
    "바탕으로",
    "말미암",
)
# 제목 바로 뒤에 붙은 서술어(활동을 했다는 주장). 제목 `방문` + `했어요`.
_ATTACHED_PREDICATE = r"(?!\s?(?:[을를은는이가도]\s?)?(?:\S{1,4}\s)?(?:했|하였|한|해|함|하는|하고|하러|하며|됐|되었|된|돼))"
# 활동이 아니라 일정을 설명하는 표현('참석 일정', '참석할 예정', '방문이 예정')은 활동 주장이 아니다.
_SCHEDULE_PHRASE = re.compile(
    r"(?:참석|참가|참여|방문|관람)(?:하는|할)?(?:[이가을를은는]\s?)? ?(?:일정|예정)"
)
# 가명 토큰(`[PERSON_1]`)은 복원하면 이름(2~4자)이 되므로 복원 전 헤드라인 길이는 토큰을 2자로 센다(2자 이름까지 살리고, 복원 뒤 검증이 실제 길이로 다시 본다).
_PSEUDONYM_TOKEN = re.compile(r"\[[A-Z]+_\d+\]")
# 기사에 쓴 요일은 인용한 근거 날짜의 요일이어야 한다(모델이 엉뚱한 요일을 쓰지 못하게). '요일' 이 붙은 낱말만 요일로 본다.
_WEEKDAY_LETTER = "[월화수목금토일]"
# `X요일`·`X욜`, 범위·나열(`월·화요일`, `월, 화요일`, `월~화요일`)의 모든 글자, 날짜 표기의 괄호 요일(`11월 10일(수)`)
_WEEKDAY_WORD = re.compile(
    rf"((?:{_WEEKDAY_LETTER}\s?[·,~\-/]\s?)*{_WEEKDAY_LETTER})\s?(?:요일|욜)|\(\s?({_WEEKDAY_LETTER})\s?\)"
)
_WEEKDAY_LETTERS = "월화수목금토일"

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
    # 기사 모드(`article_mode=True`)에서만 채운다. role·category 는 모델이 아니라 서버가 정한다.
    headline: str | None = None
    role: str | None = None  # "lead"(메인 기사 하나) | "brief"(단신)
    category: str | None = None  # 인용 근거의 종류에서 정한 고정 이름


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


def _weekdays_ok(text: str, cited: list[Source]) -> bool:
    """글에 나온 요일이 모두 인용한 근거 날짜의 요일 안에 있는가. 요일을 쓰지 않았으면 True.

    - 근거 제목을 그대로 인용한 부분(예: 제목 "금요일의 약속")은 요일 주장이 아니므로 먼저 지운다.
    - 요일 사이 공백("금 요일")과 줄임("금욜")도 요일로 본다.
    - 날짜(요일)가 다른 근거를 묶은 기사는 요일을 쓰지 않는다: 요일을 일정별로 연결해 확인할 수 없어서(뒤바꿔도 집합은 같다) 안전하게 막는다.
    """
    rest = _fold(text)
    for label in sorted({_fold(s.label) for s in cited}, key=len, reverse=True):
        if label:
            rest = rest.replace(label, " ")
    mentioned = [
        day
        for run, paren in _WEEKDAY_WORD.findall(rest)
        for day in re.findall(_WEEKDAY_LETTER, run or paren)
    ]
    if not mentioned:
        return True
    allowed = {_WEEKDAY_LETTERS[s.date.weekday()] for s in cited}
    return len(allowed) == 1 and all(day in allowed for day in mentioned)


def _quoted_out(text: str, cited: list[Source]) -> str:
    """근거 제목을 그대로 인용한 부분을 지운 비교용 사본(제목 속 낱말 때문에 멀쩡한 문장을 버리지 않으려고)."""
    rest = _fold(text)
    for label in sorted({_fold(s.label) for s in cited}, key=len, reverse=True):
        if label:
            # 제목 바로 뒤에 서술어('했어요'·'을 했어요')가 붙으면 제목 인용이 아니라 활동 주장이므로 지우지 않는다
            rest = re.sub(re.escape(label) + _ATTACHED_PREDICATE, " ", rest)
    return _SCHEDULE_PHRASE.sub(" ", rest)


def _claims_activity(text: str, cited: list[Source]) -> bool:
    """약속(event)을 인용했는데 참석·완료·방문 같은 활동이 이루어진 것처럼 쓴 문장인가."""
    if not any(s.kind == "event" for s in cited):
        return False
    rest = _quoted_out(text, cited)
    return any(stem in rest for stem in ACTIVITY_STEMS)


def _states_relation(text: str, cited: list[Source]) -> bool:
    rest = _quoted_out(text, cited)
    return any(word in rest for word in RELATION_WORDS)


def _groupable(cited: list[Source]) -> bool:
    """한 기사로 묶을 수 있는 근거인가: 모두 같은 날짜이거나 모두 같은 종류."""
    return len({s.date for s in cited}) == 1 or len({s.kind for s in cited}) == 1


def _category_of(cited: list[Source]) -> str:
    kinds = {s.kind for s in cited}
    return CATEGORY_BY_KIND[next(iter(kinds))] if len(kinds) == 1 else MIXED_CATEGORY


def _check_headline(
    raw: object,
    cited: list[Source],
    names: list[str],
    counts: set[str],
    check_wording: bool = True,
) -> str | None:
    """헤드라인도 문장과 같은 근거로 검증한다. 하나라도 어기면 헤드라인만 버린다(기사는 남는다)."""
    if not isinstance(raw, str) or len(raw) > MAX_RAW:
        return None
    headline = _clean(raw)
    if not headline or len(_PSEUDONYM_TOKEN.sub("가나", headline)) > MAX_HEADLINE:
        return None
    if not _supported(headline, cited, names, counts) or not _weekdays_ok(headline, cited):
        return None
    if check_wording and (_claims_activity(headline, cited) or _states_relation(headline, cited)):
        return None
    return headline


def _check_item(
    raw: object,
    by_id: dict[str, Source],
    names: list[str],
    counts: set[str],
    article_mode: bool = False,
    check_wording: bool = True,
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
    cited = [by_id[i] for i in unique_ids]
    if not _supported(text, cited, names, counts):
        return None
    if not article_mode:
        return ValidatedItem(text=text, source_ids=unique_ids)
    if not _weekdays_ok(text, cited):
        return None
    if len(cited) > 1 and not _groupable(cited):
        return None
    if check_wording:
        if len(cited) > 1 and _states_relation(text, cited):
            return None
        if _claims_activity(text, cited):
            return None
        # 약속은 일정을 일정으로 말하는 표현이 있어야 한다(활동을 우회해 말하는 문장을 막는 허용 목록)
        if any(s.kind == "event" for s in cited) and not any(w in text for w in SCHEDULE_WORDS):
            return None
    return ValidatedItem(
        text=text,
        source_ids=unique_ids,
        headline=_check_headline(raw.get("headline"), cited, names, counts, check_wording),
        category=_category_of(cited),
    )


def _arrange(
    kept: list[ValidatedItem], by_id: dict[str, Source], limit: int
) -> list[ValidatedItem]:
    """메인 기사 하나를 정하고(근거가 많은 기사 → 같으면 가장 이른 날짜 → 같으면 후보 순서) 나머지는 이른 날짜 순 단신으로 둔다.

    주관적 중요도나 감정은 보지 않는다. 기사는 `limit` 개까지만 남긴다(메인은 항상 남는다).
    """

    def earliest(item: ValidatedItem):
        return min(by_id[i].date for i in item.source_ids)

    order = list(enumerate(kept))
    lead_pos, lead = min(order, key=lambda p: (-len(p[1].source_ids), earliest(p[1]), p[0]))
    briefs = sorted((p for p in order if p[0] != lead_pos), key=lambda p: (earliest(p[1]), p[0]))
    arranged = [replace(lead, role="lead")]
    arranged += [replace(item, role="brief") for _, item in briefs]
    return arranged[:limit]


def _check_title(
    raw: object,
    used: list[Source],
    names: list[str],
    counts: set[str],
    article_mode: bool = False,
    check_wording: bool = True,
) -> str:
    if not isinstance(raw, str) or len(raw) > MAX_RAW:
        return FALLBACK_TITLE
    title = _clean(raw)
    if not title or len(title) > MAX_TEXT or not _supported(title, used, names, counts):
        return FALLBACK_TITLE
    if article_mode and not _weekdays_ok(title, used):
        return FALLBACK_TITLE
    if (
        article_mode
        and check_wording
        and (_claims_activity(title, used) or _states_relation(title, used))
    ):
        return FALLBACK_TITLE  # 최상위 제목도 헤드라인과 같은 규칙을 지킨다
    return title


def validate(
    candidate: object,
    sources: list[Source],
    member_names: Collection[str],
    counts: Collection[int] | None = None,
    article_mode: bool = False,
    check_wording: bool = True,
) -> Validated | Failed:
    """LLM 후보 JSON 을 근거 목록에 맞춰 검증한다.

    Args:
        candidate: `{"title": str, "items": [{"text": str, "source_ids": [str]}]}`. 모양이 다르면 `Failed`.
        sources: `build_sources` 가 만든 근거 목록.
        member_names: 가족 구성원 이름(가명 처리 전 원래 이름이든 가명이든 문장에 나오는 형태와 같아야 한다).
        counts: 추가로 허용할 집계 숫자. 기본 허용은 재료 전체의 종류별 건수와 전체 건수다.
        article_mode: 기사형(헤드라인·메인·단신) 규칙을 적용한다(묶기 제한·역할·분류·기사 수·중복 기사).
        check_wording: 기사형에서 완료·관계·감정 표현(어간 목록)과 일정 표현(허용 목록)을 검사한다. 이름을 복원한 뒤의 재검증은 끈다 —
            복원된 이름이 근거 제목의 이름과 달라 제목 인용을 알아보지 못하므로(표현 검사는 가명 상태에서 이미 했다).

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
    seen_source_sets: set[frozenset[str]] = set()
    for raw in raw_items:
        item = _check_item(raw, by_id, names, allowed_counts, article_mode, check_wording)
        if item is None or item.text in seen_texts:
            continue
        # 같은 근거만 인용한 기사를 되풀이하면 다른 근거의 기사가 상한에 밀려나므로 먼저 나온 것만 둔다
        if article_mode:
            ids = frozenset(item.source_ids)
            if ids in seen_source_sets:
                continue
            seen_source_sets.add(ids)
        seen_texts.add(item.text)
        kept.append(item)
        if len(kept) == MAX_ITEMS:
            break
    if not kept:
        return Failed(REASON_NO_VALID_ITEMS)
    if article_mode:
        # 기사 수는 재료 수보다 많을 수 없다(억지로 채우지 않는다)
        kept = _arrange(kept, by_id, min(MAX_ARTICLES, len(sources)))

    cited_ids = {i for item in kept for i in item.source_ids}
    used = [s for s in sources if s.id in cited_ids]
    title = _check_title(
        candidate.get("title"), used, names, allowed_counts, article_mode, check_wording
    )
    return Validated(title=title, items=tuple(kept), used_sources=tuple(used))
