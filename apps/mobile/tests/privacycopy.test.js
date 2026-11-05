// 가족 AI 동의 안내 문구(privacyCopy.js)와 켜기 확인 판단·접근성 라벨을 시험한다: npm test
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import {
  CONSENT_DETAILS,
  ENABLE_ON_ANALYZE_BODY,
  ENABLE_ON_ANALYZE_CONFIRM_LABEL,
  ENABLE_ON_ANALYZE_TITLE,
  CONSENT_SUMMARY,
  CONSENT_TITLE,
  consentA11ySummary,
  detailsToggleLabel,
} from "../src/features/family-chat/privacyCopy.js";
import { privacyCaption } from "../src/features/family-chat/privacyPreview.js";

const summary = CONSENT_SUMMARY.join("\n");
const all = [CONSENT_TITLE, ...CONSENT_SUMMARY, ...CONSENT_DETAILS].join("\n");

test("요약은 2~4줄이고 필수 사실을 담는다", () => {
  assert.ok(CONSENT_SUMMARY.length >= 2 && CONSENT_SUMMARY.length <= 4);
  assert.match(summary, /Claude/);
  assert.match(summary, /가려지지 않거나 일부만 가려진 채/);
  assert.match(summary, /종단간 암호화가 아니/);
  assert.match(summary, /끌 수 있어요/);
});

test("상세에는 E2EE 아님·소유자/관리자만·끄면 멈춤·도우미별 범위가 있다", () => {
  assert.match(all, /E2EE/);
  assert.match(all, /소유자·관리자만/);
  assert.match(all, /대신 동의하는 것이 아니/);
  assert.match(all, /AI 기능이 모두 멈추고/);
  assert.match(all, /AI 비서: 질문과 앞 대화\(최근 10개\)를 가리지 않고/);
  assert.match(all, /문서 질문: 문서를 저장할 때/);
  assert.match(all, /정산·돌봄 도우미/);
  assert.match(all, /위치/);
});

test("요약은 AI 비서·문서 질문·일정·정산·돌봄 도우미와 대화 분석(답장·대화 주제 추천 포함)을 모두 언급한다", () => {
  for (const word of ["대화 분석", "답장 추천", "대화 주제 추천", "AI 비서", "문서 질문", "일정", "정산", "돌봄"]) assert.ok(summary.includes(word), word);
});

test("대화 분석 상세: 한 번에 보내고, 누를 때마다 별도 확인 없이 바로 전송되며, 가린 내용은 결과 화면에 개수로 알린다", () => {
  const line = CONSENT_DETAILS.find((l) => l.startsWith("대화 분석("));
  assert.ok(line);
  assert.match(line, /답장 추천·대화 주제 추천/);
  assert.match(line, /Claude 로 한 번에 보내요/);
  assert.match(line, /“대화 분석하기”를 누를 때마다 별도 확인 없이 바로 전송돼요/);
  assert.match(line, /결과 화면에 개수로 알려 드려요\(예: 이름 3개·주소 1개 가림\)\.$/);
  // 확인 카드 흐름은 없어졌으므로 옛 표현이 남아 있으면 안 된다
  assert.doesNotMatch(all, /확인 카드|AI에 보내기/);
  assert.match(CONSENT_DETAILS.find((l) => l.startsWith("AI 비서")), /주민번호·카드·계좌·비밀번호가 든 입력은 서버가 막아요/);
});

test("요약 두 번째 줄에 '별도 확인 없이 바로 AI로 전송' 이 있고, 결과 저장(약 10분) 안내는 동의 상세에 있다", () => {
  assert.equal(CONSENT_SUMMARY[1], "켜면 “대화 분석하기”를 누를 때마다 별도 확인 없이 바로 AI로 전송돼요.");
  assert.match(CONSENT_DETAILS.find((l) => l.startsWith("대화 분석(")), /약 10분\) 저장/);
});

test("가려서 보낸다는 말은 대화 분석 줄에만 쓰고, 끄면 Claude 로는 나가지 않는다고 한정한다", () => {
  const masked = [...CONSENT_SUMMARY, ...CONSENT_DETAILS].filter((l) => /개인정보를 가려서|를 가린 뒤/.test(l));
  assert.ok(masked.length >= 1);
  for (const l of masked) assert.match(l, /대화 분석/);
  const off = CONSENT_DETAILS.find((l) => l.startsWith("끄면"));
  assert.match(off, /Claude 로는 나가지 않아요/);
  assert.match(off, /설정된 서버에서는/);
  assert.doesNotMatch(all, /아무것도 나가지/);
});

test("접근성 라벨", () => {
  assert.equal(detailsToggleLabel(false), "자세히 보기");
  assert.equal(detailsToggleLabel(true), "자세히 접기");
  assert.ok(consentA11ySummary().startsWith(CONSENT_TITLE));
  assert.match(consentA11ySummary(), /Claude/);
});

const SRC_DIR = fileURLToPath(new URL("../src/", import.meta.url));
const rel = (f) => relative(SRC_DIR, f).split(sep).join("/");
const walk = (dir) =>
  readdirSync(dir).flatMap((n) => {
    const f = join(dir, n);
    return statSync(f).isDirectory() ? walk(f) : f.endsWith(".js") ? [f] : [];
  });
const readText = (f) => readFileSync(f, "utf8").replace(/\r\n/g, "\n");
const panel = () => readText(join(SRC_DIR, "features/family-chat/components/AiPanel.js"));

test("가린 개수 안내 한 줄은 가족 채팅 AI 결과 영역에서만 쓰인다", () => {
  assert.equal(privacyCaption({ masked: { PHONE: 2 } }), "개인정보 2개를 가려서 보냈어요");
  const names = walk(SRC_DIR)
    .filter((f) => readText(f).includes("privacyCaption("))
    .map(rel)
    .filter((n) => n !== "features/family-chat/privacyPreview.js");
  assert.deepEqual(names, ["features/family-chat/components/AiPanel.js"]);
});

test("AI 패널에는 켜기·끄기 버튼이 없고 대화 분석하기만 있다(동의는 회원가입 때 받는다)", () => {
  const src = panel();
  for (const gone of ["testID=\"chat-ai-enable\"", "chat-ai-disable", "chat-ai-need-manager", "chat-ai-on-member-note", "AiConsentCard", "confirmingDisable", "changeEnabled", "startEnable", "canManage"]) {
    assert.ok(!src.includes(gone), `${gone} 는 없어야 한다`);
  }
  assert.match(src, /testID="chat-ai-analyze"/);
  assert.doesNotMatch(src, /PANEL_NOTICE|chat-ai-notice/); // 상시 안내는 마이 > 가비 AI 이용 안내로 옮겼다
});

test("AI 설정이 꺼져 있으면 확인 카드를 먼저 보이고, '켜고 분석하기'를 눌렀을 때만 켠 뒤 분석한다(켜져 있으면 곧바로 분석)", () => {
  const src = panel();
  // 분석하기 버튼: 꺼져 있으면 켜지 않고 확인 카드만 연다
  const analyze = src.match(/const analyze = async \(\) => \{[\s\S]*?\n {2}\};/)?.[0] ?? "";
  assert.match(analyze, /settings\?\.enabled === false\) \{\s*setConfirmingEnable\(true\)/);
  assert.doesNotMatch(analyze, /setAiEnabled/);
  assert.match(analyze, /await analyzeNow\(\)/); // 켜져 있으면 확인 없이 분석
  // 켜기는 분석 호출 직전 한 곳, 확인 버튼 핸들러에서만 도달한다
  const now = src.match(/const analyzeNow = \(\) =>[\s\S]*?\n {4}\}, \(res\)/)?.[0] ?? "";
  assert.match(now, /settings\?\.enabled === false\) await setAiEnabled\(true\)/);
  assert.match(now, /return analyzeChat\(\{ roomId \}\)/);
  assert.equal((src.match(/setAiEnabled\(/g) ?? []).length, 1); // 다른 곳에서 켜거나 끄지 않는다
  assert.doesNotMatch(src, /setAiEnabled\(false\)/);
  const confirm = src.match(/const confirmEnableAndAnalyze = async \(\) => \{[\s\S]*?\n {2}\};/)?.[0] ?? "";
  assert.match(confirm, /await analyzeNow\(\)/);
  assert.match(src, /onPress=\{confirmEnableAndAnalyze\}/);
  assert.match(src, /onPress=\{\(\) => setConfirmingEnable\(false\)\}/); // 취소하면 아무것도 켜지지 않는다
});

test("켜기 확인 문구: 가족 전체에 적용되고 대화는 가려서 전달된다는 것을 알린다", () => {
  assert.match(ENABLE_ON_ANALYZE_TITLE, /꺼져 있어요/);
  assert.match(ENABLE_ON_ANALYZE_BODY, /우리 가족 모두/);
  assert.match(ENABLE_ON_ANALYZE_BODY, /개인정보를 가린 최근 대화/);
  assert.equal(ENABLE_ON_ANALYZE_CONFIRM_LABEL, "켜고 분석하기");
});

test("동의 PUT(/family-chat/ai/settings) 호출 위치는 허용 목록만 — 새 우회 경로가 생기면 실패", () => {
  const files = walk(SRC_DIR);
  const hits = files
    .filter((f) => /ai\/settings"[^;]*PUT|PUT[^;]*ai\/settings"/.test(readText(f).replace(/\n/g, " ")))
    .map(rel)
    .sort();
  // family-chat/api.js: AiPanel 의 분석 흐름(꺼져 있으면 먼저 켬)이 부른다. ai-assistant/api.js(enableAi, AiOffCard): 확인 카드를 우회하는 알려진 경로.
  // TODO: 담당 팀과 공용 확인 카드(shared)로 통합하면 ai-assistant 항목을 허용 목록에서 뺀다.
  assert.deepEqual(hits, ["features/ai-assistant/api.js", "features/family-chat/api.js"]);
  const callers = files.filter((f) => /setAiEnabled\(/.test(readText(f)) && !f.endsWith("api.js")).map(rel);
  assert.deepEqual(callers, ["features/family-chat/components/AiPanel.js"]);
});
