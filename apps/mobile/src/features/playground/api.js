import { apiFetch } from "@/shared/api/client";

import { fileForUpload } from "./upload";

/**
 * 가족 놀이터(골든벨·이게 뭐게·찰칵! 탐정단) 서버 호출. 계약은 서버 `/play/*` (docs/features/play.md, docs/contracts/openapi.json).
 * 문장 폭탄방은 서버 API가 아직 없어 여기에 없다. 서버 주소가 없으면 화면이 시안(mock.js)으로 동작한다.
 */

const itemPath = (id) => `/play/items/${encodeURIComponent(id)}`;

/** 현황판: { todo, joined, past, sent, sent_past }. 각 줄은 { id, game, maker, close_at, closed, progress_done, progress_total, question_count }. */
export const getBoard = () => apiFetch("/play/board");

/** 문제 한 건(PlayItemOut). 정답은 낸 사람·끝낸 사람·닫힌 뒤에만 채워져 온다. */
export const getItem = (id) => apiFetch(itemPath(id));

/** 오늘 내가 낸 문제 수와 문제 내기 점수(+20)를 받을 수 있는 남은 횟수: { limit, used, left } */
export const getQuota = () => apiFetch("/play/quota");

/** 순위. period: "week" | "month" | "all" */
export const getRanking = (period) => apiFetch(`/play/ranking?period=${period}`);

/**
 * 골든벨을 낸다.
 * @param {{ questions: { qtype: 1 | 2, question: string, options: string[], answer_index: number, comment?: string }[], playerIds?: string[] }} input
 */
export const createQuiz = ({ questions, playerIds = [] }) => apiFetch("/play/quiz", { method: "POST", body: { questions, player_ids: playerIds } });

/** 골든벨은 문항 수만큼 { quiz_no: 1.., answer: "0100" } 를 한 번에, 탐정단은 { quiz_no: 0, answer } 한 건. 보낸 답은 고칠 수 없다. */
export const sendAnswers = (id, answers) => apiFetch(`${itemPath(id)}/answers`, { method: "POST", body: { answers } });

/** 이게 뭐게 힌트 열기 / 탐정단 조금 줄여 보기(최대 2번, 번마다 -5점). */
export const openHint = (id) => apiFetch(`${itemPath(id)}/hints`, { method: "POST" });

/** 이게 뭐게 정답 쓰기(최대 10번). 틀려도 감점은 없다. */
export const sendTry = (id, answer) => apiFetch(`${itemPath(id)}/tries`, { method: "POST", body: { answer } });

/**
 * 이게 뭐게를 낸다(그림 PNG 한 장 + 정답).
 * @param {{ image: { uri: string, file?: Blob }, answer: string, alts?: string[], hint2?: string, playerIds?: string[] }} input image 는 PNG
 */
export async function createDraw({ image, answer, alts = [], hint2 = "", playerIds = [] }) {
  const form = new FormData();
  await fileForUpload(form, image, "draw.png", "image/png");
  form.append("answer", answer);
  for (const alt of alts) form.append("alt_answers", alt);
  if (hint2) form.append("hint2", hint2);
  for (const id of playerIds) form.append("player_ids", id);
  return apiFetch("/play/draws", { method: "POST", body: form });
}

/**
 * 탐정단을 낸다(사진 한 장 + 확대 위치 + 선택식 보기).
 * @param {{ image: { uri: string, file?: Blob, fileName?: string | null, mimeType?: string }, source: 1 | 2, zoom: number, boxX: number, boxY: number, question: string, options: string[], answerIndex: number, comment?: string, playerIds?: string[] }} input
 */
export async function createPhoto({ image, source, zoom, boxX, boxY, question, options, answerIndex, comment = "", playerIds = [] }) {
  const form = new FormData();
  await fileForUpload(form, image, image.fileName || "photo.jpg", image.mimeType || "image/jpeg");
  form.append("source", String(source));
  form.append("zoom", String(zoom));
  form.append("box_x", String(boxX));
  form.append("box_y", String(boxY));
  form.append("question", question);
  for (const option of options) form.append("options", option);
  form.append("answer_index", String(answerIndex));
  if (comment) form.append("comment", comment);
  for (const id of playerIds) form.append("player_ids", id);
  return apiFetch("/play/photos", { method: "POST", body: form });
}

// ---------- 문장 폭탄방(폴링: 화면이 1초쯤마다 getBomb 을 부른다) ----------
const bombPath = (id, tail = "") => `/play/bomb/${encodeURIComponent(id)}${tail}`;

/** 내가 들어와 있는 열린 폭탄방(없으면 null) */
export const getBombCurrent = () => apiFetch("/play/bomb/current");
/** 우리 가족의 열린 폭탄방 목록(최근에 연 방이 먼저, mine 은 내가 들어와 있는 방) */
export const getBombOpen = () => apiFetch("/play/bomb/open");
/** 폭탄방을 연다(누구나). 이미 다른 방에 들어와 있으면 409 already_in_room */
export const createBomb = () => apiFetch("/play/bomb", { method: "POST" });
/** 방 상태: 선수·생명, 지금 차례와 남은 시간, 채팅, 끝났으면 결과 */
export const getBomb = (id) => apiFetch(bombPath(id));
/** 지난 방 기록: 끝난 판마다 이어 말한 문장(방에 참여한 가족만) */
export const getBombHistory = (id) => apiFetch(bombPath(id, "/history"));
export const joinBomb = (id) => apiFetch(bombPath(id, "/join"), { method: "POST" });
export const leaveBomb = (id) => apiFetch(bombPath(id, "/leave"), { method: "POST" });
/** 게임 시작 / 한 판 더(방장). 생명 1~5, 차례당 1~60초 */
export const startBomb = (id, { life, sec }) => apiFetch(bombPath(id, "/start"), { method: "POST", body: { life, sec } });
/** 내 차례에 이어 말하기(10자까지) */
export const sayBomb = (id, word) => apiFetch(bombPath(id, "/say"), { method: "POST", body: { word } });
/** 탈락·구경하는 사람의 응원(정해진 말이나 직접 쓴 20자, 모두에게 보임, 2초에 한 번) */
export const cheerBomb = (id, text) => apiFetch(bombPath(id, "/cheer"), { method: "POST", body: { text } });
/** 탈락·구경하는 사람끼리의 채팅(50자, 그런 사람들에게만 보임, 2초에 한 번) */
export const chatBomb = (id, text) => apiFetch(bombPath(id, "/chat"), { method: "POST", body: { text } });
/** 판정 투표를 연다. kind: "call" 어라?(다른 사람의 방금 말이 끝난 말인데 통과됐다) / "unfair" 억울해요(내가 끝난 말이 아닌데 탈락했다) */
export const startBombVote = (id, kind) => apiFetch(bombPath(id, "/vote/start"), { method: "POST", body: { kind } });
/** 열린 투표에 맞아요(true) / 아니에요(false). 게임 중인 사람만, 한 번 */
export const voteBomb = (id, yes) => apiFetch(bombPath(id, "/vote"), { method: "POST", body: { yes } });
/** 임시 개발용(커밋 금지): 판을 바로 끝낸다 */
export const closeBomb = (id) => apiFetch(bombPath(id, "/close"), { method: "POST" });
