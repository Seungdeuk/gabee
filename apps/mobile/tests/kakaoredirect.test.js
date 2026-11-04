import assert from "node:assert/strict";
import test from "node:test";

import { KAKAO_APP_RETURN_URL, KAKAO_RELAY_PATH, kakaoRedirectUri } from "../src/features/auth/social.js";

const args = { appReturnUrl: "gabee://kakao", relayUrl: "https://api.gabee.cloud/auth/kakao/callback" };

test("카카오 Redirect URI: 모바일은 서버 https 중계 주소, 웹은 웹 주소", () => {
  assert.equal(kakaoRedirectUri({ ...args, platform: "android" }), args.relayUrl);
  assert.equal(kakaoRedirectUri({ ...args, platform: "ios" }), args.relayUrl);
  assert.equal(kakaoRedirectUri({ platform: "web", appReturnUrl: "http://localhost:8086/kakao", relayUrl: args.relayUrl }), "http://localhost:8086/kakao");
});

test("카카오 중계 경로는 서버 라우트와 같다", () => {
  assert.equal(KAKAO_RELAY_PATH, "/auth/kakao/callback");
});

test("모바일이 돌아오기를 기다리는 앱 주소는 서버 중계가 넘겨 주는 주소와 같다", () => {
  assert.equal(KAKAO_APP_RETURN_URL, "gabee://kakao");
});
