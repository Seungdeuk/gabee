"""가족 놀이터 테이블.

문제 3종(가족 골든벨·이게 뭐게·찰칵! 탐정단)과 문장 폭탄방은 모두 `play_items` 한 줄에서 시작하고,
게임별 내용은 딸린 테이블에 둔다. 점수는 장부 `play_scores` 에 줄로 쌓고 순위는 그 합계로 구한다.
파일(그림·사진)은 DB 에 서버가 정한 상대 경로만 둔다(`play/drawings/…`, `play/photos/…`).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base

# game: 1 가족 골든벨 · 2 이게 뭐게 · 3 찰칵! 탐정단 · 4 문장 폭탄방
GAME_QUIZ = 1
GAME_DRAW = 2
GAME_PHOTO = 3
GAME_BOMB = 4

# play_scores.reason: 1 참여 · 2 정답 · 3 문제 낸 사람 · 4 폭탄 우승 · 5 힌트(줄여 보기 포함)
REASON_JOIN = 1
REASON_CORRECT = 2
REASON_MAKE = 3
REASON_BOMB_WIN = 4
REASON_HINT = 5


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class PlayItem(Base):
    """놀이 한 건의 머리(폭탄방 포함). 골든벨은 세트 하나가 한 줄, 폭탄방은 방 하나가 한 줄이다.

    닫힘은 칸으로 두지 않고 `close_at` 이 지금보다 이전인지로 계산한다.
    비동기 3종은 만든 시각 + 24시간(받는 사람이 모두 답하면 그 순간으로 덮어씀),
    폭탄방은 만든 시각 + 1시간(판이 시작되면 시작 + 2시간, 판이 끝나면 끝난 시각 + 1시간,
    방장이 닫으면 그 순간).
    """

    __tablename__ = "play_items"
    __table_args__ = (
        Index("ix_play_items_group_id_created_at", "group_id", "created_at"),
        # 문제 내기 점수는 하루 3건까지라 "이 사람이 오늘 낸 놀이 수"를 빨리 센다
        Index("ix_play_items_maker_id_created_at", "maker_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"))
    game: Mapped[int] = mapped_column(SmallInteger)
    # 낸 사람. 폭탄방은 방장
    maker_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    # 받는 사람 id 목록. 비어 있으면 가족 모두, 폭탄방은 항상 비움
    player_ids: Mapped[list] = mapped_column(JSON, default=list)
    close_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PlayQuiz(Base):
    """골든벨 문항(1~5번). answer 는 보기 순서의 비트 글자: 4지선다에서 1번이 답이면 "1000", OX 에서 O 면 "10"."""

    __tablename__ = "play_quiz"

    play_id: Mapped[str] = mapped_column(ForeignKey("play_items.id"), primary_key=True)
    quiz_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    qtype: Mapped[int] = mapped_column(SmallInteger)  # 1 OX, 2 선택
    question: Mapped[str] = mapped_column(String(100))
    options: Mapped[list] = mapped_column(JSON)  # OX 도 ["O","X"]
    answer: Mapped[str] = mapped_column(String(8))
    comment: Mapped[str | None] = mapped_column(String(100), nullable=True)


class PlayDraw(Base):
    """이게 뭐게. 힌트 1(글자 수)은 정답 길이로 계산하고 힌트 2 는 출제자가 쓴 한 줄이다."""

    __tablename__ = "play_draws"

    play_id: Mapped[str] = mapped_column(ForeignKey("play_items.id"), primary_key=True)
    image_path: Mapped[str] = mapped_column(String(255))  # play/drawings/<가족id>/<놀이id>.png
    answer: Mapped[str] = mapped_column(String(40))
    alt_answers: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 이것도 정답
    hint2: Mapped[str | None] = mapped_column(String(20), nullable=True)


class PlayPhoto(Base):
    """찰칵! 탐정단(선택식만). answer 는 보기 순서의 비트 글자(예: "0100")."""

    __tablename__ = "play_photos"

    play_id: Mapped[str] = mapped_column(ForeignKey("play_items.id"), primary_key=True)
    image_path: Mapped[str] = mapped_column(String(255))  # play/photos/<가족id>/<놀이id>.jpg
    source: Mapped[int] = mapped_column(SmallInteger)  # 1 가족 앨범, 2 내 폰, 3 흔한 사진
    zoom: Mapped[int] = mapped_column(SmallInteger)  # 4·6·8·16·32
    box_x: Mapped[float] = mapped_column(Float)  # 확대 상자 위치 0~1
    box_y: Mapped[float] = mapped_column(Float)
    question: Mapped[str] = mapped_column(String(20))
    options: Mapped[list] = mapped_column(JSON)  # 보기 2~4개
    answer: Mapped[str] = mapped_column(String(4))
    comment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 가비 추천 카드(play_photo_rec.id)로 낸 문제면 그 id. 같은 추천을 14일 안에 다시 안 보이려고 쓴다(외래 키는 없다: 추천 행이 지워져도 문제는 남는다)
    rec_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)


class PlayPhotoRec(Base):
    """찰칵! 탐정단 가비 추천이 보여 주는 사진 문제 한 건(가족 앨범 사진 또는 흔한 사진).

    가족 앨범 행은 `group_id`·`attachment_id`(채팅 사진, 유일 → 한 사진 한 문제)가 있고 이미지는 첨부 파일을 쓴다.
    흔한 사진 행은 `group_id` 가 비고 `image`(JPEG 바이트)를 DB 에 둔다. 모든 가족이 같은 행을 읽는다.
    `answer` 는 `play_photos.answer` 와 같은 보기 순서의 비트 글자(예: "0100").
    """

    __tablename__ = "play_photo_rec"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    group_id: Mapped[str | None] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source: Mapped[int] = mapped_column(
        SmallInteger
    )  # 1 가족 앨범, 3 흔한 사진(시드), 4 흔한 사진(자동)
    attachment_id: Mapped[str | None] = mapped_column(
        ForeignKey("message_attachments.id", ondelete="CASCADE"), nullable=True, unique=True
    )
    image: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    kind: Mapped[int] = mapped_column(SmallInteger)  # 1 촬영 월, 2 일정 맞추기, 3 사진 내용(AI)
    usable: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    question: Mapped[str] = mapped_column(String(20))
    options: Mapped[list] = mapped_column(JSON)  # 보기 2~4개
    answer: Mapped[str] = mapped_column(String(4))
    box_x: Mapped[float] = mapped_column(Float)  # 확대 상자 위치 0~1
    box_y: Mapped[float] = mapped_column(Float)
    zoom: Mapped[int] = mapped_column(SmallInteger)  # 4·6·8·16·32
    prompt_version: Mapped[str] = mapped_column(String(8))
    # 흔한 사진(자동)의 출처. 시드·가족 행은 비어 있다
    credit_user: Mapped[str | None] = mapped_column(String(80), nullable=True)
    credit_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    license: Mapped[str | None] = mapped_column(String(40), nullable=True)
    search_query: Mapped[str | None] = mapped_column(String(60), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PlayAnswer(Base):
    """낸 답. 시도마다 한 줄이다(이게 뭐게는 1~10번째 시도, 골든벨·탐정단은 try_no 1 고정).

    골든벨은 문항마다 한 줄(quiz_no 1, 2, 3…)이고 마지막 `답 보내기`에서 한 번에 저장한다.
    그림·사진은 quiz_no 0. hints_used 는 그 시점에 쓴 힌트 수(줄여 보기 포함)이고 마지막 줄의 값이 최종 값이다.
    """

    __tablename__ = "play_answers"
    __table_args__ = (
        UniqueConstraint("play_id", "player_id", "quiz_no", "try_no", name="uq_play_answers_try"),
        Index("ix_play_answers_play_id_player_id", "play_id", "player_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    play_id: Mapped[str] = mapped_column(ForeignKey("play_items.id"))
    player_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    quiz_no: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    try_no: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    answer: Mapped[str] = mapped_column(String(40))  # 글 또는 비트 글자
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    hints_used: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PlayScore(Base):
    """점수 장부. 순위(이번 주 월요일 시작·이번 달·전체)와 게임별 참여 횟수는 이 줄들을 합산해서 구한다.

    참여 +10은 항상, 정답 +20은 추가, 힌트 −5씩(틀려도 깎음, 최대 2번이라 총점 0 아래로는 안 내려감), 문제 내기 +20(하루 3건까지).
    골든벨은 문항마다가 아니라 세트당 참여 1줄·정답 1줄(20 × 맞힌 수 ÷ 문항 수 반올림)이다.
    """

    __tablename__ = "play_scores"
    __table_args__ = (Index("ix_play_scores_group_id_created_at", "group_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"))
    player_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    play_id: Mapped[str] = mapped_column(ForeignKey("play_items.id"))
    game: Mapped[int] = mapped_column(SmallInteger)
    round_no: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)  # 폭탄 판 번호
    reason: Mapped[int] = mapped_column(SmallInteger)
    points: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PlayBombPlayer(Base):
    """폭탄방에 들어온 사람. 나가면 줄을 지우고, 다시 들어오면 새로 넣어 맨 뒤로 간다."""

    __tablename__ = "play_bomb_players"

    play_id: Mapped[str] = mapped_column(ForeignKey("play_items.id"), primary_key=True)
    player_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PlayBombRound(Base):
    """폭탄방의 판. "한 판 더"는 같은 play_id 에 round_no 만 늘어난다. ended_at 이 비어 있으면 진행 중."""

    __tablename__ = "play_bomb_rounds"

    play_id: Mapped[str] = mapped_column(ForeignKey("play_items.id"), primary_key=True)
    round_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    life: Mapped[int] = mapped_column(SmallInteger)  # 1~5
    sec: Mapped[int] = mapped_column(SmallInteger)  # 1~60초
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    winner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    longest_len: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")


class PlayBombTurn(Base):
    """폭탄방 말 기록(한 줄 = 한 차례). 문장은 is_end 가 나올 때까지의 말을 이어 붙여서 만든다."""

    __tablename__ = "play_bomb_turns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["play_id", "round_no"],
            ["play_bomb_rounds.play_id", "play_bomb_rounds.round_no"],
        ),
    )

    play_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    round_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    turn_seq: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    player_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    is_say: Mapped[bool] = mapped_column(Boolean)  # 참 말함, 거짓 시간 초과
    word: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 말한 글, 시간 초과면 비움
    is_end: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    life: Mapped[int] = mapped_column(SmallInteger)  # 이 차례 뒤 남은 생명
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PlayDrawStock(Base):
    """이게 뭐게 가비 추천이 AI 로 만든 단어별 선 그림. 가족과 무관하게 모든 가족이 계속 다시 쓴다(단어당 최대 3종, 기간 제한 없음).
    strokes 는 선 목록(`[[[x, y], ...], ...]`, 좌표 0~255)이고 가족 정보는 들어 있지 않다."""

    __tablename__ = "play_draw_stock"
    __table_args__ = (Index("ix_play_draw_stock_word_created_at", "word", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    word: Mapped[str] = mapped_column(String(8))
    strokes: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
