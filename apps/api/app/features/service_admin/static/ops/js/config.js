/** 화면 설정. 비밀·운영 값은 넣지 않는다(코드·Git 에 남음). */
const local = (typeof window !== "undefined" && (window.GABEE_LOCAL || window.GABI_LOCAL)) || {};
const sample = (typeof window !== "undefined" && (window.GABEE_SAMPLE_ACCOUNT || window.GABI_SAMPLE_ACCOUNT)) || {};

export const config = {
  /** 서버 주소. 로컬 개발은 js/local-config.js(.gitignore)로 덮어쓴다. */
  apiBase: local.apiBase || "https://api.gabee.cloud",
  /**
   * 기본은 서버 모드이다. 샘플 모드는 로컬에서 js/local-config.js 가 `mode: "sample"` 을 명시하고
   * js/sample-account.js 에 계정이 있을 때만 켜진다. 배포본에는 이 두 파일이 없고, 파일이 섞여 들어와도
   * local-config 의 명시가 없으면 샘플 모드가 되지 않는다.
   */
  sampleMode: local.mode === "sample" && !!sample.id,
};
