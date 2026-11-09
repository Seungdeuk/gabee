// 문서함 첫 안내: 정책이 바뀐 안내(민감 문서도 등록)는 옛 안내를 본 사용자에게도 다시 보이도록 기억 키를 올렸고, 외부 AI 전달을 알린다: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { LIBRARY_NOTICE_BODY, LIBRARY_NOTICE_KEY, shouldShowLibraryNotice } from "../src/features/family-chat/libraryNotice.js";

test("안내 기억 키는 v3 이다(옛 안내를 본 사용자도 바뀐 정책 안내를 한 번 더 본다)", async () => {
  assert.equal(LIBRARY_NOTICE_KEY, "gabee.library.notice.v3");
  const seenOld = { getItem: async (key) => (key === "gabee.library.notice.v2" ? "1" : null) };
  assert.equal(await shouldShowLibraryNotice(seenOld), true);
});

test("안내 문구: 민감한 문서의 가린 글이 AI 에 전달될 수 있다고 알린다", () => {
  assert.match(LIBRARY_NOTICE_BODY, /외부 AI/);
  assert.match(LIBRARY_NOTICE_BODY, /가린 글/);
});
