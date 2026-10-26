// 프로필 사진: 업로드·삭제 API 호출 모양, 오류 문구, 주소·캐시 순수 로직: npm test
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "secret-dev-token";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

const { uploadMyPhoto, deleteMyPhoto } = await import("../src/features/family-group/api.js");
const { MAX_PHOTO_BYTES, isPhotoTooLarge, photoErrorMessage, photoFileName, photoMimeType } = await import("../src/features/family-group/photo.js");
const { createPhotoCache, holdPhoto, photoOwner, photoPath } = await import("../src/shared/photoCache.js");

function capture(response) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return response();
  };
  return calls;
}
const ok = (body) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

test("업로드: POST /family-group/me/photo, FormData 'file', Content-Type 은 직접 지정하지 않는다", async () => {
  const calls = capture(() => ok({ photo_url: "/family-group/users/u1/photo?v=5", photo_updated_at: null }));
  const blob = new Blob(["x"], { type: "image/png" });
  const out = await uploadMyPhoto({ uri: "blob:http://x/1", file: blob, fileName: "me.png", mimeType: "image/png" });
  assert.equal(out.photo_url, "/family-group/users/u1/photo?v=5");
  const [{ url, init }] = calls;
  assert.equal(url, "http://api.test/family-group/me/photo");
  assert.equal(init.method, "POST");
  assert.ok(init.body instanceof FormData);
  assert.equal(init.body.get("file").name, "me.png");
  assert.equal(Object.keys(init.headers).some((k) => k.toLowerCase() === "content-type"), false);
  assert.equal(init.headers["X-Gyeot-Token"], "secret-dev-token"); // 인증은 헤더로만
  assert.equal(url.includes("secret-dev-token"), false);
});

test("업로드(네이티브): {uri, name, type} 로 보낸다", async () => {
  const calls = capture(() => ok({ photo_url: null, photo_updated_at: null }));
  await uploadMyPhoto({ uri: "file:///cache/p.jpg", fileName: null, mimeType: undefined });
  const part = calls[0].init.body.get("file");
  // Node 의 FormData 는 객체를 문자열로 바꾸지만, 네이티브 런타임은 {uri,name,type} 을 읽는다. 여기서는 호출이 일어난 것만 확인한다.
  assert.ok(part !== null);
  assert.equal(calls[0].init.method, "POST");
});

test("삭제: DELETE /family-group/me/photo, 본문 없음, 204 는 null", async () => {
  const calls = capture(() => new Response(null, { status: 204 }));
  assert.equal(await deleteMyPhoto(), null);
  assert.equal(calls[0].url, "http://api.test/family-group/me/photo");
  assert.equal(calls[0].init.method, "DELETE");
  assert.equal(calls[0].init.body, undefined);
});

test("오류 코드 → 문구", () => {
  assert.match(photoErrorMessage({ code: "photo_too_large" }), /너무 커요/);
  assert.match(photoErrorMessage({ code: "invalid_image" }), /사진 파일이 아니거나 너무 커요/);
  assert.equal(photoErrorMessage({ code: "invalid_image", message: "사진 화소가 너무 많아요" }), "사진 화소가 너무 많아요");
  assert.match(photoErrorMessage({ code: "photo_busy" }), /잠시 후/);
  assert.match(photoErrorMessage({ code: "too_many_uploads" }), /너무 자주/);
  assert.match(photoErrorMessage({ code: "too_many_uploads", retryAfter: 90 }), /2분 뒤/);
  assert.match(photoErrorMessage({ code: "error", status: 413 }), /너무 커요/);
  assert.match(photoErrorMessage({ code: "network_error" }), /연결하지 못했어요/);
  assert.equal(photoErrorMessage(null), "");
});

test("파일 형식·이름·크기 판단", () => {
  assert.equal(photoMimeType({ mimeType: "image/webp" }), "image/webp");
  assert.equal(photoMimeType({ fileName: "a.PNG" }), "image/png");
  assert.equal(photoMimeType({ uri: "file:///x/y.jpeg?z=1" }), "image/jpeg");
  assert.equal(photoMimeType({ uri: "file:///x/y" }), "image/jpeg");
  assert.equal(photoFileName({ fileName: "me.jpg" }), "me.jpg");
  assert.equal(photoFileName({ mimeType: "image/png" }), "profile.png");
  assert.equal(isPhotoTooLarge({ fileSize: MAX_PHOTO_BYTES + 1 }), true);
  assert.equal(isPhotoTooLarge({ fileSize: MAX_PHOTO_BYTES }), false);
  assert.equal(isPhotoTooLarge({}), false);
});

test("photoPath: 서버가 만든 경로만 받는다(토큰이 나갈 주소 제한)", () => {
  assert.equal(photoPath("/family-group/users/u-1/photo?v=123"), "/family-group/users/u-1/photo?v=123");
  assert.equal(photoPath("/family-group/users/u-1/photo"), "/family-group/users/u-1/photo");
  for (const bad of [null, undefined, "", "http://evil.test/x.jpg", "//evil.test/x", "/other/path", "/family-group/users/a/b/photo?v=1", "/family-group/users/u/photo?v=x"]) {
    assert.equal(photoPath(bad), null, String(bad));
  }
  assert.equal(photoOwner("/family-group/users/u1/photo?v=9"), "/family-group/users/u1/photo");
});

test("캐시: 같은 키는 한 번만 받고, 버전이 바뀌면 새로 받는다", async () => {
  const loads = [];
  const revoked = [];
  const cache = createPhotoCache({
    load: async (k) => (loads.push(k), `data:${k}`),
    create: (d) => `blob:${d}`,
    revoke: (u) => revoked.push(u),
  });
  const a = "/family-group/users/u1/photo?v=1";
  const [x, y] = await Promise.all([cache.acquire(a), cache.acquire(a)]);
  assert.equal(x, y);
  assert.deepEqual(loads, [a]);
  cache.release(a);
  cache.release(a); // 이제 안 쓴다
  const b = "/family-group/users/u1/photo?v=2";
  await cache.acquire(b);
  assert.deepEqual(loads, [a, b]);
  assert.deepEqual(revoked, [`blob:data:${a}`]); // 안 쓰는 옛 버전은 해제
  assert.equal(cache.size, 1);
});

test("캐시: 쓰는 중인 사진은 해제하지 않고, 실패는 기억하지 않는다", async () => {
  const revoked = [];
  let fail = true;
  const cache = createPhotoCache({
    load: async (k) => {
      if (fail) throw new Error("no");
      return k;
    },
    create: (d) => `blob:${d}`,
    revoke: (u) => revoked.push(u),
    maxIdle: 1,
  });
  await assert.rejects(cache.acquire("/family-group/users/a/photo?v=1"));
  assert.equal(cache.size, 0);
  fail = false;
  await cache.acquire("/family-group/users/a/photo?v=1");
  await cache.acquire("/family-group/users/b/photo?v=1");
  await cache.acquire("/family-group/users/c/photo?v=1");
  cache.release("/family-group/users/b/photo?v=1");
  cache.release("/family-group/users/c/photo?v=1"); // 안 쓰는 것 2개 > maxIdle 1 → 오래된 b 해제
  assert.deepEqual(revoked, ["blob:/family-group/users/b/photo?v=1"]);
  assert.equal(cache.size, 2); // a(사용 중), c
  cache.clear();
  assert.equal(cache.size, 0);
});

const tick = () => new Promise((r) => setTimeout(r, 0));

test("holdPhoto: acquire 가 실패하면 release 하지 않아 다른 곳의 새 항목 참조를 줄이지 않는다", async () => {
  const key = "/family-group/users/a/photo?v=1";
  const revoked = [];
  let fail = true;
  const cache = createPhotoCache({
    load: async (k) => {
      if (fail) throw new Error("no");
      return k;
    },
    create: (d) => `blob:${d}`,
    revoke: (u) => revoked.push(u),
    maxIdle: 0, // 참조가 0 이 되는 즉시 버려서 잘못된 release 를 드러낸다
  });
  let failed = false;
  const dispose = holdPhoto(cache, key, { onReady: () => assert.fail("ready"), onFail: () => (failed = true) });
  await tick();
  assert.equal(failed, true);
  fail = false;
  await cache.acquire(key); // 다른 컴포넌트가 만든 새 항목(참조 1)
  dispose(); // 실패한 쪽의 정리: release 하면 새 항목이 버려진다
  assert.deepEqual(revoked, []);
  assert.equal(cache.size, 1);
});

test("holdPhoto: 받는 도중 정리되면 받기가 끝나는 즉시 참조를 푼다", async () => {
  const released = [];
  const cache = { acquire: async (k) => `blob:${k}`, release: (k) => released.push(k) };
  const dispose = holdPhoto(cache, "k", { onReady: () => assert.fail("ready"), onFail: () => assert.fail("fail") });
  dispose();
  await tick();
  assert.deepEqual(released, ["k"]);
  dispose();
  assert.deepEqual(released, ["k"]);
});

test("holdPhoto: 성공 후 정리하면 한 번만 release", async () => {
  const released = [];
  let url = "";
  const cache = { acquire: async (k) => `blob:${k}`, release: (k) => released.push(k) };
  const dispose = holdPhoto(cache, "k", { onReady: (u) => (url = u), onFail: () => {} });
  await tick();
  assert.equal(url, "blob:k");
  dispose();
  dispose();
  assert.deepEqual(released, ["k"]);
});
