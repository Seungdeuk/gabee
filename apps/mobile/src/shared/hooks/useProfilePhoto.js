import { useEffect, useState } from "react";
import { Platform } from "react-native";

import { apiUrl, authHeaders, ensureFreshAccess, isApiConfigured } from "@/shared/api/client";
import { createPhotoCache, holdPhoto, photoPath } from "@/shared/photoCache";

/** 웹에서만 쓴다: 인증 헤더로 사진을 받아 blob 으로 둔다. 토큰은 주소·로그에 남기지 않는다. */
async function loadBlob(path) {
  await ensureFreshAccess().catch(() => {});
  const res = await fetch(apiUrl(path), { headers: authHeaders() });
  if (!res.ok) throw new Error("photo_unavailable");
  return res.blob();
}

const webCache = createPhotoCache({
  load: loadBlob,
  create: (blob) => URL.createObjectURL(blob),
  revoke: (url) => URL.revokeObjectURL(url),
});

/**
 * 인증이 필요한 프로필 사진을 화면에 쓸 수 있는 소스로 바꾼다.
 * - 네이티브: expo-image 가 헤더를 붙여 받는 { uri, headers }
 * - 웹: 받아 둔 blob 주소 { uri } (같은 사진은 한 번만 받고, 쓰는 곳이 없어지면 해제한다)
 * 사진이 없거나 받지 못하면 null — 호출한 쪽이 이니셜 아바타로 되돌아간다. photo_url 의 ?v= 가 바뀌면 다시 받는다.
 * @param {string | null | undefined} photoUrl 서버가 준 photo_url(상대 경로)
 * @returns {{ source: { uri: string, headers?: Record<string, string> } | null, markFailed: () => void }}
 */
export default function useProfilePhoto(photoUrl) {
  const path = isApiConfigured() ? photoPath(photoUrl) : null;
  const [state, setState] = useState({ path: null, source: null, failed: false });

  useEffect(() => {
    if (!path) return undefined;
    let cancelled = false;
    if (Platform.OS === "web") {
      return holdPhoto(webCache, path, {
        onReady: (uri) => setState({ path, source: { uri }, failed: false }),
        onFail: () => setState({ path, source: null, failed: true }),
      });
    }
    ensureFreshAccess()
      .catch(() => {})
      .then(() => {
        if (!cancelled) setState({ path, source: { uri: apiUrl(path), headers: authHeaders() }, failed: false });
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  const current = state.path === path && !state.failed ? state.source : null;
  return { source: path ? current : null, markFailed: () => setState((s) => ({ ...s, path, source: null, failed: true })) };
}
