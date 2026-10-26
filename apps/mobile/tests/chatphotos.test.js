// 채팅 사진 보내기/보기(앱): 미리보기, 경로 검증, 업로드 요청 모양, 오류 문구, 표시 크기: npm test
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "secret-dev-token";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

const { previewText, photoSendErrorMessage, roomErrorMessage } = await import("../src/features/family-chat/chatUtils.js");
const { buildRoomRows, roomA11yLabel } = await import("../src/features/family-chat/listUtils.js");
const { sendPhoto } = await import("../src/features/family-chat/api.js");
const { MAX_CHAT_PHOTO_BYTES, chatPhotoFileName, chatPhotoMimeType, fitSize, isChatPhotoTooLarge } = await import("../src/features/family-chat/photo.js");
const { createPhotoCache, photoOwner, photoPath } = await import("../src/shared/photoCache.js");

const att = { id: "a1", kind: "image", url: "/family-chat/photos/a1", thumb_url: "/family-chat/photos/a1?size=thumb", width: 800, height: 600 };
const photoMsg = (user_id) => ({ id: 5, user_id, user_name: "x", text: "", created_at: "2026-10-23T06:00:00Z", attachment: att });

function capture(response) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return response();
  };
  return calls;
}
const ok = (body) => new Response(JSON.stringify(body), { status: 201, headers: { "Content-Type": "application/json" } });

test("미리보기: 사진 메시지(글자 없음)는 '사진', 내 것은 '나: 사진'", () => {
  assert.equal(previewText(photoMsg("mom"), "me"), "사진");
  assert.equal(previewText(photoMsg("me"), "me"), "나: 사진");
  assert.equal(previewText({ ...photoMsg("mom"), attachment: null, text: "안녕" }, "me"), "안녕");
  assert.equal(previewText({ ...photoMsg("mom"), text: "  이거 봐 " }, "me"), "이거 봐"); // 글자가 있으면 글자
  assert.equal(previewText(null), "아직 대화가 없어요");
});

test("방 목록 행: 마지막 메시지가 사진이면 '사진' / '나: 사진'", () => {
  const group = { name: "우리 가족", my_id: "me", members: [{ id: "me", name: "지민" }, { id: "mom", name: "엄마" }] };
  const rooms = [
    { id: "f", kind: "family", peer_user_id: null, last_message: photoMsg("mom"), unread: 0 },
    { id: "d", kind: "direct", peer_user_id: "mom", last_message: photoMsg("me"), unread: 1 },
  ];
  const rows = buildRoomRows(rooms, group, previewText, () => "오후 3:00");
  assert.equal(rows[0].last, "사진");
  assert.equal(rows[1].last, "나: 사진");
  assert.equal(roomA11yLabel(rows[1].last, 1, rows[1].a11yTitle), "엄마님과 1:1 대화, 안 읽은 메시지 1개, 마지막 메시지 나: 사진");
});

test("사진 경로: 서버가 준 채팅 사진 경로만 받는다", () => {
  assert.equal(photoPath("/family-chat/photos/a1"), "/family-chat/photos/a1");
  assert.equal(photoPath("/family-chat/photos/a1?size=thumb"), "/family-chat/photos/a1?size=thumb");
  assert.equal(photoPath("/family-chat/photos/a1?size=full"), "/family-chat/photos/a1?size=full");
  assert.equal(photoPath("/family-chat/photos/3f2a-9b_c"), "/family-chat/photos/3f2a-9b_c");
  // 기존 프로필 사진 경로는 그대로 허용
  assert.equal(photoPath("/family-group/users/u-1/photo?v=123"), "/family-group/users/u-1/photo?v=123");
  const bad = [
    "http://evil.test/family-chat/photos/a1",
    "https://api.test/family-chat/photos/a1",
    "//evil.test/family-chat/photos/a1",
    "/family-chat/photos/",
    "/family-chat/photos",
    "/family-chat/photos/../messages",
    "/family-chat/photos/a1/../../x",
    "/family-chat/photos/a1/extra",
    "/family-chat/photos/a1?size=big",
    "/family-chat/photos/a1?size=thumb&x=1",
    "/family-chat/photos/a1?v=1",
    "/family-chat/photos/a1#frag",
    "/family-chat/photos/a1 ",
    "/family-chat/photos/a%2F1",
    "/family-chat/photos/a1\n",
    "/family-chat/messages",
    "family-chat/photos/a1",
    "//family-chat/photos/a1",
    null,
    undefined,
    42,
    {},
  ];
  for (const b of bad) assert.equal(photoPath(b), null, String(b));
});

test("사진 캐시: 같은 사진의 원본과 썸네일은 서로 밀어내지 않는다, 프로필 사진은 기존대로 버전 교체", async () => {
  assert.equal(photoOwner("/family-chat/photos/a1"), "/family-chat/photos/a1");
  assert.equal(photoOwner("/family-chat/photos/a1?size=thumb"), "/family-chat/photos/a1?size=thumb");
  assert.equal(photoOwner("/family-group/users/u1/photo?v=9"), "/family-group/users/u1/photo");
  const revoked = [];
  const cache = createPhotoCache({ load: async (k) => k, create: (d) => `blob:${d}`, revoke: (u) => revoked.push(u) });
  await cache.acquire("/family-chat/photos/a1?size=thumb");
  cache.release("/family-chat/photos/a1?size=thumb");
  await cache.acquire("/family-chat/photos/a1");
  assert.deepEqual(revoked, []); // 썸네일이 버려지지 않았다
  assert.equal(cache.size, 2);
});

test("sendPhoto(웹): POST /family-chat/photos, FormData file(+room_id), Content-Type 미지정, 토큰은 헤더로만", async () => {
  const calls = capture(() => ok({ id: 9, user_id: "me", user_name: "지민", text: "", created_at: "2026-10-23T06:00:00Z", attachment: att }));
  const blob = new Blob(["x"], { type: "image/png" });
  const out = await sendPhoto({ uri: "blob:http://x/1", file: blob, fileName: "a.png", mimeType: "image/png" }, "room-1");
  assert.equal(out.attachment.id, "a1");
  const [{ url, init }] = calls;
  assert.equal(url, "http://api.test/family-chat/photos");
  assert.equal(init.method, "POST");
  assert.ok(init.body instanceof FormData);
  assert.equal(init.body.get("file").name, "a.png");
  assert.equal(init.body.get("room_id"), "room-1");
  assert.equal(Object.keys(init.headers).some((k) => k.toLowerCase() === "content-type"), false);
  assert.equal(init.headers["X-Gyeot-Token"], "secret-dev-token");
  assert.equal(url.includes("secret-dev-token"), false);
});

test("sendPhoto: roomId 가 없으면 room_id 를 form 에 넣지 않는다(가족 전체방)", async () => {
  for (const roomId of [undefined, null, ""]) {
    const calls = capture(() => ok({ id: 1, user_id: "me", user_name: "x", text: "", created_at: "2026-10-23T06:00:00Z", attachment: att }));
    await sendPhoto({ uri: "file:///cache/p.jpg", fileName: null, mimeType: undefined }, roomId);
    assert.equal(calls[0].init.body.has("room_id"), false);
    assert.equal(calls[0].init.method, "POST");
  }
});

test("sendPhoto 오류: 서버 오류 코드가 ApiError 로 올라온다", async () => {
  capture(() => new Response(JSON.stringify({ code: "photo_too_large", message: "x" }), { status: 413, headers: { "Content-Type": "application/json" } }));
  await assert.rejects(sendPhoto({ uri: "file:///p.jpg" }, null), (e) => e.status === 413 && e.code === "photo_too_large");
});

test("오류 문구: 사진 오류 코드와 상태를 사용자 문장으로, 그 밖에는 기존 문구", () => {
  assert.match(photoSendErrorMessage({ code: "photo_too_large" }), /너무 커요/);
  assert.match(photoSendErrorMessage({ code: "invalid_image" }), /보낼 수 없어요/);
  assert.match(photoSendErrorMessage({ code: "too_many_uploads" }), /너무 자주/);
  assert.match(photoSendErrorMessage({ code: "photo_busy" }), /요청이 많아요/);
  assert.match(photoSendErrorMessage({ status: 413 }), /너무 커요/);
  assert.match(photoSendErrorMessage({ status: 429 }), /너무 자주/);
  assert.equal(photoSendErrorMessage({ code: "not_found", status: 404 }), "대화방을 찾을 수 없어요");
  assert.equal(photoSendErrorMessage({ code: "network_error" }), roomErrorMessage({ code: "network_error" }));
  assert.equal(photoSendErrorMessage(null), roomErrorMessage(null));
});

test("표시 크기: 원본 비율 유지, 최대 폭·높이 안, 확대 없음", () => {
  assert.deepEqual(fitSize(800, 600, 220, 280), { width: 220, height: 165 });
  assert.deepEqual(fitSize(600, 1200, 220, 280), { width: 140, height: 280 }); // 세로로 긴 사진은 높이가 한도
  assert.deepEqual(fitSize(100, 50, 220, 280), { width: 100, height: 50 }); // 작은 사진은 키우지 않는다
  assert.deepEqual(fitSize(1, 5000, 220, 280), { width: 1, height: 280 });
  for (const [w, h] of [[0, 0], [null, 10], [10, undefined], [-1, 5], [NaN, 5], ["a", "b"]]) {
    assert.deepEqual(fitSize(w, h, 220, 280), { width: 220, height: 220 }, `${w},${h}`); // 모르면 정사각형(점프 방지)
  }
  const d = fitSize(4000, 3000);
  assert.ok(d.width <= 220 && d.height <= 280);
});

test("파일 형식·이름·크기 한도", () => {
  assert.equal(chatPhotoMimeType({ mimeType: "image/webp" }), "image/webp");
  assert.equal(chatPhotoMimeType({ fileName: "a.PNG" }), "image/png");
  assert.equal(chatPhotoMimeType({ uri: "file:///x/y" }), "image/jpeg");
  assert.equal(chatPhotoFileName({ fileName: "a.png" }), "a.png");
  assert.equal(chatPhotoFileName({ mimeType: "image/png" }), "photo.png");
  assert.equal(chatPhotoFileName({}), "photo.jpg");
  assert.equal(MAX_CHAT_PHOTO_BYTES, 8 * 1024 * 1024);
  assert.equal(isChatPhotoTooLarge({ fileSize: MAX_CHAT_PHOTO_BYTES }), false);
  assert.equal(isChatPhotoTooLarge({ fileSize: MAX_CHAT_PHOTO_BYTES + 1 }), true);
  assert.equal(isChatPhotoTooLarge({}), false);
});
