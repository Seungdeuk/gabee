/**
 * 갤러리에서 채팅 사진 고르기(expo-image-picker 와 웹 canvas 를 쓰므로 node 시험 대상이 아니다. 순수 로직은 photo.js).
 */
import * as ImagePicker from "expo-image-picker";
import { Platform } from "react-native";

import { shrinkImageForWeb } from "@/shared/shrinkImage";

import { MAX_ALBUM_PHOTOS } from "./album";
import { isChatPhotoTooLarge, PICKER_QUALITY, WEB_JPEG_QUALITY, WEB_MAX_SIDE } from "./photo";

/**
 * 갤러리에서 사진 여러 장(최대 MAX_ALBUM_PHOTOS)을 고른다(고른 순서대로). 취소하면 빈 배열. 장마다 웹은 긴 변 2048px 이하 JPEG(0.85)로 줄이고 8MB 를 넘는 것이 분명하면 거르고(한 장만 골라도 같다), 8MB 초과가 있으면 { code: "photo_too_large" } 오류를 던진다. 시스템 선택기라 권한 요청이 필요 없다.
 * @returns {Promise<{ uri: string, file?: Blob, fileName?: string | null, mimeType?: string, fileSize?: number | null }[]>}
 */
export async function pickChatPhotos() {
  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["images"],
    allowsEditing: false,
    allowsMultipleSelection: true,
    selectionLimit: MAX_ALBUM_PHOTOS,
    orderedSelection: true,
    quality: PICKER_QUALITY,
    exif: false,
  });
  if (result.canceled || !result.assets?.length) return [];
  const picked = [];
  for (const asset of result.assets.slice(0, MAX_ALBUM_PHOTOS)) picked.push(await prepareAsset(asset));
  return picked;
}

/**
 * 고른 사진 한 장을 보내기 좋게 다듬는다(웹은 줄이기, 8MB 초과 검사).
 * @param {{ uri: string, file?: Blob, fileName?: string | null, mimeType?: string, fileSize?: number | null }} first expo-image-picker asset
 * @returns {Promise<object>}
 */
async function prepareAsset(first) {
  let asset = first;
  if (Platform.OS === "web") {
    const original = asset.file ?? (await (await fetch(asset.uri)).blob());
    const small = await shrinkImageForWeb(original, { maxSide: WEB_MAX_SIDE, quality: WEB_JPEG_QUALITY });
    if (small !== original) asset = { uri: asset.uri, file: small, fileName: "photo.jpg", mimeType: "image/jpeg", fileSize: small.size };
  }
  if (isChatPhotoTooLarge(asset)) throw Object.assign(new Error("photo_too_large"), { code: "photo_too_large" });
  return asset;
}
