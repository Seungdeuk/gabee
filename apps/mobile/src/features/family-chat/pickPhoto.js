/**
 * 갤러리에서 채팅 사진 고르기(expo-image-picker 와 웹 canvas 를 쓰므로 node 시험 대상이 아니다. 순수 로직은 photo.js).
 */
import * as ImagePicker from "expo-image-picker";
import { Platform } from "react-native";

import { shrinkImageForWeb } from "@/shared/shrinkImage";

import { isChatPhotoTooLarge, PICKER_QUALITY, WEB_JPEG_QUALITY, WEB_MAX_SIDE } from "./photo";

/**
 * 갤러리에서 사진 한 장을 고른다(시스템 선택기라 권한 요청이 필요 없다). 취소하면 null.
 * 웹은 긴 변 2048px 이하 JPEG(0.85)로 줄이고(실패하면 원본), 네이티브는 선택기 품질 옵션으로 줄인다.
 * 8MB 를 넘는 것이 분명하면 { code: "photo_too_large" } 오류를 던진다.
 * @returns {Promise<{ uri: string, file?: Blob, fileName?: string | null, mimeType?: string, fileSize?: number | null } | null>}
 */
export async function pickChatPhoto() {
  const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], allowsEditing: false, quality: PICKER_QUALITY, exif: false });
  if (result.canceled || !result.assets?.length) return null;
  let asset = result.assets[0];
  if (Platform.OS === "web") {
    const original = asset.file ?? (await (await fetch(asset.uri)).blob());
    const small = await shrinkImageForWeb(original, { maxSide: WEB_MAX_SIDE, quality: WEB_JPEG_QUALITY });
    if (small !== original) asset = { uri: asset.uri, file: small, fileName: "photo.jpg", mimeType: "image/jpeg", fileSize: small.size };
  }
  if (isChatPhotoTooLarge(asset)) throw Object.assign(new Error("photo_too_large"), { code: "photo_too_large" });
  return asset;
}
