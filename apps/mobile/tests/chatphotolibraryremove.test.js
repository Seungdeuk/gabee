// 채팅 사진 -> 가족 문서함 "문서함에서 빼기"(T09: API 호출, 두 번 눌러 빼기, 결과 문구, 화면 배선)를 시험한다: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, test } from "node:test";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

const MOD = "../src/features/family-chat/saveToLibrary.js";
const GOOD = { id: "a1b2c3", url: "/family-chat/photos/a1b2c3", in_library: true };
const src = (p) => readFileSync(new URL(`../src/features/family-chat/${p}`, import.meta.url), "utf8");

const realFetch = globalThis.fetch;
beforeEach(() => {
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("API removePhotoFromLibrary: DELETE /family-chat/photos/{id}/library, 본문 없음, 204 는 null", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: init?.method, body: init?.body });
    return new Response(null, { status: 204 });
  };
  const api = await import("../src/features/family-chat/api.js");
  assert.equal(await api.removePhotoFromLibrary("a1 b/2"), null);
  assert.equal(calls[0].url, "http://api.test/family-chat/photos/a1%20b%2F2/library");
  assert.equal(calls[0].method, "DELETE");
  assert.ok(calls[0].body == null);
});

test("removeFromLibrary: 성공·이미 없음(not_in_library)은 ok, 다른 오류는 문구로 바꿔 던지지 않는다", async () => {
  const m = await import(MOD);
  assert.deepEqual(await m.removeFromLibrary(GOOD, { remove: async () => null }), { ok: true, message: m.LIBRARY_REMOVED_MESSAGE });
  assert.equal(m.LIBRARY_REMOVED_MESSAGE, "문서함에서 뺐어요. 채팅 사진은 그대로예요");
  const gone = await m.removeFromLibrary(GOOD, {
    remove: async () => {
      throw Object.assign(new Error("x"), { status: 409, code: "not_in_library" });
    },
  });
  assert.deepEqual(gone, { ok: true, message: m.LIBRARY_REMOVED_MESSAGE });
  const failed = await m.removeFromLibrary(GOOD, {
    remove: async () => {
      throw Object.assign(new Error("x"), { code: "network_error" });
    },
  });
  assert.equal(failed.ok, false);
  assert.match(failed.message, /연결/);
  const noId = await m.removeFromLibrary({ url: "/x" }, { remove: async () => assert.fail("id 없으면 호출하지 않는다") });
  assert.equal(noId.ok, false);
  assert.equal(noId.message, m.LIBRARY_REMOVE_FAIL_MESSAGE);
});

test("두 번 눌러 빼기: 처음은 확인 단계, 확인 단계에서 다시 누르면 요청, 진행 중·뺀 뒤에는 무시", async () => {
  const { nextRemoveStep, removeLabel, LIBRARY_REMOVE_LABEL, LIBRARY_REMOVE_CONFIRM_LABEL, LIBRARY_REMOVING_LABEL, LIBRARY_REMOVED_LABEL } = await import(MOD);
  assert.equal(nextRemoveStep({}), "confirm");
  assert.equal(nextRemoveStep({ confirming: true }), "remove");
  assert.equal(nextRemoveStep({ removing: true }), "ignore");
  assert.equal(nextRemoveStep({ removed: true }), "ignore");
  assert.equal(removeLabel({}), LIBRARY_REMOVE_LABEL);
  assert.equal(removeLabel({ confirming: true }), LIBRARY_REMOVE_CONFIRM_LABEL);
  assert.equal(removeLabel({ removing: true }), LIBRARY_REMOVING_LABEL);
  assert.equal(removeLabel({ removed: true }), LIBRARY_REMOVED_LABEL);
  assert.equal(LIBRARY_REMOVE_LABEL, "문서함에서 빼기");
});

test("화면 배선: 문서함에 있는 사진에만 '문서함에서 빼기'(사진 보기·앨범), 채팅방은 가족 전체방 사진에만 넘긴다", () => {
  const photo = src("components/PhotoViewer.js");
  assert.match(photo, /onRemoveFromLibrary/);
  assert.match(photo, /removeLabel\(removeState\)/);
  const bubble = src("components/MessageBubble.js");
  assert.match(bubble, /onRemoveFromLibrary=\{onRemoveFromLibrary && attachment\.in_library \? removeLibrary : undefined\}/);
  assert.match(bubble, /if \(!photo\.inLibrary\) return \[\];/); // 앨범: 문서함에 없는 사진에는 버튼이 없다
  assert.match(bubble, /nextRemoveStep/);
  const room = src("screens/ChatRoomScreen.js");
  assert.match(room, /onRemoveFromLibrary=\{canSaveToLibrary\(\{ direct, attachment: item\.message\.attachment \}\) \? removeFromLibrary : undefined\}/);
});
