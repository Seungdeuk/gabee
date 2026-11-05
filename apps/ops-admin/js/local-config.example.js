/* 로컬 개발용 설정 예시. 이 파일을 local-config.js 로 복사해 쓴다(local-config.js 는 .gitignore 로 커밋 제외).
   mode: "sample" → 서버 없이 가짜 값과 샘플 로그인(js/sample-account.js 필요). mode: "server" → apiBase 의 실제 서버. */
window.GABEE_LOCAL = { mode: "server", apiBase: "http://127.0.0.1:8000" };
// window.GABEE_LOCAL = { mode: "sample" };
