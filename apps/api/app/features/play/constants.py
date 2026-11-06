"""가족 놀이터 규칙 값. 앱 화면과 위키 `family-playground` 의 확정 규칙과 같다."""

from .models import (
    GAME_BOMB,
    GAME_DRAW,
    GAME_PHOTO,
    GAME_QUIZ,
    REASON_CORRECT,
    REASON_JOIN,
    REASON_MAKE,
)

# 비동기 3종(골든벨·이게 뭐게·찰칵! 탐정단). 폭탄방은 실시간이라 다른 규칙을 쓴다
ASYNC_GAMES = (GAME_QUIZ, GAME_DRAW, GAME_PHOTO)

CLOSE_HOURS = 24  # 만든 시각 + 24시간(받는 사람이 모두 답하면 그 순간으로 당김)
RESULT_DAYS = 3  # 지난 결과는 닫힌 뒤 최근 3일
SETTLE_DAYS = 14  # 닫힌 뒤 이 기간 안의 놀이만 "문제 낸 사람 점수" 정산 대상으로 본다

# 점수
POINT_JOIN = 10  # 참여(실패해도 항상)
POINT_CORRECT = 20  # 정답(골든벨은 세트 전체 20점을 맞힌 비율로 나눔)
POINT_MAKE = 20  # 문제 내기(받는 가족 중 한 명이라도 풀어야, 닫힐 때 지급)
POINT_HINT = 5  # 힌트·줄여 보기 한 번당 감점
POINT_BOMB_WIN = 30  # 문장 폭탄 우승(참여 +10 은 따로)
DAILY_MAKE_LIMIT = 3  # 한 사람이 하루(한국 시간)에 낸 문제 전체(게임 구분 없이) 3건까지만 점수

QUIZ_MAX_QUESTIONS = 5
DRAW_MAX_TRIES = 10  # 이게 뭐게 정답 시도 횟수(틀려도 감점 없음)
MAX_HINTS = 2  # 이게 뭐게 힌트 1·2, 탐정단 줄여 보기는 모두 최대 2번(번마다 -5점)
DRAW_ANSWER_MAX = 40
DRAW_ALT_MAX = 5  # 이것도 정답 개수
DRAW_HINT2_MAX = 20
PHOTO_QUESTION_MAX = 20
PHOTO_COMMENT_MAX = 100
PHOTO_ZOOMS = (4, 6, 8, 16, 32)
QUIZ_QUESTION_MAX = 100
QUIZ_OPTION_MAX = 20
QUIZ_COMMENT_MAX = 100
RECIPIENT_MAX = 30

__all__ = [
    "ASYNC_GAMES",
    "DRAW_ALT_MAX",
    "DRAW_ANSWER_MAX",
    "DRAW_HINT2_MAX",
    "DRAW_MAX_TRIES",
    "MAX_HINTS",
    "PHOTO_COMMENT_MAX",
    "PHOTO_QUESTION_MAX",
    "PHOTO_ZOOMS",
    "CLOSE_HOURS",
    "DAILY_MAKE_LIMIT",
    "GAME_BOMB",
    "GAME_DRAW",
    "GAME_PHOTO",
    "GAME_QUIZ",
    "POINT_BOMB_WIN",
    "POINT_CORRECT",
    "POINT_HINT",
    "POINT_JOIN",
    "POINT_MAKE",
    "QUIZ_COMMENT_MAX",
    "QUIZ_MAX_QUESTIONS",
    "QUIZ_OPTION_MAX",
    "QUIZ_QUESTION_MAX",
    "RECIPIENT_MAX",
    "REASON_CORRECT",
    "REASON_JOIN",
    "REASON_MAKE",
    "RESULT_DAYS",
    "SETTLE_DAYS",
]
