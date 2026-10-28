"""경량 한국어 NER(KoELECTRA-small, ONNX) 보강 어댑터. 규칙 탐지(``detectors``)를 대체하지 않고 이름·주소를 **더한다**.

사용하는 쪽(가족 채팅 AI·일정 에이전트 등)은 코드를 바꾸지 않는다. ``Pseudonymizer.apply``/``apply_values`` 가 규칙 탐지 대신
이 모듈의 ``detect_with_ner`` 를 부르고, ``prepare_transcript`` 는 줄 전체를 ``batch_scope`` 로 한 번에 추론한다.

- 모델 파일은 저장소에 없다. 서버 폴더(``PRIVACY_NER_MODEL_DIR``, 기본 ``<DATA_DIR>/models/ner``)의 ``model.onnx``(또는 int8),
  ``tokenizer.json``, ``labels.json``, ``model_card.json`` 을 읽는다. 새 의존성은 없다(``onnxruntime``·``tokenizers``·``numpy``).
- ``PRIVACY_NER_MODE``: ``off``(안 씀) / ``auto``(쓸 수 있으면 쓰고, 없거나 실패하면 규칙만 + 프로세스당 한 번 경고) /
  ``required``(쓸 수 없으면 503 ``privacy_unavailable``, fail-closed). 알 수 없는 값은 안전 쪽인 ``required`` 로 본다.
- 로그에는 글자·값·경로를 남기지 않는다. 모델 입력·결과 캐시는 프로세스 메모리 안에서만(해시 키, 작은 LRU) 있다.
- 한계: 모델이 틀릴 수 있다(오탐·미탐). 마스킹은 위험을 줄일 뿐 보호를 보장하지 않는다.
"""

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.shared.errors import ApiError

from .detectors import _FOLD, _INVISIBLE, INVISIBLE_CHARS, KINSHIP_TERMS, detect
from .types import Kind, Span

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 상수(정책 판단은 여기서 바꾼다)
# ---------------------------------------------------------------------------
# 모델 라벨 -> 탐지 종류. 여기에 없는 라벨(LOCATION: 랜드마크·지역명, ORGANIZATION: 기관명)은 마스킹 기본 제외 정책이라
# **내보내지 않는다**. 정책을 바꾸려면 이 표에 줄을 더한다(예: "LOCATION": Kind.ADDRESS). 가족 호칭(엄마·아빠)은 모델이 라벨하지 않고,
# 혹시 라벨해도 아래에서 KINSHIP_TERMS 와 같으면 버린다.
LABEL_TO_KIND: dict[str, Kind] = {
    "PERSON": Kind.PERSON,
    "PERSON_ALIAS": Kind.PERSON,
    "ADDRESS": Kind.ADDRESS,
}
# NER 탐지 점수 범위. 상한 0.69 는 정책 기본 ``block_min_score`` 0.7 바로 아래다: PERSON·ADDRESS 가 어떤 정책에서 BLOCK 이 되더라도
# NER 탐지만으로는 메시지 통째 제외가 되지 않고 **값만 가명화**된다(현재 모든 정책에서 PERSON·ADDRESS 는 MASK 라 영향은 없다).
# 하한 0.5 미만(모델이 자신 없는 것)은 버린다.
NER_MIN_SCORE = 0.5
NER_MAX_SCORE = 0.69

DEFAULT_MAX_LEN = 128
WINDOW_OVERLAP = 32  # 슬라이딩 윈도우 겹침(토큰). 겹치는 토큰은 창 가장자리에서 먼 쪽의 예측을 쓴다
BATCH_SIZE = 64  # 한 번에 모델에 넣는 창 수(길이순으로 묶어 패딩 낭비가 작다)
MAX_INPUT_CHARS = 8000  # 글 하나의 입력 길이 상한(넘는 뒷부분은 NER 을 안 쓴다)
MAX_WINDOWS = 24  # 글 하나의 윈도우 수 상한
CACHE_SIZE = 512  # 최근 입력 해시 -> 결과(스팬만 든다. 대화 재가명화·같은 도구 결과 반복에 적중하도록 줄 수보다 크게)
RETRY_SECONDS = 60.0  # 로드 실패 뒤 다시 시도하기까지(모델 파일을 나중에 복사하는 경우)
# 요청(prepare_* 한 번) 단위 비용 상한. 글자 수는 추론이 필요한 글(캐시 적중 제외)의 합이다. 근거: 실측 긴 줄(2000자) 기준 약 110us/글자(2스레드) 라 30000자 ≈ 3.4초(짧은 줄은 더 빠르다).
# 가족 채팅 분석의 글자 한도(12000자)의 2.5배이고 정상적인 도구 결과 JSON 보다 넉넉하며, 넘으면 auto 는 초과분만 규칙으로, required 는 503 이다.
BATCH_MAX_CHARS = 30000
BATCH_MAX_TEXTS = 3000
TIME_BUDGET_SECONDS = 10.0  # 한 번의 추론 호출 시간 상한(넘으면 중단: auto 규칙만, required 503)
QUEUE_WAIT_SECONDS = 8.0  # 동시 추론 슬롯을 기다리는 시간 상한
MAX_CONCURRENCY_DEFAULT = 2
MODES = ("off", "auto", "required")
_SALT = os.urandom(
    16
)  # 캐시 키 해시용(프로세스마다 다름: 메모리 덤프에서 짧은 이름 사전 대입을 어렵게)

PRIVACY_UNAVAILABLE_MESSAGE = "개인정보 보호 엔진을 사용할 수 없어 AI 요청을 보내지 않았어요"


class NerTimeout(Exception):
    """추론이 시간 상한을 넘었다."""


class NerBusy(Exception):
    """동시 추론 슬롯을 기다리다 시간이 지났다."""


class ModelIntegrityError(ValueError):
    """model_card.json 의 sha256 과 실제 파일이 다르다."""


class PrivacyUnavailable(ApiError):
    """mode=required 에서 NER 을 쓸 수 없을 때. 공통 에러 형식(503 ``privacy_unavailable``)이며 원인·경로·글자를 담지 않는다."""

    def __init__(self) -> None:
        super().__init__(503, "privacy_unavailable", PRIVACY_UNAVAILABLE_MESSAGE)


@dataclass(frozen=True)
class NerSpan:
    """모델이 찾은 구간(문자 단위, 원문 위치 기준 [start, end))."""

    label: str
    start: int
    end: int
    score: float


@dataclass(frozen=True)
class NerResult:
    spans: tuple[NerSpan, ...]
    truncated: bool = False  # 길이·윈도우 상한 때문에 뒷부분을 NER 로 보지 못했다


# ---------------------------------------------------------------------------
# 입력 정규화(detectors 와 같은 방식 + 원문 위치 매핑)
# ---------------------------------------------------------------------------
_JAMO = re.compile("[ᄀ-ᇿ]")


def _normalize(text: str) -> tuple[str, list[int] | None, list[int] | None]:
    """전각·대시는 반각으로(길이 불변), 보이지 않는 문자는 지우고, 조합형(NFD) 한글 자모는 완성형 음절로 합친다.

    바뀐 글이 있으면 plain 위치 -> 원문 [시작, 끝) 표(starts, ends)도 돌려준다(없으면 None: 위치가 같다)."""
    folded = text.translate(_FOLD)
    if not (_INVISIBLE.search(folded) or _JAMO.search(folded)):
        return folded, None, None
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    i, n = 0, len(folded)
    while i < n:
        ch = folded[i]
        if ch in INVISIBLE_CHARS:
            i += 1
            continue
        if 0x1100 <= ord(ch) <= 0x1112 and i + 1 < n and 0x1161 <= ord(folded[i + 1]) <= 0x1175:
            lead, vowel, j, tail = ord(ch) - 0x1100, ord(folded[i + 1]) - 0x1161, i + 2, 0
            if j < n and 0x11A8 <= ord(folded[j]) <= 0x11C2:
                tail, j = ord(folded[j]) - 0x11A7, j + 1
            out.append(chr(0xAC00 + (lead * 21 + vowel) * 28 + tail))
            starts.append(i)
            ends.append(j)
            i = j
            continue
        out.append(ch)
        starts.append(i)
        ends.append(i + 1)
        i += 1
    return "".join(out), starts, ends


def _has_hangul(text: str) -> bool:
    return any("가" <= ch <= "힣" or "ᄀ" <= ch <= "ᇿ" for ch in text)


# ---------------------------------------------------------------------------
# 엔진
# ---------------------------------------------------------------------------
def _parse_labels(raw: Any) -> dict[int, str]:
    """labels.json: ``{"id2label": {"0": "O", ...}, ...}`` 또는 그 안쪽 사전·목록 자체."""
    if isinstance(raw, dict) and "id2label" in raw:
        raw = raw["id2label"]
    items = raw.items() if isinstance(raw, dict) else enumerate(raw)
    return {int(k): str(v) for k, v in items}


class NerEngine:
    """tokenizer + ONNX 세션을 감싼 추론기. 객체를 주입할 수 있어(``session`` 은 ``get_inputs``·``run`` 만 있으면 된다) 시험에서
    가짜 세션을 쓴다. 세션 실행은 스레드 안전하다(요청별 상태는 지역 변수에만 둔다)."""

    def __init__(
        self,
        tokenizer: Any,
        session: Any,
        id2label: dict[int, str],
        *,
        max_len: int = DEFAULT_MAX_LEN,
        overlap: int = WINDOW_OVERLAP,
        batch_size: int = BATCH_SIZE,
        max_chars: int = MAX_INPUT_CHARS,
        max_windows: int = MAX_WINDOWS,
        fingerprint: str = "",
    ) -> None:
        if max_len < 8 or not 0 <= overlap < max_len - 2:
            raise ValueError("max_len·overlap 값이 올바르지 않다")
        self._tok = tokenizer
        self._session = session
        self._labels = id2label
        self._num_labels = max(id2label) + 1
        self.max_len = max_len
        self._overlap = overlap
        self._batch = max(1, batch_size)
        self.max_chars = max_chars
        self.max_windows = max_windows
        self.fingerprint = fingerprint
        for name in ("no_truncation", "no_padding"):
            fn = getattr(tokenizer, name, None)
            if fn:
                fn()
        self._cls = tokenizer.token_to_id("[CLS]")
        self._sep = tokenizer.token_to_id("[SEP]")
        self._pad = tokenizer.token_to_id("[PAD]") or 0
        if self._cls is None or self._sep is None:
            raise ValueError("tokenizer 에 [CLS]/[SEP] 가 없다")
        self._input_names = {i.name for i in session.get_inputs()}

    # ----- 공개 -----
    def predict(self, text: str) -> list[NerSpan]:
        return list(self.analyze_many([text])[0].spans)

    def predict_many(self, texts: Sequence[str]) -> list[list[NerSpan]]:
        return [list(r.spans) for r in self.analyze_many(texts)]

    def analyze_many(self, texts: Sequence[str], deadline: float | None = None) -> list[NerResult]:
        """글 여러 개를 윈도우로 나눠 한꺼번에 추론한다. 결과 순서는 입력 순서다. deadline(time.monotonic 값)을 넘기면 NerTimeout."""
        import numpy as np

        plains: list[tuple[str, list[int] | None, list[int] | None]] = []
        encs: list[tuple[list[int], list[tuple[int, int]]]] = []
        truncated = [False] * len(texts)
        windows: list[tuple[int, int, list[int]]] = []  # (글 번호, 시작 토큰, 토큰 id)
        for ti, text in enumerate(texts):
            if len(text) > self.max_chars:
                text = text[: self.max_chars]
                truncated[ti] = True
            plain, starts_map, ends_map = _normalize(text)
            plains.append((plain, starts_map, ends_map))
            enc = self._tok.encode(plain, add_special_tokens=False)
            ids, offsets = list(enc.ids), [tuple(o) for o in enc.offsets]
            n = len(ids)
            content = self.max_len - 2
            step = content - self._overlap
            starts = [0] if n else []
            while starts and starts[-1] + content < n:
                starts.append(starts[-1] + step)
            if len(starts) > self.max_windows:
                starts = starts[: self.max_windows]
                truncated[ti] = True
                n = min(n, starts[-1] + content)
                ids, offsets = ids[:n], offsets[:n]
            encs.append((ids, offsets))
            for s in starts:
                windows.append((ti, s, ids[s : s + content]))

        # 토큰마다 창 가운데에 가장 가까운 예측의 logits 를 쓴다
        best = [np.zeros((len(ids), self._num_labels), dtype=np.float32) for ids, _ in encs]
        best_c = [np.full(len(ids), -1, dtype=np.int32) for ids, _ in encs]
        # 길이가 비슷한 창끼리 묶어 패딩 낭비를 줄인다(결과는 창이 가진 글·위치 번호로 되돌려 놓으므로 순서와 무관)
        windows.sort(key=lambda w: len(w[2]))
        for b in range(0, len(windows), self._batch):
            if deadline is not None and time.monotonic() > deadline:
                raise NerTimeout
            chunk = windows[b : b + self._batch]
            width = max(len(w[2]) for w in chunk) + 2
            input_ids = np.full((len(chunk), width), self._pad, dtype=np.int64)
            mask = np.zeros((len(chunk), width), dtype=np.int64)
            for r, (_, _, ids) in enumerate(chunk):
                seq = [self._cls, *ids, self._sep]
                input_ids[r, : len(seq)] = seq
                mask[r, : len(seq)] = 1
            feed: dict[str, Any] = {"input_ids": input_ids, "attention_mask": mask}
            if "token_type_ids" in self._input_names:
                feed["token_type_ids"] = np.zeros_like(input_ids)
            logits = np.asarray(self._session.run(None, feed)[0])
            if (
                logits.ndim != 3
                or logits.shape[0] != len(chunk)
                or logits.shape[2] < self._num_labels
            ):
                raise ValueError("모델 출력 모양이 맞지 않는다")
            for r, (ti, start, ids) in enumerate(chunk):
                m = len(ids)
                for j in range(m):
                    centrality = min(j, m - 1 - j)
                    g = start + j
                    if centrality > best_c[ti][g]:
                        best_c[ti][g] = centrality
                        best[ti][g] = logits[r, j + 1, : self._num_labels]

        out: list[NerResult] = []
        for ti, (ids, offsets) in enumerate(encs):
            plain, starts_map, ends_map = plains[ti]
            spans = self._decode(plain, starts_map, ends_map, offsets, best[ti]) if ids else []
            out.append(NerResult(tuple(spans), truncated[ti]))
        return out

    # ----- BIO 디코딩 -----
    def _decode(
        self,
        plain: str,
        starts_map: list[int] | None,
        ends_map: list[int] | None,
        offsets: list[tuple[int, int]],
        logits: Any,
    ) -> list[NerSpan]:
        import numpy as np

        shifted = logits - logits.max(axis=1, keepdims=True)
        probs = np.exp(shifted)
        probs /= probs.sum(axis=1, keepdims=True)
        pred = probs.argmax(axis=1)
        spans: list[NerSpan] = []
        cur: tuple[str, int, int, list[float]] | None = None  # (라벨, 시작 문자, 끝 문자, 확률들)

        def close() -> None:
            nonlocal cur
            if cur is None:
                return
            label, s, e, ps = cur
            cur = None
            while s < e and plain[s].isspace():
                s += 1
            while e > s and plain[e - 1].isspace():
                e -= 1
            if e <= s:
                return
            if starts_map is not None and ends_map is not None:
                s, e = starts_map[s], ends_map[e - 1]
            spans.append(NerSpan(label, s, e, float(sum(ps) / len(ps))))

        for i, (cs, ce) in enumerate(offsets):
            tag = self._labels.get(int(pred[i]), "O")
            if tag == "O" or ce <= cs:
                close()
                continue
            prefix, _, label = tag.partition("-") if tag[:2] in ("B-", "I-") else ("I", "", tag)
            p = float(probs[i, pred[i]])
            if prefix == "B" or cur is None or cur[0] != label:
                close()
                cur = (label, cs, ce, [p])
            else:
                cur = (label, cur[1], ce, [*cur[3], p])
        close()
        return spans

    # ----- 파일에서 만들기 -----
    @classmethod
    def from_dir(cls, model_dir: Path, model_file: str, threads: int) -> "NerEngine":
        model_path = model_dir / model_file
        if (
            not model_path.is_file()
        ):  # 모델이 없는 환경(CI·로컬)에서는 onnxruntime 을 불러오지도 않는다
            raise FileNotFoundError("model file")
        card: dict[str, Any] = {}
        card_path = model_dir / "model_card.json"
        if card_path.is_file():
            card = json.loads(card_path.read_bytes())
        card_hashes = card.get("sha256") or {}
        # 무결성: model_card.json 의 sha256 과 실제 파일을 대조한다(로드 때 한 번). 카드나 해시가 없으면 경고만 한다.
        model_sha = _sha256_file(model_path)
        for name in (model_file, "tokenizer.json", "labels.json"):
            expected = card_hashes.get(name)
            if not expected:
                _warn_once(
                    "nohash", "model_card.json 에 sha256 이 없어 모델 파일 무결성을 확인하지 못했다"
                )
                continue
            actual = model_sha if name == model_file else _sha256_file(model_dir / name)
            if actual != str(expected).lower():
                raise ModelIntegrityError(name)
        import onnxruntime as ort
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        id2label = _parse_labels(
            json.loads((model_dir / "labels.json").read_text(encoding="utf-8"))
        )
        max_len = int(card.get("max_len") or card.get("max_length") or DEFAULT_MAX_LEN)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, int(threads))
        opts.inter_op_num_threads = 1
        session = ort.InferenceSession(
            str(model_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        engine = cls(tokenizer, session, id2label, max_len=max_len, fingerprint=model_sha[:12])
        engine.predict("테스트")  # 첫 호출 지연을 앞당기고 모델·라벨 크기가 맞는지 확인한다
        return engine


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 설정·싱글턴·캐시
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Config:
    mode: str
    model_dir: str
    model_file: str
    threads: int
    concurrency: int = MAX_CONCURRENCY_DEFAULT


def _config() -> _Config:
    from app.shared.config import settings

    mode = str(settings.privacy_ner_mode or "").strip().lower()
    if mode not in MODES:
        mode = "required"  # 오타는 안전 쪽(fail-closed)
    model_dir = (settings.privacy_ner_model_dir or "").strip() or str(
        Path(settings.data_dir) / "models" / "ner"
    )
    model_file = (settings.privacy_ner_model_file or "").strip() or "model.onnx"
    return _Config(
        mode,
        model_dir,
        model_file,
        int(settings.privacy_ner_threads),
        max(1, int(settings.privacy_ner_max_concurrency)),
    )


def current_mode() -> str:
    return _config().mode


def _load_engine(cfg: _Config) -> NerEngine:
    """모델 폴더에서 엔진을 만든다(시험에서 바꿔 끼울 수 있다)."""
    return NerEngine.from_dir(Path(cfg.model_dir), cfg.model_file, cfg.threads)


@dataclass
class _State:
    cfg: _Config
    engine: NerEngine | None
    retry_at: float


_lock = threading.Lock()  # 상태·세마포어 짧은 구간용(로드 중에는 잡지 않는다)
_load_lock = threading.Lock()  # 모델 로드는 한 번에 하나
_state: _State | None = None
_warned: set[str] = set()
_cache: "OrderedDict[tuple[str, str], NerResult]" = OrderedDict()
_cache_lock = threading.Lock()
_sem: tuple[int, threading.BoundedSemaphore] | None = None


def reset() -> None:
    """엔진·캐시·경고 표시를 비운다(시험·설정 변경용)."""
    global _state, _sem
    with _lock:
        _state = None
        _sem = None
    _warned.clear()
    with _cache_lock:
        _cache.clear()


def _warn_once(key: str, message: str, level: int = logging.WARNING) -> None:
    if key in _warned:
        return
    _warned.add(key)
    log.log(level, message)  # 글자·값·경로를 담지 않는다


def _fresh_state(cfg: _Config) -> _State | None:
    st = _state
    if (
        st is not None
        and st.cfg == cfg
        and (st.engine is not None or time.monotonic() < st.retry_at)
    ):
        return st
    return None


def _get_engine(cfg: _Config) -> NerEngine | None:
    """싱글턴 엔진. 로드는 락 밖(``_load_lock``)에서 한다: auto 는 다른 스레드가 로드 중이면 기다리지 않고 규칙만(None)을 돌려주고,
    required 는 로드가 끝나길 기다린다."""
    global _state
    with _lock:
        st = _fresh_state(cfg)
    if st is not None:
        return st.engine
    if cfg.mode == "required":
        _load_lock.acquire()
    elif not _load_lock.acquire(blocking=False):
        return None
    try:
        with _lock:  # 기다리는 동안 다른 스레드가 이미 로드했을 수 있다
            st = _fresh_state(cfg)
        if st is not None:
            return st.engine
        started = time.monotonic()
        try:
            engine = _load_engine(cfg)
        except Exception as e:  # 경로·내용은 로그에 남기지 않고 예외 종류만
            engine = None
            if cfg.mode == "required":
                _warn_once(
                    "load",
                    f"NER 엔진을 불러오지 못했다(종류={type(e).__name__}). mode=required 라 가명화 요청은 503 으로 거부된다",
                    logging.ERROR,
                )
            else:
                _warn_once(
                    "load",
                    f"NER 엔진을 불러오지 못했다(종류={type(e).__name__}). 규칙 탐지만 사용한다",
                )
        else:
            log.info(
                "NER 엔진 준비 완료 (mode=%s, 모델 파일=%s, 지문=%s, 스레드=%d, 동시 추론=%d, 로드 %.1f초)",
                cfg.mode,
                cfg.model_file,
                engine.fingerprint,
                cfg.threads,
                cfg.concurrency,
                time.monotonic() - started,
            )
        with _lock:
            _state = _State(cfg, engine, 0.0 if engine else time.monotonic() + RETRY_SECONDS)
        return engine
    finally:
        _load_lock.release()


def _engine_or_none(cfg: _Config) -> NerEngine | None:
    """off 면 None. auto 에서 못 쓰면 None. required 에서 못 쓰면 PrivacyUnavailable."""
    if cfg.mode == "off":
        return None
    engine = _get_engine(cfg)
    if engine is None and cfg.mode == "required":
        raise PrivacyUnavailable
    return engine


def ensure_ready() -> None:
    """공개 함수 경계에서 부른다. mode=required 인데 NER 을 쓸 수 없으면 PrivacyUnavailable(외부 호출 전에 막는다). off·auto 는 아무 일도 하지 않는다."""
    cfg = _config()
    if cfg.mode == "required":
        _engine_or_none(cfg)


def start_preload() -> threading.Thread | None:
    """서버 시작 때 백그라운드로 모델을 미리 불러와 첫 요청이 느려지지 않게 한다(off 면 아무 일도 안 한다). 실패해도 서버 기동은 막지 않는다:
    결과는 로그(성공 INFO / 실패 WARNING·ERROR)에만 남고, required 는 요청 시점에 fail-closed 다."""
    if _config().mode == "off":
        return None

    def run() -> None:
        try:
            _get_engine(_config())
        except Exception as e:
            log.error("NER 미리 불러오기 실패(종류=%s)", type(e).__name__)

    t = threading.Thread(target=run, name="privacy-ner-preload", daemon=True)
    t.start()
    return t


def ner_status() -> dict[str, Any]:
    """진단용 요약(글자·경로 없음): 모드, 지금 쓸 수 있는지, 모델 지문."""
    cfg = _config()
    engine = None if cfg.mode == "off" else _get_engine(cfg)
    return {
        "mode": cfg.mode,
        "active": engine is not None,
        "fingerprint": engine.fingerprint if engine else "",
    }


def _digest(engine: NerEngine, text: str) -> tuple[str, str]:
    return (
        engine.fingerprint or str(id(engine)),
        hashlib.sha256(_SALT + text.encode()).hexdigest(),
    )


def _cache_get(key: tuple[str, str]) -> NerResult | None:
    with _cache_lock:
        res = _cache.get(key)
        if res is not None:
            _cache.move_to_end(key)
        return res


def _cache_put(key: tuple[str, str], res: NerResult) -> None:
    with _cache_lock:
        _cache[key] = res
        _cache.move_to_end(key)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)


def _worth(text: str) -> bool:
    """한글이 없는 글(숫자·영문 코드·URL 등)은 모델이 볼 이유가 없다. 지연을 아끼는 조기 반환이다."""
    return _has_hangul(text)


def _semaphore(n: int) -> threading.BoundedSemaphore:
    global _sem
    with _lock:
        if _sem is None or _sem[0] != n:
            _sem = (n, threading.BoundedSemaphore(n))
        return _sem[1]


def _fail(mode: str, key: str, message: str) -> None:
    """추론을 못 쓴 경우의 mode 별 처리: required 는 fail-closed, auto 는 경고 한 번 뒤 규칙만."""
    if mode == "required":
        raise PrivacyUnavailable
    _warn_once(key, message)


def _infer(engine: NerEngine, texts: list[str], cfg: _Config) -> dict[str, NerResult] | None:
    """캐시에 없는 글을 한 번에(배치) 추론한다. 동시 추론 수·시간 상한을 지킨다. 실패하면 mode 별로 처리한다(auto: None, required: 예외)."""
    mode = cfg.mode
    sem = _semaphore(cfg.concurrency)
    if not sem.acquire(timeout=QUEUE_WAIT_SECONDS):
        _fail(mode, "busy", "NER 추론 대기가 길어져 규칙 탐지만 사용한다(동시 추론 상한)")
        return None
    try:
        results = engine.analyze_many(texts, deadline=time.monotonic() + TIME_BUDGET_SECONDS)
    except NerTimeout:
        _fail(mode, "timeout", "NER 추론이 시간 상한을 넘어 규칙 탐지만 사용한다")
        return None
    except Exception as e:
        _fail(mode, "infer", f"NER 추론에 실패해 규칙 탐지만 사용한다(종류={type(e).__name__})")
        return None
    finally:
        sem.release()
    out: dict[str, NerResult] = {}
    for text, res in zip(texts, results, strict=True):
        if res.truncated:
            _fail(
                mode, "limit", "입력이 NER 상한(길이·윈도우)을 넘어 초과분은 규칙 탐지만 사용한다"
            )
        out[text] = res
        _cache_put(_digest(engine, text), res)
    return out


# ---------------------------------------------------------------------------
# 배치 범위(prepare_* 가 글 여러 개를 한 번에 추론)
# ---------------------------------------------------------------------------
@dataclass
class _Scope:
    results: dict[str, NerResult] = field(default_factory=dict)
    skipped: set[str] = field(default_factory=set)  # 예산 초과: 규칙만
    failed: bool = False  # auto 에서 배치 추론이 실패했다 -> 이 범위에서는 규칙만


_scope: ContextVar[_Scope | None] = ContextVar("privacy_ner_scope", default=None)


@contextmanager
def batch_scope(texts: Sequence[str], *, newest_last: bool = False) -> Iterator[None]:
    """블록 안의 ``detect_with_ner`` 가 이 글들의 NER 결과를 미리 한 번에(배치) 구해 쓰게 한다. off·모델 없음(auto)이면 아무 일도 안 한다.

    요청 단위 예산(``BATCH_MAX_CHARS``·``BATCH_MAX_TEXTS``)을 넘는 글은 추론하지 않는다: auto 는 그 글만 규칙으로(경고 한 번),
    required 는 PrivacyUnavailable. ``newest_last=True`` 면 뒤쪽 글이 최신이라 예산을 뒤에서부터 쓴다(대화 줄 순서)."""
    cfg = _config()
    engine = _engine_or_none(cfg)  # required 에서 못 쓰면 여기서 예외
    if engine is None:
        yield
        return
    scope = _Scope()
    unique = list(dict.fromkeys(t for t in texts if t and _worth(t)))
    if newest_last:
        unique.reverse()
    todo: list[str] = []
    chars = 0
    for text in unique:
        cached = _cache_get(_digest(engine, text))
        if cached is not None:
            scope.results[text] = cached
            continue
        cost = min(len(text), engine.max_chars)
        if len(todo) >= BATCH_MAX_TEXTS or chars + cost > BATCH_MAX_CHARS:
            scope.skipped.add(text)
            continue
        todo.append(text)
        chars += cost
    if scope.skipped:
        _fail(cfg.mode, "budget", "NER 요청 예산(글자·개수)을 넘은 글은 규칙 탐지만 사용한다")
    if todo:
        got = _infer(engine, todo, cfg)
        if got is None:
            scope.failed = True
        else:
            scope.results.update(got)
    token = _scope.set(scope)
    try:
        yield
    finally:
        _scope.reset(token)


def spans_for(text: str) -> list[NerSpan] | None:
    """text 의 NER 구간. NER 을 안 쓰면(off·auto 에서 못 씀·실패) None, 글에 볼 것이 없으면 빈 목록. required 에서 못 쓰면 예외."""
    cfg = _config()
    if cfg.mode == "off" or not text:
        return None
    scope = _scope.get()
    if scope is not None:
        if scope.failed or text in scope.skipped:
            return None
        hit = scope.results.get(text)
        if hit is not None:
            return list(hit.spans)
    engine = _engine_or_none(cfg)
    if engine is None:
        return None
    if not _worth(text):
        return []
    key = _digest(engine, text)
    cached = _cache_get(key)
    if cached is None:
        got = _infer(engine, [text], cfg)
        if got is None:
            return None
        cached = got[text]
    return list(cached.spans)


# ---------------------------------------------------------------------------
# 병합
# ---------------------------------------------------------------------------
_TRIM = " \t\r\n.,;:!?~·…()[]{}\"'“”‘’"
# 주소 끝의 조사 한 글자('202호로' -> '202호'): 숫자·호·동·층·번·지 바로 뒤의 조사만 뗀다('테헤란로' 의 로는 건드리지 않는다)
_ADDR_TAIL = re.compile(r"(?<=[0-9호동층번지])[로에의은는이가을를도만]$")


def _overlaps(a: Span, b: Span) -> bool:
    return a.start < b.end and b.start < a.end


def _trim(text: str, start: int, end: int, kind: Kind) -> tuple[int, int]:
    while start < end and text[start] in _TRIM:
        start += 1
    while end > start and text[end - 1] in _TRIM:
        end -= 1
    if kind is Kind.ADDRESS and end - start > 1 and _ADDR_TAIL.search(text[start:end]):
        end -= 1
    return start, end


def _leftovers(start: int, end: int, covered: list[Span]) -> list[tuple[int, int]]:
    """[start, end) 중 covered 구간들이 덮지 못한 조각."""
    pieces, pos = [], start
    for r in sorted(covered, key=lambda x: x.start):
        if r.start > pos:
            pieces.append((pos, min(r.start, end)))
        pos = max(pos, r.end)
    if pos < end:
        pieces.append((pos, end))
    return [(a, b) for a, b in pieces if a < b]


def merge_ner(text: str, rule_spans: list[Span], ner_spans: Sequence[NerSpan]) -> list[Span]:
    """규칙 탐지를 우선하며 NER 구간을 더한다(시작 위치순). 규칙 구간의 종류·점수는 어떤 경우에도 바뀌지 않는다.

    - 규칙 구간과 겹치지 않는 NER 구간은 그대로 더한다.
    - 같은 종류(ADDRESS·PERSON)이고 NER 구간이 겹친 규칙 구간들을 **모두 감싸며 더 넓으면** 규칙 구간들을 NER 범위로 넓힌다(점수·출처 유지,
      이름 사전의 대표 이름이 있는 PERSON 은 넓히지 않는다). 그렇지 않은 부분 겹침과 다른 종류와의 겹침은 규칙 구간이 덮지 못한
      나머지 조각만 별도 구간으로 더한다(2글자 미만은 버린다).
    NER 점수는 [NER_MIN_SCORE, NER_MAX_SCORE] 로 제한한다."""
    result = list(rule_spans)
    cands: list[Span] = []
    for s in ner_spans:
        kind = LABEL_TO_KIND.get(s.label)
        if kind is None or s.score < NER_MIN_SCORE or not 0 <= s.start < s.end <= len(text):
            continue
        a, b = _trim(text, s.start, s.end, kind)
        value = text[a:b]
        if b <= a or value in KINSHIP_TERMS or (kind is Kind.PERSON and len(value) < 2):
            continue
        cands.append(Span(kind, a, b, min(s.score, NER_MAX_SCORE), "ner"))
    changed = False
    for cand in sorted(cands, key=lambda c: c.start):
        over = [r for r in result if _overlaps(cand, r)]
        if not over:
            result.append(cand)
            changed = True
            continue
        lo, hi = min(r.start for r in over), max(r.end for r in over)
        if (
            all(r.kind is cand.kind for r in over)
            and all(r.canonical is None for r in over)
            and cand.start <= lo
            and cand.end >= hi
        ):
            if _leftovers(
                cand.start, cand.end, over
            ):  # 규칙 구간들을 NER 범위로 넓힌다(사이·바깥의 빈 곳이 있을 때)
                first = over[0]
                result = [r for r in result if r not in over]
                result.append(
                    Span(
                        cand.kind,
                        cand.start,
                        cand.end,
                        max(r.score for r in over),
                        first.source,
                        first.canonical,
                    )
                )
                changed = True
            continue
        for a, b in _leftovers(cand.start, cand.end, over):
            a, b = _trim(text, a, b, cand.kind)
            if b - a >= 2:
                result.append(Span(cand.kind, a, b, cand.score, "ner"))
                changed = True
    if not changed:
        return rule_spans
    return sorted(result, key=lambda x: x.start)


def detect_with_ner(text: str, known_names: tuple[str, ...] | list[str] = ()) -> list[Span]:
    """``detectors.detect`` 와 같은 결과 + NER 보강. NER 을 안 쓰는 환경에서는 ``detect`` 와 완전히 같다."""
    rule = detect(text, known_names)
    ner = spans_for(text)
    if not ner:
        return rule
    return merge_ner(text, rule, ner)
