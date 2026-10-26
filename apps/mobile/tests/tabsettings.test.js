// 소통 탭 안 읽은 수 합계와 Enter 전송 판단: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { shouldSendOnEnter } from "../src/features/family-chat/chatUtils.js";
import { totalUnread, unreadBadgeText } from "../src/features/family-chat/listUtils.js";

test("totalUnread: 모든 방의 안 읽은 수를 더하고, 잘못된 값은 0 으로 본다", () => {
  assert.equal(totalUnread([{ unread: 2 }, { unread: 0 }, { unread: 5 }]), 7);
  assert.equal(totalUnread([{ unread: "3" }, { unread: -4 }, { unread: NaN }, { unread: undefined }, null]), 3);
  assert.equal(totalUnread([{ unread: 1.9 }]), 1);
  assert.equal(totalUnread([]), 0);
  assert.equal(totalUnread(null), 0);
  assert.equal(totalUnread(undefined), 0);
});

test("탭 배지 문구: 합계 0 은 숨기고 99 를 넘으면 99+", () => {
  assert.equal(unreadBadgeText(totalUnread([])), "");
  assert.equal(unreadBadgeText(totalUnread([{ unread: 12 }, { unread: 30 }])), "42");
  assert.equal(unreadBadgeText(totalUnread([{ unread: 60 }, { unread: 60 }])), "99+");
});

test("shouldSendOnEnter: 웹에서 Shift 없는 Enter 만 보낸다", () => {
  assert.equal(shouldSendOnEnter({ key: "Enter" }, "web"), true);
  assert.equal(shouldSendOnEnter({ key: "Enter", shiftKey: true }, "web"), false); // Shift+Enter 는 줄바꿈
  assert.equal(shouldSendOnEnter({ key: "a" }, "web"), false);
  assert.equal(shouldSendOnEnter({ key: "Enter", isComposing: true }, "web"), false); // 한글 조합 확정용 Enter
  assert.equal(shouldSendOnEnter({ key: "Enter", keyCode: 229 }, "web"), false);
});

test("shouldSendOnEnter: 폰(네이티브) 키보드의 Enter 는 줄바꿈 유지", () => {
  assert.equal(shouldSendOnEnter({ key: "Enter" }, "ios"), false);
  assert.equal(shouldSendOnEnter({ key: "Enter" }, "android"), false);
  assert.equal(shouldSendOnEnter(null, "web"), false);
  assert.equal(shouldSendOnEnter(undefined, "web"), false);
});
