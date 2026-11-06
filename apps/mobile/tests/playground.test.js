// 가족 놀이터: 서버 응답 → 화면 모양 바꾸기(현황판·시각 문구·순위)와 서버 호출을 가짜 서버로 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { base64ToBytes } from "../src/features/playground/upload.js";
import { bestView, bitsOf, bombChat, bombPath, bombScreen, boardRow, recordNote, drawResultView, photoGuessView, photoResultView, zoomBoxStyle, familyView, quizAnswerBody, quizPlayView, quizQuestions, quizResultView, boardView, clockLabel, indexOfBits, pastLabel, playRoute, rankingView, revealLabel, withIga } from "../src/features/playground/adapt.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

// 서버 주소는 불러올 때 읽으므로 환경 변수를 정한 뒤에 가져온다
const { createDraw, createPhoto, createQuiz, getQuota, openHint, sendAnswers, sendTry } = await import("../src/features/playground/api.js");

const realFetch = globalThis.fetch;
beforeEach(() => {
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

// 2026-11-06 (금) 오전 10:00, 시험 기계의 시간대와 상관없이 같은 날로 읽히도록 지역 시간으로 만든다
const NOW = new Date(2026, 10, 6, 10, 0, 0);
const at = (dayOffset, hour, minute = 0) => new Date(2026, 10, 6 + dayOffset, hour, minute).toISOString();

test("이름 뒤에 이/가를 붙인다", () => {
  assert.equal(withIga("엄마"), "엄마가");
  assert.equal(withIga("아들"), "아들이");
  assert.equal(withIga("딸"), "딸이");
  assert.equal(withIga("Mina"), "Mina가");
});

test("시각 문구: 오전·오후와 12시간제", () => {
  assert.equal(clockLabel(new Date(2026, 10, 6, 14, 10)), "오후 2:10");
  assert.equal(clockLabel(new Date(2026, 10, 6, 9, 5)), "오전 9:05");
  assert.equal(clockLabel(new Date(2026, 10, 6, 0, 0)), "오전 12:00");
  assert.equal(clockLabel(new Date(2026, 10, 6, 12, 30)), "오후 12:30");
});

test("공개 시각은 오늘·내일·날짜로, 지난 결과는 어제·n일 전으로 쓴다", () => {
  assert.equal(revealLabel(at(0, 14, 10), NOW), "오늘 오후 2:10");
  assert.equal(revealLabel(at(1, 9, 30), NOW), "내일 오전 9:30");
  assert.equal(revealLabel(at(3, 11), NOW), "11/9 오전 11:00");
  assert.equal(pastLabel(at(0, 8), NOW), "오늘 공개");
  assert.equal(pastLabel(at(-1, 23), NOW), "어제 공개");
  assert.equal(pastLabel(at(-2, 1), NOW), "2일 전 공개");
});

test("비트 글자와 보기 위치를 오간다", () => {
  assert.equal(bitsOf(1, 4), "0100");
  assert.equal(bitsOf(0, 2), "10");
  assert.equal(indexOfBits("0010"), 2);
  assert.equal(indexOfBits("0000"), -1);
  assert.equal(indexOfBits(null), -1);
});

test("화면 주소에 문제 id 와 종류를 싣는다", () => {
  assert.equal(playRoute("todo", 1, "ab12"), "/play/quiz-play?id=ab12");
  assert.equal(playRoute("todo", 2, "ab12"), "/play/draw-guess?id=ab12");
  assert.equal(playRoute("todo", 3, "ab12"), "/play/photo-guess?id=ab12");
  assert.equal(playRoute("joined", 2, "x"), "/play/my-answer?id=x&kind=draw");
  assert.equal(playRoute("past", 3, "x"), "/play/photo-result?id=x");
  assert.equal(playRoute("sent", 1, "x"), "/play/sent-detail?id=x&kind=quiz");
  assert.equal(playRoute("sentPast", 2, "x"), "/play/sent-result?id=x&kind=draw");
  assert.equal(playRoute("todo", 4, "x"), "/play/bomb-lobby?id=x"); // 폭탄방은 상태에 따라 화면이 옮겨 준다
});

const row = (over = {}) => ({
  id: "g1",
  game: 1,
  maker: { id: "u1", name: "엄마" },
  close_at: at(1, 9, 30),
  closed: false,
  progress_done: 1,
  progress_total: 3,
  question_count: 3,
  ...over,
});

test("내 차례 줄: 누가 낸 어떤 게임인지, 공개 시각과 N/M, 할 일 글자", () => {
  assert.deepEqual(boardRow(row(), "todo", NOW), {
    id: "g1",
    game: "quiz",
    route: "/play/quiz-play?id=g1",
    title: "엄마가 낸 가족 골든벨",
    sub: "내일 오전 9:30 공개",
    progress: "1/3",
    action: "풀기",
  });
  const draw = boardRow(row({ game: 2, maker: { id: "u2", name: "아들" } }), "todo", NOW);
  assert.equal(draw.title, "아들이 낸 이게 뭐게");
  assert.equal(draw.action, "맞히기");
});

test("참여했어요 줄에는 할 일 글자가 없다", () => {
  const joined = boardRow(row({ game: 3, progress_done: 2 }), "joined", NOW);
  assert.equal(joined.action, undefined);
  assert.equal(joined.progress, "2/3");
  assert.equal(joined.route, `/play/my-answer?id=g1&kind=photo`);
});

test("지난 결과와 보낸 문제 줄", () => {
  const past = boardRow(row({ close_at: at(-1, 12), closed: true }), "past", NOW);
  assert.equal(past.sub, "어제 공개");
  assert.equal(past.action, "결과 보기");
  assert.equal(past.progress, undefined);
  const sent = boardRow(row({ game: 3 }), "sent", NOW);
  assert.equal(sent.title, "내가 낸 찰칵! 탐정단");
  assert.equal(sent.sub, "내일 오전 9:30 공개");
  const sentPast = boardRow(row({ close_at: at(-2, 12) }), "sentPast", NOW);
  assert.equal(sentPast.title, "내가 낸 가족 골든벨");
  assert.equal(sentPast.sub, "2일 전 공개");
});

test("현황판 전체: 비어 있어도 다섯 칸이 모두 배열이다", () => {
  assert.deepEqual(boardView(null, NOW), { todo: [], waiting: [], past: [], sent: [], sentPast: [] });
  const view = boardView({ todo: [row()], joined: [row({ id: "g2" })], past: [], sent: [row({ id: "g3" })], sent_past: [] }, NOW);
  assert.deepEqual([view.todo.length, view.waiting.length, view.past.length, view.sent.length, view.sentPast.length], [1, 1, 0, 1, 0]);
  assert.equal(view.waiting[0].id, "g2");
});

test("순위: 게임 번호별 점수와 참여 횟수를 화면 모양으로", () => {
  const [a, b] = rankingView({
    period: "week",
    rows: [
      { player: { id: "u1", name: "엄마" }, score: 95, by_game: { 1: 40, 2: 20 }, etc: 35, counts: { 1: 2, 3: 1 } },
      { player: { id: "u2", name: "딸" }, score: 0, by_game: { 1: 0, 2: 0, 3: 0, 4: 0 }, etc: 0, counts: {} },
    ],
  });
  assert.deepEqual(a, { id: "u1", name: "엄마", quiz: 40, draw: 20, photo: 0, bomb: 0, etc: 35, n: [2, 0, 1, 0], corrects: [0, 0, 0, 0], score: 95 });
  assert.equal(b.score, 0);
  assert.deepEqual(rankingView(null), []);
});

test("게임별 최고 기록: 가장 많이 맞힌 사람, 같으면 점수 높은 사람, 없으면 '아직 없어요'", () => {
  const rows = rankingView({
    rows: [
      { player: { id: "u1", name: "엄마" }, score: 90, by_game: {}, etc: 0, counts: {}, corrects: { 1: 5, 2: 2, 4: 1 } },
      { player: { id: "u2", name: "나" }, score: 80, by_game: {}, etc: 0, counts: {}, corrects: { 1: 5, 2: 3 } },
    ],
  });
  const best = bestView(rows);
  assert.deepEqual(best.quiz, { who: "엄마", value: "정답 5개" });
  assert.deepEqual(best.draw, { who: "나", value: "정답 3개" });
  assert.deepEqual(best.photo, { who: "", value: "아직 없어요" });
  assert.deepEqual(best.bomb, { who: "엄마", value: "우승 1회" });
  assert.deepEqual(bestView([]).quiz, { who: "", value: "아직 없어요" });
});

test("골든벨 만들기: 빈 보기는 빼고 정답 위치를 맞춰 옮긴다", () => {
  const out = quizQuestions([
    { kind: "ox", q: " 엄마 생신은 12월이다 ", options: ["O", "X"], answer: 1, withNote: true, note: " 11월이야 " },
    { kind: "choice", q: "처음 간 여행지는?", options: ["제주도", "", "부산"], answer: 2, withNote: false, note: "남은 글" },
  ]);
  assert.deepEqual(out[0], { qtype: 1, question: "엄마 생신은 12월이다", options: ["O", "X"], answer_index: 1, comment: "11월이야" });
  assert.deepEqual(out[1], { qtype: 2, question: "처음 간 여행지는?", options: ["제주도", "부산"], answer_index: 1, comment: undefined });
});

const quizItem = (over = {}) => ({
  id: "q1",
  game: 1,
  maker: { id: "u1", name: "엄마" },
  close_at: at(1, 9, 30),
  closed: true,
  my_state: "done",
  questions: [
    { quiz_no: 1, qtype: 1, question: "엄마 생신은 12월이다", options: ["O", "X"], answer: "01", comment: "11월이야" },
    { quiz_no: 2, qtype: 2, question: "아빠가 좋아하는 반찬은?", options: ["계란말이", "멸치볶음", "김치찌개"], answer: "100", comment: null },
  ],
  my_answers: [
    { quiz_no: 1, answer: "01", is_correct: true },
    { quiz_no: 2, answer: "010", is_correct: false },
  ],
  my_score: { total: 20, join: 10, correct: 10, hint: 0 },
  family_status: [
    { player: { id: "me", name: "수진" }, done: true },
    { player: { id: "u3", name: "아빠" }, done: true },
    { player: { id: "u4", name: "딸" }, done: false },
  ],
  family_answers: [
    { player: { id: "u3", name: "아빠" }, answered_at: new Date(2026, 10, 6, 9, 30).toISOString(), answers: [{ quiz_no: 1, answer: "10", is_correct: false }, { quiz_no: 2, answer: "100", is_correct: true }] },
    { player: { id: "me", name: "수진" }, answered_at: new Date(2026, 10, 6, 10, 0).toISOString(), answers: [] },
  ],
  ...over,
});

test("골든벨 푸는 화면: 문제 종류와 닫히는 시각", () => {
  const v = quizPlayView(quizItem());
  assert.equal(v.maker, "엄마");
  assert.deepEqual(v.questions.map((q) => [q.no, q.kind]), [[1, "OX"], [2, "선택"]]);
  assert.deepEqual(v.questions[1].options, ["계란말이", "멸치볶음", "김치찌개"]);
});

test("골든벨 답 보내기: 모두 골라야 하고 보기 위치를 비트 글자로 바꾼다", () => {
  const { questions } = quizPlayView(quizItem());
  assert.equal(quizAnswerBody(questions, { 0: 1 }), null);
  assert.deepEqual(quizAnswerBody(questions, { 0: 1, 1: 2 }), [
    { quiz_no: 1, answer: "01" },
    { quiz_no: 2, answer: "001" },
  ]);
});

test("골든벨 결과: 정답·내 답·맞힌 개수·가족의 답(나는 빼고, 시각은 시:분)", () => {
  const v = quizResultView(quizItem(), "me");
  assert.equal(v.right, 1);
  assert.equal(v.total, 2);
  assert.equal(v.hasScore, true);
  assert.deepEqual(v.score, { total: 20, join: 10, correct: 10, hint: 0 });
  assert.deepEqual(v.questions[0], {
    no: 1, kind: "OX", q: "엄마 생신은 12월이다", options: ["O", "X"], answer: "X", mine: "X", hit: true, note: "11월이야",
    rows: [{ name: "아빠", text: "O", ok: false, time: "09:30" }],
  });
  assert.equal(v.questions[1].mine, "멸치볶음");
  assert.equal(v.questions[1].answer, "계란말이");
  assert.equal(v.questions[1].hit, false);
  assert.equal(v.questions[1].note, "");
  assert.deepEqual(v.questions[1].rows, [{ name: "아빠", text: "계란말이", ok: true, time: "09:30" }]);
});

test("골든벨 결과: 공개 전이거나 낸 사람이 보면 정답이 없을 수 있다", () => {
  const hidden = quizItem({ closed: false, my_state: "todo", my_answers: null, my_score: null, family_answers: null, questions: [{ quiz_no: 1, qtype: 1, question: "문제", options: ["O", "X"], answer: null, comment: null }] });
  const v = quizResultView(hidden, "me");
  assert.equal(v.questions[0].answer, null);
  assert.equal(v.questions[0].mine, null);
  assert.equal(v.hasScore, false);
  assert.equal(v.right, 0);
  assert.deepEqual(v.score, { total: 0, join: 0, correct: 0, hint: 0 });
});

test("가족 현황: 끝낸 사람 앞에 '나', 아직인 사람은 대기", () => {
  assert.deepEqual(familyView(quizItem(), "me"), { done: ["나", "아빠"], pending: ["딸"] });
  assert.deepEqual(familyView(quizItem({ my_state: "todo", family_status: [{ player: { id: "me", name: "수진" }, done: false }, { player: { id: "u3", name: "아빠" }, done: false }] }), "me"), { done: [], pending: ["아빠"] });
});

const drawItem = (over = {}) => ({
  id: "d1",
  game: 2,
  maker: { id: "u2", name: "아들" },
  close_at: at(1, 14, 10),
  image_url: "/play/items/d1/image",
  draw: { tries_used: 2, max_tries: 10, solved: true, finished: true, last_try_correct: null, hints_used: 1, max_hints: 2, hint1: "3글자", hint2: "동물이야", answer: "강아지", alt_answers: ["멍멍이", "개"] },
  my_answers: [
    { quiz_no: 0, answer: "고양이", is_correct: false, hints_used: 1 },
    { quiz_no: 0, answer: "멍멍이", is_correct: true, hints_used: 1 },
  ],
  my_score: { total: 25, join: 10, correct: 20, hint: -5 },
  family_answers: [
    { player: { id: "u3", name: "엄마" }, answered_at: new Date(2026, 10, 6, 9, 20).toISOString(), answers: [{ quiz_no: 0, answer: "강아지", is_correct: true, hints_used: 0 }] },
    { player: { id: "u4", name: "아빠" }, answered_at: new Date(2026, 10, 6, 13, 0).toISOString(), answers: [{ quiz_no: 0, answer: "고양이", is_correct: false, hints_used: 1 }, { quiz_no: 0, answer: "토끼", is_correct: false, hints_used: 1 }] },
    { player: { id: "me", name: "수진" }, answered_at: new Date(2026, 10, 6, 10, 0).toISOString(), answers: [] },
  ],
  ...over,
});

test("이게 뭐게 결과: 정답·이것도 정답, 내가 쓴 답과 연 힌트, 점수, 가족의 답", () => {
  const v = drawResultView(drawItem(), "me");
  assert.equal(v.heroText, "강아지 (멍멍이, 개)");
  assert.equal(v.mineText, "멍멍이"); // 맞힌 답
  assert.equal(v.hint1, "3글자");
  assert.equal(v.hint2, null); // 힌트 2는 열지 않았다
  assert.deepEqual(v.score, { total: 25, join: 10, correct: 20, hint: -5 });
  assert.deepEqual(v.rows, [
    { name: "엄마", text: "강아지", ok: true, hints: 0, time: "09:20" },
    { name: "아빠", text: "고양이 · 토끼", ok: false, hints: 1, time: "13:00" },
  ]);
});

test("이게 뭐게 결과: 못 맞혔으면 틀린 답을 모두 보이고 이것도 정답이 없으면 정답만", () => {
  const v = drawResultView(
    drawItem({
      draw: { ...drawItem().draw, solved: false, alt_answers: null, hints_used: 2 },
      my_answers: [{ quiz_no: 0, answer: "곰", is_correct: false }, { quiz_no: 0, answer: "사자", is_correct: false }],
      my_score: { total: 0, join: 10, correct: 0, hint: -10 },
    }),
    "me",
  );
  assert.equal(v.heroText, "강아지");
  assert.equal(v.mineText, "곰 · 사자");
  assert.equal(v.hint2, "동물이야");
  assert.equal(v.score.total, 0);
});

const photoItem = (over = {}) => ({
  id: "p1",
  game: 3,
  maker: { id: "u2", name: "딸" },
  close_at: at(1, 14, 10),
  image_url: "/play/items/p1/image?v=1f",
  photo: { question: "어디서 찍었을까요?", options: ["제주도 여행", "할머니 댁", "강릉 바다", "우리 집"], zoom: 4, source: 1, shrinks_used: 1, max_shrinks: 2, answer: "1000", comment: "비가 왔어요", box_x: 0.8, box_y: 0.2 },
  my_answers: [{ quiz_no: 0, answer: "1000", is_correct: true, hints_used: 1 }],
  my_score: { total: 25, join: 10, correct: 20, hint: -5 },
  family_answers: [
    { player: { id: "u3", name: "아빠" }, answered_at: new Date(2026, 10, 6, 13, 50).toISOString(), answers: [{ quiz_no: 0, answer: "0010", is_correct: false, hints_used: 0 }] },
    { player: { id: "me", name: "수진" }, answered_at: new Date(2026, 10, 6, 10, 0).toISOString(), answers: [{ quiz_no: 0, answer: "1000", is_correct: true, hints_used: 1 }] },
  ],
  ...over,
});

test("탐정단 푸는 화면: 출처 문구와 줄여 보기 횟수", () => {
  const v = photoGuessView(photoItem({ photo: { ...photoItem().photo, source: 2, answer: null, box_x: null, box_y: null } }));
  assert.equal(v.sourceText, "딸이 폰에서 고른 사진이에요");
  assert.equal(v.shrinksUsed, 1);
  assert.equal(v.maxShrinks, 2);
  assert.equal(v.zoom, 4);
  assert.deepEqual(photoGuessView(photoItem()).options, ["제주도 여행", "할머니 댁", "강릉 바다", "우리 집"]);
});

test("탐정단 결과: 정답·내 답, 문제로 낸 부분(네모), 가족의 답은 나를 빼고", () => {
  const v = photoResultView(photoItem(), "me");
  assert.equal(v.answer, "제주도 여행");
  assert.equal(v.mine, "제주도 여행");
  assert.equal(v.hit, true);
  assert.equal(v.comment, "비가 왔어요");
  assert.deepEqual(v.box, { x: 0.8, y: 0.2, zoom: 4 });
  assert.deepEqual(v.rows, [{ name: "아빠", text: "강릉 바다", ok: false, time: "13:50" }]);
  assert.equal(photoResultView(photoItem({ photo: { ...photoItem().photo, box_x: null, box_y: null } }), "me").box, null);
});

test("확대 창 네모: 가운데 위치를 퍼센트로, 사진 밖으로 나가지 않게", () => {
  assert.deepEqual(zoomBoxStyle({ x: 0.5, y: 0.5, zoom: 4 }), { left: "37.5%", top: "37.5%", width: "25%", height: "25%" });
  assert.deepEqual(zoomBoxStyle({ x: 1, y: 0, zoom: 4 }), { left: "75%", top: "0%", width: "25%", height: "25%" });
  assert.deepEqual(zoomBoxStyle({ x: 0.5, y: 0.5, zoom: 1 }), { left: "0%", top: "0%", width: "100%", height: "100%" });
});

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** 요청을 모아 두고 정해진 응답을 돌려주는 가짜 서버 */
function fakeServer(reply = {}) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method ?? "GET", body: init.body, headers: init.headers });
    return json(200, reply);
  };
  return calls;
}

test("서버 호출: 주소·방법·본문이 계약대로 나간다", async () => {
  const calls = fakeServer({ ok: true });
  await createQuiz({ questions: [{ qtype: 1, question: "문제", options: ["O", "X"], answer_index: 0 }], playerIds: ["u1"] });
  await sendAnswers("q 1", [{ quiz_no: 1, answer: "10" }]);
  await openHint("d1");
  await sendTry("d1", "고양이");
  await getQuota();
  assert.deepEqual(
    calls.map((c) => [c.method, c.url.replace("http://api.test", "")]),
    [
      ["POST", "/play/quiz"],
      ["POST", "/play/items/q%201/answers"], // 문제 id 는 주소에 안전하게 담긴다
      ["POST", "/play/items/d1/hints"],
      ["POST", "/play/items/d1/tries"],
      ["GET", "/play/quota"],
    ],
  );
  assert.deepEqual(JSON.parse(calls[0].body), { questions: [{ qtype: 1, question: "문제", options: ["O", "X"], answer_index: 0 }], player_ids: ["u1"] });
  assert.deepEqual(JSON.parse(calls[1].body), { answers: [{ quiz_no: 1, answer: "10" }] });
  assert.deepEqual(JSON.parse(calls[3].body), { answer: "고양이" });
  assert.equal(calls[0].headers["X-Gyeot-Token"], "legacy-dev-token");
});

test("이게 뭐게 올리기: 그림 한 장과 정답·이것도 정답·힌트·받는 사람을 폼으로", async () => {
  const calls = fakeServer({ id: "d1" });
  const png = new Blob([new Uint8Array([137, 80, 78, 71])], { type: "image/png" });
  await createDraw({ image: { uri: "draw.png", file: png }, answer: "고양이", alts: ["냥이", "야옹이"], hint2: "야옹 해요", playerIds: ["u1", "u2"] });
  const form = calls[0].body;
  assert.equal(calls[0].url, "http://api.test/play/draws");
  assert.ok(form instanceof FormData);
  assert.equal(form.get("file").type, "image/png");
  assert.equal(form.get("answer"), "고양이");
  assert.deepEqual(form.getAll("alt_answers"), ["냥이", "야옹이"]);
  assert.equal(form.get("hint2"), "야옹 해요");
  assert.deepEqual(form.getAll("player_ids"), ["u1", "u2"]);
  assert.equal(calls[0].headers["Content-Type"], undefined); // multipart 경계는 fetch 가 붙인다
});

test("이게 뭐게 올리기: 힌트·받는 사람이 비면 폼에 넣지 않는다", async () => {
  const calls = fakeServer({});
  await createDraw({ image: { uri: "d.png", file: new Blob(["x"]) }, answer: "고양이" });
  const form = calls[0].body;
  assert.equal(form.has("hint2"), false);
  assert.deepEqual(form.getAll("alt_answers"), []);
  assert.deepEqual(form.getAll("player_ids"), []);
});

test("탐정단 올리기: 사진·출처·확대·위치·질문·보기·정답 위치·한마디", async () => {
  const calls = fakeServer({ id: "p1" });
  const jpeg = new Blob(["x"], { type: "image/jpeg" });
  await createPhoto({ image: { uri: "p.jpg", file: jpeg, fileName: "p.jpg", mimeType: "image/jpeg" }, source: 2, zoom: 8, boxX: 0.25, boxY: 0.75, question: "어디서?", options: ["가", "나", "다"], answerIndex: 1, comment: "비 왔어요", playerIds: [] });
  const form = calls[0].body;
  assert.equal(calls[0].url, "http://api.test/play/photos");
  assert.equal(form.get("source"), "2");
  assert.equal(form.get("zoom"), "8");
  assert.equal(form.get("box_x"), "0.25");
  assert.equal(form.get("box_y"), "0.75");
  assert.equal(form.get("question"), "어디서?");
  assert.deepEqual(form.getAll("options"), ["가", "나", "다"]);
  assert.equal(form.get("answer_index"), "1");
  assert.equal(form.get("comment"), "비 왔어요");
});

test("그림판 PNG(base64)를 바이트로 바꾼다", () => {
  assert.deepEqual([...base64ToBytes("iVBORw==")], [137, 80, 78, 71]);
  assert.deepEqual([...base64ToBytes("data:image/png;base64,iVBORw==")], [137, 80, 78, 71]); // data 주소 머리말은 뗀다
});

test("폭탄방 현황판 줄: 받는 쪽은 입장 카드, 방장은 입장 인원", () => {
  const room = { id: "b1", game: 4, maker: { id: "u1", name: "엄마" }, close_at: at(0, 12), closed: false, progress_done: 3, progress_total: 0, question_count: 0 };
  assert.deepEqual(boardRow(room, "todo", NOW), { id: "b1", game: "bomb", route: "/play/bomb-lobby?id=b1", title: "엄마가 폭탄 방을 열었어요", sub: "", action: "입장", strong: true });
  assert.deepEqual(boardRow(room, "sent", NOW), { id: "b1", game: "bomb", route: "/play/bomb-lobby?id=b1", title: "내가 연 문장 폭탄 방", sub: "방이 열려 있어요 · 3명 입장", strong: true });
});

test("폭탄 화면 고르기: 상태와 내 처지에 따라", () => {
  assert.equal(bombScreen({ phase: "lobby", my_status: "player" }), "lobby");
  assert.equal(bombScreen({ phase: "lobby", my_status: "none" }), "lobby");
  assert.equal(bombScreen({ phase: "playing", my_status: "player" }), "play");
  assert.equal(bombScreen({ phase: "playing", my_status: "out" }), "spectate");
  assert.equal(bombScreen({ phase: "playing", my_status: "spectator" }), "spectate");
  assert.equal(bombScreen({ phase: "playing", my_status: "none" }), "lobby"); // 방에 안 들어왔으면 들어올 수 있는 로비
  assert.equal(bombScreen({ phase: "finished", my_status: "player" }), "result");
  assert.equal(bombScreen({ phase: "closed", my_status: "player", result: { round_no: 1 } }), "result");
  assert.equal(bombScreen({ phase: "closed", my_status: "player", result: null }), "lobby");
  assert.equal(bombPath("spectate", "r 1"), "/play/bomb-spectate?id=r%201");
});

test("가족 기록 안내", () => {
  assert.equal(recordNote({ is_record: true, prev_record: 11 }), "우리 가족 신기록이에요\n(이전 11개)");
  assert.equal(recordNote({ is_record: true, prev_record: null }), "우리 가족 첫 기록이에요");
  assert.equal(recordNote({ is_record: false, prev_record: 14 }), "우리 가족 기록은 14개예요");
  assert.equal(recordNote({ is_record: false, prev_record: null }), "");
});

test("폭탄 채팅: 말풍선, 문장 끝냄·시간 초과 안내, 응원", () => {
  const p = (id, name) => ({ id, name });
  const chat = bombChat(
    [
      { id: "t1", kind: "say", player: p("u1", "엄마"), text: "누가", ended: false, lost_life: false, out: false },
      { id: "t2", kind: "say", player: p("me", "수진"), text: "먹었다", ended: true, lost_life: true, out: false },
      { id: "t3", kind: "timeout", player: p("u1", "엄마"), text: "", ended: false, lost_life: true, out: true },
      { id: "c1", kind: "cheer", player: p("u3", "아들"), text: "힘내요", ended: false, lost_life: false, out: false },
      { id: "t4", kind: "say", player: p("u1", "엄마"), text: "밥을", ended: true, reason: "repeat", lost_life: true, out: false },
    ],
    "me",
  );
  assert.deepEqual(chat.map((c) => [c.kind, c.text, c.mine ?? false]), [
    ["say", "누가", false],
    ["say", "먹었다", true],
    ["system", "수진이 문장을 끝냈어요 · 생명 -1", false],
    ["system", "엄마 시간 초과 · 생명 -1 · 탈락", false],
    ["cheer", "힘내요!", false],
    ["say", "밥을", false],
    ["system", "엄마가 같은 말을 또 했어요 · 생명 -1", false],
  ]);
  assert.deepEqual(bombChat(null, "me"), []);
});
