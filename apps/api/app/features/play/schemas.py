from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .constants import (
    QUIZ_COMMENT_MAX,
    QUIZ_MAX_QUESTIONS,
    QUIZ_OPTION_MAX,
    QUIZ_QUESTION_MAX,
    RECIPIENT_MAX,
)


# ---------- 골든벨 만들기 ----------
class PlayQuizQuestionIn(BaseModel):
    qtype: Literal[1, 2]  # 1 OX, 2 선택
    question: str = Field(min_length=1, max_length=QUIZ_QUESTION_MAX)
    options: list[str] = Field(min_length=2, max_length=4)  # OX 는 ["O","X"]
    answer_index: int = Field(ge=0, le=3)  # 정답 보기의 위치(0부터)
    comment: str | None = Field(default=None, max_length=QUIZ_COMMENT_MAX)

    @field_validator("question")
    @classmethod
    def _strip_question(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("문제를 써 주세요")
        return v

    @field_validator("options")
    @classmethod
    def _clean_options(cls, v: list[str]) -> list[str]:
        out = [o.strip() for o in v]
        if any(not o or len(o) > QUIZ_OPTION_MAX for o in out):
            raise ValueError(f"보기는 1~{QUIZ_OPTION_MAX}자로 채워 주세요")
        if len(set(out)) != len(out):
            raise ValueError("같은 보기가 있어요")
        return out

    @model_validator(mode="after")
    def _check_shape(self) -> "PlayQuizQuestionIn":
        if self.qtype == 1 and self.options != ["O", "X"]:
            raise ValueError("OX 문제의 보기는 O, X 여야 해요")
        if self.answer_index >= len(self.options):
            raise ValueError("정답 보기가 보기 개수를 넘었어요")
        return self


class PlayQuizCreateIn(BaseModel):
    questions: list[PlayQuizQuestionIn] = Field(min_length=1, max_length=QUIZ_MAX_QUESTIONS)
    # 받는 사람. 비어 있으면 가족 모두(만든 사람은 빼고)
    player_ids: list[str] = Field(default_factory=list, max_length=RECIPIENT_MAX)


class PlayQuizRecItem(BaseModel):
    id: str
    source: Literal["schedule", "chat"]  # 일정에서 / 소통방에서
    kind: Literal["ox", "choice"]
    question: str
    options: list[str]
    answer_index: int


class PlayQuizRecOut(BaseModel):
    """가비 추천. state 가 ok 일 때만 items 가 있다. no_data 재료 없음, used_up 오늘 추천을 다 썼음(또는 한도), preparing 다른 가족이 만드는 중,
    cooldown 방금 불렀음, failed 만들지 못함, ai_off 가족 AI 꺼짐."""

    state: Literal["ok", "no_data", "used_up", "preparing", "cooldown", "failed", "ai_off"]
    items: list[PlayQuizRecItem] = Field(default_factory=list)


# ---------- 이게 뭐게 가비 추천 ----------
class PlayDrawRecItem(BaseModel):
    id: str
    source: Literal["schedule", "chat", "common"]  # 일정에서 / 소통방에서 / 흔한 단어
    word: str  # 정답 단어(한 단어)
    alt_answers: list[str] = Field(default_factory=list)  # 이것도 정답
    strokes: list[list[list[int]]]  # 선 목록: 선마다 [x, y] 점 목록, 좌표 0~255


class PlayDrawRecOut(BaseModel):
    """이게 뭐게 가비 추천. items 는 state 가 ok(5개가 다 모임 또는 한도를 다 쓴 뒤 저장된 그림) 또는 partial(일부만 준비됨, 다시 불러오면 모자란 만큼 채움)일 때 있다. used_up 오늘 추천을 다 썼음(또는 한도), preparing 다른 가족이 만드는 중,
    cooldown 방금 불렀음, failed 만들지 못함, ai_off 가족 AI 꺼짐. 재료가 없어도 흔한 단어로 채우므로 no_data 는 없다."""

    state: Literal["ok", "partial", "used_up", "preparing", "cooldown", "failed", "ai_off"]
    items: list[PlayDrawRecItem] = Field(default_factory=list)


# ---------- 이게 뭐게 ----------
class PlayDrawTryIn(BaseModel):
    answer: str = Field(min_length=1, max_length=40)

    @field_validator("answer")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("정답을 써 주세요")
        return v


# ---------- 답 보내기 ----------
class PlayAnswerItemIn(BaseModel):
    quiz_no: int = Field(ge=0, le=QUIZ_MAX_QUESTIONS)  # 골든벨 1~5, 탐정단은 0
    answer: str = Field(pattern=r"^[01]{2,4}$")  # 고른 보기를 비트 글자로("0100")


class PlayQuizAnswerIn(BaseModel):
    """골든벨은 마지막 `답 보내기` 에서 문항 수만큼 한 번에 보낸다."""

    answers: list[PlayAnswerItemIn] = Field(min_length=1, max_length=QUIZ_MAX_QUESTIONS)


# ---------- 응답 ----------
class PlayPersonOut(BaseModel):
    id: str
    name: str


class PlayQuestionOut(BaseModel):
    quiz_no: int
    qtype: int
    question: str
    options: list[str]
    # 정답과 한마디는 낸 사람, 이미 푼 사람, 닫힌 뒤에만 채워진다
    answer: str | None = None
    comment: str | None = None


class PlayAnswerOut(BaseModel):
    quiz_no: int
    answer: str
    is_correct: bool
    hints_used: int = 0  # 그 시도 때까지 쓴 힌트·줄여 보기 수


class PlayFamilyStatusOut(BaseModel):
    player: PlayPersonOut
    done: bool
    answered_at: datetime | None = None


class PlayFamilyAnswersOut(BaseModel):
    player: PlayPersonOut
    answered_at: datetime
    answers: list[PlayAnswerOut]


class PlayScoreOut(BaseModel):
    total: int
    join: int
    correct: int
    hint: int = 0


class PlayDrawOut(BaseModel):
    """이게 뭐게. 힌트는 연 만큼만, 정답은 낸 사람·끝낸 사람·닫힌 뒤에만 보인다."""

    tries_used: int
    max_tries: int
    solved: bool
    finished: bool  # 맞혔거나 10번 다 틀림(참여 처리됨)
    last_try_correct: bool | None = None  # 방금 보낸 답이 맞았는지(조회만 하면 None)
    hints_used: int
    max_hints: int
    hint1: str | None = None  # "3글자"
    hint2: str | None = None
    answer: str | None = None
    alt_answers: list[str] | None = None


class PlayPhotoOut(BaseModel):
    """찰칵! 탐정단(선택식). 풀고 있는 사람의 사진은 확대해서 자른 부분만 나간다."""

    question: str
    options: list[str]
    zoom: int
    source: int
    shrinks_used: int  # 조금 줄여 보기를 쓴 횟수
    max_shrinks: int
    answer: str | None = None  # 비트 글자
    comment: str | None = None
    # 확대 창 가운데 위치(0~1). 원본 전체를 볼 수 있을 때만 채워진다(풀이 중에는 사진의 어디인지 새지 않게 비움)
    box_x: float | None = None
    box_y: float | None = None


class PlayItemOut(BaseModel):
    id: str
    game: int
    maker: PlayPersonOut
    created_at: datetime
    close_at: datetime
    closed: bool
    is_maker: bool
    my_state: Literal["maker", "todo", "done"]
    progress_done: int
    progress_total: int
    questions: list[PlayQuestionOut] = []
    draw: PlayDrawOut | None = None
    photo: PlayPhotoOut | None = None
    image_url: str | None = None  # 그림·사진 가져오는 주소(로그인 필요)
    my_answers: list[PlayAnswerOut] | None = None
    my_score: PlayScoreOut | None = None
    family_status: list[PlayFamilyStatusOut] = []
    # 가족 모두의 답은 닫힌 뒤에만(푼 순서)
    family_answers: list[PlayFamilyAnswersOut] | None = None
    # 문제를 낸 사람의 점수: 닫힌 뒤 paid(받음)·none_solved(아무도 안 풀음)·daily_limit(하루 한도), 닫히기 전은 pending
    maker_score: int | None = None
    maker_score_state: Literal["pending", "paid", "none_solved", "daily_limit"] | None = None


class PlayBoardItemOut(BaseModel):
    id: str
    game: int
    maker: PlayPersonOut
    close_at: datetime
    closed: bool
    progress_done: int
    progress_total: int
    question_count: int = 0
    winner: PlayPersonOut | None = None  # 닫힌 폭탄 방: 마지막 판의 우승자(판 수는 question_count)


class PlayBoardOut(BaseModel):
    # 받은: 내가 할 차례 / 내가 참여했어요 / 지난 결과(최근 3일, 참여한 것만)
    todo: list[PlayBoardItemOut]
    joined: list[PlayBoardItemOut]
    past: list[PlayBoardItemOut]
    # 보낸: 내가 낸 문제 / 지난 결과(최근 3일)
    sent: list[PlayBoardItemOut]
    sent_past: list[PlayBoardItemOut]


class PlayRankRow(BaseModel):
    player: PlayPersonOut
    score: int
    by_game: dict[int, int]  # game(1~4) → 정답·우승·힌트 점수
    etc: int  # 참여·문제 내기 점수
    counts: dict[int, int]  # game(1~4) → 참여 횟수
    corrects: dict[int, int]  # game(1~4) → 맞힌 개수(폭탄은 우승 횟수)


class PlayQuotaOut(BaseModel):
    """오늘(한국 시간) 내가 낸 문제 수와 문제 내기 점수(+20)를 받을 수 있는 남은 횟수."""

    limit: int
    used: int
    left: int


class PlayRankingOut(BaseModel):
    period: Literal["week", "month", "all"]
    rows: list[PlayRankRow]
