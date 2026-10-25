import * as ImagePicker from "expo-image-picker";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Platform, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Field from "@/shared/components/Field";
import UserAvatar from "@/shared/components/UserAvatar";
import { colors, font } from "@/theme";

import { deleteMyPhoto, updateMyProfile, uploadMyPhoto } from "../api";
import FamilyFrame from "../components/FamilyFrame";
import Notice from "../components/Notice";
import { familyErrorMessage } from "../messages";
import { isPhotoTooLarge, photoErrorMessage, shrinkPhotoForWeb } from "../photo";
import { DETAIL_MAX, RELATIONS } from "../relations";
import useFamilyState from "../useFamilyState";

/**
 * 내 가족 프로필: 이 가족에서 쓸 이름과 가족 관계(엄마·아빠·아들·딸·할머니·할아버지·기타).
 * 기타를 고르면 관계를 직접 적을 수 있다. 내 프로필만 바꿀 수 있고, 다른 가족은 그 그룹에서 이 이름·관계로 나를 본다.
 */
export default function FamilyProfileScreen() {
  const router = useRouter();
  const family = useFamilyState();
  const [name, setName] = useState("");
  const [relation, setRelation] = useState(null);
  const [detail, setDetail] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoError, setPhotoError] = useState("");
  const [photo, setPhoto] = useState(undefined); // 방금 올리거나 지운 결과(undefined 면 서버 목록의 값)

  // 내 현재 프로필로 채운다(내 id 는 my_role 이 있는 구성원 중 이름·역할이 아니라 서버가 알려 준 목록에는 없으므로 /me 로 찾는다)
  useEffect(() => {
    if (family.status !== "member" || loaded) return;
    const mine = family.group.members.find((m) => m.id === family.group.my_id) ?? null;
    if (mine) {
      setName(mine.display_name ?? "");
      setRelation(mine.family_relation ?? null);
      setDetail(mine.family_relation_detail ?? "");
    }
    setLoaded(true);
  }, [family.status, family.group, loaded]);

  /** 갤러리에서 정사각형으로 골라 올린다. 성공하면 화면과 가족 상태를 새 photo_url 로 갱신한다. */
  const changePhoto = async () => {
    setPhotoError("");
    setPhotoBusy(true);
    try {
      // 시스템 선택기는 권한이 필요 없다. 취소하면 조용히 끝낸다.
      const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], allowsEditing: true, aspect: [1, 1], quality: 0.5 });
      if (result.canceled || !result.assets?.length) return;
      let asset = result.assets[0];
      if (Platform.OS === "web") {
        // 웹은 올리기 전에 긴 변 1024px 이하 JPEG 로 줄인다(실패하면 원본)
        const original = asset.file ?? (await (await fetch(asset.uri)).blob());
        const small = await shrinkPhotoForWeb(original);
        if (small !== original) asset = { uri: asset.uri, file: small, fileName: "profile.jpg", mimeType: "image/jpeg", fileSize: small.size };
      }
      if (isPhotoTooLarge(asset)) {
        setPhotoError(photoErrorMessage({ code: "photo_too_large" }));
        return;
      }
      const out = await uploadMyPhoto(asset);
      setPhoto(out.photo_url ?? null);
      await family.reload();
    } catch (e) {
      setPhotoError(photoErrorMessage(e));
    } finally {
      setPhotoBusy(false);
    }
  };

  const removePhoto = async () => {
    setPhotoError("");
    setPhotoBusy(true);
    try {
      await deleteMyPhoto();
      setPhoto(null);
      await family.reload();
    } catch (e) {
      setPhotoError(photoErrorMessage(e));
    } finally {
      setPhotoBusy(false);
    }
  };

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await updateMyProfile({
        display_name: name.trim() || null,
        family_relation: relation,
        family_relation_detail: relation === "other" ? detail.trim() || null : null,
      });
      router.replace("/family");
    } catch (e) {
      setError(familyErrorMessage(e));
      setBusy(false);
    }
  };

  if (family.status === "loading") {
    return (
      <FamilyFrame title="내 프로필">
        <Notice text="불러오고 있어요..." />
      </FamilyFrame>
    );
  }
  if (family.status !== "member") {
    return (
      <FamilyFrame title="내 프로필">
        <Notice tone={family.status === "error" ? "error" : "info"} text={family.status === "error" ? family.error : "가족 그룹에 먼저 들어가 주세요"} />
        <Button label="가족 그룹으로" onPress={() => router.replace("/family")} />
      </FamilyFrame>
    );
  }

  const mine = family.group.members.find((m) => m.id === family.group.my_id);
  const photoUrl = photo !== undefined ? photo : (mine?.photo_url ?? null);
  return (
    <FamilyFrame title="내 프로필" subtitle="가족에게 보여줄 이름과 관계예요">
      <View style={styles.photo}>
        <UserAvatar name={name.trim() || mine?.display_name || mine?.name || "?"} userId={family.group.my_id} photoUrl={photoUrl} size={96} />
        <View style={styles.photoButtons}>
          <Button label={photoBusy ? "올리는 중..." : "사진 변경"} small variant="secondary" onPress={changePhoto} disabled={photoBusy} testID="photo-change" />
          {photoUrl ? <Button label="사진 삭제" small variant="secondary" onPress={removePhoto} disabled={photoBusy} testID="photo-delete" /> : null}
        </View>
        <Text style={styles.photoHint}>정사각형으로 잘라 올려요. 사진이 너무 크면 더 작게 잘라 주세요</Text>
        <Notice tone="error" text={photoError} />
      </View>
      <Field label="가족에서 쓸 이름" value={name} onChangeText={setName} maxLength={40} placeholder="비워 두면 계정 이름을 써요" testID="profile-name" />
      <View style={styles.block}>
        <Text style={styles.label}>가족 관계</Text>
        <View style={styles.chips}>
          {RELATIONS.map((r) => (
            <Button key={r.key} label={r.label} small variant="secondary" selected={relation === r.key} onPress={() => setRelation(relation === r.key ? null : r.key)} testID={`relation-${r.key}`} />
          ))}
        </View>
      </View>
      {relation === "other" ? (
        <Field label="관계 직접 적기" value={detail} onChangeText={setDetail} maxLength={DETAIL_MAX} placeholder="예: 이모, 삼촌, 사촌" hint="적어 두면 가족에게 이 관계로 보여요 (선택)" testID="profile-detail" />
      ) : null}
      <Notice tone="error" text={error} />
      <Button label={busy ? "저장 중..." : "저장"} onPress={save} disabled={busy} testID="profile-save" />
    </FamilyFrame>
  );
}

const styles = StyleSheet.create({
  photo: { alignItems: "center", gap: 8 },
  photoButtons: { flexDirection: "row", gap: 8 },
  photoHint: { ...font.caption, color: colors.textMuted },
  block: { gap: 8 },
  label: { fontSize: 14, fontWeight: "500", color: colors.text },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
});
