// AI 패널: 결과 아래 가려진 개수 한 줄(privacyCaption)과 승인 정책(버튼 한 번에 분석·동의 게이트·상시 안내·확인 카드 없음)을 시험한다: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { maskedTotal, privacyCaption } from "../src/features/family-chat/privacyPreview.js";
import { PANEL_NOTICE } from "../src/features/family-chat/privacyCopy.js";

test("maskedTotal: 종류 구분 없이 0 보다 큰 개수만 더한다", () => {
  assert.equal(maskedTotal({ PHONE: 1, PLATE: 2, PERSON: 0 }), 3);
  assert.equal(maskedTotal({ PHONE: -1, EMAIL: "x" }), 0);
  assert.equal(maskedTotal(undefined), 0);
});

test("privacyCaption: meta.privacy 한 줄, 0 이면 생략", () => {
  assert.equal(privacyCaption({ masked: { PHONE: 2, PERSON: 5 }, blocked_messages: 1 }), "개인정보 7개를 가려서 보냈고 메시지 1개는 제외했어요");
  assert.equal(privacyCaption({ masked: { PHONE: 2 }, blocked_messages: 0 }), "개인정보 2개를 가려서 보냈어요");
  assert.equal(privacyCaption({ masked: {}, blocked_messages: 4 }), "메시지 4개는 제외하고 보냈어요");
  assert.equal(privacyCaption({ masked: { PHONE: 0 }, blocked_messages: 0 }), "");
  assert.equal(privacyCaption(undefined), "");
  assert.equal(privacyCaption(null), "");
});

test("승인 정책: 답장 추천은 입력창에 넣기만 하고, 일정·할 일 등록은 버튼 핸들러에서만 일어난다(소스 확인)", () => {
  const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8").replace(/\r\n/g, "\n");
  const room = read("../src/features/family-chat/screens/ChatRoomScreen.js");
  const pick = room.slice(room.indexOf("const pickReply"), room.indexOf("const pickReply") + 200);
  assert.match(pick, /setDraft/);
  assert.doesNotMatch(pick, /send|post|apiFetch/i);

  const panel = read("../src/features/family-chat/components/AiPanel.js");
  // 확인 카드(미리보기 -> "AI에 보내기") 흐름은 없다
  assert.doesNotMatch(panel, /AiConfirmCard|requestPreview|confirmSend|cancelPreview|previewAiRange|pending/);
  assert.equal(readFileSync(new URL("../src/features/family-chat/api.js", import.meta.url), "utf8").includes("previewAiRange"), false);
  // "대화 분석하기" 버튼 한 번에 분석을 부른다(run("analysis", ...) 는 analyze 핸들러 한 곳, 안에서 analyzeChat 을 한 번 부른다)
  assert.equal((panel.match(/run\("analysis"/g) ?? []).length, 1);
  assert.match(panel, /const analyzeNow = \(\) =>\s*run\("analysis", async \(\) => \{[\s\S]*return analyzeChat\(\)/);
  assert.match(panel, /onPress=\{analyze\}/);
  assert.doesNotMatch(panel.slice(panel.indexOf("useEffect"), panel.indexOf("useEffect") + 150), /analyze/);
  // 동의는 회원가입 때 받으므로 꺼짐 분기(동의 카드)가 없고 분석 버튼이 항상 있는 화면이다
  assert.doesNotMatch(panel, /if \(!settings\.enabled\)/);
  assert.ok(panel.indexOf('testID="chat-ai-analyze"') > 0);
  // 켜진 상태에는 상시 안내문이 분석 버튼 위에 있다(문구는 privacyCopy 상수)
  assert.match(panel, /\{PANEL_NOTICE\}/);
  assert.ok(panel.indexOf("{PANEL_NOTICE}") < panel.indexOf('testID="chat-ai-analyze"'));
  assert.match(PANEL_NOTICE, /바로 AI로 전달돼요/);
  // 결과 아래 가려진 개수 표시는 유지
  assert.match(panel, /privacyCaption\(analysis\.meta\?\.privacy\)/);
  // 답장·주제 추천은 버튼이 없고 분석 결과에서만 나온다(별도 AI 호출 없음)
  assert.doesNotMatch(panel, /suggestReplies|suggestTopics|run\("(replies|topics)"/);
  assert.match(panel, /onPick=\{pickText\}/);
  // 일정·할 일 등록은 사용자가 누르는 핸들러에 연결돼 있고 effect 에서 부르지 않는다
  assert.match(panel, /onPress=\{\(\) => register\(i, c\)\}/);
  assert.match(panel, /onRegister=\{\(\) => registerTodo\(i, t\)\}/);
  assert.doesNotMatch(panel.slice(panel.indexOf("useEffect"), panel.indexOf("useEffect") + 150), /register/);
});
