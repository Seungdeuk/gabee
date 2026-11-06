/* 서비스 관리자 화면 안(iframe)에서 운영 화면을 띄울 때 쓰는 연결 코드. 운영 원본(apps/ops-admin)에는 없는 파일이다.
 * - 서버 주소: 같은 출처(지금 이 화면을 준 API 서버)만 부른다.
 * - 로그인: 바깥 서비스 관리자 화면이 같은 탭의 sessionStorage 에 둔 토큰을 그대로 쓴다(로그인 한 번).
 *   토큰이 없거나 바깥 화면이 아니면 아무것도 하지 않는다(그러면 운영 화면이 자기 로그인 화면을 보여 준다).
 * - 로그인 만료(401): 바깥 화면에 알려 바깥 화면이 로그인으로 돌아가게 한다. */
(function () {
  "use strict";
  var token = null;
  try {
    token = sessionStorage.getItem("gabee_admin_token");
  } catch (e) {
    token = null;
  }
  window.GABEE_LOCAL = { apiBase: location.origin };
  if (!token || window.parent === window) return;
  window.GABEE_EMBED = {
    token: token,
    expired: function () {
      try {
        window.parent.dispatchEvent(new CustomEvent("gabee-admin-expired"));
      } catch (e) {
        /* 바깥 화면에 알리지 못하면 운영 화면이 자기 안내를 보여 준다 */
      }
    },
  };
})();
