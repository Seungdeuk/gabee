/**
 * 웹 출처 주소에서 보기 좋은 사이트 이름을 뽑는다(앞의 www. 는 뺀다).
 * @param {string} url 페이지 주소
 * @returns {string} 사이트 이름. 주소가 잘못됐으면 빈 문자열
 */
export function webSourceHost(url) {
  const m = /^https?:\/\/([^/?#]+)/i.exec(url ?? "");
  return m ? m[1].replace(/^www\./i, "") : "";
}

/**
 * 앱에서 열어도 되는 주소인지 본다(http·https 만 연다. 답에 섞인 다른 방식의 링크로 앱이 열리지 않게).
 * @param {string} url 페이지 주소
 * @returns {boolean} 열어도 되면 true
 */
export function canOpenWebSource(url) {
  return webSourceHost(url) !== "";
}
