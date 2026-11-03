// 내가 붙인 별명이 모든 탭의 이름에 반영되는지 시험한다(가짜 서버, fetch 대체): npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

// 서버 주소는 불러올 때 읽으므로 환경 값을 정한 뒤에 가져온다.
const { getMembers } = await import("../src/features/billing/api.js");
const { getRoomInfo } = await import("../src/features/family-chat/api.js");
const { buildFamily } = await import("../src/features/schedule/members.js");
const { getGroupWithNicknames, loadNicknames, nicknameById, withNicknames } = await import("../src/shared/members/nicknames.js");

const realFetch = globalThis.fetch;
beforeEach(() => {
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const GROUP = {
  id: "g1",
  name: "우리집",
  my_id: "me1",
  members: [
    { id: "me1", name: "김나", display_name: null, family_relation: null },
    { id: "u2", name: "박엄마계정", display_name: "표시이름", family_relation: "mom" },
    { id: "u3", name: "이아빠계정", display_name: null, family_relation: "dad" },
  ],
};
const NICKS = [
  { target_user_id: "u2", nickname: " 어머니 ", memo: null },
  { target_user_id: "u3", nickname: null, memo: "메모만" },
];
function serve({ nicknames = NICKS, nickFails = false } = {}) {
  globalThis.fetch = async (url) => {
    const path = new URL(String(url)).pathname;
    if (path === "/family-group/groups/me/nicknames") return nickFails ? json(500, { code: "x" }) : json(200, nicknames);
    if (path === "/family-group/groups/me") return json(200, GROUP);
    throw new Error(`예상 밖 호출 ${path}`);
  };
}

test("nicknameById: 별명이 비었거나 공백뿐이면 넣지 않고, 앞뒤 공백은 자른다", () => {
  assert.deepEqual(nicknameById(NICKS), { u2: "어머니" });
  assert.deepEqual(nicknameById(null), {});
});

test("withNicknames: 별명이 있는 사람만 display_name 을 별명으로 바꾸고 나머지는 그대로다", () => {
  const out = withNicknames(GROUP.members, { u2: "어머니" });
  assert.equal(out[1].display_name, "어머니");
  assert.equal(out[1].nickname, "어머니");
  assert.equal(out[0], GROUP.members[0]);
  assert.equal(out[2], GROUP.members[2]);
  assert.equal(GROUP.members[1].display_name, "표시이름"); // 원본은 바꾸지 않는다
});

test("별명 목록을 못 받아도 그룹은 원래 이름으로 온다", async () => {
  serve({ nickFails: true });
  assert.deepEqual(await loadNicknames(), {});
  const group = await getGroupWithNicknames();
  assert.equal(group.members[1].display_name, "표시이름");
});

test("소통 getRoomInfo: 별명이 구성원 이름이 되고, raw 는 서버 값 그대로다", async () => {
  serve();
  assert.equal((await getRoomInfo()).members[1].display_name, "어머니");
  assert.equal((await getRoomInfo({ raw: true })).members[1].display_name, "표시이름");
});

test("가계 getMembers: 정산 담당자·나눌 사람 이름에 별명이 반영된다", async () => {
  serve();
  const members = await getMembers();
  assert.equal(members.find((m) => m.id === "u2").name, "어머니"); // 가계 화면이 그리는 필드
  assert.equal(members.find((m) => m.id === "u3").name, "이아빠계정"); // 별명 없는 사람은 그대로
});

test("일정 buildFamily: 별명 > 관계 이름 > 표시 이름이고, 별명이 없으면 관계 이름 그대로다", async () => {
  serve();
  const family = buildFamily(await getGroupWithNicknames());
  const name = (id) => family.members.find((m) => m.id === id)?.name;
  assert.equal(name("me"), "나");
  assert.equal(name("mom"), "어머니"); // 별명이 관계 이름(엄마)보다 먼저
  assert.equal(name("dad"), "아빠"); // 별명 없음 → 관계 이름
});
