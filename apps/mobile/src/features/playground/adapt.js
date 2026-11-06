/**
 * 가족 놀이터 서버 응답(`/play/*`)을 화면이 쓰는 모양으로 바꾸는 순수 함수 모음(React·네트워크와 무관). 시험: tests/playground.test.js
 * 화면은 서버 주소가 없으면 mock.js 의 시안 데이터를 그대로 쓰고, 있으면 여기서 바꾼 값을 쓴다.
 */
import { GAMES } from "./games";

/** 서버 game 번호 → 화면의 게임 키 */
export const GAME_KEY = { 1: "quiz", 2: "draw", 3: "photo", 4: "bomb" };
export const gameKey = (game) => GAME_KEY[game] ?? "quiz";

/** 받침이 있는 한글 이름인지(이름 뒤 "이/가" 고르기) */
function hasFinalConsonant(text) {
  const code = String(text ?? "").trim().codePointAt(String(text ?? "").trim().length - 1);
  return code >= 0xac00 && code <= 0xd7a3 && (code - 0xac00) % 28 !== 0;
}

/** "엄마가", "아들이" 처럼 이름 뒤에 이/가를 붙인다. */
export const withIga = (name) => `${name}${hasFinalConsonant(name) ? "이" : "가"}`;

const pad2 = (n) => String(n).padStart(2, "0");

/** "오후 2:10" */
export function clockLabel(date) {
  const h = date.getHours();
  return `${h < 12 ? "오전" : "오후"} ${h % 12 || 12}:${pad2(date.getMinutes())}`;
}

const dayStart = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate());

/** 오늘과 며칠 차이인지(자정 기준, 미래는 +) */
export function dayDiff(date, now = new Date()) {
  return Math.round((dayStart(date) - dayStart(now)) / 86400000);
}

/** 앞으로 열리는 시각: "오늘 오후 2:10", "내일 오전 9:30", 그 밖에는 "11/9 오후 2:10" */
export function revealLabel(iso, now = new Date()) {
  const date = new Date(iso);
  const diff = dayDiff(date, now);
  const day = diff === 0 ? "오늘" : diff === 1 ? "내일" : `${date.getMonth() + 1}/${date.getDate()}`;
  return `${day} ${clockLabel(date)}`;
}

/** 지금 내면 닫히는(정답이 공개되는) 시각: 지금부터 24시간 뒤 */
export const closeLabel = (now = new Date()) => revealLabel(new Date(now.getTime() + 24 * 3600 * 1000).toISOString(), now);

/** 이미 닫힌 때: "오늘 공개", "어제 공개", "2일 전 공개" */
export function pastLabel(iso, now = new Date()) {
  const ago = -dayDiff(new Date(iso), now);
  return ago <= 0 ? "오늘 공개" : ago === 1 ? "어제 공개" : `${ago}일 전 공개`;
}

/** 비트 글자("0100")에서 고른 보기의 위치(없으면 -1) */
export const indexOfBits = (bits) => String(bits ?? "").indexOf("1");

/** 보기 위치 → 비트 글자. bitsOf(1, 4) = "0100" */
export const bitsOf = (index, length) => Array.from({ length }, (_, i) => (i === index ? "1" : "0")).join("");

// 게임별 화면 주소. 서버 문제 id 를 쿼리로 넘긴다.
const ROUTE = {
  todo: { quiz: "/play/quiz-play", draw: "/play/draw-guess", photo: "/play/photo-guess" },
  joined: { quiz: "/play/my-answer", draw: "/play/my-answer", photo: "/play/my-answer" },
  past: { quiz: "/play/quiz-result", draw: "/play/draw-result", photo: "/play/photo-result" },
  sent: { quiz: "/play/sent-detail", draw: "/play/sent-detail", photo: "/play/sent-detail" },
  sentPast: { quiz: "/play/sent-result", draw: "/play/sent-result", photo: "/play/sent-result" },
};
const ACTION = { quiz: "풀기", draw: "맞히기", photo: "맞히기" };

/** 시안과 같은 주소 모양: 상세 화면은 id 로 서버에서 다시 불러오고, 게임 종류는 kind 로 알려 준다. */
export function playRoute(section, game, id) {
  const key = gameKey(game);
  const base = ROUTE[section]?.[key];
  if (!base) return "/play";
  const kind = section === "joined" || section === "sent" || section === "sentPast" ? `&kind=${key}` : "";
  return `${base}?id=${encodeURIComponent(id)}${kind}`;
}

const progressOf = (row) => `${row.progress_done}/${row.progress_total}`;

/**
 * 현황판 한 줄(PlayBoardItemOut) → TurnRow 가 그리는 모양.
 * @param {"todo" | "joined" | "past" | "sent" | "sentPast"} section
 */
export function boardRow(row, section, now = new Date()) {
  const key = gameKey(row.game);
  const game = GAMES[key];
  const mine = section === "sent" || section === "sentPast";
  const title = `${mine ? "내가" : withIga(row.maker?.name ?? "가족")} 낸 ${game.name}`;
  const item = { id: row.id, game: key, route: playRoute(section, row.game, row.id), title };
  if (section === "past" || section === "sentPast") return { ...item, sub: pastLabel(row.close_at, now), action: "결과 보기" };
  const sub = `${revealLabel(row.close_at, now)} 공개`;
  const withProgress = { ...item, sub, progress: progressOf(row) };
  return section === "todo" ? { ...withProgress, action: ACTION[key] } : withProgress;
}

/** 서버 현황판 전체 → { todo, waiting, past, sent, sentPast } (mock.js 의 TODO·WAITING·PAST·SENT·SENT_PAST 와 같은 이름) */
export function boardView(board, now = new Date()) {
  const rows = (list, section) => (list ?? []).map((row) => boardRow(row, section, now));
  return {
    todo: rows(board?.todo, "todo"),
    waiting: rows(board?.joined, "joined"),
    past: rows(board?.past, "past"),
    sent: rows(board?.sent, "sent"),
    sentPast: rows(board?.sent_past, "sentPast"),
  };
}

/**
 * 서버 순위 → 순위 화면의 줄. by_game 의 키는 게임 번호(1~4), counts 는 게임별 참여 횟수.
 * @param {{ rows: { player: { id: string, name: string }, score: number, by_game: Record<string, number>, etc: number, counts: Record<string, number>, corrects?: Record<string, number> }[] } | null | undefined} ranking
 */
export function rankingView(ranking) {
  return (ranking?.rows ?? []).map((r) => ({
    id: r.player.id,
    name: r.player.name,
    quiz: r.by_game?.[1] ?? 0,
    draw: r.by_game?.[2] ?? 0,
    photo: r.by_game?.[3] ?? 0,
    bomb: r.by_game?.[4] ?? 0,
    etc: r.etc ?? 0,
    n: [1, 2, 3, 4].map((g) => r.counts?.[g] ?? 0),
    corrects: [1, 2, 3, 4].map((g) => r.corrects?.[g] ?? 0),
    score: r.score,
  }));
}

/**
 * 게임별 최고 기록: 그 기간에 가장 많이 맞힌 사람(폭탄은 우승 횟수). 아무도 없으면 "아직 없어요".
 * 같은 기록이면 점수가 높은 사람(rows 의 앞쪽)을 보인다.
 * @param {ReturnType<typeof rankingView>} rows 점수 높은 순
 * @param {(row: { id: string, name: string }) => string} [nameOf]
 */
export function bestView(rows, nameOf = (r) => r.name) {
  const out = {};
  ["quiz", "draw", "photo", "bomb"].forEach((key, i) => {
    let top = null;
    for (const r of rows ?? []) if ((r.corrects?.[i] ?? 0) > (top?.corrects[i] ?? 0)) top = r;
    out[key] = top ? { who: nameOf(top), value: key === "bomb" ? `우승 ${top.corrects[i]}회` : `정답 ${top.corrects[i]}개` } : { who: "", value: "아직 없어요" };
  });
  return out;
}

/**
 * 골든벨 만들기 화면의 문제 목록 → 서버 요청 본문. 빈 보기는 빼고 정답 위치를 그에 맞춰 옮긴다.
 * @param {{ kind: "ox" | "choice", q: string, options: string[], answer: number | null, withNote?: boolean, note?: string }[]} qs
 */
export function quizQuestions(qs) {
  return qs.map((q) => {
    if (q.kind === "ox") return { qtype: 1, question: q.q.trim(), options: ["O", "X"], answer_index: q.answer, comment: q.withNote ? q.note.trim() || undefined : undefined };
    const kept = q.options.map((text, i) => ({ text: text.trim(), i })).filter((o) => o.text);
    return {
      qtype: 2,
      question: q.q.trim(),
      options: kept.map((o) => o.text),
      answer_index: kept.findIndex((o) => o.i === q.answer),
      comment: q.withNote ? q.note.trim() || undefined : undefined,
    };
  });
}

const hhmm = (iso) => {
  const d = new Date(iso);
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
};

/** 보기 글자 중 비트 글자가 가리키는 것(없으면 null) */
const optionAt = (options, bits) => options[indexOfBits(bits)] ?? null;

/** 골든벨 푸는 화면: 문제 목록과 낸 사람, 닫히는 시각 */
export function quizPlayView(item) {
  return {
    maker: item.maker?.name ?? "가족",
    makerId: item.maker?.id,
    closeAt: revealLabel(item.close_at),
    questions: (item.questions ?? []).map((q) => ({ no: q.quiz_no, kind: q.qtype === 1 ? "OX" : "선택", q: q.question, options: q.options })),
  };
}

/** 고른 보기 위치(문항 번호 0부터 → 위치)를 서버에 보낼 답으로. 하나라도 안 골랐으면 null. */
export function quizAnswerBody(questions, picks) {
  if (questions.some((_, i) => picks[i] == null)) return null;
  return questions.map((q, i) => ({ quiz_no: q.no, answer: bitsOf(picks[i], q.options.length) }));
}

/** 가족 현황: 끝낸 사람(나는 맨 앞 "나")과 아직인 사람 */
export function familyView(item, myId) {
  const status = item.family_status ?? [];
  const mine = status.find((s) => s.player.id === myId);
  const others = status.filter((s) => s.player.id !== myId);
  return {
    done: [...(item.my_state === "done" || mine?.done ? ["나"] : []), ...others.filter((s) => s.done).map((s) => s.player.name)],
    pending: others.filter((s) => !s.done).map((s) => s.player.name),
  };
}

/**
 * 골든벨 내가 낸 답 / 정답 공개: 문제마다 정답·내 답·한마디·가족의 답(푼 순서), 맞힌 개수와 받은 점수.
 * 가족의 답은 닫힌 뒤에만 서버가 준다. 문제를 낸 사람이 보면 mine 은 null.
 * @param {object} item 서버 PlayItemOut(골든벨)
 * @param {string | null} myId
 */
export function quizResultView(item, myId) {
  const familyByNo = {};
  for (const fa of item.family_answers ?? []) {
    if (fa.player.id === myId) continue;
    for (const a of fa.answers) (familyByNo[a.quiz_no] ??= []).push({ name: fa.player.name, bits: a.answer, ok: a.is_correct, at: fa.answered_at });
  }
  const mine = Object.fromEntries((item.my_answers ?? []).map((a) => [a.quiz_no, a]));
  const questions = (item.questions ?? []).map((q) => {
    const answer = q.answer ? optionAt(q.options, q.answer) : null;
    const my = mine[q.quiz_no];
    return {
      no: q.quiz_no,
      kind: q.qtype === 1 ? "OX" : "선택",
      q: q.question,
      options: q.options,
      answer,
      mine: my ? optionAt(q.options, my.answer) : null,
      hit: my ? my.is_correct : null,
      note: q.comment ?? "",
      rows: (familyByNo[q.quiz_no] ?? []).map((r) => ({ name: r.name, text: optionAt(q.options, r.bits) ?? "", ok: r.ok, time: hhmm(r.at) })),
    };
  });
  const right = questions.filter((q) => q.hit).length;
  const score = item.my_score ?? { total: 0, join: 0, correct: 0, hint: 0 };
  return { maker: item.maker?.name ?? "가족", makerId: item.maker?.id, total: questions.length, right, score, hasScore: Boolean(item.my_score), questions };
}

const TRY_SEP = " · ";

/** 이 사람이 쓴 답들(시도 순서) → 화면에 쓸 한 줄: 맞혔으면 맞힌 답, 못 맞혔으면 틀린 답을 모두 */
function triesText(tries) {
  const hit = tries.find((t) => t.is_correct);
  return hit ? hit.answer : tries.map((t) => t.answer).join(TRY_SEP);
}

/**
 * 이게 뭐게 정답 공개 / 내가 낸 답: 정답(이것도 정답), 그림 주소, 내가 쓴 답과 연 힌트, 받은 점수, 가족이 낸 답(푼 순서).
 * @param {object} item 서버 PlayItemOut(이게 뭐게)
 * @param {string | null} myId
 */
export function drawResultView(item, myId) {
  const d = item.draw;
  const mine = (item.my_answers ?? []).filter((a) => a.quiz_no === 0);
  const alts = d.alt_answers ?? [];
  return {
    maker: item.maker?.name ?? "가족",
    makerId: item.maker?.id,
    imageUrl: item.image_url,
    answer: d.answer,
    alts,
    heroText: alts.length ? `${d.answer} (${alts.join(", ")})` : (d.answer ?? ""),
    solved: d.solved,
    mineText: mine.length ? triesText(mine) : "",
    hintsUsed: d.hints_used,
    hint1: d.hints_used >= 1 ? d.hint1 : null,
    hint2: d.hints_used >= 2 ? d.hint2 : null,
    hasScore: Boolean(item.my_score),
    score: item.my_score ?? { total: 0, join: 0, correct: 0, hint: 0 },
    rows: (item.family_answers ?? [])
      .filter((fa) => fa.player.id !== myId && fa.answers.length)
      .map((fa) => ({
        name: fa.player.name,
        text: triesText(fa.answers),
        ok: fa.answers.some((a) => a.is_correct),
        hints: Math.max(0, ...fa.answers.map((a) => a.hints_used ?? 0)),
        time: hhmm(fa.answered_at),
      })),
  };
}

/** 사진 문제를 낸 출처 문구: "딸이 앨범에서 고른 사진이에요" */
export const photoSourceText = (makerName, source) => `${withIga(makerName)} ${source === 1 ? "앨범에서 고른" : "폰에서 고른"} 사진이에요`;

/** 탐정단 푸는 화면: 서버가 확대해 잘라 준 사진(image_url), 질문, 보기, 줄여 보기 횟수 */
export function photoGuessView(item) {
  const p = item.photo;
  return {
    maker: item.maker?.name ?? "가족",
    makerId: item.maker?.id,
    sourceText: photoSourceText(item.maker?.name ?? "가족", p.source),
    imageUrl: item.image_url,
    question: p.question,
    options: p.options,
    zoom: p.zoom,
    shrinksUsed: p.shrinks_used,
    maxShrinks: p.max_shrinks,
    closeAt: revealLabel(item.close_at),
  };
}

/**
 * 탐정단 정답 공개 / 내가 낸 답: 정답, 원본 사진과 문제로 낸 부분, 한마디, 받은 점수, 가족이 고른 답(푼 순서).
 * 원본(전체)을 볼 수 있을 때만 box 가 있다.
 */
export function photoResultView(item, myId) {
  const p = item.photo;
  const mineRow = (item.my_answers ?? []).find((a) => a.quiz_no === 0);
  const answerIndex = indexOfBits(p.answer);
  const mineIndex = mineRow ? indexOfBits(mineRow.answer) : -1;
  return {
    maker: item.maker?.name ?? "가족",
    makerId: item.maker?.id,
    imageUrl: item.image_url,
    question: p.question,
    options: p.options,
    answerIndex,
    answer: p.options[answerIndex] ?? null,
    mineIndex,
    mine: p.options[mineIndex] ?? null,
    hit: mineRow ? mineRow.is_correct : null,
    comment: p.comment ?? "",
    zoom: p.zoom,
    box: p.box_x == null || p.box_y == null ? null : { x: p.box_x, y: p.box_y, zoom: p.zoom },
    shrinks: p.shrinks_used,
    source: p.source,
    hasScore: Boolean(item.my_score),
    score: item.my_score ?? { total: 0, join: 0, correct: 0, hint: 0 },
    rows: (item.family_answers ?? [])
      .filter((fa) => fa.player.id !== myId && fa.answers.length)
      .map((fa) => ({
        name: fa.player.name,
        text: p.options[indexOfBits(fa.answers[0].answer)] ?? "",
        ok: fa.answers[0].is_correct,
        time: hhmm(fa.answered_at),
      })),
  };
}

/** 확대 창 위치(가운데 x, y 와 배율)를 사진 위 네모(퍼센트)로. 사진 밖으로 나가지 않게 끼워 맞춘다. */
export function zoomBoxStyle({ x, y, zoom }) {
  const size = 1 / Math.max(1, zoom);
  const left = Math.min(Math.max(x - size / 2, 0), 1 - size);
  const top = Math.min(Math.max(y - size / 2, 0), 1 - size);
  const pct = (v) => `${Math.round(v * 10000) / 100}%`;
  return { left: pct(left), top: pct(top), width: pct(size), height: pct(size) };
}
