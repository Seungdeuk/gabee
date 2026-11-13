/**
 * 사진 촬영 시각 꺼내기(T05-c, 순수 함수라 node 시험 대상). 갤러리가 돌려준 EXIF 에서 촬영 시각 한 값만 꺼낸다.
 * - 읽는 키는 바깥에 있는 DateTimeOriginal·OffsetTimeOriginal 두 개뿐이다(iOS 네이티브가 "{Exif}" 를 바깥으로 펼쳐 주므로 중첩은 보지 않는다). 위치(GPS)·기기 정보 키는 읽지 않는다.
 * - 안드로이드 갤러리는 OffsetTimeOriginal 을 돌려주지 않아 항상 null 이다(그래서 pickPhoto 는 iOS 에서만 exif 를 받는다). 안드로이드는 서버가 업로드 파일의 EXIF 를 읽는다.
 * - 시간대(오프셋)가 확인된 값만 쓴다. 오프셋이 없거나 틀리면 한국·UTC 로 추측하지 않고 null 이다(서버가 보낸 날 기준으로 둔다).
 * - EXIF 객체는 호출한 쪽이 보관·로그·전송하지 않는다(withTakenAt 이 떼어 낸다).
 */

const DATETIME = /^(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})$/;
const OFFSET = /^([+-])(\d{2}):(\d{2})$/;
const MIN_MS = Date.UTC(1990, 0, 1); // 서버(photo_service.TAKEN_MIN)와 같은 범위
const MAX_AHEAD_MS = 24 * 60 * 60 * 1000; // 서버(TAKEN_MAX_AHEAD)와 같은 범위: 현재 + 1일

/**
 * EXIF 에서 촬영 시각을 ISO 8601("2024-10-05T14:30:00+09:00")로 돌려준다. 없거나 오프셋이 불명확하거나 값·범위가 틀리면 null.
 * 서버는 EXIF 를 우선하고 이 값은 서버가 못 읽었을 때만 쓴다. 이상한 객체(읽다가 예외)도 null 이라 사진 고르기를 막지 않는다.
 * @param {unknown} exif expo-image-picker asset.exif (없으면 null/undefined)
 * @param {Date} [now] 범위 검사 기준 시각(시험용)
 * @returns {string | null}
 */
export function extractTakenAt(exif, now = new Date()) {
  try {
    return parseTakenAt(exif, now);
  } catch {
    return null;
  }
}

/**
 * extractTakenAt 의 본문(예외는 호출한 쪽이 null 로 바꾼다). 읽는 키는 DateTimeOriginal·OffsetTimeOriginal 두 개뿐이다.
 * @param {unknown} exif EXIF 비슷한 객체
 * @param {Date} now 범위 검사 기준 시각
 * @returns {string | null}
 */
function parseTakenAt(exif, now) {
  if (!exif || typeof exif !== "object") return null;
  const rawDate = exif.DateTimeOriginal;
  const rawOffset = exif.OffsetTimeOriginal;
  if (typeof rawDate !== "string" || typeof rawOffset !== "string") return null;
  const dt = DATETIME.exec(rawDate);
  const off = OFFSET.exec(rawOffset);
  if (!dt || !off) return null;
  const [year, month, day, hour, minute, second] = dt.slice(1).map(Number);
  const offHours = Number(off[2]);
  const offMinutes = Number(off[3]);
  if (offHours > 14 || offMinutes > 59) return null;
  const wall = Date.UTC(year, month - 1, day, hour, minute, second);
  const check = new Date(wall);
  // 없는 날짜(2월 30일)·범위 밖 시각(24시)·0000 년 같은 값은 Date 가 보정하므로, 되읽어 같은지 본다
  if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day || check.getUTCHours() !== hour || check.getUTCMinutes() !== minute || check.getUTCSeconds() !== second) return null;
  const instant = wall - (off[1] === "+" ? 1 : -1) * (offHours * 60 + offMinutes) * 60000;
  if (instant < MIN_MS || instant > now.getTime() + MAX_AHEAD_MS) return null;
  return `${dt[1]}-${dt[2]}-${dt[3]}T${dt[4]}:${dt[5]}:${dt[6]}${off[1]}${off[2]}:${off[3]}`;
}

/**
 * 갤러리 asset 에서 EXIF 객체를 떼어 내고 촬영 시각 한 값(takenAt, 없으면 null)만 붙인 새 asset 을 돌려준다. 원본 asset 은 바꾸지 않는다.
 * @template {object} T
 * @param {T & { exif?: unknown }} asset expo-image-picker asset
 * @param {Date} [now] 범위 검사 기준 시각(시험용)
 * @returns {Omit<T, "exif"> & { takenAt: string | null }}
 */
export function withTakenAt(asset, now) {
  const rest = {};
  // exif 칸은 건너뛰고 나머지만 복사한다(Object.keys 는 게터를 부르지 않아, exif 게터가 예외를 던져도 asset 을 잃지 않는다)
  for (const key of Object.keys(asset ?? {})) if (key !== "exif") rest[key] = asset[key];
  let exif;
  try {
    exif = asset?.exif;
  } catch {
    exif = undefined;
  }
  return { ...rest, takenAt: extractTakenAt(exif, now) };
}
