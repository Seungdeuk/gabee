import { MAKE_LIMIT } from "./games";

// 서버 연결 전까지 쓰는 시안 데이터. 화면 구조는 와이어프레임(v1.1)과 같다.
export const ME = { id: "me", name: "나" };
export const MEMBERS = [
  { id: "mom", name: "엄마" },
  { id: "dad", name: "아빠" },
  { id: "son", name: "아들" },
  { id: "daughter", name: "딸" },
  ME,
];

// 내 차례(받은 것). 폭탄 방이 열려 있으면 항상 맨 앞.
export const TODO = [
  { id: "t1", game: "bomb", route: "/play/bomb-lobby?host=0", title: "엄마가 폭탄 방을 열었어요", sub: "", action: "입장", strong: true },
  { id: "t2", reveal: "오늘 오후 2:10", game: "draw", route: "/play/draw-guess", title: "아들이 낸 이게 뭐게", sub: "이게 뭐게 · 오늘 오후 2:10 공개", action: "맞히기", done: ["엄마"], pending: ["아빠", "딸"] },
  { id: "t3", reveal: "내일 오후 2:10", game: "photo", route: "/play/photo-guess", title: "딸이 낸 찰칵! 탐정단", sub: "찰칵! 탐정단 · 내일 오후 2:10 공개", action: "맞히기", done: ["엄마"], pending: ["아빠", "아들"] },
  { id: "t4", reveal: "내일 오전 9:30", game: "quiz", route: "/play/quiz-play", title: "엄마가 낸 가족 골든벨", sub: "가족 골든벨 · 내일 오전 9:30 공개", action: "풀기", done: ["아빠"], pending: ["아들", "딸"] },
  { id: "t5", reveal: "내일 오전 11:00", game: "draw", route: "/play/draw-guess", title: "아빠가 낸 이게 뭐게", sub: "이게 뭐게 · 내일 오전 11:00 공개", action: "맞히기", done: [], pending: ["엄마", "아들", "딸"] },
];
// 나는 끝냈고 가족을 기다리는 중
export const WAITING = [
  { id: "w1", reveal: "내일 오전 9:30", game: "quiz", route: "/play/my-answer?kind=quiz", title: "아빠가 낸 가족 골든벨", sub: "내 답은 보냈어요", done: ["엄마"], pending: ["아들", "딸"] },
  { id: "w2", reveal: "내일 오전 11:00", game: "draw", route: "/play/my-answer?kind=draw", title: "딸이 낸 이게 뭐게", sub: "내 답은 보냈어요", done: ["아들"], pending: ["엄마", "아빠"] },
  { id: "w4", reveal: "내일 오후 2:10", game: "draw", route: "/play/my-answer?kind=draw&maker=%EC%97%84%EB%A7%88%EA%B0%80&answer=%EA%B3%A0%EC%96%91%EC%9D%B4&alt=&hints=1&tries=%5B%22%ED%86%A0%EB%81%BC%22%2C%22%EA%B3%B0%22%2C%22%EC%82%AC%EC%9E%90%22%2C%22%ED%98%B8%EB%9E%91%EC%9D%B4%22%2C%22%EC%97%AC%EC%9A%B0%22%2C%22%EB%8A%91%EB%8C%80%22%2C%22%EB%8B%A4%EB%9E%8C%EC%A5%90%22%2C%22%EC%9B%90%EC%88%AD%EC%9D%B4%22%2C%22%EA%B8%B0%EB%A6%B0%22%2C%22%EC%BD%94%EB%81%BC%EB%A6%AC%22%5D", title: "엄마가 낸 이게 뭐게", sub: "", done: ["아빠"], pending: ["아들", "딸"] },
  { id: "w5", reveal: "내일 오후 2:10", game: "photo", route: "/play/my-answer?kind=photo&hit=1", title: "아빠가 낸 찰칵! 탐정단", sub: "", done: ["엄마"], pending: ["아들", "딸"] },
  { id: "w3", reveal: "내일 오후 2:10", game: "photo", route: "/play/my-answer?kind=photo", title: "엄마가 낸 찰칵! 탐정단", sub: "내 답은 보냈어요", done: ["아빠"], pending: ["아들", "딸"] },
];
// 지난 결과(최근 3일)
export const PAST = [
  { id: "p1", game: "quiz", route: "/play/quiz-result", title: "엄마가 낸 가족 골든벨", sub: "어제 공개", action: "결과 보기" },
  { id: "p2", game: "photo", route: "/play/photo-result", title: "딸이 낸 찰칵! 탐정단", sub: "2일 전 공개", action: "결과 보기" },
  { id: "p3", game: "draw", route: "/play/draw-result", title: "아들이 낸 이게 뭐게", sub: "어제 공개", action: "결과 보기" },
];
// 내가 낸 문제(보낸 것)
export const SENT = [
  { id: "s1", game: "quiz", route: "/play/sent-detail?kind=quiz", title: "내가 낸 가족 골든벨", sub: "내일 오전 9:30 공개", done: ["엄마"], pending: ["아빠", "아들"] },
  { id: "s2", game: "draw", route: "/play/sent-detail?kind=draw", title: "내가 낸 이게 뭐게", sub: "내일 오후 2:10 공개", done: ["딸"], pending: ["엄마"] },
  { id: "s3", game: "photo", route: "/play/sent-detail?kind=photo", title: "내가 낸 찰칵! 탐정단", sub: "내일 오후 2:10 공개", done: ["엄마"], pending: ["아빠", "딸"] },
  { id: "s4", game: "bomb", route: "/play/sent-detail?kind=bomb", title: "내가 연 문장 폭탄 방", sub: "방이 열려 있어요 · 3명 입장" },
];
// 방장이 닫은 폭탄 방(시안). 닫으면 보낸 목록에서 사라진다
const closedRooms = new Set();
export const closeRoom = (id) => closedRooms.add(id);
export const reopenRooms = () => closedRooms.clear(); // 시안: 놀이터 홈에 오면 닫은 방을 다시 열어 둔다(테스트용)
export const openSent = () => SENT.filter((s) => !closedRooms.has(s.id));
export const SENT_PAST = [
  { id: "sp1", game: "photo", route: "/play/sent-result?kind=photo", title: "내가 낸 찰칵! 탐정단", sub: "어제 공개", action: "결과 보기" },
  { id: "sp2", game: "quiz", route: "/play/sent-result?kind=quiz", title: "내가 낸 가족 골든벨", sub: "2일 전 공개", action: "결과 보기" },
  { id: "sp3", game: "draw", route: "/play/sent-result?kind=draw", title: "내가 낸 이게 뭐게", sub: "어제 공개", action: "결과 보기" },
];

// 순위(이번 주 / 이번 달 / 전체). 점수는 활동 횟수에서 계산한다(참여 +10, 정답 +20, 문제 내기 +20, 폭탄 우승 +30).
// joins 참여 횟수, corrects 맞힌 개수, makes 낸 문제 수, wins 폭탄 우승 횟수
// 점수는 게임별로 쌓아 보여 준다. etc 는 참여·문제 내기 점수.
// n = 게임별 참여 횟수 [골든벨, 이게 뭐게, 찰칵, 폭탄]
const rank = (id, name, quiz, draw, photo, bomb, etc, n) => ({ id, name, quiz, draw, photo, bomb, etc, n, score: quiz + draw + photo + bomb + etc });
const byScore = (list) => [...list].sort((a, b) => b.score - a.score);
export const RANKING_BY = {
  week: byScore([rank("mom", "엄마", 95, 40, 60, 30, 95, [4, 3, 3, 1]), rank("me", "나", 80, 60, 40, 0, 100, [3, 3, 2, 0]), rank("dad", "아빠", 60, 20, 20, 0, 50, [2, 1, 1, 0]), rank("daughter", "딸", 0, 0, 0, 0, 0, [0, 0, 0, 0])]),
  month: byScore([rank("me", "나", 300, 160, 100, 60, 290, [12, 8, 5, 2]), rank("mom", "엄마", 260, 120, 200, 30, 270, [10, 6, 8, 1]), rank("dad", "아빠", 170, 80, 60, 30, 200, [7, 4, 3, 1]), rank("daughter", "딸", 50, 30, 50, 0, 80, [2, 1, 2, 0])]),
  all: byScore([rank("mom", "엄마", 800, 400, 700, 120, 920, [30, 18, 26, 4]), rank("me", "나", 760, 560, 400, 90, 900, [28, 22, 15, 3]), rank("dad", "아빠", 520, 280, 240, 0, 580, [20, 12, 10, 0]), rank("daughter", "딸", 160, 120, 150, 0, 300, [7, 5, 6, 0])]),
};
export const RANKING = RANKING_BY.week;
// 게임별 최고 기록: 그 기간에 가장 많이 한 사람. 골든벨·이게 뭐게·탐정단은 "맞힌 개수", 문장 폭탄은 "우승 횟수".
export const BEST = {
  week: { quiz: { value: "정답 9개", who: "엄마" }, draw: { value: "정답 5개", who: "나" }, photo: { value: "정답 7개", who: "엄마" }, bomb: { value: "우승 1회", who: "엄마" } },
  month: { quiz: { value: "정답 25개", who: "나" }, draw: { value: "정답 12개", who: "나" }, photo: { value: "정답 19개", who: "엄마" }, bomb: { value: "우승 2회", who: "나" } },
  all: { quiz: { value: "정답 80개", who: "엄마" }, draw: { value: "정답 30개", who: "나" }, photo: { value: "정답 41개", who: "엄마" }, bomb: { value: "우승 4회", who: "엄마" } },
};

// 폭탄 방 선수 시안(7명). order = 입장한 순서, joined false 면 아직 안 들어옴
const BOMB_PLAYERS = [
  { id: "me", name: "나", joined: true, order: 0, note: "" },
  { id: "mom", name: "엄마", joined: true, order: 1, note: "" },
  { id: "dad", name: "아빠", joined: true, order: 2, note: "" },
  { id: "daughter", name: "딸", joined: true, order: 3, note: "" },
  { id: "grandpa", name: "할아버지", joined: true, order: 4, note: "" },
  { id: "son", name: "아들", joined: false, order: 98, note: "아직 안 들어왔어요" },
  { id: "grandma", name: "할머니", joined: false, order: 99, note: "아직 안 들어왔어요" },
];
/** 게임 진행 순서: 방장이 먼저, 그다음은 들어온 순서(나도 특별히 앞이 아님). 시안이라 화면에 나오는 사람(ids)만 추린다. */
export function bombTurnOrder(hostId = "me", ids = ["me", "mom", "dad"]) {
  const rank = (p) => (p.id === hostId ? -1 : p.order);
  return BOMB_PLAYERS.filter((p) => p.joined && ids.includes(p.id))
    .sort((a, b) => rank(a) - rank(b))
    .map((p) => ({ id: p.id, name: p.name }));
}

/** 방장이 맨 위, 그다음 나, 그다음 입장한 순서, 아직 안 들어온 사람은 맨 아래. hostId 는 "me" 또는 "mom" */
export function bombRoom(hostId = "me") {
  const rank = (p) => (p.id === hostId ? -2 : p.id === "me" ? -1 : p.order);
  return [...BOMB_PLAYERS]
    .sort((a, b) => rank(a) - rank(b))
    .map((p) => ({ ...p, name: p.id === hostId ? `${p.name} (방장)` : p.name }));
}

// 오늘 내가 낸 문제 수(시안). 앱을 다시 열면 1건부터 다시 시작. 보낼 때마다 늘어나 한도(3건) 안내를 바꿔 볼 수 있다
let madeToday = 1;
export const makeLeft = () => Math.max(0, MAKE_LIMIT - madeToday);
export const recordMade = () => {
  madeToday += 1;
};

/** 가비 추천 시안(서버 주소가 없을 때). 서버 응답 `{ state, items }` 와 같은 모양이다. */
export const MOCK_RECS = {
  state: "ok",
  items: [
    { id: "r1", source: "schedule", kind: "choice", question: "작년 여름 가족 여행지는 어디였을까?", options: ["제주도", "강릉", "부산", "여수"], answer_index: 0 },
    { id: "r2", source: "schedule", kind: "ox", question: "엄마 생신은 12월이다", options: ["O", "X"], answer_index: 1 },
    { id: "r3", source: "chat", kind: "choice", question: "이번 주말에 가족이 가기로 한 곳은 어디일까?", options: ["해운대", "남산", "한강", "북촌"], answer_index: 2 },
  ],
};

/** 이게 뭐게 가비 추천 시안(서버 주소가 없을 때). 서버 응답 `{ state, items }` 와 같은 모양이고 그림은 선 좌표(0~255)다. */
export const MOCK_DRAW_RECS = {
  state: "ok",
  items: [
    { id: "d1", source: "common", word: "집", alt_answers: [], strokes: [[[30, 120], [128, 30], [226, 120]], [[50, 110], [50, 225], [206, 225], [206, 110]], [[110, 225], [110, 160], [146, 160], [146, 225]]] },
    { id: "d2", source: "schedule", word: "우산", alt_answers: [], strokes: [[[28, 120], [60, 50], [128, 25], [196, 50], [228, 120]], [[28, 120], [60, 105], [92, 120], [128, 105], [164, 120], [196, 105], [228, 120]], [[128, 25], [128, 210], [150, 235], [175, 215]]] },
  ],
};
