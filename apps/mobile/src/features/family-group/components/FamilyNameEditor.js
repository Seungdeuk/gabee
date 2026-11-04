import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import { colors, font, spacing } from "@/theme";

import { renameFamily } from "../api";
import { familyErrorMessage, validateFamilyName, FAMILY_NAME_MAX } from "../messages";

/**
 * 가족 이름 바꾸기(가족 관리자에게만 그려진다). "이름 바꾸기"를 누르면 입력칸과 저장·취소가 나온다.
 * 저장하면 서버가 이름을 바꾸고(`PUT /family-group/groups/me/name`) onRenamed 로 알린다. 오류는 입력칸 아래에 문구로 보인다.
 * @param {{ name: string, onRenamed: () => Promise<void> | void }} props name: 지금 가족 이름, onRenamed: 저장에 성공한 뒤 부를 함수(가족 정보를 다시 읽는다)
 * @returns {import("react").ReactElement}
 */
export default function FamilyNameEditor({ name, onRenamed }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(name);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const start = () => {
    setText(name);
    setError("");
    setEditing(true);
  };

  const save = async () => {
    const checked = validateFamilyName(text);
    if (!checked.ok) {
      setError(checked.error);
      return;
    }
    if (checked.value === name) {
      setEditing(false);
      return;
    }
    setBusy(true);
    setError("");
    try {
      await renameFamily(checked.value);
      setEditing(false);
      await onRenamed();
    } catch (e) {
      setError(familyErrorMessage(e));
    }
    setBusy(false);
  };

  if (!editing) {
    return (
      <Card tone="white" testID="family-name-card">
        <Text style={styles.label}>가족 이름</Text>
        <View style={styles.row}>
          <Text style={styles.name} numberOfLines={1}>
            {name}
          </Text>
          <Button label="이름 바꾸기" variant="secondary" small onPress={start} testID="rename-start" />
        </View>
      </Card>
    );
  }
  return (
    <Card tone="white" testID="family-name-card">
      <Field label="가족 이름" value={text} onChangeText={setText} maxLength={FAMILY_NAME_MAX} error={error} editable={!busy} onSubmitEditing={save} returnKeyType="done" testID="rename-input" />
      <View style={styles.row}>
        <View style={styles.grow}>
          <Button label={busy ? "저장 중..." : "저장"} small onPress={save} disabled={busy} testID="rename-save" />
        </View>
        <View style={styles.grow}>
          <Button label="취소" variant="secondary" small onPress={() => setEditing(false)} disabled={busy} testID="rename-cancel" />
        </View>
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  label: { ...font.caption, color: colors.textMuted },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  name: { ...font.cardTitle, color: colors.text, flex: 1 },
  grow: { flex: 1 },
});
