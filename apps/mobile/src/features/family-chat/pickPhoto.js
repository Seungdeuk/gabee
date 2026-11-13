/**
 * 갤러리에서 채팅 사진 고르기(expo-image-picker 와 웹 canvas 를 쓰므로 node 시험 대상이 아니다. 순수 로직은 photo.js).
 */
import * as ImagePicker from "expo-image-picker";
import { Platform } from "react-native";

import { shrinkImageForWeb } from "@/shared/shrinkImage";

import { MAX_ALBUM_PHOTOS } from "./album";
import { isChatPhotoTooLarge, PICKER_QUALITY, WEB_JPEG_QUALITY, WEB_MAX_SIDE } from "./photo";
import { withTakenAt } from "./takenAt";

/**
 * 갤러리에서 사진 여러 장(최대 MAX_ALBUM_PHOTOS)을 고른다(고른 순서대로). 취소하면 빈 배열. 장마다 웹은 긴 변 2048px 이하 JPEG(0.85)로 줄이고, 8MB 를 넘는 사진은 빼서 skipped 로 센다(나머지는 그대로 돌려준다, 한 장만 골라도 같다). 시스템 선택기라 권한 요청이 필요 없다.
 * 촬영 시각: iOS 에서만 exif 를 받아, 고른 직후 withTakenAt 이 촬영 시각 한 값(takenAt, 시간대가 확인된 값만, 없으면 null)만 꺼내고 EXIF 객체(위치 포함)는 바로 버린다. 안드로이드·웹은 항상 takenAt null 이다. 돌려주는 asset 에는 exif 가 없다.
 * @returns {Promise<{ assets: { uri: string, file?: Blob, fileName?: string | null, mimeType?: string, fileSize?: number | null, takenAt: string | null }[], skipped: number }>}
 */
export async function pickChatPhotos() {
  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["images"],
    allowsEditing: false,
    allowsMultipleSelection: true,
    selectionLimit: MAX_ALBUM_PHOTOS,
    orderedSelection: true,
    quality: PICKER_QUALITY,
    // 촬영 시각 한 값만 쓰기 위해 iOS 에서만 받는다(꺼낸 뒤 EXIF 는 보관·전송·로그하지 않는다). 안드로이드는 시간대(OffsetTimeOriginal)를 돌려주지 않아 값을 쓸 수 없고, 위치·기기 정보만 앱으로 넘어오므로 받지 않는다(서버가 업로드 파일의 EXIF 를 읽는다). 웹은 EXIF 가 없다.
    exif: Platform.OS === "ios",
  });
  if (result.canceled || !result.assets?.length) return { assets: [], skipped: 0 };
  const assets = [];
  let skipped = 0;
  for (const picked of result.assets.slice(0, MAX_ALBUM_PHOTOS)) {
    const asset = withTakenAt(picked); // 여기서 EXIF 객체를 떼어 낸다
    try {
      assets.push(await prepareAsset(asset));
    } catch (e) {
      if (e?.code !== "photo_too_large") throw e;
      skipped += 1;
    }
  }
  return { assets, skipped };
}

/**
 * 고른 사진 한 장을 보내기 좋게 다듬는다(웹은 줄이기, 8MB 초과 검사).
 * @param {{ uri: string, file?: Blob, fileName?: string | null, mimeType?: string, fileSize?: number | null, takenAt: string | null }} first expo-image-picker asset(EXIF 는 이미 떼어 냈다)
 * @returns {Promise<object>}
 */
async function prepareAsset(first) {
  let asset = first;
  if (Platform.OS === "web") {
    const original = asset.file ?? (await (await fetch(asset.uri)).blob());
    const small = await shrinkImageForWeb(original, { maxSide: WEB_MAX_SIDE, quality: WEB_JPEG_QUALITY });
    if (small !== original) asset = { uri: asset.uri, file: small, fileName: "photo.jpg", mimeType: "image/jpeg", fileSize: small.size, takenAt: asset.takenAt };
  }
  if (isChatPhotoTooLarge(asset)) throw Object.assign(new Error("photo_too_large"), { code: "photo_too_large" });
  return asset;
}
