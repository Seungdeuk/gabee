// 가족 초대 링크·공유 문구: 공개 초대 페이지가 있으면 https 링크, 없으면 앱 주소를 쓰는지 시험한다: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { inviteLink, inviteMessage } from "../src/features/family-group/inviteLink.js";

const APP = "gabee://family-join?code=K7M2Q9XW4P";

test("초대 페이지 주소가 있으면 https 링크에 코드를 붙인다", () => {
  assert.equal(inviteLink("K7M2Q9XW4P", APP, "https://gabee.example/invite/"), "https://gabee.example/invite/?code=K7M2Q9XW4P");
});

test("초대 페이지 주소가 없으면 앱 주소를 그대로 쓴다", () => {
  assert.equal(inviteLink("K7M2Q9XW4P", APP, ""), APP);
});

test("이상한 코드로는 링크를 만들지 않는다", () => {
  assert.equal(inviteLink("<script>", APP, "https://gabee.example"), "");
});

test("공유 문구에 링크와 코드가 함께 들어간다", () => {
  const text = inviteMessage("K7M2Q9XW4P", "https://gabee.example/?code=K7M2Q9XW4P");
  assert.match(text, /https:\/\/gabee\.example\/\?code=K7M2Q9XW4P/);
  assert.match(text, /K7M2Q9XW4P 를 입력/);
});

test("링크가 없어도 코드는 안내한다", () => {
  assert.doesNotMatch(inviteMessage("K7M2Q9XW4P", ""), /링크를 누르면/);
});
