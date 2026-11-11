import assert from "node:assert/strict";
import { test } from "node:test";

import { joinPromptVisible } from "@/features/family-group/joinPrompt";

test("가족 그룹도 대기 요청도 없을 때만 홈에 초대 코드 참여 버튼을 보인다", () => {
  assert.equal(joinPromptVisible("none"), true);
});

test("불러오는 중·오류·승인 대기·가족 구성원이면 버튼을 숨긴다", () => {
  for (const status of ["loading", "error", "pending", "member", undefined]) {
    assert.equal(joinPromptVisible(status), false, String(status));
  }
});
