// 추억 화면 노출 스위치(개발·시험 전용, 기본 꺼짐). 서버에는 "후보 조회 API 가 열려 있는가"를 알려 주는 계약이 없다(미출시면 404 만 온다)
// 그래서 앱은 이 빌드 변수로 화면 진입점을 숨긴다. 켜도 404 는 "추억 없음"이 아니라 "아직 열려 있지 않음"으로 보인다.
//   EXPO_PUBLIC_FAMILY_MEMORY_UI = off(기본) | on(실제 API 호출) | mock(합성 데이터로만 화면 확인, API 를 부르지 않는다)

/**
 * @param {unknown} [value] 빌드 변수 값(시험에서 직접 넣는다)
 * @returns {"off" | "on" | "mock"}
 */
export function memoryUiMode(value = process.env.EXPO_PUBLIC_FAMILY_MEMORY_UI) {
  const v = typeof value === "string" ? value.trim().toLowerCase() : "";
  return v === "on" || v === "mock" ? v : "off";
}

/** 드로어 등에 진입점을 보일지. 기본(off)은 보이지 않는다. */
export const memoryUiVisible = (mode = memoryUiMode()) => mode !== "off";