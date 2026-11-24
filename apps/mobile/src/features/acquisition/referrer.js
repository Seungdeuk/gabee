// 플레이 스토어 설치 꼬리표(install referrer)에서 유입 경로 값만 꺼낸다 — docs/requirements/acquisition.md
// 꼬리표 원문에는 광고 클릭 번호(gclid) 같은 다른 값이 섞일 수 있어서 utm 세 값만 쓴다.

const TAG = /^[a-z0-9_-]{1,40}$/; // 서버 규칙과 같다(영어 소문자·숫자·_·-, 40자)

// 메타(페이스북·인스타그램) 광고는 utm_source 에 "apps.facebook.com" 같은 주소를 넣는다.
// 서버 schemas.py 의 ALIASES 와 같은 표다.
const ALIASES = {
  "apps.facebook.com": "facebook",
  "m.facebook.com": "facebook",
  "l.facebook.com": "facebook",
  "lm.facebook.com": "facebook",
  "facebook.com": "facebook",
  fb: "facebook",
  facebook: "facebook",
  "instagram.com": "instagram",
  "l.instagram.com": "instagram",
  ig: "instagram",
  instagram: "instagram",
};

/**
 * utm 값을 서버와 같은 방식으로 다듬는다: 공백 제거·소문자, 알려진 별칭은 채널 이름으로,
 * 허용되지 않는 글자(점 등)는 "-" 로 바꾸고 겹친 "-" 는 하나로, 앞뒤 "-" 는 빼고 40자까지.
 * @param {string} raw 꼬리표에서 꺼낸 값
 * @returns {string} 다듬은 값(빈 문자열일 수 있다)
 */
export function normalizeTag(raw) {
  const value = String(raw || "").trim().toLowerCase();
  if (Object.prototype.hasOwnProperty.call(ALIASES, value)) return ALIASES[value];
  return value
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40)
    .replace(/-+$/, "");
}

/**
 * 꼬리표 하나를 서버 규칙에 맞게 다듬는다. 다듬어도 맞지 않으면 버린다.
 * @param {URLSearchParams} params 꼬리표를 나눈 값
 * @param {string} key utm 이름(utm_source 등)
 * @returns {string | undefined} 규칙에 맞는 값, 없거나 맞지 않으면 undefined
 */
function pick(params, key) {
  const value = normalizeTag(params.get(key));
  return TAG.test(value) ? value : undefined;
}

/**
 * 설치 꼬리표에서 utm_source·utm_medium·utm_campaign 만 꺼낸다.
 * @param {string | null | undefined} raw 예: "utm_source=youtube&utm_medium=video&utm_campaign=launch"
 * @returns {{source: string, medium?: string, campaign?: string} | null} source 가 없으면 null
 */
export function parseReferrer(raw) {
  if (!raw) return null;
  const params = new URLSearchParams(String(raw).replace(/^\?/, ""));
  const source = pick(params, "utm_source");
  if (!source) return null;
  const tags = { source };
  const medium = pick(params, "utm_medium");
  const campaign = pick(params, "utm_campaign");
  if (medium) tags.medium = medium;
  if (campaign) tags.campaign = campaign;
  return tags;
}
