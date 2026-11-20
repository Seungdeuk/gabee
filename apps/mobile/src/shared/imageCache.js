import { Image } from "expo-image";
import { File } from "expo-file-system";

import { apiUrl } from "@/shared/api/client";
import { onBeforeSignOut } from "@/shared/auth/signOutHooks";

import { clearAllImageCaches, evictCachedPhotos } from "./imageCacheLogic";

/** 디스크 캐시 파일 한 개를 지운다(없으면 아무것도 안 한다). */
const removeCachedFile = (path) => {
  const file = new File(path);
  if (file.exists) file.delete();
};

/** 서버 사진 주소들의 이 기기 캐시 사본을 지운다(화면에서 사라진 사진용). 오류는 던지지 않는다. */
export const evictPhotoCache = (paths) => evictCachedPhotos(paths, { image: Image, remove: removeCachedFile, toUrl: apiUrl });

/** 로그아웃 직전에 메모리·디스크 이미지 캐시를 모두 비우도록 등록한다(앱 시작 때 한 번). @returns {() => void} 등록 해제 */
export const registerSignOutImageCacheClear = () => onBeforeSignOut(() => clearAllImageCaches(Image));