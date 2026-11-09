// 채팅 사진 -> 가족 문서함 "문서로 저장"(버튼 노출 규칙, API 호출, 상태 문구, 화면 배선)을 시험한다: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, test } from "node:test";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

const MOD = "../src/features/family-chat/saveToLibrary.js";
const GOOD = { id: "a1b2c3", url: "/family-chat/photos/a1b2c3" };
const src = (p) => readFileSync(new URL(`../src/features/family-chat/${p}`, import.meta.url), "utf8");
const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const realFetch = globalThis.fetch;
beforeEach(() => {
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("canSaveToLibrary: 가족 전체방의 사진 메시지에만 버튼을 보인다(1:1 방·사진 없음·id 없음은 아님)", async () => {
  const { canSaveToLibrary } = await import(MOD);
  assert.equal(canSaveToLibrary({ direct: false, attachment: GOOD }), true);
  assert.equal(canSaveToLibrary({ direct: true, attachment: GOOD }), false);
  assert.equal(canSaveToLibrary({ direct: false, attachment: null }), false);
  assert.equal(canSaveToLibrary({ direct: false, attachment: { url: "/family-chat/photos/x" } }), false);
  assert.equal(canSaveToLibrary({ direct: false, attachment: { id: "x", url: "" } }), false);
});

test("API savePhotoToLibrary: POST /family-chat/photos/{id}/library, 본문 없음, 응답 status 를 돌려준다", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: init?.method, body: init?.body });
    return json(200, { status: "queued" });
  };
  const api = await import("../src/features/family-chat/api.js");
  assert.deepEqual(await api.savePhotoToLibrary("a1 b/2"), { status: "queued" });
  assert.equal(calls[0].url, "http://api.test/family-chat/photos/a1%20b%2F2/library");
  assert.equal(calls[0].method, "POST");
  assert.ok(calls[0].body == null);
});

test("saveToLibrary: queued·already 는 문구와 함께 ok, 오류는 문구로 바꿔 던지지 않는다", async () => {
  const m = await import(MOD);
  assert.deepEqual(await m.saveToLibrary(GOOD, { save: async () => ({ status: "queued" }) }), { ok: true, message: m.LIBRARY_QUEUED_MESSAGE });
  assert.deepEqual(await m.saveToLibrary(GOOD, { save: async () => ({ status: "already" }) }), { ok: true, message: m.LIBRARY_ALREADY_MESSAGE });
  assert.equal(m.LIBRARY_QUEUED_MESSAGE, "문서함에 저장을 시작했어요. 글을 읽는 데 시간이 걸리고, 처방전·신분증 같은 민감한 문서는 저장하지 않아요");
  assert.equal(m.LIBRARY_DONE_LABEL, "저장 요청했어요"); // 서버가 읽은 뒤 민감 문서 등을 거를 수 있어 "저장했어요"라고 단정하지 않는다
  assert.equal(m.LIBRARY_ALREADY_MESSAGE, "이미 가족 문서함에 있어요");
  const failed = await m.saveToLibrary(GOOD, {
    save: async () => {
      throw Object.assign(new Error("x"), { code: "network_error" });
    },
  });
  assert.equal(failed.ok, false);
  assert.match(failed.message, /연결/);
  const noId = await m.saveToLibrary({ url: "/x" }, { save: async () => assert.fail("id 없으면 호출하지 않는다") });
  assert.equal(noId.ok, false);
  assert.ok(noId.message);
});

test("화면 배선: 사진 보기·앨범 뷰어·말풍선·채팅방이 '문서로 저장'을 같은 방식으로 이어 받는다", () => {
  const photo = src("components/PhotoViewer.js");
  assert.match(photo, /onSaveToLibrary/);
  assert.match(photo, /LIBRARY_BUTTON_LABEL/);
  assert.match(photo, /저장하는 중/);
  const album = src("components/AlbumViewer.js");
  assert.match(album, /onSaveToLibrary/);
  assert.match(album, /libraryOf/);
  const bubble = src("components/MessageBubble.js");
  assert.match(bubble, /onSaveToLibrary/);
  assert.match(bubble, /albumLibraries/);
  const room = src("screens/ChatRoomScreen.js");
  assert.match(room, /canSaveToLibrary\(\{ direct, attachment: item\.message\.attachment \}\) \? savePhotoToLibraryDoc : undefined/);
});
