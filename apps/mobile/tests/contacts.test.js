// 가족 연락처(별명·메모) 순수 함수와 API 경로·본문을 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import {
  applySavedNickname,
  contactErrorMessage,
  contactRows,
  memoLine,
  nicknameMap,
  relationLabel,
  validateNickname,
} from "../src/features/family-chat/contactUtils.js";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

// api.js 는 가져올 때 서버 주소를 읽으므로 환경변수를 정한 뒤에 가져온다
const { listNicknames, setNickname } = await import("../src/features/family-chat/api.js");

const realFetch = globalThis.fetch;
const calls = [];
beforeEach(() => {
  calls.length = 0;
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const mockFetch = (res) => {
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return typeof res === "function" ? res() : res;
  };
};


test("relationLabel: 정해진 관계는 한글, other 는 직접 적은 관계(없으면 가족), 안 정했으면 빈 문자열", () => {
  assert.equal(relationLabel({ family_relation: "mom" }), "엄마");
  assert.equal(relationLabel({ family_relation: "grandpa" }), "할아버지");
  assert.equal(relationLabel({ family_relation: "other", family_relation_detail: " 이모 " }), "이모");
  assert.equal(relationLabel({ family_relation: "other", family_relation_detail: null }), "가족");
  assert.equal(relationLabel({ family_relation: null }), "");
  assert.equal(relationLabel({ family_relation: "alien" }), "");
});

test("contactRows: 나는 맨 위에 별명·대화 없이, 별명이 있으면 별명이 title 이고 표시 이름이 subtitle, 메모는 한 줄로", () => {
  const members = [
    { id: "dad", name: "아빠", display_name: null, family_relation: "dad", photo_url: null },
    { id: "me", name: "지민", display_name: null, photo_url: "/p" },
    { id: "mom", name: "엄마", display_name: "우리 엄마", family_relation: "mom", photo_url: null },
  ];
  const nicks = nicknameMap([
    { target_user_id: "mom", nickname: "마미", memo: "생일\n3월 2일" },
    { target_user_id: "me", nickname: "나님", memo: "x" },
  ]);
  const rows = contactRows(members, "me", nicks);
  assert.deepEqual(rows.map((r) => r.id), ["me", "dad", "mom"]);
  assert.equal(rows[0].isMe, true);
  assert.equal(rows[0].title, "지민");
  assert.equal(rows[0].nickname, "");
  assert.equal(rows[0].memo, "");
  assert.deepEqual([rows[1].title, rows[1].subtitle, rows[1].relation], ["아빠", "", "아빠"]);
  assert.deepEqual([rows[2].title, rows[2].subtitle, rows[2].memo], ["마미", "우리 엄마", "생일 3월 2일"]);
  assert.deepEqual(contactRows(null, "me"), []);
  assert.equal(memoLine("a\n\nb"), "a b");
});

test("validateNickname·applySavedNickname: 길이 검사, 둘 다 비면 항목 삭제", () => {
  assert.equal(validateNickname("가".repeat(40), "메모"), "");
  assert.match(validateNickname("가".repeat(41), ""), /40자/);
  assert.match(validateNickname("", "가".repeat(1001)), /1000자/);
  assert.equal(validateNickname("", ""), "");
  const map = { a: { nickname: "별", memo: "" } };
  assert.deepEqual(applySavedNickname(map, "b", { nickname: "새", memo: null }), { a: map.a, b: { nickname: "새", memo: "" } });
  assert.deepEqual(applySavedNickname(map, "a", { nickname: null, memo: null }), {});
  assert.match(contactErrorMessage({ code: "invalid_nickname" }), /40자/);
  assert.match(contactErrorMessage({ code: "cannot_nickname_self" }), /자기 자신/);
  assert.match(contactErrorMessage({ code: "network_error" }), /서버에 연결하지 못했어요/);
});

test("listNicknames·setNickname: family-group 계약 경로, 빈 값은 null 로 보내 지운다", async () => {
  mockFetch(() => json(200, []));
  await listNicknames();
  assert.equal(calls[0].url, "http://api.test/family-group/groups/me/nicknames");
  mockFetch(() => json(200, { target_user_id: "u1", nickname: "마미", memo: null }));
  await setNickname("u1", { nickname: " 마미 ", memo: "" });
  assert.equal(calls[1].url, "http://api.test/family-group/groups/me/nicknames/u1");
  assert.equal(calls[1].init.method, "PUT");
  assert.deepEqual(JSON.parse(calls[1].init.body), { nickname: "마미", memo: null });
  await setNickname("u1", { nickname: "", memo: "  " });
  assert.deepEqual(JSON.parse(calls[2].init.body), { nickname: null, memo: null });
});

