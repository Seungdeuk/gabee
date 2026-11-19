"""찰칵! 탐정단 가비 추천 조립: 가족 사진 문제 최대 2개 + 흔한 사진 문제로 하루 3개를 만든다.

- 구성은 저장하지 않는다. 가족·사용자·한국 시간 날짜로 시드한 난수로 매번 같은 방식으로 고른다(같은 사용자·같은 날은 같은 카드, 사용자마다 다름).
- 후보 = 가족 전체방 사진 중 "일반 사진으로 확인"된 것(`confirmed_photo_ids`)에서 이 가족이 최근 14일 안에 보낸 것·쓸 수 없는 것을 뺀 사진.
- 가족 사진 한 장은 문제를 하나만 갖는다(행 한 줄, 저장 뒤 재사용). 종류는 일정 -> (AI 동의 가족만) 내용 -> 월 순서로 시도한다.
- AI 는 내용 질문에만 쓰고 한 번 열 때 한 묶음(`ai_guard.run`)이다. 동의가 꺼졌거나 한도·쿨다운·다른 호출 중이어도 AI 없는 카드는 그대로 나온다.
"""

import hashlib
import random
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.ai_assistant.ingest.photo_judge import to_judge_jpeg
from app.features.family_chat import photo_check_repository as checks
from app.features.family_chat.models import MessageAttachment
from app.features.family_chat.photo_service import attachment_files
from app.features.family_group.models import User
from app.shared import ai_guard
from app.shared.errors import ApiError, not_found
from app.shared.llm import client as llm

from . import media, quiz_rec
from . import photo_rec_store as store
from .models import PlayPhotoRec
from .photo_rec_ai import FEATURE, PROMPT_VERSION, ContentFailed, ContentResult, content_question
from .photo_rec_pool import pool_rows
from .photo_rec_questions import PhotoQuestion, event_question, month_question
from .photo_rec_store import KIND_CONTENT, KIND_EVENT, KIND_MONTH, RECENT_DAYS
from .timeutil import local_day_start, local_tz

ASK_COUNT = 3  # 한 번에 보여 주는 카드 수
FAMILY_MAX = 2  # 그중 가족 사진 카드 최대(흔한 사진이 최소 1개 들어간다)
CANDIDATE_LIMIT = 200  # 후보로 읽는 최근 가족 사진 수
BOX_MIN, BOX_MAX = 0.25, 0.75  # 월·일정 문제의 확대 위치 범위(가운데 쪽)
KIND_NAME = {KIND_MONTH: "month", KIND_EVENT: "event", KIND_CONTENT: "content"}


def rec_rng(group_id: str, user_id: str, today: date) -> random.Random:
    """가족·사용자·날짜로 시드한 난수. 같은 사용자의 같은 날은 같고 사용자마다 다르다."""
    raw = f"{group_id}|{user_id}|{today.isoformat()}"
    return random.Random(int(hashlib.sha256(raw.encode()).hexdigest()[:16], 16))


def _sorted_by_key(items: list, salt: int, key_of) -> list:
    """시드(salt)로 정한 해시 순서. 후보가 하나 줄거나 늘어도 나머지의 상대 순서는 그대로다."""
    return sorted(items, key=lambda x: hashlib.sha256(f"{salt}|{key_of(x)}".encode()).hexdigest())


def family_candidates(db: Session, group_id: str, now: datetime) -> list[MessageAttachment]:
    """가족 전체방 사진 중 확인된 것에서 최근 14일에 보낸 추천·쓸 수 없는 행의 사진을 뺀다."""
    atts = store.family_image_attachments(db, group_id, CANDIDATE_LIMIT)
    ids = [a.id for a in atts]
    confirmed = checks.confirmed_photo_ids(db, group_id, ids)
    rows = store.rows_for_attachments(db, list(confirmed))
    sent = store.sent_rec_ids(db, group_id, now, RECENT_DAYS)
    out = []
    for att in atts:
        if att.id not in confirmed:
            continue
        row = rows.get(att.id)
        if row is not None and (row.id in sent or not row.usable):
            continue
        out.append(att)
    return out


def compose(
    family_cards: list[dict],
    common_cards: list[dict],
    total: int = ASK_COUNT,
    family_max: int = FAMILY_MAX,
) -> list[dict]:
    """가족 카드 `min(len, family_max)` 개 + 나머지를 흔한 카드로(가족 -> 흔한 순서). 흔한 카드가 최소 `total - family_max` 개 들어갈 자리를 둔다."""
    family = family_cards[:family_max]
    return family + common_cards[: total - len(family)]


def _answer_bits(count: int, index: int) -> str:
    return "".join("1" if i == index else "0" for i in range(count))


def _item(row: PlayPhotoRec) -> dict:
    return {
        "id": row.id,
        "kind": KIND_NAME[row.kind],
        "source": "album" if row.source == store.SOURCE_ALBUM else "common",
        "question": row.question,
        "options": list(row.options),
        "answer_index": row.answer.index("1"),
        "box_x": row.box_x,
        "box_y": row.box_y,
        "zoom": row.zoom,
        "image_url": f"/play/photo/recommendations/{row.id}/image",
    }


def _save(db: Session, group_id: str, att_id: str, **fields):
    """행 한 줄을 저장한다. 다른 요청이 먼저 저장했으면(`attachment_id` 유일) 그 행을 다시 읽어 쓴다."""
    try:
        return store.add_row(
            db,
            group_id=group_id,
            source=store.SOURCE_ALBUM,
            attachment_id=att_id,
            prompt_version=PROMPT_VERSION,
            **fields,
        )
    except IntegrityError:
        db.rollback()
        return store.row_for_attachment(db, att_id)


def _save_question(db, group_id, att_id, q: PhotoQuestion, rng: random.Random):
    return _save(
        db,
        group_id,
        att_id,
        kind=q.kind,
        question=q.question,
        options=q.options,
        answer=_answer_bits(len(q.options), q.answer_index),
        box_x=rng.uniform(BOX_MIN, BOX_MAX),
        box_y=rng.uniform(BOX_MIN, BOX_MAX),
        zoom=q.zoom,
    )


def _save_content(db, group_id, att_id, res: ContentResult):
    if not res.usable:  # 쓸 수 없는 사진도 저장해 다시 묻지 않는다
        return _save(
            db,
            group_id,
            att_id,
            kind=KIND_CONTENT,
            usable=False,
            question="",
            options=[],
            answer="",
            box_x=0.5,
            box_y=0.5,
            zoom=8,
        )
    return _save(
        db,
        group_id,
        att_id,
        kind=KIND_CONTENT,
        question=res.question,
        options=res.options,
        answer=_answer_bits(len(res.options), res.answer_index),
        box_x=res.box_x,
        box_y=res.box_y,
        zoom=8,
    )


def _kind_order(used: list[int], ai_ok: bool) -> list[int]:
    """일정 -> 내용(AI 가능할 때) -> 월. 앞 사진이 쓴 종류는 뒤로 미룬다."""
    kinds = [KIND_EVENT, *([KIND_CONTENT] if ai_ok else []), KIND_MONTH]
    return sorted(kinds, key=lambda k: k in used)


def _judge_jpeg(att: MessageAttachment) -> bytes | None:
    """AI 에 보낼 사진(원본 -> EXIF 제거·1024px). 파일이 없거나 못 읽으면 None."""
    files = attachment_files(att)
    if files is None or not files[0].is_file():
        return None
    try:
        return to_judge_jpeg(files[0].read_bytes())
    except Exception:
        return None


@dataclass(frozen=True)
class _Batch:
    """ai_guard 가 사용 기록·한도에 세는 값. 사진이 몇 장이든 한 번 열기를 호출 1회로 센다(토큰은 실제 쓴 만큼)."""

    model: str
    input_tokens: int
    output_tokens: int
    calls: int = 1


def _ask_content(
    db: Session, user: User, group_id: str, jobs: dict[str, bytes]
) -> tuple[dict[str, ContentResult], str | None]:
    """내용 질문을 사진마다 동시에 부른다(DB 는 이 스레드에서만 쓴다). (사진 id -> 결과, 한도·실패 상태)."""
    results: dict[str, ContentResult] = {}

    def call():
        tokens_in = tokens_out = 0
        model, error = None, None
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = {aid: pool.submit(content_question, jpeg) for aid, jpeg in jobs.items()}
            for aid, future in futures.items():
                try:
                    res = future.result()
                except ContentFailed as failed:
                    tokens_in += failed.input_tokens
                    tokens_out += failed.output_tokens
                    error = error or failed
                except llm.LLMUnavailable as unavailable:
                    error = error or unavailable
                else:
                    results[aid] = res
                    tokens_in += res.input_tokens
                    tokens_out += res.output_tokens
                    model = res.model
        if not results:
            if isinstance(error, ContentFailed):
                raise ContentFailed(str(error), 1, tokens_in, tokens_out)
            raise error
        return {"n": len(results)}, _Batch(model, tokens_in, tokens_out)

    try:
        # 결과 캐시는 쓰지 않는다: cache_key=None 이면 ai_guard 가 캐시를 읽지도 쓰지도 않는다(구성 고정에 못 쓰고, 읽으면 호출이 0번이라
        # 사진 몇 장 결과가 섞일 수 있다). 사진별 결과는 `play_photo_rec` 행으로 저장하고 다시 쓴다.
        ai_guard.run(
            db,
            user_id=user.id,
            group_id=group_id,
            feature=FEATURE,
            cache_key=None,
            call=call,
        )
    except ApiError as error:
        return {}, quiz_rec._state_of(error)
    return results, None


def _family_cards(
    db: Session,
    user: User,
    group_id: str,
    now: datetime,
    salt: int,
    qrng: random.Random,
    enabled: bool,
) -> tuple[list[PlayPhotoRec], str | None]:
    """가족 사진 카드(행)를 최대 `FAMILY_MAX` 개. (행 목록, AI 문제 상태 또는 None)."""
    cands = family_candidates(db, group_id, now)
    rows = store.rows_for_attachments(db, [a.id for a in cands])
    if not enabled:  # 동의 꺼진 가족의 AI 행은 보이지 않는다
        cands = [a for a in cands if not (a.id in rows and rows[a.id].kind == KIND_CONTENT)]
    queue = deque(_sorted_by_key(cands, salt, lambda a: a.id))
    cards: list = []  # 행, 또는 AI 결과를 기다리는 사진 id
    jobs: dict[str, bytes] = {}
    atts: dict[str, MessageAttachment] = {}
    used: list[int] = []

    def fill(allow_ai: bool) -> None:
        while queue and len(cards) < FAMILY_MAX:
            att = queue.popleft()
            row = rows.get(att.id)
            if row is not None:
                cards.append(row)
                used.append(row.kind)
                continue
            files = attachment_files(att)
            if files is None or not files[0].is_file():  # 사진 파일이 없으면 건너뜀
                continue
            for kind in _kind_order(used, allow_ai and enabled):
                if kind == KIND_CONTENT:
                    jpeg = _judge_jpeg(att)
                    if jpeg is None:
                        continue
                    jobs[att.id], atts[att.id] = jpeg, att
                    cards.append(att.id)
                    used.append(kind)
                    break
                q = (
                    event_question(db, group_id, att.taken_at, qrng)
                    if kind == KIND_EVENT
                    else month_question(att.taken_at, qrng)
                )
                if q is not None:
                    row = _save_question(db, group_id, att.id, q, qrng)
                    if row is not None:
                        cards.append(row)
                        used.append(kind)
                        break

    fill(allow_ai=True)
    ai_state = None
    if jobs:
        results, ai_state = _ask_content(db, user, group_id, jobs)
        resolved = []
        for card in cards:
            if not isinstance(card, str):
                resolved.append(card)
            elif card in results:
                row = _save_content(db, group_id, card, results[card])
                if row is not None and row.usable:
                    resolved.append(row)
            else:  # AI 가 안 된 사진은 뒤로 미뤄 두고(저장 안 함) 다른 사진을 먼저 채운다
                queue.append(atts[card])
        cards[:] = resolved
        fill(allow_ai=False)
    return [c for c in cards if not isinstance(c, str)], ai_state


def recommend(db: Session, user: User, group_id: str, rng: random.Random | None = None) -> dict:
    """오늘의 사진 가비 추천: {"state": ..., "items": [...]}. 가족 사진 0~2개 + 흔한 사진으로 3개를 채운다.
    AI 문제가 안 돼도 AI 없는 카드가 있으면 `ok` 로 돌려주고, 카드가 하나도 없을 때만 AI 문제 상태를 알린다."""
    now = datetime.now(UTC)
    today = now.astimezone(local_tz()).date()
    if store.sent_today(db, group_id, user.id, local_day_start(now)) >= ASK_COUNT:
        return {"state": quiz_rec.USED_UP, "items": []}
    rng = rng or rec_rng(group_id, user.id, today)
    salt = rng.getrandbits(64)
    qrng = random.Random(rng.getrandbits(64))
    enabled = ai_guard.is_enabled(db, group_id)
    rows, ai_state = _family_cards(db, user, group_id, now, salt, qrng, enabled)
    sent = store.sent_rec_ids(db, group_id, now, RECENT_DAYS)
    common = _sorted_by_key(pool_rows(db, sent), salt, lambda r: r.id)[:ASK_COUNT]
    items = compose([_item(r) for r in rows], [_item(r) for r in common])
    return {"state": quiz_rec.OK if items else (ai_state or quiz_rec.OK), "items": items}


def image_for(db: Session, group_id: str, rec_id: str) -> bytes:
    """추천 행의 사진 JPEG. 흔한 사진은 저장된 바이트 그대로, 가족 사진은 첨부 원본을 줄여서. 다른 가족 행·사라진 첨부는 404."""
    row = db.get(PlayPhotoRec, rec_id)
    if row is None or (row.group_id is not None and row.group_id != group_id):
        raise not_found("이미지")
    if row.attachment_id is None:
        if row.image is None:
            raise not_found("이미지")
        return row.image
    att = db.get(MessageAttachment, row.attachment_id)
    files = attachment_files(att) if att is not None else None
    if files is None or not files[0].is_file():
        raise not_found("이미지")
    try:
        return media.make_photo_jpeg(files[0].read_bytes())
    except Exception:
        raise not_found("이미지") from None
