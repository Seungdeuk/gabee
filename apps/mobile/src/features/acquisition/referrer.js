// 플레이 스토어 설치 꼬리표(install referrer)에서 유입 경로 값만 꺼낸다 — docs/requirements/acquisition.md
// 꼬리표 원문에는 광고 클릭 번호(gclid) 같은 다른 값이 섞일 수 있어서 utm 세 값만 쓴다.

const TAG = /^[a-z0-9_-]{1,40}$/; // 서버 규칙과 같다(영어 소문자·숫자·_·-, 40자)

/**
 * 꼬리표 하나를 서버 규칙에 맞게 다듬는다. 맞지 않으면 버린다.
 * @param {URLSearchParams} params 꼬리표를 나눈 값
 * @param {string} key utm 이름(utm_source 등)
 * @returns {string | undefined} 규칙에 맞는 값, 없거나 맞지 않으면 undefined
 */
function pick(params, key) {
  const value = (params.get(key) || "").trim().toLowerCase();
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
