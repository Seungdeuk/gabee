// 업로드 직후 "일정에 넣을까요?" 카드를 띄울지 정하는 규칙을 시험한다: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { localToday, schedulePromptFor, schedulePromptSentence } from "../src/features/ai-assistant/uploadSchedule.js";

const record = (extra = {}) => ({ title: "제주 항공권", kind_label: "항공권", occurred_on: "2026-11-20", ...extra });

test("오늘 이후 날짜가 있는 기록은 일정 제안 값을 돌려준다", () => {
  assert.deepEqual(schedulePromptFor(record(), "2026-10-27"), { title: "제주 항공권", kindLabel: "항공권", date: "2026-11-20" });
  assert.equal(schedulePromptFor(record({ occurred_on: "2026-10-27" }), "2026-10-27")?.date, "2026-10-27"); // 오늘도 포함
});

test("지난 날짜·날짜 없음·제목 없음·이상한 값은 묻지 않는다", () => {
  assert.equal(schedulePromptFor(record({ occurred_on: "2026-10-15" }), "2026-10-27"), null); // 영수증 같은 지난 기록
  assert.equal(schedulePromptFor(record({ occurred_on: null }), "2026-10-27"), null);
  assert.equal(schedulePromptFor(record({ occurred_on: "내일" }), "2026-10-27"), null);
  assert.equal(schedulePromptFor(record({ title: "  " }), "2026-10-27"), null);
  assert.equal(schedulePromptFor(null, "2026-10-27"), null);
  assert.equal(schedulePromptFor(undefined, "2026-10-27"), null);
});

test("채팅으로 보낼 문장은 제목과 날짜를 모두 담는다", () => {
  assert.equal(schedulePromptSentence({ title: "제주 항공권", date: "2026-11-20" }), '방금 올린 "제주 항공권" 문서의 날짜(2026-11-20)를 일정에 넣어줘. 시간과 장소가 문서에 있으면 함께 넣고, 메모에는 문서의 핵심 내용만 적어줘');
});

test("오늘 날짜는 기기 날짜를 YYYY-MM-DD 로 만든다", () => {
  assert.equal(localToday(new Date(2026, 0, 5, 23, 30)), "2026-01-05");
  assert.match(localToday(), /^\d{4}-\d{2}-\d{2}$/);
});
