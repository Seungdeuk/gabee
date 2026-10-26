// 순수 로직 시험(Node 내장 test runner): npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { digitsOnly, formatClock, parseCode } from "../src/features/auth/code.js";
import { errorMessage, formatWait } from "../src/features/auth/messages.js";
import { extractToken, scrubTokenFromBrowserUrl } from "../src/features/auth/tokenLink.js";
import { checkEmail, checkLoginId, checkName, checkPassword, normalizeLoginId } from "../src/features/auth/validation.js";
import { createTokenStore } from "../src/shared/auth/tokenStore.js";

test("아이디 검사: 서버 규칙과 같다", () => {
  assert.equal(checkLoginId("jimin_kim"), "");
  assert.equal(checkLoginId("  Jimin_Kim "), ""); // 공백·대문자는 정규화된다
  for (const bad of ["abc", "a".repeat(33), "1abcde", "ji min", "지민아이디", "jimin-kim", "admin", "ROOT"]) {
    assert.notEqual(checkLoginId(bad), "", bad);
  }
  assert.equal(normalizeLoginId(" AbC_1 "), "abc_1");
});

test("이메일 검사", () => {
  assert.equal(checkEmail(" A.B+c@Sub.Example.com "), "");
  for (const bad of ["nope", "a@b", "a b@example.com", "a@@example.com", "a..b@example.com", "a@example..com", ""]) {
    assert.notEqual(checkEmail(bad), "", bad);
  }
});

test("비밀번호 검사: 길이·문자와 숫자·아이디 포함 금지", () => {
  assert.equal(checkPassword("Sunny-day-2026", "jimin_kim", "j@example.com"), "");
  assert.equal(checkPassword("비밀번호-가나다-12"), ""); // 한글 비밀번호도 문자로 인정
  for (const bad of ["Short1", "onlyletterspassword", "12345678901", "x1".repeat(65)]) {
    assert.notEqual(checkPassword(bad), "", bad);
  }
  assert.notEqual(checkPassword("Jimin_Kim-2026", "jimin_kim", ""), "");
  assert.notEqual(checkPassword("JIMIN-pass-1", "other_id", "jimin@example.com"), "");
});

test("이름 검사", () => {
  assert.equal(checkName(" 김  지민 "), "");
  assert.notEqual(checkName("   "), "");
  assert.notEqual(checkName("가".repeat(41)), "");
});

test("메일 링크/코드에서 토큰 꺼내기", () => {
  const token = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abc";
  assert.equal(extractToken(token), token);
  assert.equal(extractToken(`  ${token}\n`), token);
  assert.equal(extractToken(`gabee://verify-email?token=${token}`), token);
  assert.equal(extractToken(`gabee://reset-password?foo=1&token=${token}&x=2`), token);
  for (const bad of ["", "   ", null, undefined, "short", "has space inside the code value 12345", "gabee://verify-email", "token=%%%"]) {
    assert.equal(extractToken(bad), "", String(bad));
  }
});

test("오류 문구: 서버 코드를 사용자 문장으로, 토큰/비밀번호는 넣지 않는다", () => {
  assert.match(errorMessage({ code: "invalid_credentials" }), /아이디 또는 비밀번호/);
  assert.match(errorMessage({ code: "verification_expired" }), /만료/);
  assert.match(errorMessage({ code: "reset_token_used" }), /이미 사용/);
  assert.match(errorMessage({ code: "too_many_requests", retryAfter: 45 }), /45초/);
  assert.match(errorMessage({ code: "too_many_requests", retryAfter: 150 }), /3분/);
  assert.equal(errorMessage({ code: "something_new", message: "서버 문구" }), "서버 문구");
  assert.equal(errorMessage(null), "");
  assert.equal(formatWait(59), "59초");
});

test("토큰 보관소: 저장·복원·삭제, 저장소 오류에도 앱은 계속 동작", async () => {
  const data = new Map();
  const backend = {
    getItemAsync: async (k) => data.get(k) ?? null,
    setItemAsync: async (k, v) => void data.set(k, v),
    deleteItemAsync: async (k) => void data.delete(k),
  };
  const store = createTokenStore(backend);
  assert.equal(await store.load(), "");
  await store.save("refresh-1");
  assert.equal(await store.load(), "refresh-1");
  assert.equal(await createTokenStore(backend).load(), "refresh-1"); // 앱을 다시 켠 것처럼 새 객체로 복원
  await store.clear();
  assert.equal(await store.load(), "");

  const broken = createTokenStore({
    getItemAsync: async () => {
      throw new Error("keystore");
    },
    setItemAsync: async () => {
      throw new Error("keystore");
    },
    deleteItemAsync: async () => {
      throw new Error("keystore");
    },
  });
  await broken.save("memory-only"); // 던지지 않는다
  assert.equal(await broken.load(), "memory-only");
  await broken.clear();

  const web = createTokenStore(null); // 보안 저장소가 없는 환경: 이번 실행 동안만 메모리
  await web.save("w");
  assert.equal(await web.load(), "w");
});

test("웹 주소창의 ?token= 을 새 기록 항목 없이 지운다(다른 쿼리는 유지)", () => {
  const calls = [];
  const win = {
    location: { href: "https://app.example/verify-email?sent=1&token=SECRETSECRETSECRET1234#top" },
    history: { state: { k: 1 }, replaceState: (...args) => calls.push(args) },
  };
  assert.equal(scrubTokenFromBrowserUrl(win), true);
  assert.deepEqual(calls, [[{ k: 1 }, "", "/verify-email?sent=1#top"]]);
  assert.equal(JSON.stringify(calls).includes("SECRET"), false);
  // 토큰이 없거나 브라우저가 아니면(네이티브) 아무것도 하지 않는다
  assert.equal(scrubTokenFromBrowserUrl({ location: { href: "https://app.example/verify-email" }, history: { replaceState: () => assert.fail("호출되면 안 돼요") } }), false);
  assert.equal(scrubTokenFromBrowserUrl(undefined), false);
  assert.equal(scrubTokenFromBrowserUrl({}), false);
});

test("인증번호: 숫자만 6자리로, 6자리가 아니면 비어 있다", () => {
  assert.equal(digitsOnly(" 482-913 "), "482913");
  assert.equal(digitsOnly("4829137"), "482913"); // 붙여 넣기로 넘쳐도 6자리까지
  assert.equal(digitsOnly("abc"), "");
  assert.equal(digitsOnly(null), "");
  assert.equal(parseCode("482 913"), "482913");
  assert.equal(parseCode("48291"), "");
  assert.equal(parseCode(undefined), "");
});

test("남은 시간 표시: 02:48 형식, 음수는 00:00", () => {
  assert.equal(formatClock(168), "02:48");
  assert.equal(formatClock(180), "03:00");
  assert.equal(formatClock(9), "00:09");
  assert.equal(formatClock(-5), "00:00");
});

test("인증번호 오류 문구", () => {
  assert.match(errorMessage({ code: "verification_code_invalid" }), /인증번호가 맞지 않아요/);
  assert.match(errorMessage({ code: "verification_code_locked" }), /다시 받아/);
  assert.match(errorMessage({ code: "reset_code_invalid" }), /만료/);
  assert.match(errorMessage({ code: "invalid_role_detail" }), /40자/);
});

test("이메일 선택 칸: 비어 있으면 통과, 적었다면 형식을 본다", async () => {
  const { checkOptionalEmail } = await import("../src/features/auth/validation.js");
  assert.equal(checkOptionalEmail(""), "");
  assert.equal(checkOptionalEmail("   "), "");
  assert.equal(checkOptionalEmail("jimin@example.com"), "");
  assert.notEqual(checkOptionalEmail("nope"), "");
});

test("회원가입 요청: 이메일이 비어 있으면 본문에서 뺀다", async () => {
  const calls = [];
  const realFetch = globalThis.fetch;
  process.env.EXPO_PUBLIC_API_URL = "http://api.test";
  globalThis.fetch = async (url, init = {}) => {
    calls.push(JSON.parse(init.body));
    return new Response(JSON.stringify({ user: {} }), { status: 201, headers: { "Content-Type": "application/json" } });
  };
  try {
    const { signupAccount } = await import("../src/features/auth/api.js");
    await signupAccount({ loginId: "Jimin_Kim", password: "Sunny-day-2026", email: "  ", name: "지민" });
    await signupAccount({ loginId: "jimin2", password: "Sunny-day-2026", email: " A@B.com ", name: "지민", role: "other", roleDetail: "이모" });
  } finally {
    globalThis.fetch = realFetch;
  }
  assert.equal("email" in calls[0], false);
  assert.equal(calls[0].login_id, "jimin_kim");
  assert.equal(calls[1].email, "a@b.com");
  assert.equal(calls[1].role_detail, "이모");
});
