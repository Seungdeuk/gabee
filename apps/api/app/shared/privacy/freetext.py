"""자유 글·구조화 JSON 가명화 API(순수 함수, DB 모델에 의존하지 않는다).

가족 채팅 대화(줄 단위)는 ``gateway.prepare_transcript`` 를 쓴다. 이 모듈은 AI 어시스턴트 질문·앞 대화·도구 결과처럼
**줄 구조가 없는 글**과 **JSON** 을 위한 것이다. 같은 탐지기(``detect``)와 같은 대응표(``Pseudonymizer``)를 쓴다.

- ``prepare_text(text, policy=ASSISTANT, members=())`` -> ``(가명화된 글, PrivacySession)``
- ``prepare_json(obj, ...)`` -> ``(가명화된 JSON, PrivacySession)``: 문자열 값만 바꾸고 구조·키·숫자·불리언·null 은 유지한다.
- 같은 요청의 여러 조각(질문 + 앞 대화 + 도구 결과)이 토큰 번호를 공유하려면 ``session=`` 에 같은 세션을 넘긴다.
- 자유 글에는 '메시지 통째 제외'가 없다. 고위험 값은 **그 값만** ``[RRN]`` 같은 고정 자리표시로 바꾼다.
  ``session.blocked_count``(점수 >= ``block_min_score`` 만)와 ``session.high_risk_count``(RRN·CARD·ACCOUNT·SECRET 전부)로 알린다.
- 복원은 ``session.restore_text`` / ``session.restore_json``: 이 요청이 만든 정확한 토큰만, ``policy.restore_kinds`` 안의 종류만 되돌린다.
- ``generalize_coordinates`` / ``generalize_number`` 는 좌표·금액을 거칠게 만드는 순수 함수, ``contains_placeholders`` 는 일반화 문구·
  자리표시가 남았는지 보는 검사(쓰기 도구 인자 거부용)다.

E2EE 가 아니며 완전한 보호를 보장하지 않는다. 자세한 설명은 docs/security/PRIVACY_PIPELINE_MODULE.md.
"""

import math
import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime, time
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from . import ner
from .detectors import INVISIBLE_CHARS
from .gateway import JsonRestoreResult, restore_json, restore_value
from .policy import ASSISTANT, Policy
from .pseudonymizer import (
    _FIXED_TOKENS,
    GENERIC_TEXT,
    SENSITIVE_TEXT,
    UNKNOWN_TEXT,
    Pseudonymizer,
)
from .types import Kind

# 좌표로 보고 일반화하는 JSON 키(소문자 비교)
COORDINATE_KEYS: tuple[str, ...] = ("lat", "lng", "lon", "long", "latitude", "longitude")
# 소수점 둘째 자리까지만 남긴다: 위도 0.01도 ≈ 1.1km, 경도는 한국 위도(≈37도)에서 ≈ 0.9km 칸으로 뭉개진다.
DEFAULT_COORDINATE_PRECISION = 2
MAX_DEPTH = 64
_HIGH_RISK_KINDS = (Kind.RRN.value, Kind.CARD.value, Kind.ACCOUNT.value, Kind.SECRET.value)
# 좌표 쌍 후보: 소수점 4자리 이상 두 수가 쉼표·세미콜론·공백으로 붙은 것. 앞이 영문자·숫자·점이면 시작하지 않는다
# (`v1.23456 2.34567`, `a37.5665 126.978`, `1,234.5678 12.3456`). 범위·단서는 코드로 확인한다.
_COORD_PAIR = re.compile(
    r"(?<![A-Za-z0-9.])(?<!\d,)(-?\d{1,3}\.\d{4,})(?:\s*[,;]\s*|\s+)(-?\d{1,3}\.\d{4,})(?![\d.])"
)
# 위도·경도 단서: 후보 앞 24자·뒤 12자 안에 있으면 소수 4자리 쌍도 좌표로 본다
_COORD_CUE = re.compile(
    r"위치|좌표|위도|경도|현위치|gps|lat|lng|lon|latlng|coord|location|geo|지도|map|[?&]q=|@",
    re.IGNORECASE,
)
# 단서 없이도 좌표로 보는 '정밀 좌표': 두 수 모두 소수 5자리 이상이고 어느 한 수는 절댓값이 10 이상(확률·비율 같은 0~1 값 제외)
_PRECISE_DECIMALS = 5
_PRECISE_MIN_MAGNITUDE = 10


def _valid_pair(a: float, b: float) -> bool:
    """[위도, 경도] 또는 [경도, 위도] 로 지구상 유효한 쌍인가(앞 수가 |90| 초과면 경도가 먼저인 GeoJSON 순서로 본다)."""
    return (abs(a) <= 90 and abs(b) <= 180) or (abs(a) <= 180 and abs(b) <= 90)


def _decimals(s: str) -> int:
    return len(s.split(".", 1)[1]) if "." in s else 0


def _precise_pair(a: float, b: float, da: int, db: int) -> bool:
    return (
        da >= _PRECISE_DECIMALS
        and db >= _PRECISE_DECIMALS
        and max(abs(a), abs(b)) >= _PRECISE_MIN_MAGNITUDE
    )


def generalize_coordinates(
    lat: float, lng: float, *, precision: int = DEFAULT_COORDINATE_PRECISION
) -> tuple[float, float]:
    """좌표를 소수점 ``precision`` 자리 **아래를 절삭**(0 쪽으로 버림, 반올림 아님)해 거칠게 만든다.

    precision=2 이면 위도 방향 약 1.1km, 경도 방향 약 0.9km(위도 37도) 칸의 모서리 값이 된다. 1=약 11km, 3=약 110m, 0=약 111km.
    칸의 한쪽 모서리로 모이므로 원래 위치는 그 칸 안 어디든일 수 있다. 정확한 주소를 알 수 없다는 뜻이지 익명이라는 뜻은 아니다
    (집·직장 같은 곳은 여전히 동네 수준으로 추정된다). 범위(위도 +-90, 경도 +-180)를 벗어나거나 숫자가 아니면 ValueError.
    """
    _check_precision(precision)
    return _trunc_coord(lat, precision, 90.0, "lat"), _trunc_coord(lng, precision, 180.0, "lng")


def _check_precision(precision: Any) -> None:
    if isinstance(precision, bool) or not isinstance(precision, int) or not 0 <= precision <= 6:
        raise ValueError("precision 은 0~6 사이 정수여야 한다")


def _trunc_coord(value: Any, precision: int, limit: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        raise ValueError(f"{label} 는 숫자여야 한다")
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation as e:
        raise ValueError(f"{label} 는 숫자여야 한다") from e
    if not d.is_finite() or abs(d) > Decimal(str(limit)):
        raise ValueError(f"{label} 가 범위를 벗어났다")
    out = float(d.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_DOWN))
    return out + 0.0  # -0.0 -> 0.0


def generalize_number(value: int | float, *, significant: int = 2) -> int | float:
    """금액 같은 숫자를 유효숫자 ``significant`` 자리로 반올림한다(예: 123456 -> 120000, 0.4567 -> 0.46). bool·nan·inf 는 그대로."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return value
    if isinstance(value, float) and not math.isfinite(value):
        return value
    d = Decimal(str(value))
    if not d.is_finite() or d == 0:
        return value
    quantum = Decimal(1).scaleb(d.adjusted() - significant + 1)
    try:
        rounded = d.quantize(quantum, rounding=ROUND_HALF_UP)
    except InvalidOperation:  # 자릿수가 Decimal 정밀도(28자리)를 넘는 아주 큰 수는 그대로 둔다
        return value
    if isinstance(value, int):
        return int(rounded)
    if isinstance(value, Decimal):
        return rounded
    return float(rounded)


def _generalize_coordinate_text(text: str, precision: int) -> tuple[str, int]:
    """자유 글 속 좌표 쌍('37.566535,126.977969')을 절삭해 바꾼다. (바뀐 글, 바꾼 쌍의 수).

    좌표로 보는 조건(둘 다 소수 4자리 이상이고 지구상 유효한 쌍이며 영문자·숫자 뒤가 아님) 중에서
    (a) 위도·경도 단서(위치·좌표·위도·경도·GPS·lat·lng·지도·링크 등)가 가까이 있거나, (b) 두 수 모두 소수 5자리 이상이고 한 수가 10 이상인
    정밀 좌표일 때만 바꾼다. 단서 없는 4자리 소수 두 개(환율·금리·체온 등)는 그대로 둔다. 경도가 먼저인 표기(126.97, 37.56)도 범위로 알아본다.
    """
    count = 0

    def sub(m: re.Match) -> str:
        nonlocal count
        sa, sb = m.group(1), m.group(2)
        try:
            a, b = float(sa), float(sb)
        except ValueError:
            return m.group(0)
        if not _valid_pair(a, b):
            return m.group(0)
        near = text[max(0, m.start() - 24) : m.start()] + " " + text[m.end() : m.end() + 12]
        if not (_COORD_CUE.search(near) or _precise_pair(a, b, _decimals(sa), _decimals(sb))):
            return m.group(0)
        ta = _trunc_coord(sa, precision, 180.0, "a")
        tb = _trunc_coord(sb, precision, 180.0, "b")
        count += 1
        return f"{ta:.{precision}f}, {tb:.{precision}f}"

    return _COORD_PAIR.sub(sub, text), count


_COORD_PARENT_KEYS = frozenset(
    {
        "coord", "coords", "coordinate", "coordinates", "location", "position", "pos", "point", "geo",
        "latlng", "lnglat", "latlon", "lonlat", "pt", "loc", "center", "centre", "geometry", "gps",
    }
)  # fmt: skip


def _float_decimals(x: float) -> int:
    r = repr(x)
    return 0 if "e" in r or "E" in r else _decimals(r)


def _looks_like_coordinate_pair(node: Any, parent_key: str | None = None) -> bool:
    """[위도, 경도] 또는 [경도, 위도] 모양의 실수 두 개인가.

    부모 키가 좌표 단서(location·coord·position·point·geo·latlng 등)면 소수 4자리 이상이면 되고, 단서가 없으면 두 수 모두 소수 5자리
    이상이고 한 수가 10 이상일 때만 좌표로 본다(`{"probs": [0.12345, 0.98765]}` 같은 확률·비율은 건드리지 않는다).
    """
    if not isinstance(node, (list, tuple)) or len(node) != 2:
        return False
    a, b = node
    if any(isinstance(x, bool) or not isinstance(x, float) for x in (a, b)):
        return False
    if not (math.isfinite(a) and math.isfinite(b)) or not _valid_pair(a, b):
        return False
    da, db = _float_decimals(a), _float_decimals(b)
    if parent_key is not None and parent_key.lower() in _COORD_PARENT_KEYS:
        return da >= 4 and db >= 4
    return _precise_pair(a, b, da, db)


def _name_groups(members: Iterable[str | Sequence[str]]) -> tuple[tuple[str, ...], dict[str, str]]:
    """``prepare_transcript`` 와 같은 규칙: (이름 사전, 별칭 -> 대표 이름)."""
    groups: list[tuple[str, ...]] = []
    for item in members:
        parts = [item] if isinstance(item, str) else list(item)
        group = tuple(dict.fromkeys(" ".join(str(x).split()) for x in parts if x))
        if group:
            groups.append(group)
    names = tuple(dict.fromkeys(n for g in groups for n in g))
    aliases: dict[str, str] = {}
    for g in groups:
        for alias in g[1:]:
            aliases.setdefault(alias, g[0])
    return names, aliases


def _id_like(key: str) -> bool:
    """식별자 키(id, ids, *_id, *_ids, *Id, *ID, *Ids, *IDs): 숫자를 뭉개면 안 된다(값이 리스트여도 안쪽 숫자까지 보존)."""
    low = key.lower()
    return (
        low in ("id", "ids")
        or low.endswith(("_id", "_ids"))
        or key.endswith(("Id", "ID", "Ids", "IDs"))
    )


class PrivacySession:
    """한 요청 안의 자유 글·JSON 가명화 상태. 대응표는 ``pseudonymizer`` 메모리에만 있다(``repr`` 에는 개수만).

    같은 세션으로 여러 번 ``prepare_*`` 하면 같은 값은 같은 토큰이다. ``with`` 블록이나 ``close()`` 로 대응표 참조를 지운다.
    ``__slots__`` 라 ``vars(sess)``/``__dict__`` 가 없고, ``pickle``·``copy``·``dataclasses.replace`` 는 막혀 있다(코드가 속성을
    직접 읽는 것까지는 막지 못한다). ``restore_json(session, ...)`` 같은 기존 함수에도 ``Prepared`` 처럼 넘길 수 있다.
    """

    __slots__ = (
        "_known_names",
        "blocked_count",
        "coordinates_generalized",
        "counts_by_kind",
        "policy",
        "pseudonymizer",
    )

    def __init__(
        self, policy: Policy = ASSISTANT, members: Iterable[str | Sequence[str]] = ()
    ) -> None:
        names, aliases = _name_groups(members)
        self.policy = policy
        self.pseudonymizer = Pseudonymizer()
        self.pseudonymizer.set_aliases(aliases)
        self._known_names: tuple[str, ...] = names
        self.counts_by_kind: dict[str, int] = {}
        self.blocked_count = 0
        self.coordinates_generalized = 0

    @property
    def high_risk_count(self) -> int:
        """가린 RRN·CARD·ACCOUNT·SECRET 값의 총수(점수와 무관). 사용자 안내에는 ``blocked_count`` 보다 이것을 쓴다."""
        return sum(self.counts_by_kind.get(k, 0) for k in _HIGH_RISK_KINDS)

    def __repr__(self) -> str:
        return (
            f"<PrivacySession policy={self.policy.name} tokens={self.pseudonymizer.size} "
            f"high_risk={self.high_risk_count}>"
        )

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("PrivacySession 은 직렬화·복사할 수 없다")

    def __reduce_ex__(self, protocol):
        raise TypeError("PrivacySession 은 직렬화·복사할 수 없다")

    def __copy__(self):
        raise TypeError("PrivacySession 은 복사할 수 없다")

    def __deepcopy__(self, memo):
        raise TypeError("PrivacySession 은 복사할 수 없다")

    def close(self) -> None:
        self.pseudonymizer.clear()
        self._known_names = ()

    def __enter__(self) -> "PrivacySession":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    # ----- 가명화 -----
    def prepare_text(
        self, text: str, *, coordinate_precision: int = DEFAULT_COORDINATE_PRECISION
    ) -> str:
        """글 하나를 가명화해 돌려준다(개수·고위험 수는 세션에 쌓인다).

        글 속의 좌표 쌍('37.566535,126.977969': 소수점 4자리 이상 두 수, 위도 +-90·경도 +-180 안)은 소수점 둘째 자리로 절삭한다.
        """
        if not isinstance(text, str):
            raise TypeError("text 는 문자열이어야 한다")
        _check_precision(coordinate_precision)
        text, n = _generalize_coordinate_text(text, coordinate_precision)
        self.coordinates_generalized += n
        result = self.pseudonymizer.apply_values(text, self.policy, self._known_names)
        for kind, count in result.counts_by_kind.items():
            self.counts_by_kind[kind] = self.counts_by_kind.get(kind, 0) + count
        self.blocked_count += result.blocked_values
        return result.text

    def prepare_json(
        self,
        obj: Any,
        *,
        keys_to_drop: Iterable[str] = (),
        coordinate_keys: Iterable[str] = COORDINATE_KEYS,
        coordinate_precision: int = DEFAULT_COORDINATE_PRECISION,
        numbers: str | None = None,
        number_keys: Iterable[str] | None = None,
        pseudonymize_keys: bool = False,
    ) -> Any:
        """JSON 값(dict·list·tuple·set·str·숫자·bool·None·날짜)을 재귀로 가명화한 새 객체를 돌려준다(원본은 건드리지 않는다).

        - 문자열 **값**만 ``prepare_text`` 한다. 구조·키(``pseudonymize_keys=False``)·불리언·None·날짜는 그대로다.
          키가 사람 이름일 수 있는 dict({"김민수": 5000})는 ``pseudonymize_keys=True`` 로 키도 가명화한다. 서로 다른 키가 같은
          키로 바뀌어 값이 덮어써질 상황이면 ValueError(값을 잃지 않는다).
        - ``keys_to_drop`` 의 키는 값과 함께 뺀다(대소문자 무시). 좌표 키(``coordinate_keys``, 기본 lat/lng 등)의 값은
          ``generalize_coordinates`` 의 절삭 규칙으로 거칠게 만들고, 숫자로 해석되지 않으면 None 으로 둔다. ``keys_to_drop`` 이 우선한다.
          좌표 키가 아니어도 ``[위도, 경도]``·``[경도, 위도]`` 모양의 실수 두 개 리스트는 부모 키가 좌표 단서(location·coord·point·geo 등)이고 소수 4자리
          이상이거나, 단서 없이 두 수 모두 소수 5자리 이상이고 한 수가 10 이상이면 같은 규칙으로 절삭한다(확률 ``[0.12345, 0.98765]`` 는 그대로).
        - 숫자: ``numbers`` 가 ``"keep"`` 이면 그대로, ``"round"`` 면 유효숫자 2자리(``None`` 이면 ``policy.number_mode``).
          ``id``·``*_id``·``*Id`` 키의 숫자는 항상 보존한다. ``number_keys`` 를 주면 **그 키들의 숫자만** 뭉갠다(그 키 아래의 중첩 dict 값도 포함, id 키 아래는 제외; 기본 None: id 외 전부).
        - 지원하지 않는 형식(사용자 정의 객체 등)은 개인정보를 못 가릴 수 있어 TypeError. Pydantic 모델은 ``model_dump(mode="json")``.
        """
        mode = numbers if numbers is not None else self.policy.number_mode
        if mode not in ("keep", "round"):
            raise ValueError("numbers 는 keep 또는 round 다")
        _check_precision(coordinate_precision)
        drop = {str(k).lower() for k in keys_to_drop}
        coords = {str(k).lower() for k in coordinate_keys} - drop
        round_keys = None if number_keys is None else {str(k).lower() for k in number_keys}

        def walk(node: Any, depth: int, round_ok: bool, parent_key: str | None = None) -> Any:
            if depth > MAX_DEPTH:
                raise ValueError("JSON 이 너무 깊다")
            if isinstance(node, str):
                return self.prepare_text(node, coordinate_precision=coordinate_precision)
            if node is None or isinstance(node, (bool, date, datetime, time)):
                return node
            if isinstance(node, (int, float, Decimal)):
                return generalize_number(node) if mode == "round" and round_ok else node
            if isinstance(node, dict):
                out: dict[Any, Any] = {}
                for k, v in node.items():
                    ks = k.lower() if isinstance(k, str) else None
                    if ks in drop:
                        continue
                    new_key = (
                        self.prepare_text(k, coordinate_precision=coordinate_precision)
                        if pseudonymize_keys and isinstance(k, str)
                        else k
                    )
                    if new_key in out:
                        raise ValueError("키를 가명화하면 서로 다른 키가 같아져 값이 사라진다")
                    if ks in coords:
                        out[new_key] = _coord_value(v, coordinate_precision)
                        continue
                    if ks is not None and _id_like(k):
                        child_ok = False
                    elif round_keys is not None:
                        # 지정한 키 아래(중첩 dict 포함)는 그 키의 숫자로 본다. id 키 아래는 위에서 막힌다
                        child_ok = round_ok or ks in round_keys
                    else:
                        child_ok = True
                    out[new_key] = walk(v, depth + 1, child_ok, ks)
                return out
            if isinstance(node, (list, tuple)) and _looks_like_coordinate_pair(node, parent_key):
                self.coordinates_generalized += 1
                first = _trunc_coord(
                    node[0], coordinate_precision, 180.0, "a"
                )  # [경도, 위도] 순서도 있어 둘 다 180 까지 허용
                second = _trunc_coord(node[1], coordinate_precision, 180.0, "b")
                return type(node)((first, second))
            if isinstance(node, list):
                return [walk(x, depth + 1, round_ok, parent_key) for x in node]
            if isinstance(node, tuple):
                return tuple(walk(x, depth + 1, round_ok, parent_key) for x in node)
            if isinstance(node, (set, frozenset)):
                return type(node)(walk(x, depth + 1, round_ok, parent_key) for x in node)
            raise TypeError(f"지원하지 않는 형식: {type(node).__name__}")

        # NER 을 켠 경우 문자열 값을 모아 한 번(배치)에 추론한다(값마다 부르면 지연이 값 수만큼 곱해진다). 끄면 모으지도 않는다.
        if ner.current_mode() == "off":
            return walk(obj, 0, round_keys is None)
        texts = _collect_texts(obj, pseudonymize_keys, coordinate_precision)
        with ner.batch_scope(texts):
            return walk(obj, 0, round_keys is None)

    # ----- 복원 -----
    def restore_text(
        self, text: str, generalize_unknown: bool = False, scrub: bool = False
    ) -> JsonRestoreResult:
        """응답 글 하나를 복원한다(``gateway.restore_value`` 와 같은 규칙)."""
        return restore_value(self, text, generalize_unknown=generalize_unknown, scrub=scrub)  # type: ignore[arg-type]

    def restore_json(
        self, obj: Any, generalize_unknown: bool = False, scrub: bool = False
    ) -> JsonRestoreResult:
        """응답 JSON 을 복원한다(``gateway.restore_json`` 과 같은 규칙)."""
        return restore_json(self, obj, generalize_unknown=generalize_unknown, scrub=scrub)  # type: ignore[arg-type]

    def tokenize_mapped_names(self, text: str) -> str:
        """글에서 이 세션이 **이미 가명화한** 사람 이름만 같은 토큰으로 바꾼다(새 토큰·다른 개인정보·아직 가리지 않은 이름은 그대로)."""
        return self.pseudonymizer.tokenize_mapped_names(text)

    def tokenize_mapped_names_json(self, obj: Any) -> Any:
        """JSON 의 문자열 **값**에 ``tokenize_mapped_names`` 를 적용한 새 객체를 돌려준다(키·숫자·구조는 그대로). prepare_json 과 달리 결과 전체를
        가명화하지 않고, 질문 등에서 이미 토큰을 준 이름만 같은 토큰으로 맞춘다."""
        return _map_strings(obj, self.pseudonymizer.tokenize_mapped_names)

    def retokenize_values_json(self, obj: Any, tokens: Iterable[str]) -> Any:
        """JSON(또는 글)의 문자열 **값**에서, ``tokens`` 로 복원해 도구에 넘긴 원래 값과 똑같은 글자를 같은 토큰으로 되돌려 놓는다."""
        tokens = tuple(tokens)
        return _map_strings(obj, lambda text: self.pseudonymizer.retokenize_values(text, tokens))


def _map_strings(obj: Any, fn: Callable[[str], str]) -> Any:
    """JSON 의 문자열 값에 fn 을 적용한 새 객체(키·숫자·구조는 그대로)."""

    def walk(node: Any, depth: int) -> Any:
        if depth > MAX_DEPTH:
            raise ValueError("JSON 이 너무 깊다")
        if isinstance(node, str):
            return fn(node)
        if isinstance(node, list):
            return [walk(x, depth + 1) for x in node]
        if isinstance(node, tuple):
            return tuple(walk(x, depth + 1) for x in node)
        if isinstance(node, dict):
            return {k: walk(v, depth + 1) for k, v in node.items()}
        return node

    return walk(obj, 0)


def _collect_texts(node: Any, with_keys: bool, precision: int) -> list[str]:
    """prepare_json 이 ``prepare_text`` 에 넘길 문자열(좌표 절삭 뒤의 글)을 미리 모은다. 쓰이지 않는 값(버리는 키 등)까지 모으는
    것은 괜찮다(예산을 조금 더 쓸 뿐). 형식 검사는 본 처리(walk)가 한다."""
    out: list[str] = []
    stack = [(node, 0)]
    while stack:
        cur, depth = stack.pop()
        if depth > MAX_DEPTH:
            continue
        if isinstance(cur, str):
            out.append(_generalize_coordinate_text(cur, precision)[0])
        elif isinstance(cur, dict):
            for k, v in cur.items():
                if with_keys and isinstance(k, str):
                    out.append(_generalize_coordinate_text(k, precision)[0])
                stack.append((v, depth + 1))
        elif isinstance(cur, (list, tuple, set, frozenset)):
            stack.extend((x, depth + 1) for x in cur)
    return out


def _coord_value(value: Any, precision: int) -> Any:
    """좌표 키의 값: 숫자면 절삭, 아니면(해석 불가·bool·구조) None. 위도·경도 범위 검사는 +-180 으로 느슨하게 한다."""
    if isinstance(value, (dict, list, tuple, set, frozenset)) or value is None:
        return None
    try:
        return _trunc_coord(value, precision, 180.0, "coord")
    except ValueError:
        return None


_PLACEHOLDER_PHRASES = tuple(
    re.sub(r"\s+", "", p) for p in (*GENERIC_TEXT.values(), UNKNOWN_TEXT, SENSITIVE_TEXT)
)  # 공백을 지운 문구: '( 연락처 )', '(알 수 없는 항목)' 변형도 잡는다
_TOKEN_KINDS = "PHONE|EMAIL|ADDRESS|ADDR|PERSON|NAME|SECRET|RRN|CARD|ACCOUNT"
# 괄호 종류·공백·0 채움이 달라도 잡는다: [PERSON_1] (PERSON_1) <PHONE_1> {PERSON_1} ［ADDR_1］ ‹PERSON_1› [ADDRESS_1] [NAME_1]
_TOKEN_BRACKETED = re.compile(
    rf"[\[(<{{‹«]\s{{0,8}}(?:{_TOKEN_KINDS})[\s_]{{0,8}}\d{{0,6}}\s{{0,8}}[\])>}}›»]", re.IGNORECASE
)
# 괄호 없는 PERSON_1 · PHONE_1 (종류 이름과 일치할 때만)
_TOKEN_BARE = re.compile(
    rf"(?<![A-Za-z0-9])(?:{_TOKEN_KINDS})_\d{{1,6}}(?![A-Za-z0-9])", re.IGNORECASE
)
_INVISIBLE_STRIP = {ord(c): None for c in INVISIBLE_CHARS}


def contains_placeholders(obj: Any) -> bool:
    """문자열·JSON 에 일반화 문구(``(연락처)``·``(이메일)``·``(주소)``·``(사람)``·``(알 수 없는 항목)``·``(민감 정보)``), 복원 불가 고정 토큰
    (``[RRN]`` 등), 번호 토큰 모양(``[PERSON_3]``·``(PERSON_1)``·``<PHONE_1>``·``[ADDRESS_1]``·``[NAME_1]``·괄호 없는 ``PERSON_1``),
    무력화 토큰(``‹PHONE_1›``)이 있는가.

    검사 전에 폭 없는 문자(ZWSP 등)를 지우고 NFKC 로 접어(전각 괄호·숫자) 공백·대소문자 변형(``( 연락처 )``, ``[person_1]``)도 잡는다.
    사용자가 실제로 쓴 글(``회의 (주소) 확인``)도 True 가 될 수 있다(오탐은 안전한 방향이라 허용: 쓰기 도구 호출만 거부된다).
    모델이 쓰기 도구(일정·지출 저장 등)에 넘긴 인자는 복원한 뒤 이 검사를 통과해야 한다. True 면 그 도구 호출을 **거부**한다
    (일반화 문구나 자리표시가 그대로 DB 에 저장되는 것을 막는다). dict 의 키와 값, list·tuple·set 의 원소를 모두 본다.
    """

    def check(node: Any, depth: int) -> bool:
        if depth > MAX_DEPTH:
            return True  # 너무 깊으면 안전 쪽으로 본다
        if isinstance(node, str):
            s = unicodedata.normalize("NFKC", node.translate(_INVISIBLE_STRIP))
            compact = re.sub(r"\s+", "", s)
            if any(p in compact for p in _PLACEHOLDER_PHRASES) or any(
                f in compact.upper() for f in _FIXED_TOKENS
            ):
                return True
            return bool(_TOKEN_BRACKETED.search(s) or _TOKEN_BARE.search(s))
        if isinstance(node, dict):
            return any(check(k, depth + 1) or check(v, depth + 1) for k, v in node.items())
        if isinstance(node, (list, tuple, set, frozenset)):
            return any(check(x, depth + 1) for x in node)
        return False

    return check(obj, 0)


def new_session(
    policy: Policy = ASSISTANT, members: Iterable[str | Sequence[str]] = ()
) -> PrivacySession:
    """빈 세션을 만든다. members 는 ``prepare_transcript`` 와 같다(이름 하나 또는 같은 사람의 표기 묶음).

    mode=required 에서 NER 을 쓸 수 없으면 PrivacyUnavailable(외부 모델을 처음 부르기 전에 막는다: 에이전트는 세션을 먼저 만든다)."""
    ner.ensure_ready()
    return PrivacySession(policy, members)


def prepare_text(
    text: str,
    *,
    policy: Policy = ASSISTANT,
    members: Iterable[str | Sequence[str]] = (),
    session: PrivacySession | None = None,
) -> tuple[str, PrivacySession]:
    """자유 글 하나를 가명화한다. ``session`` 을 주면 그 세션의 대응표를 이어 쓴다(policy·members 는 무시).

    돌려준 세션은 호출부가 ``close()`` (또는 ``with``)로 지운다. 예외가 나면 새로 만든 세션은 여기서 지운다.
    """
    ner.ensure_ready()  # mode=required 에서 NER 을 쓸 수 없으면 503 privacy_unavailable
    sess = session or new_session(policy, members)
    try:
        return sess.prepare_text(text), sess
    except Exception:
        if session is None:
            sess.close()
        raise


def prepare_json(
    obj: Any,
    *,
    policy: Policy = ASSISTANT,
    members: Iterable[str | Sequence[str]] = (),
    keys_to_drop: Iterable[str] = (),
    coordinate_keys: Iterable[str] = COORDINATE_KEYS,
    coordinate_precision: int = DEFAULT_COORDINATE_PRECISION,
    numbers: str | None = None,
    number_keys: Iterable[str] | None = None,
    pseudonymize_keys: bool = False,
    session: PrivacySession | None = None,
) -> tuple[Any, PrivacySession]:
    """JSON 을 가명화한다(``PrivacySession.prepare_json`` 참고). 돌려준 세션은 호출부가 지운다."""
    ner.ensure_ready()  # mode=required 에서 NER 을 쓸 수 없으면 503 privacy_unavailable
    sess = session or new_session(policy, members)
    try:
        value = sess.prepare_json(
            obj,
            keys_to_drop=keys_to_drop,
            coordinate_keys=coordinate_keys,
            coordinate_precision=coordinate_precision,
            numbers=numbers,
            number_keys=number_keys,
            pseudonymize_keys=pseudonymize_keys,
        )
        return value, sess
    except Exception:
        if session is None:
            sess.close()
        raise
