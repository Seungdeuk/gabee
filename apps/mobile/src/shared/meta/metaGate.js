// 메타 SDK 를 켜도 되는지 정하는 순수 함수(시험: tests/metagate.test.js).
// Expo Go 에는 메타 부품이 없어서, 거기서 SDK 를 부르면 앱이 에러 화면으로 멈춘다. 그래서 먼저 확인한다.

/**
 * 메타 SDK 를 켤 수 있는 실행 환경인지 본다.
 * @param {{ os: string, executionEnvironment?: string, metaEnabled?: boolean }} env
 *   os: Platform.OS, executionEnvironment: expo-constants 값("storeClient" 는 Expo Go),
 *   metaEnabled: 빌드에 클라이언트 토큰이 들어갔는지(app.config.js 의 extra.metaEnabled)
 * @returns {boolean} 안드로이드·아이폰의 개발 빌드나 스토어 앱이고 토큰이 있으면 true
 */
export function canUseMeta({ os, executionEnvironment, metaEnabled }) {
  if (os !== "android" && os !== "ios") return false;
  if (executionEnvironment === "storeClient") return false;
  return metaEnabled === true;
}
