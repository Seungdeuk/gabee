import assert from "node:assert/strict";
import test from "node:test";

import { createKakaoReturnBus } from "../src/features/auth/kakaoReturn.js";
import { acceptKakaoReturn, KAKAO_APP_RETURN_URL, KAKAO_RELAY_PATH, kakaoRedirectUri } from "../src/features/auth/social.js";

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

// ── 카카오톡 앱으로 로그인하고 돌아온 경우: 인증 창 결과와 별개로 gabee://kakao?code=… 가 라우트로 들어온다 ──
const NOW = 1_000_000;
const ok = { params: { code: "C1", state: "S1" }, expectedState: "S1", pendingUntil: NOW + 5000, now: NOW, handledCode: null };

test("카카오톡 복귀: 진행 중인 로그인의 state 와 같으면 코드를 받는다", () => {
  assert.deepEqual(acceptKakaoReturn(ok), { code: "C1" });
});

test("카카오톡 복귀: state 가 다르거나 없으면 받지 않는다(다른 곳에서 온 주소 방지)", () => {
  assert.equal(acceptKakaoReturn({ ...ok, params: { code: "C1", state: "X" } }), null);
  assert.equal(acceptKakaoReturn({ ...ok, params: { code: "C1" } }), null);
  assert.equal(acceptKakaoReturn({ ...ok, expectedState: undefined }), null);
});

test("카카오톡 복귀: 로그인을 시작하지 않았거나 기다리는 시간이 지나면 받지 않는다", () => {
  assert.equal(acceptKakaoReturn({ ...ok, pendingUntil: 0 }), null);
  assert.equal(acceptKakaoReturn({ ...ok, pendingUntil: NOW }), null); // 끝 시각은 포함하지 않음
});

test("카카오톡 복귀: 이미 처리한 코드는 다시 받지 않는다(정상 경로와 중복 교환 방지)", () => {
  assert.equal(acceptKakaoReturn({ ...ok, handledCode: "C1" }), null);
  assert.deepEqual(acceptKakaoReturn({ ...ok, handledCode: "OLD" }), { code: "C1" });
});

test("카카오톡 복귀: 코드가 없거나 문자열이 아니면 받지 않는다", () => {
  assert.equal(acceptKakaoReturn({ ...ok, params: { state: "S1" } }), null);
  assert.equal(acceptKakaoReturn({ ...ok, params: { code: "", state: "S1" } }), null);
  assert.equal(acceptKakaoReturn({ ...ok, params: { code: ["a"], state: "S1" } }), null);
});

test("카카오톡 복귀: 카카오가 error 를 돌려주면 실패로 알린다(state 가 맞을 때만)", () => {
  assert.deepEqual(acceptKakaoReturn({ ...ok, params: { error: "access_denied", state: "S1" } }), { error: true });
  assert.equal(acceptKakaoReturn({ ...ok, params: { error: "access_denied", state: "X" } }), null);
});

test("복귀 알림 통: 구독한 쪽에 전달되고, 해제하면 더 오지 않는다", () => {
  const bus = createKakaoReturnBus();
  const got = [];
  const off = bus.subscribe((p) => got.push(p));
  bus.publish({ code: "A" });
  off();
  bus.publish({ code: "B" });
  assert.deepEqual(got, [{ code: "A" }]);
});

test("복귀 알림 통: 한 구독자가 오류를 내도 나머지는 받는다", () => {
  const bus = createKakaoReturnBus();
  const got = [];
  bus.subscribe(() => {
    throw new Error("boom");
  });
  bus.subscribe((p) => got.push(p));
  bus.publish({ code: "A" });
  assert.deepEqual(got, [{ code: "A" }]);
});
