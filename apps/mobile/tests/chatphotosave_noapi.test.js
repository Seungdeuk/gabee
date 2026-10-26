// 서버 주소가 설정되지 않았을 때(임시 데이터 모드) 사진 저장 요청을 만들지 않는지 시험한다: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

process.env.EXPO_PUBLIC_API_URL = "";

test("photoDownloadRequest: 서버 주소가 없으면 던지고 네트워크를 쓰지 않는다", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return new Response("{}");
  };
  const { photoDownloadRequest } = await import("../src/features/family-chat/api.js");
  await assert.rejects(photoDownloadRequest("/family-chat/photos/a1"), /photo_unavailable/);
  assert.equal(calls, 0);
});
