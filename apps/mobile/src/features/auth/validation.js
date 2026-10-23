/**
 * 가입·재설정 입력값 검사. 서버(app/features/family_group/credentials.py)와 같은 규칙이다 — 서버가 최종 판단하고,
 * 여기서는 보내기 전에 빠르게 안내만 한다. 각 함수는 문제가 없으면 "" 를, 있으면 사용자에게 보여줄 문장을 돌려준다.
 */
export const LOGIN_ID_MIN = 4;
export const LOGIN_ID_MAX = 32;
export const PASSWORD_MIN = 8;
export const PASSWORD_MAX = 128;

const RESERVED_LOGIN_IDS = ["admin", "administrator", "root", "system", "support", "gabee", "null", "undefined", "anonymous"];
const EMAIL_RE =
  /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$/;

/** 아이디는 앞뒤 공백을 지우고 소문자로 보낸다(서버도 같은 방식으로 저장한다). */
export const normalizeLoginId = (value) => value.trim().toLowerCase();
export const normalizeEmail = (value) => value.trim().toLowerCase();

/**
 * @param {string} value
 * @returns {string} 오류 문장 또는 ""
 */
export function checkLoginId(value) {
  const id = normalizeLoginId(value);
  if (id.length < LOGIN_ID_MIN || id.length > LOGIN_ID_MAX) return `아이디는 ${LOGIN_ID_MIN}~${LOGIN_ID_MAX}자로 입력해 주세요`;
  if (!/^[a-z][a-z0-9_]*$/.test(id)) return "아이디는 영문 소문자로 시작하고 영문 소문자·숫자·밑줄(_)만 쓸 수 있어요";
  if (RESERVED_LOGIN_IDS.includes(id)) return "사용할 수 없는 아이디예요";
  return "";
}

/** @param {string} value */
export function checkEmail(value) {
  const email = normalizeEmail(value);
  if (email.length > 255 || email.includes("..") || !EMAIL_RE.test(email)) return "이메일 형식이 올바르지 않아요";
  return "";
}

/**
 * @param {string} password
 * @param {string} [loginId] 아이디가 비밀번호에 들어 있으면 안 된다
 * @param {string} [email]
 */
export function checkPassword(password, loginId = "", email = "") {
  if (password.length < PASSWORD_MIN || password.length > PASSWORD_MAX) {
    return `비밀번호는 ${PASSWORD_MIN}~${PASSWORD_MAX}자로 입력해 주세요`;
  }
  if (!/\p{L}/u.test(password) || !/\p{Nd}/u.test(password)) return "비밀번호에는 문자와 숫자가 모두 들어가야 해요";
  const lowered = password.toLowerCase();
  const id = normalizeLoginId(loginId);
  const local = normalizeEmail(email).split("@")[0];
  if ((id && lowered.includes(id)) || (local.length >= 4 && lowered.includes(local))) {
    return "비밀번호에 아이디나 이메일 아이디를 넣을 수 없어요";
  }
  return "";
}

/** @param {string} value */
export function checkName(value) {
  const name = value.trim().split(/\s+/).join(" ");
  return name.length >= 1 && name.length <= 40 ? "" : "이름은 1~40자로 입력해 주세요";
}
