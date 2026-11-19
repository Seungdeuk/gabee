"""찰칵 흔한 사진 자동 보충: 하루 한 번 Pixabay 사진 + AI 질문으로 흔한 사진(source 4)을 채운다.

- `run_daily`: 오늘(한국 날짜) 이미 넣은 자동 행 수를 하루 목표에서 뺀 부족분만 채운다. 시도 한 번 = 검색어 몇 개로 후보를 찾아
  사진을 내려받고(`photo_rec_pixabay`), AI 로 질문을 만들고(`photo_rec_auto_ai`), 규칙을 통과하면 저장한다. 후보가 어느 단계든 실패하면 다음 후보로 넘어간다.
  부족분이 남아 있으면 시도는 최대 `photo_rec_auto_max_attempts` 번(기본 3, 처음 + 재시도 2)이고, 그래도 못 채우면 모자란 채로 두고 로그를 남긴다.
- 같은 Pixabay id 는 다시 쓰지 않는다. 쓸 수 없다고 하거나 규칙에 안 맞은 사진은 `usable=False`·사진 없는 행으로 남겨 다시 묻지 않는다
  (내려받기·AI 장애 같은 일시 실패는 남기지 않는다).
- `start()`: 서버 시작 때 부른다. `photo_rec_auto_enabled` 가 켜져 있을 때만 백그라운드 스레드를 한 번 띄우고, 한국 시간 `photo_rec_auto_hour` 시 이후
  하루 한 번 돈다(그 시각에 꺼져 있었으면 켜졌을 때). PostgreSQL 이면 advisory lock 으로 여러 서버가 동시에 돌지 않게 한다.
- 로그에는 키·요청 주소를 넣지 않고 예외 종류만 적는다.
"""

import logging
import random
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.ai_assistant.ingest.photo_judge import to_judge_jpeg
from app.shared.config import settings
from app.shared.db import SessionLocal, engine
from app.shared.llm import client as llm

from . import photo_rec_auto_ai as auto_ai
from . import photo_rec_pixabay as pix
from . import photo_rec_store as store
from .models import PlayPhotoRec
from .timeutil import aware, local_day_start, local_tz

logger = logging.getLogger(__name__)

CANDIDATES_PER_ATTEMPT = (
    6  # 시도 한 번에 AI 에 보내는 사진 상한(하루 AI 호출 <= 목표 x 시도 수의 상한 x 이 값)
)
QUERIES_PER_ATTEMPT = 4
ZOOM = 8
TICK_SECONDS = 600
LOCK_KEY = 7240001  # pg_try_advisory_lock

_started = threading.Event()
_last_done: str | None = None  # 오늘(한국 날짜)을 이미 돌았으면 그 날짜


@dataclass
class RunResult:
    added: int = 0
    attempts: int = 0
    skipped: str | None = None  # no_key | no_llm


def _credit(hit: dict, query: str) -> dict:
    return dict(
        credit_user=str(hit.get("user", ""))[:80] or None,
        credit_url=str(hit.get("pageURL", ""))[:300] or None,
        license=pix.LICENSE,
        search_query=query[:60],
        external_id=str(hit["id"])[:32],
    )


def _base(hit: dict, query: str, now: datetime) -> dict:
    return dict(
        id=f"auto{hit['id']}"[:32],
        group_id=None,
        attachment_id=None,
        source=store.SOURCE_AUTO,
        kind=store.KIND_CONTENT,
        zoom=ZOOM,
        prompt_version=auto_ai.PROMPT_VERSION,
        created_at=now,
        **_credit(hit, query),
    )


def _save(db: Session, fields: dict) -> bool:
    """행을 저장한다. 이미 같은 id 가 있으면(다른 서버가 먼저 넣음) 건너뛰고 False."""
    try:
        db.add(PlayPhotoRec(**fields))
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def _today_count(db: Session, now: datetime) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(PlayPhotoRec)
            .where(
                PlayPhotoRec.source == store.SOURCE_AUTO,
                PlayPhotoRec.usable.is_(True),
                PlayPhotoRec.created_at >= local_day_start(now),
            )
        )
        or 0
    )


def _try_candidate(db, hit, query, now, fetch, ask, used: set[str]) -> bool:
    """후보 한 장을 처리한다. 쓸 수 있는 행을 저장했으면 True."""
    used.add(str(hit["id"]))
    try:
        image = fetch.download(hit)
        question = ask(to_judge_jpeg(image))
    except auto_ai.Rejected as exc:
        logger.info("photo rec auto: candidate rejected id=%s reason=%s", hit["id"], exc)
        _save(db, dict(_base(hit, query, now), usable=False, question="", options=[], answer="",
                       box_x=0.5, box_y=0.5, image=None))  # fmt: skip
        return False
    except Exception as exc:  # noqa: BLE001  내려받기·AI 장애: 일시 실패라 남기지 않고 다음 후보
        logger.warning(
            "photo rec auto: candidate failed id=%s error=%s", hit["id"], type(exc).__name__
        )
        return False
    if not question.usable:
        _save(db, dict(_base(hit, query, now), usable=False, question="", options=[], answer="",
                       box_x=0.5, box_y=0.5, image=None))  # fmt: skip
        return False
    answer = "".join(
        "1" if i == question.answer_index else "0" for i in range(len(question.options))
    )
    return _save(
        db,
        dict(
            _base(hit, query, now),
            usable=True,
            image=image,
            question=question.question,
            options=question.options,
            answer=answer,
            box_x=question.box_x,
            box_y=question.box_y,
        ),
    )


def _attempt(db, now, missing: int, fetch, ask, rng, used: set[str]) -> int:
    """시도 한 번: 부족분 `missing` 을 채우려 후보를 최대 CANDIDATES_PER_ATTEMPT 장 처리한다. 저장한 수를 돌려준다."""
    added = tried = 0
    for _group, query in rng.sample(pix.QUERIES, min(QUERIES_PER_ATTEMPT, len(pix.QUERIES))):
        if added >= missing or tried >= CANDIDATES_PER_ATTEMPT:
            break
        try:
            hits = fetch.search(query)
        except Exception as exc:  # noqa: BLE001
            logger.warning("photo rec auto: search failed error=%s", type(exc).__name__)
            continue
        for hit in hits:
            if added >= missing or tried >= CANDIDATES_PER_ATTEMPT:
                break
            if not pix.is_clean(hit) or str(hit["id"]) in used:
                continue
            tried += 1
            if _try_candidate(db, hit, query, now, fetch, ask, used):
                added += 1
    return added


def run_daily(
    db: Session,
    now: datetime,
    fetch=None,
    ask=None,
    rng: random.Random | None = None,
) -> RunResult:
    """오늘 부족분(하루 목표 - 오늘 넣은 자동 행)을 채운다. `fetch`(search·download)·`ask`(JPEG -> AutoQuestion)는 시험용으로 바꿔 끼운다."""
    result = RunResult()
    missing = settings.photo_rec_auto_per_day - _today_count(db, now)
    if missing <= 0:
        return result
    if fetch is None:
        if not settings.pixabay_api_key:
            logger.info("photo rec auto: skipped, no pixabay key")
            result.skipped = "no_key"
            return result
        fetch = pix.PixabayClient(settings.pixabay_api_key)
    if ask is None:
        if not llm.available():
            logger.info("photo rec auto: skipped, no llm key")
            result.skipped = "no_llm"
            return result
        ask = auto_ai.make_question
    rng = rng or random.Random()
    used = {x for x in db.scalars(select(PlayPhotoRec.external_id)) if x}
    for _ in range(max(1, settings.photo_rec_auto_max_attempts)):
        if missing <= 0:
            break
        result.attempts += 1
        got = _attempt(db, now, missing, fetch, ask, rng, used)
        result.added += got
        missing -= got
    if missing > 0:
        logger.warning(
            "photo rec auto: short by %d after %d attempts (added %d)",
            missing,
            result.attempts,
            result.added,
        )
    else:
        logger.info(
            "photo rec auto: filled, added %d in %d attempts", result.added, result.attempts
        )
    return result


def is_due(now: datetime, hour: int, last_done_day: str | None) -> bool:
    """한국 시간 `hour` 시 이후이고 오늘 아직 안 돌았으면 참."""
    local = aware(now).astimezone(local_tz())
    return local.hour >= hour and last_done_day != local.date().isoformat()


def _run_locked(now: datetime) -> bool:
    """advisory lock(PostgreSQL)을 잡고 한 번 돈다. 다른 서버가 돌고 있어 못 잡았으면 False."""
    if engine.dialect.name != "postgresql":
        with SessionLocal() as db:
            run_daily(db, now)
        return True
    with engine.connect() as lock_conn:  # 잠금은 이 연결에 붙으므로 끝까지 들고 있는다
        if not lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar():
            logger.info("photo rec auto: another server is running")
            return False
        try:
            with SessionLocal() as db:
                run_daily(db, now)
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            lock_conn.commit()
    return True


def tick(now: datetime | None = None) -> None:
    """한 번 확인한다. 어떤 오류도 밖으로 내지 않는다(주기 작업이 멈추지 않게, 로그에는 종류만)."""
    global _last_done
    now = now or datetime.now(UTC)
    if not is_due(now, settings.photo_rec_auto_hour, _last_done):
        return
    try:
        if _run_locked(now):
            _last_done = aware(now).astimezone(local_tz()).date().isoformat()
    except Exception as exc:  # noqa: BLE001
        logger.warning("photo rec auto: tick failed error=%s", type(exc).__name__)
        _last_done = (
            aware(now).astimezone(local_tz()).date().isoformat()
        )  # 실패해도 하루 시도 수는 지킨다


def _loop() -> None:
    while True:
        tick()
        threading.Event().wait(TICK_SECONDS)


def start() -> None:
    """서버가 시작할 때 부른다: 자동 보충이 켜져 있으면 백그라운드 스레드를 한 번만 띄운다."""
    if not settings.photo_rec_auto_enabled or _started.is_set():
        return
    _started.set()
    threading.Thread(target=_loop, name="photo-rec-auto", daemon=True).start()
