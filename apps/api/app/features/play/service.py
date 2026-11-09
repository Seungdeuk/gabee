"""가족 놀이터 비동기 놀이(골든벨·이게 뭐게·찰칵! 탐정단)의 규칙. 마감은 조회·제출 때 계산한다(별도 배치 없음).

- 닫힘: `close_at` 이 지금보다 이전이면 닫힌 것. 받는 사람이 모두 끝내면 `close_at` 을 그 순간으로 당긴다.
- 참여: 골든벨·탐정단은 답을 보내면 참여, 이게 뭐게는 맞히거나 10번을 다 쓰면 참여다(끝내지 못한 채 닫히면
  시도한 사람은 닫힐 때 참여로 친다).
- 점수: 참여 +10(항상), 정답 +20(골든벨은 세트 20점을 맞힌 비율로), 힌트·줄여 보기 -5씩(최대 2번이라
  틀려도 총점이 0 아래로 내려가지 않는다. 힌트만 열고 답을 한 번도 안 낸 사람은 참여도 점수도 없다),
  문제 낸 사람 +20(닫힐 때, 한 명이라도 참여해야, 하루 3건까지).
  낸 사람 점수는 닫힌 놀이를 조회·제출 때 정산하며 같은 놀이는 한 번만 들어간다.
- 힌트 상태: 이게 뭐게의 힌트와 탐정단의 줄여 보기는 `play_answers` 의 try_no=0 줄 하나(hints_used)에 둔다.
  이 줄은 답이 아니라서 참여로 세지 않는다.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.features.family_group import repository as group_repo
from app.features.family_group.models import User
from app.shared.errors import ApiError, bad_request, not_found

from . import media, repository
from .constants import (
    CLOSE_HOURS,
    DAILY_MAKE_LIMIT,
    DRAW_ALT_MAX,
    DRAW_ANSWER_MAX,
    DRAW_HINT2_MAX,
    DRAW_MAX_TRIES,
    GAME_QUIZ,
    MAX_HINTS,
    PHOTO_COMMENT_MAX,
    PHOTO_QUESTION_MAX,
    PHOTO_ZOOMS,
    POINT_CORRECT,
    POINT_HINT,
    POINT_JOIN,
    POINT_MAKE,
    REASON_CORRECT,
    REASON_JOIN,
    REASON_MAKE,
    RESULT_DAYS,
    SETTLE_DAYS,
)
from .models import (
    GAME_DRAW,
    GAME_PHOTO,
    REASON_BOMB_WIN,
    REASON_HINT,
    PlayAnswer,
    PlayDraw,
    PlayItem,
    PlayPhoto,
    PlayQuiz,
    PlayScore,
)
from .schemas import (
    PlayAnswerOut,
    PlayBoardItemOut,
    PlayBoardOut,
    PlayDrawOut,
    PlayDrawTryIn,
    PlayFamilyAnswersOut,
    PlayFamilyStatusOut,
    PlayItemOut,
    PlayPersonOut,
    PlayPhotoOut,
    PlayQuestionOut,
    PlayQuizAnswerIn,
    PlayQuizCreateIn,
    PlayQuotaOut,
    PlayRankingOut,
    PlayRankRow,
    PlayScoreOut,
)
from .timeutil import aware, local_day_start, month_start, week_start

PHOTO_OPTION_MAX = 20


def _now() -> datetime:
    return datetime.now(UTC)


def _person(u: User | None) -> PlayPersonOut:
    return PlayPersonOut(id=u.id, name=u.name) if u else PlayPersonOut(id="", name="알 수 없음")


def is_closed(item: PlayItem, now: datetime) -> bool:
    return aware(item.close_at) <= now


def recipient_ids(item: PlayItem, members: list[User]) -> list[str]:
    """받는 사람 id(가족 순서). 목록이 비어 있으면 만든 사람을 뺀 가족 모두."""
    ids = [m.id for m in members if m.id != item.maker_id]
    if item.player_ids:
        wanted = set(item.player_ids)
        ids = [i for i in ids if i in wanted]
    return ids


def _tries(rows: list[PlayAnswer]) -> list[PlayAnswer]:
    """답으로 센 줄(힌트 상태 줄 try_no=0 은 뺀다)."""
    return [a for a in rows if a.try_no >= 1]


def _draw_finished(rows: list[PlayAnswer]) -> bool:
    tries = _tries(rows)
    return any(a.is_correct for a in tries) or len(tries) >= DRAW_MAX_TRIES


def participants(
    item: PlayItem, answers: list[PlayAnswer], closed: bool = False
) -> dict[str, datetime]:
    """참여한 사람과 끝낸 시각. 이게 뭐게는 끝낸 사람만(닫힌 뒤에는 시도한 사람도) 참여로 센다."""
    by_player: dict[str, list[PlayAnswer]] = {}
    for a in _tries(answers):
        by_player.setdefault(a.player_id, []).append(a)
    out: dict[str, datetime] = {}
    for pid, rows in by_player.items():
        if item.game == GAME_DRAW and not closed and not _draw_finished(rows):
            continue
        out[pid] = max(aware(a.answered_at) for a in rows)
    return out


def _norm(text: str) -> str:
    return "".join(text.split()).casefold()


def _hint_row(answers: list[PlayAnswer], player_id: str) -> PlayAnswer | None:
    return next((a for a in answers if a.player_id == player_id and a.try_no == 0), None)


# ---------- 정산 ----------
def _daily_rank(db: Session, item: PlayItem) -> int:
    rank = repository.maker_daily_rank(db, item)
    return rank if rank is not None else DAILY_MAKE_LIMIT + 1


def _settle_unfinished_draws(db: Session, item: PlayItem, answers: list[PlayAnswer]) -> None:
    """끝내지 못한 채 닫힌 이게 뭐게는 시도한 사람에게 참여 +10 을 준다(한 번만)."""
    by_player: dict[str, list[PlayAnswer]] = {}
    for a in _tries(answers):
        by_player.setdefault(a.player_id, []).append(a)
    for pid, rows in by_player.items():
        if _draw_finished(rows):
            continue
        if any(s.reason == REASON_JOIN for s in repository.scores_of(db, item.id, pid)):
            continue
        hint = _hint_row(answers, pid)
        hints = hint.hints_used if hint else 0
        rows = [(REASON_JOIN, POINT_JOIN)]
        if hints > 0:
            rows.append((REASON_HINT, -POINT_HINT * hints))  # 힌트를 쓰고 끝내지 못해도 감점은 같다
        repository.add(
            db,
            *[
                PlayScore(
                    group_id=item.group_id,
                    player_id=pid,
                    play_id=item.id,
                    game=item.game,
                    reason=reason,
                    points=points,
                    created_at=aware(item.close_at),
                )
                for reason, points in rows
            ],
        )


def _settle_item(db: Session, item: PlayItem, members: list[User]) -> None:
    locked = repository.get_item(db, item.id, item.group_id, lock=True)
    if locked is None:
        return
    answers = repository.answers_of(db, item.id)
    if item.game == GAME_DRAW:
        _settle_unfinished_draws(db, item, answers)
    if repository.score_exists(db, item.id, REASON_MAKE):
        return
    joined = participants(item, answers, closed=True)
    if not set(joined) & set(recipient_ids(item, members)):
        return  # 아무도 안 풀면 점수 없음
    if _daily_rank(db, item) > DAILY_MAKE_LIMIT:
        return  # 하루 한도(낸 순서)를 넘으면 점수 없음
    repository.add(
        db,
        PlayScore(
            group_id=item.group_id,
            player_id=item.maker_id,
            play_id=item.id,
            game=item.game,
            reason=REASON_MAKE,
            points=POINT_MAKE,
        ),
    )


def settle_group(db: Session, group_id: str, now: datetime | None = None) -> None:
    """닫힌 놀이의 "문제 낸 사람" 점수를 정산한다. 여러 번 불러도 같은 놀이는 한 번만 들어간다."""
    now = now or _now()
    items = repository.unsettled_closed_items(
        db, group_id, now, now - timedelta(days=SETTLE_DAYS), REASON_MAKE
    )
    if not items:
        return
    members = group_repo.members(db, group_id)
    for item in items:
        _settle_item(db, item, members)
    db.commit()


# ---------- 만들기 ----------
def _bits(options: list[str], index: int) -> str:
    return "".join("1" if i == index else "0" for i in range(len(options)))


def _prepare(
    db: Session, user: User, group_id: str, player_ids_in: list[str]
) -> tuple[list[User], list[str]]:
    members = group_repo.members(db, group_id)
    member_ids = {m.id for m in members}
    player_ids = list(dict.fromkeys(player_ids_in))
    if any(p == user.id or p not in member_ids for p in player_ids):
        raise bad_request("invalid_recipient", "받는 사람은 우리 가족 중 내가 아닌 사람이어야 해요")
    if not [m for m in members if m.id != user.id]:
        raise bad_request("no_recipient", "함께 풀 가족이 아직 없어요")
    return members, player_ids


def _new_item(user: User, group_id: str, game: int, player_ids: list[str]) -> PlayItem:
    now = _now()
    return PlayItem(
        group_id=group_id,
        game=game,
        maker_id=user.id,
        player_ids=player_ids,
        close_at=now + timedelta(hours=CLOSE_HOURS),
        created_at=now,
    )


def create_quiz(db: Session, user: User, group_id: str, body: PlayQuizCreateIn) -> PlayItemOut:
    members, player_ids = _prepare(db, user, group_id, body.player_ids)
    item = _new_item(user, group_id, GAME_QUIZ, player_ids)
    repository.add(db, item)
    repository.add(
        db,
        *[
            PlayQuiz(
                play_id=item.id,
                quiz_no=n,
                qtype=q.qtype,
                question=q.question,
                options=q.options,
                answer=_bits(q.options, q.answer_index),
                comment=(q.comment or "").strip() or None,
            )
            for n, q in enumerate(body.questions, start=1)
        ],
    )
    db.commit()
    return item_out(db, item, user, members, _now())


def _clean_text(
    value: str | None, max_len: int, label: str, *, required: bool = True
) -> str | None:
    v = (value or "").strip()
    if not v:
        if required:
            raise bad_request("invalid_input", f"{label}을(를) 써 주세요")
        return None
    if len(v) > max_len:
        raise bad_request("invalid_input", f"{label}은(는) {max_len}자 이하로 써 주세요")
    return v


def _save_file_and_commit(db: Session, rel_path: str, data: bytes) -> None:
    """파일을 쓰고 DB 를 확정한다. 어느 쪽이 실패해도 반쪽 상태(파일만 있거나 줄만 있음)를 남기지 않는다."""
    try:
        media.write(rel_path, data)
        db.commit()
    except Exception:
        db.rollback()
        media.delete(rel_path)
        raise


def create_draw(
    db: Session,
    user: User,
    group_id: str,
    *,
    data: bytes,
    answer: str,
    alt_answers: list[str],
    hint2: str | None,
    player_ids: list[str],
) -> PlayItemOut:
    answer_text = _clean_text(answer, DRAW_ANSWER_MAX, "정답")
    hint2_text = _clean_text(hint2, DRAW_HINT2_MAX, "힌트", required=False)
    alts: list[str] = []
    for raw in alt_answers:
        alt = _clean_text(raw, DRAW_ANSWER_MAX, "이것도 정답", required=False)
        if alt and _norm(alt) != _norm(answer_text) and _norm(alt) not in map(_norm, alts):
            alts.append(alt)
    if len(alts) > DRAW_ALT_MAX:
        raise bad_request("invalid_input", f"이것도 정답은 {DRAW_ALT_MAX}개까지예요")
    png = media.make_draw_png(data)
    members, ids = _prepare(db, user, group_id, player_ids)
    item = _new_item(user, group_id, GAME_DRAW, ids)
    repository.add(db, item)
    path = media.draw_path(group_id, item.id)
    repository.add(
        db,
        PlayDraw(
            play_id=item.id,
            image_path=path,
            answer=answer_text,
            alt_answers=alts or None,
            hint2=hint2_text,
        ),
    )
    _save_file_and_commit(db, path, png)
    return item_out(db, item, user, members, _now())


def create_photo(
    db: Session,
    user: User,
    group_id: str,
    *,
    data: bytes,
    source: int,
    zoom: int,
    box_x: float,
    box_y: float,
    question: str,
    options: list[str],
    answer_index: int,
    comment: str | None,
    player_ids: list[str],
) -> PlayItemOut:
    if source not in (1, 2):
        raise bad_request("invalid_input", "사진 출처는 1(가족 앨범) 또는 2(내 폰)예요")
    if zoom not in PHOTO_ZOOMS:
        raise bad_request(
            "invalid_input", f"확대 배율은 {', '.join(map(str, PHOTO_ZOOMS))} 중 하나예요"
        )
    if not (0 <= box_x <= 1 and 0 <= box_y <= 1):
        raise bad_request("invalid_input", "확대 위치는 0~1 사이여야 해요")
    q_text = _clean_text(question, PHOTO_QUESTION_MAX, "질문")
    opts = [o.strip() for o in options]
    if not 2 <= len(opts) <= 4 or any(not o or len(o) > PHOTO_OPTION_MAX for o in opts):
        raise bad_request("invalid_input", f"보기는 2~4개, 1~{PHOTO_OPTION_MAX}자로 채워 주세요")
    if len(set(opts)) != len(opts):
        raise bad_request("invalid_input", "같은 보기가 있어요")
    if not 0 <= answer_index < len(opts):
        raise bad_request("invalid_input", "정답 보기가 보기 개수를 넘었어요")
    comment_text = _clean_text(comment, PHOTO_COMMENT_MAX, "한마디", required=False)
    jpeg = media.make_photo_jpeg(data)
    members, ids = _prepare(db, user, group_id, player_ids)
    item = _new_item(user, group_id, GAME_PHOTO, ids)
    repository.add(db, item)
    path = media.photo_path(group_id, item.id)
    repository.add(
        db,
        PlayPhoto(
            play_id=item.id,
            image_path=path,
            source=source,
            zoom=zoom,
            box_x=box_x,
            box_y=box_y,
            question=q_text,
            options=opts,
            answer=_bits(opts, answer_index),
            comment=comment_text,
        ),
    )
    _save_file_and_commit(db, path, jpeg)
    return item_out(db, item, user, members, _now())


# ---------- 답 보내기 ----------
def _half_up(numer: int, denom: int) -> int:
    return (2 * numer + denom) // (2 * denom)


def _load_for_answer(
    db: Session, user: User, group_id: str, item_id: str, games: tuple[int, ...]
) -> tuple[PlayItem, list[User], datetime, list[PlayAnswer]]:
    """답·힌트를 보낼 수 있는 문제인지 확인하고 잠가서 가져온다."""
    item = repository.get_item(db, item_id, group_id, lock=True)
    if item is None or item.game not in games:
        raise not_found("문제")
    now = _now()
    members = group_repo.members(db, group_id)
    if item.maker_id == user.id:
        raise ApiError(403, "maker_cannot_answer", "내가 낸 문제는 풀 수 없어요")
    if user.id not in recipient_ids(item, members):
        raise ApiError(403, "not_recipient", "이 문제를 받은 가족이 아니에요")
    if is_closed(item, now):
        raise ApiError(409, "closed", "이미 마감된 문제예요")
    return item, members, now, repository.answers_of(db, item.id)


def _award(
    db: Session, item: PlayItem, user_id: str, *, correct_points: int, hints: int, now: datetime
) -> None:
    """참여 +10 은 항상, 정답 점수는 있을 때만, 힌트 -5 는 틀려도 깎는다(최대 2번이라 총점은 0 아래로 안 내려감)."""
    rows = [(REASON_JOIN, POINT_JOIN)]
    if correct_points > 0:
        rows.append((REASON_CORRECT, correct_points))
    if hints > 0:
        rows.append((REASON_HINT, -POINT_HINT * hints))
    repository.add(
        db,
        *[
            PlayScore(
                group_id=item.group_id,
                player_id=user_id,
                play_id=item.id,
                game=item.game,
                reason=reason,
                points=points,
                created_at=now,
            )
            for reason, points in rows
        ],
    )


def _close_if_all_done(
    item: PlayItem, members: list[User], answers: list[PlayAnswer], now: datetime
) -> None:
    """받는 사람이 모두 끝냈으면 그 순간 닫는다."""
    if set(recipient_ids(item, members)) <= set(participants(item, answers)):
        item.close_at = now


def submit_quiz(
    db: Session, user: User, group_id: str, item_id: str, body: PlayQuizAnswerIn
) -> PlayItemOut:
    item, members, now, existing = _load_for_answer(db, user, group_id, item_id, (GAME_QUIZ,))
    if user.id in participants(item, existing):
        raise ApiError(409, "already_answered", "이미 답을 보냈어요. 보낸 답은 고칠 수 없어요")

    questions = {q.quiz_no: q for q in repository.quiz_rows(db, item.id)}
    sent = {a.quiz_no: a.answer for a in body.answers}
    if len(sent) != len(body.answers) or set(sent) != set(questions):
        raise bad_request("invalid_answers", "모든 문제의 답을 한 번에 보내 주세요")
    rows = []
    for no, q in questions.items():
        ans = sent[no]
        if len(ans) != len(q.options) or ans.count("1") != 1:
            raise bad_request("invalid_answers", f"{no}번 문제는 보기를 하나만 골라 주세요")
        rows.append(
            PlayAnswer(
                play_id=item.id,
                player_id=user.id,
                quiz_no=no,
                try_no=1,
                answer=ans,
                is_correct=ans == q.answer,
                hints_used=0,
                answered_at=now,
            )
        )
    repository.add(db, *rows)
    right = sum(1 for r in rows if r.is_correct)
    # 세트 20점을 맞힌 비율로 나눠 반올림
    _award(
        db,
        item,
        user.id,
        correct_points=_half_up(POINT_CORRECT * right, len(rows)),
        hints=0,
        now=now,
    )
    _close_if_all_done(item, members, existing + rows, now)
    db.commit()
    settle_group(db, group_id, now)
    return item_out(db, item, user, members, now)


def submit_photo(
    db: Session, user: User, group_id: str, item_id: str, body: PlayQuizAnswerIn
) -> PlayItemOut:
    item, members, now, existing = _load_for_answer(db, user, group_id, item_id, (GAME_PHOTO,))
    if user.id in participants(item, existing):
        raise ApiError(409, "already_answered", "이미 답을 보냈어요. 보낸 답은 고칠 수 없어요")
    photo = repository.get_photo(db, item.id)
    if photo is None:
        raise not_found("문제")
    if len(body.answers) != 1 or body.answers[0].quiz_no != 0:
        raise bad_request("invalid_answers", "사진 문제는 보기를 하나만 골라 주세요")
    ans = body.answers[0].answer
    if len(ans) != len(photo.options) or ans.count("1") != 1:
        raise bad_request("invalid_answers", "보기를 하나만 골라 주세요")
    hint = _hint_row(existing, user.id)
    shrinks = hint.hints_used if hint else 0
    row = PlayAnswer(
        play_id=item.id,
        player_id=user.id,
        quiz_no=0,
        try_no=1,
        answer=ans,
        is_correct=ans == photo.answer,
        hints_used=shrinks,
        answered_at=now,
    )
    repository.add(db, row)
    _award(
        db,
        item,
        user.id,
        correct_points=POINT_CORRECT if row.is_correct else 0,
        hints=shrinks,
        now=now,
    )
    _close_if_all_done(item, members, existing + [row], now)
    db.commit()
    settle_group(db, group_id, now)
    return item_out(db, item, user, members, now)


def submit_answers(
    db: Session, user: User, group_id: str, item_id: str, body: PlayQuizAnswerIn
) -> PlayItemOut:
    """골든벨(문항 수만큼 한 번에)과 탐정단(보기 하나)이 같은 주소를 쓴다."""
    item = repository.get_item(db, item_id, group_id)
    if item is None:
        raise not_found("문제")
    if item.game == GAME_PHOTO:
        return submit_photo(db, user, group_id, item_id, body)
    if item.game == GAME_QUIZ:
        return submit_quiz(db, user, group_id, item_id, body)
    raise bad_request("use_tries", "이 문제는 정답 쓰기로 풀어요")


def open_hint(db: Session, user: User, group_id: str, item_id: str) -> PlayItemOut:
    """이게 뭐게 힌트 열기 / 탐정단 조금 줄여 보기. 쓸 때마다 -5점(맞혔을 때), 최대 2번."""
    item, members, now, existing = _load_for_answer(
        db, user, group_id, item_id, (GAME_DRAW, GAME_PHOTO)
    )
    mine = [a for a in existing if a.player_id == user.id]
    if item.game == GAME_DRAW:
        draw = repository.get_draw(db, item.id)
        if draw is None:
            raise not_found("문제")
        limit = MAX_HINTS if draw.hint2 else 1
        if _draw_finished(mine):
            raise ApiError(409, "already_finished", "이미 끝낸 문제예요")
    else:
        limit = MAX_HINTS
        if _tries(mine):
            raise ApiError(409, "already_answered", "이미 답을 보냈어요")
    hint = _hint_row(existing, user.id)
    used = hint.hints_used if hint else 0
    if used >= limit:
        raise ApiError(409, "no_more_hints", "더 쓸 수 있는 힌트가 없어요")
    if hint is None:
        repository.add(
            db,
            PlayAnswer(
                play_id=item.id,
                player_id=user.id,
                quiz_no=0,
                try_no=0,
                answer="",
                is_correct=False,
                hints_used=1,
                answered_at=now,
            ),
        )
    else:
        hint.hints_used = used + 1
    db.commit()
    return item_out(db, item, user, members, now)


def submit_try(
    db: Session, user: User, group_id: str, item_id: str, body: PlayDrawTryIn
) -> PlayItemOut:
    """이게 뭐게 정답 쓰기(최대 10번). 틀려도 깎이지 않고, 맞히거나 10번을 다 쓰면 끝나서 참여 +10 이 들어간다."""
    item, members, now, existing = _load_for_answer(db, user, group_id, item_id, (GAME_DRAW,))
    draw = repository.get_draw(db, item.id)
    if draw is None:
        raise not_found("문제")
    mine = [a for a in existing if a.player_id == user.id]
    if _draw_finished(mine):
        raise ApiError(409, "already_finished", "이미 끝낸 문제예요")
    tried = len(_tries(mine))
    hint = _hint_row(existing, user.id)
    hints = hint.hints_used if hint else 0
    accepted = {_norm(draw.answer), *(_norm(a) for a in (draw.alt_answers or []))}
    correct = _norm(body.answer) in accepted
    row = PlayAnswer(
        play_id=item.id,
        player_id=user.id,
        quiz_no=0,
        try_no=tried + 1,
        answer=body.answer,
        is_correct=correct,
        hints_used=hints,
        answered_at=now,
    )
    repository.add(db, row)
    if correct or tried + 1 >= DRAW_MAX_TRIES:
        _award(
            db,
            item,
            user.id,
            correct_points=POINT_CORRECT if correct else 0,
            hints=hints,
            now=now,
        )
    _close_if_all_done(item, members, existing + [row], now)
    db.commit()
    settle_group(db, group_id, now)
    return item_out(db, item, user, members, now, last_try_correct=correct)


# ---------- 이미지 ----------
def _photo_view(
    item: PlayItem, user: User, closed: bool, answers: list[PlayAnswer]
) -> tuple[bool, int]:
    """(원본 전체를 보여줄지, 줄여 보기를 쓴 횟수). 푸는 중인 사람에게는 확대한 조각만 보인다."""
    mine = [a for a in answers if a.player_id == user.id]
    full = item.maker_id == user.id or closed or bool(_tries(mine))
    hint = _hint_row(answers, user.id)
    return full, (hint.hints_used if hint else 0)


def image_for(db: Session, user: User, group_id: str, item_id: str) -> tuple[bytes, str]:
    item = repository.get_item(db, item_id, group_id)
    if item is None or item.game not in (GAME_DRAW, GAME_PHOTO):
        raise not_found("이미지")
    members = group_repo.members(db, group_id)
    if item.maker_id != user.id and user.id not in recipient_ids(item, members):
        raise not_found("이미지")
    if item.game == GAME_DRAW:
        draw = repository.get_draw(db, item.id)
        if draw is None:
            raise not_found("이미지")
        return media.read(draw.image_path), "image/png"
    photo = repository.get_photo(db, item.id)
    if photo is None:
        raise not_found("이미지")
    jpeg = media.read(photo.image_path)
    full, shrinks = _photo_view(
        item, user, is_closed(item, _now()), repository.answers_of(db, item.id)
    )
    if full:
        return jpeg, "image/jpeg"
    return media.crop_zoom(jpeg, photo.box_x, photo.box_y, photo.zoom, shrinks), "image/jpeg"


# ---------- 보기 ----------
def _score_out(scores: list[PlayScore]) -> PlayScoreOut:
    by = {}
    for s in scores:
        by[s.reason] = by.get(s.reason, 0) + s.points
    join, correct, hint = by.get(REASON_JOIN, 0), by.get(REASON_CORRECT, 0), by.get(REASON_HINT, 0)
    return PlayScoreOut(total=sum(by.values()), join=join, correct=correct, hint=hint)


def _draw_out(
    draw: PlayDraw,
    mine: list[PlayAnswer],
    hint: PlayAnswer | None,
    *,
    is_maker: bool,
    show_answers: bool,
    last_try_correct: bool | None,
) -> PlayDrawOut:
    tries = _tries(mine)
    used = hint.hints_used if hint else 0
    # 낸 사람과 결과를 볼 수 있는 사람에게는 힌트를 모두 보여 준다
    show_hint1 = show_answers or used >= 1
    show_hint2 = bool(draw.hint2) and (show_answers or used >= 2)
    return PlayDrawOut(
        tries_used=len(tries),
        max_tries=DRAW_MAX_TRIES,
        solved=any(a.is_correct for a in tries),
        finished=False if is_maker else _draw_finished(mine),
        last_try_correct=last_try_correct,
        hints_used=used,
        max_hints=MAX_HINTS if draw.hint2 else 1,
        hint1=f"{len(_norm(draw.answer))}글자" if show_hint1 else None,
        hint2=draw.hint2 if show_hint2 else None,
        answer=draw.answer if show_answers else None,
        alt_answers=(draw.alt_answers or []) if show_answers else None,
    )


def item_out(
    db: Session,
    item: PlayItem,
    user: User,
    members: list[User],
    now: datetime | None = None,
    *,
    last_try_correct: bool | None = None,
) -> PlayItemOut:
    now = now or _now()
    by_id = {m.id: m for m in members}
    closed = is_closed(item, now)
    is_maker = item.maker_id == user.id
    recipients = recipient_ids(item, members)
    if not is_maker and user.id not in recipients:
        raise not_found("문제")
    all_rows = repository.answers_of(db, item.id)
    answers = _tries(all_rows)
    joined = participants(item, all_rows, closed)
    mine = [a for a in answers if a.player_id == user.id]
    state = "maker" if is_maker else ("done" if user.id in joined else "todo")
    show_answers = is_maker or closed or state == "done"
    questions = [
        PlayQuestionOut(
            quiz_no=q.quiz_no,
            qtype=q.qtype,
            question=q.question,
            options=q.options,
            answer=q.answer if show_answers else None,
            comment=q.comment if show_answers else None,
        )
        for q in repository.quiz_rows(db, item.id)
    ]
    draw_out = photo_out = image_url = None
    if item.game == GAME_DRAW:
        draw = repository.get_draw(db, item.id)
        if draw is not None:
            draw_out = _draw_out(
                draw,
                [a for a in all_rows if a.player_id == user.id],
                _hint_row(all_rows, user.id),
                is_maker=is_maker,
                show_answers=show_answers,
                last_try_correct=last_try_correct,
            )
            image_url = f"/play/items/{item.id}/image"
    elif item.game == GAME_PHOTO:
        photo = repository.get_photo(db, item.id)
        if photo is not None:
            full, shrinks = _photo_view(item, user, closed, all_rows)
            photo_out = PlayPhotoOut(
                question=photo.question,
                options=photo.options,
                zoom=photo.zoom if full else media.effective_zoom(photo.zoom, shrinks),
                source=photo.source,
                shrinks_used=shrinks,
                max_shrinks=MAX_HINTS,
                answer=photo.answer if show_answers else None,
                comment=photo.comment if show_answers else None,
                box_x=photo.box_x if full else None,
                box_y=photo.box_y if full else None,
            )
            # 줄여 보기·결과 공개로 사진이 달라지면 주소도 달라져서 오래된 사진이 남지 않는다
            image_url = f"/play/items/{item.id}/image?v={shrinks}{'f' if full else ''}"
    my_answers = [
        PlayAnswerOut(
            quiz_no=a.quiz_no,
            answer=a.answer,
            is_correct=a.is_correct,
            hints_used=a.hints_used,
        )
        for a in mine
    ] or None
    my_score = _score_out(repository.scores_of(db, item.id, user.id)) if mine else None
    status = [
        PlayFamilyStatusOut(
            player=_person(by_id.get(pid)), done=pid in joined, answered_at=joined.get(pid)
        )
        for pid in recipients
    ]
    family_answers = None
    if closed:
        family_answers = [
            PlayFamilyAnswersOut(
                player=_person(by_id.get(pid)),
                answered_at=when,
                answers=[
                    PlayAnswerOut(
                        quiz_no=a.quiz_no,
                        answer=a.answer,
                        is_correct=a.is_correct,
                        hints_used=a.hints_used,
                    )
                    for a in answers
                    if a.player_id == pid
                ],
            )
            for pid, when in sorted(joined.items(), key=lambda kv: kv[1])
            if pid in by_id
        ]
    maker_score, maker_state = None, None
    if is_maker:
        if not closed:
            maker_state = "pending"
        elif repository.score_exists(db, item.id, REASON_MAKE):
            maker_score, maker_state = POINT_MAKE, "paid"
        elif not set(joined) & set(recipients):
            maker_score, maker_state = 0, "none_solved"
        else:
            maker_score, maker_state = 0, "daily_limit"
    return PlayItemOut(
        id=item.id,
        game=item.game,
        maker=_person(by_id.get(item.maker_id)),
        created_at=aware(item.created_at),
        close_at=aware(item.close_at),
        closed=closed,
        is_maker=is_maker,
        my_state=state,
        progress_done=len(set(joined) & set(recipients)),
        progress_total=len(recipients),
        questions=questions,
        draw=draw_out,
        photo=photo_out,
        image_url=image_url,
        my_answers=my_answers,
        my_score=my_score,
        family_status=status,
        family_answers=family_answers,
        maker_score=maker_score,
        maker_score_state=maker_state,
    )


def get_item(db: Session, user: User, group_id: str, item_id: str) -> PlayItemOut:
    settle_group(db, group_id)
    item = repository.get_item(db, item_id, group_id)
    if item is None:
        raise not_found("문제")
    return item_out(db, item, user, group_repo.members(db, group_id))


def board(db: Session, user: User, group_id: str) -> PlayBoardOut:
    now = _now()
    settle_group(db, group_id, now)
    members = group_repo.members(db, group_id)
    by_id = {m.id: m for m in members}
    items = repository.board_items(db, group_id, now - timedelta(days=RESULT_DAYS))
    ids = [i.id for i in items]
    answers = repository.answers_of_many(db, ids)
    counts = repository.quiz_counts(db, ids)
    out = PlayBoardOut(todo=[], joined=[], past=[], sent=[], sent_past=[])
    room = repository.open_bomb_room(db, group_id, now)  # 열린 폭탄방은 맨 위
    if room is not None:
        row = PlayBoardItemOut(
            id=room.id,
            game=room.game,
            maker=_person(by_id.get(room.maker_id)),
            close_at=aware(room.close_at),
            closed=False,
            progress_done=len(repository.bomb_players(db, room.id)),
            progress_total=0,
            question_count=0,
        )
        (out.sent if room.maker_id == user.id else out.todo).append(row)
    for item in items:
        closed = is_closed(item, now)
        joined = participants(item, answers[item.id], closed)
        recipients = recipient_ids(item, members)
        row = PlayBoardItemOut(
            id=item.id,
            game=item.game,
            maker=_person(by_id.get(item.maker_id)),
            close_at=aware(item.close_at),
            closed=closed,
            progress_done=len(set(joined) & set(recipients)),
            progress_total=len(recipients),
            question_count=counts.get(item.id, 1),  # 그림·사진은 문제 하나
        )
        if item.maker_id == user.id:
            (out.sent_past if closed else out.sent).append(row)
        elif user.id in recipients:
            if not closed:
                (out.joined if user.id in joined else out.todo).append(row)
            elif user.id in joined:
                out.past.append(row)  # 지난 결과는 내가 참여한 것만
    return out


# ---------- 오늘 남은 횟수 ----------
def quota(db: Session, user: User) -> PlayQuotaOut:
    """문제 내기 점수(+20)는 하루 3건까지(게임 구분 없음). 한도를 넘어도 문제는 보낼 수 있고 점수만 없다."""
    start = local_day_start(_now())
    used = len(repository.maker_items_between(db, user.id, start, start + timedelta(days=1)))
    return PlayQuotaOut(limit=DAILY_MAKE_LIMIT, used=used, left=max(0, DAILY_MAKE_LIMIT - used))


# ---------- 순위 ----------
def ranking(db: Session, group_id: str, period: str) -> PlayRankingOut:
    now = _now()
    settle_group(db, group_id, now)
    since = {"week": week_start(now), "month": month_start(now), "all": None}[period]
    members = group_repo.members(db, group_id)
    rows: dict[str, dict] = {
        m.id: {
            "by": {1: 0, 2: 0, 3: 0, 4: 0},
            "etc": 0,
            "n": {1: 0, 2: 0, 3: 0, 4: 0},
            "right": {1: 0, 2: 0, 3: 0, 4: 0},
            "win": {1: 0, 2: 0, 3: 0, 4: 0},
        }
        for m in members
    }
    for s in repository.scores_since(db, group_id, since):
        r = rows.get(s.player_id)
        if r is None:
            continue  # 가족을 나간 사람은 순위에서 뺀다
        if s.reason in (REASON_JOIN, REASON_MAKE):
            r["etc"] += s.points
        else:
            r["by"][s.game] = r["by"].get(s.game, 0) + s.points
        if s.reason == REASON_JOIN:
            r["n"][s.game] = r["n"].get(s.game, 0) + 1
        if s.reason == REASON_BOMB_WIN:
            r["win"][s.game] = r["win"].get(s.game, 0) + 1  # 폭탄 우승 횟수
    for pid, game, n in repository.correct_counts(db, group_id, since):
        if pid in rows:
            rows[pid]["right"][game] = n
    out = [
        PlayRankRow(
            player=_person(m),
            score=sum(rows[m.id]["by"].values()) + rows[m.id]["etc"],
            by_game=rows[m.id]["by"],
            etc=rows[m.id]["etc"],
            counts=rows[m.id]["n"],
            # 골든벨·이게 뭐게·탐정단은 맞힌 개수, 폭탄은 우승 횟수
            corrects={**rows[m.id]["right"], 4: rows[m.id]["win"][4]},
        )
        for m in members
    ]
    out.sort(key=lambda r: (-r.score, r.player.name))
    return PlayRankingOut(period=period, rows=out)
