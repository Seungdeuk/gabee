// AI 보내기 전 확인(미리보기): 칩 문구·차단 경고·결과 한 줄·오류 문구와 API 경로·본문, 승인 정책(자동 전송/등록 없음)을 시험한다: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, test } from "node:test";

import {
  blockedWarning,
  canSendToAi,
  maskedChips,
  maskedTotal,
  INSUFFICIENT_WARNING,
  parsePreview,
  previewErrorMessage,
  previewLineText,
  privacyCaption,
  sendBlockReason,
} from "../src/features/family-chat/privacyPreview.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";

const realFetch = globalThis.fetch;
beforeEach(() => {
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

test("maskedChips: 0 개 종류는 빼고 정해진 순서로, 한국어 라벨", () => {
  assert.deepEqual(maskedChips({ PERSON: 5, PHONE: 2, EMAIL: 0, CARD: 1 }), ["전화번호 2개 가림", "카드번호 1개 가림", "이름 5개 가림"]);
  assert.deepEqual(maskedChips({ ADDRESS: 1, SECRET: 3, ACCOUNT: 2, RRN: 1 }), ["주민번호 1개 가림", "계좌번호 2개 가림", "비밀번호·인증 정보 3개 가림", "주소 1개 가림"]);
  assert.deepEqual(maskedChips({}), []);
  assert.deepEqual(maskedChips(null), []);
  assert.deepEqual(maskedChips({ PHONE: -1, EMAIL: "x" }), []);
});

test("maskedChips: 모르는 종류는 '기타 정보' 로 맨 뒤에 합친다", () => {
  assert.deepEqual(maskedChips({ PHONE: 1, PLATE: 2, VIN: 1 }), ["전화번호 1개 가림", "기타 정보 3개 가림"]);
  assert.equal(maskedTotal({ PHONE: 1, PLATE: 2, PERSON: 0 }), 3);
  assert.equal(maskedTotal(undefined), 0);
});

test("blockedWarning: 제외되는 메시지가 있을 때만 경고 문구", () => {
  assert.equal(blockedWarning(0), "");
  assert.equal(blockedWarning(undefined), "");
  assert.equal(blockedWarning(3), "주민번호·카드·비밀번호처럼 민감한 정보가 있는 메시지 3개는 보내지 않아요");
});

test("privacyCaption: meta.privacy 한 줄, 0 이면 생략", () => {
  assert.equal(privacyCaption({ masked: { PHONE: 2, PERSON: 5 }, blocked_messages: 1 }), "개인정보 7개를 가려서 보냈고 메시지 1개는 제외했어요");
  assert.equal(privacyCaption({ masked: { PHONE: 2 }, blocked_messages: 0 }), "개인정보 2개를 가려서 보냈어요");
  assert.equal(privacyCaption({ masked: {}, blocked_messages: 4 }), "메시지 4개는 제외하고 보냈어요");
  assert.equal(privacyCaption({ masked: { PHONE: 0 }, blocked_messages: 0 }), "");
  assert.equal(privacyCaption(undefined), "");
  assert.equal(privacyCaption(null), "");
});

test("parsePreview·canSendToAi: ai_enabled=false 면 보내기를 막는다", () => {
  const ok = parsePreview({ message_count: 12, masked: { PERSON: 2 }, blocked_messages: 1, lines: [{ id: 1, speaker: "[PERSON_1]", text: "안녕", blocked: false }], ai_enabled: true });
  assert.equal(ok.messageCount, 12);
  assert.equal(ok.blockedMessages, 1);
  assert.equal(canSendToAi(ok), true);
  assert.equal(canSendToAi(parsePreview({ ai_enabled: false })), false);
  assert.equal(canSendToAi(null), false);
  assert.deepEqual(parsePreview(null).lines, []);
});

test("sendable=false 면 보내기 막힘, ai_enabled=false 와 겹치면 동의 안내가 먼저", () => {
  assert.equal(parsePreview({ ai_enabled: true, sendable: true }).sendable, true);
  assert.equal(parsePreview({ ai_enabled: true }).sendable, true);
  const few = parsePreview({ ai_enabled: true, sendable: false, blocked_messages: 9 });
  assert.equal(canSendToAi(few), false);
  assert.equal(sendBlockReason(few), "insufficient");
  assert.match(INSUFFICIENT_WARNING, /AI에 보낼 수 있는 대화가 부족해요/);
  const both = parsePreview({ ai_enabled: false, sendable: false });
  assert.equal(sendBlockReason(both), "disabled");
  assert.equal(sendBlockReason(parsePreview({ ai_enabled: true, sendable: true })), "");
  assert.equal(sendBlockReason(null), "disabled");
});

test("previewLineText: 차단된 줄은 내용을 보이지 않고 '제외됨'", () => {
  assert.equal(previewLineText({ id: 1, speaker: "[PERSON_1]", text: "[PERSON_2] 연락처 [PHONE_1]", blocked: false }), "[PERSON_1]: [PERSON_2] 연락처 [PHONE_1]");
  assert.equal(previewLineText({ id: 2, speaker: "[PERSON_2]", text: "원문이 오더라도 숨김", blocked: true }), "[PERSON_2]: (제외됨)");
});

test("previewErrorMessage: 서버 코드를 한국어 문구로, 모르면 일반 문구", () => {
  assert.equal(previewErrorMessage({ code: "too_few_messages" }), "분석할 대화가 아직 충분하지 않아요. 대화가 조금 더 쌓인 뒤에 눌러 주세요");
  assert.equal(previewErrorMessage({ code: "no_group" }), "가족 그룹에 먼저 참여해 주세요");
  assert.equal(previewErrorMessage({ code: "network_error" }), "서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요");
  assert.ok(previewErrorMessage({}).length > 0);
});

test("previewAiRange: POST /family-chat/ai/preview 에 범위만 보내고 AI 경로는 부르지 않는다", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ path: new URL(url).pathname, method: init.method ?? "GET", body: init.body ? JSON.parse(init.body) : null });
    return json(200, { message_count: 0, masked: {}, blocked_messages: 0, lines: [], ai_enabled: true });
  };
  const api = await import("../src/features/family-chat/api.js");
  await api.previewAiRange();
  await api.previewAiRange({ limit: 50, afterId: 7 });
  assert.deepEqual(
    calls.map((c) => `${c.method} ${c.path}`),
    ["POST /family-chat/ai/preview", "POST /family-chat/ai/preview"],
  );
  assert.deepEqual(calls[0].body, { limit: 100, after_id: 0 });
  assert.deepEqual(calls[1].body, { limit: 50, after_id: 7 });
});

test("previewAiRange: 400 too_few_messages 는 오류 코드로 전달돼 문구로 바뀐다", async () => {
  globalThis.fetch = async () => json(400, { code: "too_few_messages", message: "x" });
  const api = await import("../src/features/family-chat/api.js");
  await assert.rejects(api.previewAiRange(), (e) => {
    assert.equal(e.code, "too_few_messages");
    return true;
  });
});

test("승인 정책: 답장 추천은 입력창에 넣기만 하고, 일정·할 일 등록은 버튼 핸들러에서만 일어난다(소스 확인)", () => {
  const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8").replace(/\r\n/g, "\n");
  const room = read("../src/features/family-chat/screens/ChatRoomScreen.js");
  const pick = room.slice(room.indexOf("const pickReply"), room.indexOf("const pickReply") + 200);
  assert.match(pick, /setDraft/);
  assert.doesNotMatch(pick, /send|post|apiFetch/i);

  const panel = read("../src/features/family-chat/components/AiPanel.js");
  // 분석·추천 API 는 confirmSend 안에서만 부른다(버튼은 requestPreview 만 부름)
  assert.doesNotMatch(panel.replace(/const confirmSend[\s\S]*?\n {2}\};/, ""), /run\("(analysis|replies|topics)"/);
  assert.match(panel, /onPress=\{\(\) => requestPreview\("analysis"\)\}/);
  assert.match(panel, /onPress=\{\(\) => requestPreview\("replies"\)\}/);
  assert.match(panel, /onPress=\{\(\) => requestPreview\("topics"\)\}/);
  // 일정·할 일 등록은 사용자가 누르는 핸들러에 연결돼 있고 effect 에서 부르지 않는다
  assert.match(panel, /onPress=\{\(\) => register\(i, c\)\}/);
  assert.match(panel, /onRegister=\{\(\) => registerTodo\(i, t\)\}/);
  assert.doesNotMatch(panel.slice(panel.indexOf("useEffect"), panel.indexOf("useEffect") + 150), /register/);
});
