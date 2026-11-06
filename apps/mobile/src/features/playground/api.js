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
