// 메타 SDK 를 켜도 되는 환경인지 시험: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { canUseMeta } from "../src/shared/meta/metaGate.js";

test("Expo Go 에서는 켜지 않는다(앱이 멈추지 않게)", () => {
  assert.equal(canUseMeta({ os: "android", executionEnvironment: "storeClient", metaEnabled: true }), false);
  assert.equal(canUseMeta({ os: "ios", executionEnvironment: "storeClient", metaEnabled: true }), false);
});

test("개발 빌드·스토어 앱에 토큰이 있으면 켠다", () => {
  assert.equal(canUseMeta({ os: "android", executionEnvironment: "bare", metaEnabled: true }), true);
  assert.equal(canUseMeta({ os: "android", executionEnvironment: "standalone", metaEnabled: true }), true);
  assert.equal(canUseMeta({ os: "ios", executionEnvironment: "bare", metaEnabled: true }), true);
});

test("토큰 없는 빌드와 웹에서는 켜지 않는다", () => {
  assert.equal(canUseMeta({ os: "android", executionEnvironment: "bare", metaEnabled: false }), false);
  assert.equal(canUseMeta({ os: "android", executionEnvironment: "bare" }), false);
  assert.equal(canUseMeta({ os: "web", executionEnvironment: "bare", metaEnabled: true }), false);
});
