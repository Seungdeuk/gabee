/**
 * 기기에서 문서 파일 한 개 고르기(expo-document-picker 를 쓰므로 node 시험 대상이 아니다. 순수 로직은 fileUtils.js).
 */
import * as DocumentPicker from "expo-document-picker";

import { validateChatFile } from "./fileUtils";

/**
 * 문서 한 개를 고른다. 기기마다 한글(hwp) 등의 형식 이름이 달라 선택기는 모든 파일을 보이고, 확장자와 크기(20MB)는 앱에서 먼저 검사한다.
 * 취소하면 null, 허용하지 않는 형식·큰 파일이면 { code } 오류를 던진다(서버도 다시 검사한다).
 * @returns {Promise<{ uri: string, name: string, size?: number | null, mimeType?: string | null, file?: Blob } | null>}
 */
export async function pickChatDocument() {
  const result = await DocumentPicker.getDocumentAsync({ type: "*/*", copyToCacheDirectory: true, multiple: false });
  if (result.canceled || !result.assets?.length) return null;
  const asset = result.assets[0];
  const check = validateChatFile(asset);
  if (!check.ok) throw Object.assign(new Error(check.code), { code: check.code });
  return asset;
}
