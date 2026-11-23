// 인증 이미지 캐시 정리의 순수 로직(expo 모듈 없이 시험하도록 의존을 주입받는다). 실제 연결은 imageCache.js.
// 구분: 이 정리는 **기기에 남은 사본**을 줄이는 것이다. 가족 채팅에서 원래 접근 권한이 유지되는 사진(AI 분석만 철회·제외한 경우)의 원본을 지우지 않는다.

/**
 * 메모리·디스크 이미지 캐시를 모두 비운다(로그아웃 때: 같은 기기에서 다른 사람이 로그인해도 이전 사용자의 사진이 남지 않게). 하나가 실패해도 다음을 계속한다.
 * @param {{ clearMemoryCache?: () => Promise<boolean>, clearDiskCache?: () => Promise<boolean> }} image
 * @returns {Promise<{ memory: boolean, disk: boolean }>}
 */
export async function clearAllImageCaches(image) {
  const out = { memory: false, disk: false };
  try {
    out.memory = (await image.clearMemoryCache?.()) === true;
  } catch {
    // 네이티브 모듈이 없는 환경에서는 건너뛴다
  }
  try {
    out.disk = (await image.clearDiskCache?.()) === true;
  } catch {
    // 건너뛴다
  }
  return out;
}

/**
 * 화면에서 사라진 사진들의 디스크 캐시 사본만 골라 지운다(서버가 후보에서 뺐거나 사진이 열리지 않을 때). 다른 사진의 캐시는 건드리지 않는다.
 * 사진 주소는 로그인 헤더 이미지 규칙(서버가 준 상대 경로)이고, 캐시 키는 expo-image 기본값(요청 주소)이다. 어떤 오류도 던지지 않는다.
 * @param {string[]} paths 서버가 준 상대 사진 주소들
 * @param {{ image: { getCachePathAsync: (key: string) => Promise<string | null> }, remove: (cachedPath: string) => Promise<void> | void, toUrl: (path: string) => string }} deps
 * @returns {Promise<number>} 지운 사본 수
 */
export async function evictCachedPhotos(paths, { image, remove, toUrl }) {
  let evicted = 0;
  for (const path of [...new Set(paths)]) {
    try {
      const cached = await image.getCachePathAsync(toUrl(path));
      if (cached) {
        await remove(cached);
        evicted += 1;
      }
    } catch {
      // 한 장이 실패해도 나머지를 계속한다
    }
  }
  return evicted;
}