// 테스트 동의서: 동의가 필요한 사용자를 가려내는지 시험한다: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { CONSENT_VERSION } from "../src/features/consent/consentCopy.js";
import { declineForNow, needsTesterConsent } from "../src/features/consent/consentState.js";

test("동의한 적 없는 사용자는 동의 화면을 본다", () => {
  assert.equal(needsTesterConsent({ id: "u1", tester_consent_version: null }), true);
});

test("현재 버전에 동의한 사용자는 건너뛴다", () => {
  assert.equal(needsTesterConsent({ id: "u2", tester_consent_version: CONSENT_VERSION }), false);
});

test("예전 버전에만 동의했으면 다시 묻는다", () => {
  assert.equal(needsTesterConsent({ id: "u3", tester_consent_version: "v0.0" }), true);
});

test("이번에 거부한 사용자는 다시 묻지 않는다", () => {
  declineForNow("u4");
  assert.equal(needsTesterConsent({ id: "u4", tester_consent_version: null }), false);
});

test("사용자 정보가 없으면 묻지 않는다", () => {
  assert.equal(needsTesterConsent(null), false);
  assert.equal(needsTesterConsent({}), false);
});
