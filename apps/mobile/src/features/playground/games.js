// 가족 놀이터 게임 4종의 이름·문구·아이콘. 와이어프레임(v1.1) 기준.
export const GAMES = {
  quiz: { key: "quiz", name: "가족 골든벨", tagline: "우리 가족 얼마나 알까?", icon: { set: "ion", name: "bulb-outline" }, create: "/play/quiz-create" },
  draw: { key: "draw", name: "이게 뭐게", tagline: "이 그림, 뭘 그린 걸까?", icon: { set: "ion", name: "color-palette-outline" }, create: "/play/draw-create" },
  photo: { key: "photo", name: "찰칵! 탐정단", tagline: "그날의 추억을 찾아서", icon: { set: "ion", name: "camera-outline" }, create: "/play/photo-create" },
  bomb: { key: "bomb", name: "문장 폭탄", tagline: "끝내는 순간 터진다!", icon: { set: "mci", name: "bomb" }, create: "/play/bomb-lobby" },
};
export const GAME_LIST = [GAMES.quiz, GAMES.draw, GAMES.photo, GAMES.bomb];

// 점수 규칙: 참여 +10, 정답 +20, 문제 내기 +20, 폭탄 우승 +30. 힌트·줄여 보기는 -5
export const SCORE = { join: 10, correct: 20, make: 20, bombWin: 30, hintCost: 5 };

// 문제 내기 점수는 한 사람이 하루에 낸 문제 전체(게임 구분 없이) 3건까지. 한도를 넘어도 문제는 보낼 수 있고 점수만 없다
export const MAKE_LIMIT = 3;

/** 문제 내기 점수(+20)를 받을 수 있는 남은 횟수 안내. 다 썼으면 두 줄: 점수는 없어도 문제는 보낼 수 있다는 것을 알린다. */
export const makeQuotaText = (left) =>
  left > 0 ? `오늘 문제 출제로 받는 +${SCORE.make}은 ${left}회 남았어요` : `오늘은 문제 출제로 +${SCORE.make} 받는 ${MAKE_LIMIT}회를 다 썼어요\n문제는 보낼 수 있지만 점수는 없어요`;
