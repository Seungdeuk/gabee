import { Pressable, StyleSheet, Text, View } from "react-native";

import Avatar from "@/shared/components/Avatar";
import { colors, font, fonts } from "@/theme";

/** 폭탄 방 선수 한 줄: 아바타, 이름 옆에 입장 시각, 오른쪽에 입장 칩. 아직 안 들어온 사람은 초대하기 + 대기 칩. */
export default function PlayerRow({ id, name, note, joined, onInvite }) {
  return (
    <View style={styles.row}>
      <Avatar name={id === "me" ? "나" : name} userId={id} size={36} />
      <View style={styles.text}>
        <Text style={styles.name}>{name}</Text>
        {note ? <Text style={styles.note}>{note}</Text> : null}
      </View>
      {joined ? null : (
        <Pressable onPress={onInvite} accessibilityRole="button" accessibilityLabel={`${name} 초대하기`} hitSlop={6} style={styles.invite}>
          <Text style={styles.inviteText}>초대하기</Text>
        </Pressable>
      )}
      <Text style={[styles.chip, !joined && styles.chipWait]}>{joined ? "입장" : "대기"}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { minHeight: 52, flexDirection: "row", alignItems: "center", gap: 12 },
  text: { flex: 1, flexDirection: "row", alignItems: "baseline", gap: 8 },
  name: { ...font.bodyStrong, color: colors.text },
  note: { ...font.caption, color: colors.textSub },
  invite: { paddingVertical: 4, paddingHorizontal: 6 }, // 외곽선 없이 글자만
  inviteText: { fontSize: 12, fontFamily: fonts.bold, color: "#8A5A2B" },
  chip: { paddingVertical: 3, paddingHorizontal: 10, borderRadius: 12, overflow: "hidden", backgroundColor: colors.successSoft, color: "#2F4A3B", fontSize: 12, fontFamily: fonts.bold },
  chipWait: { backgroundColor: "#F7F0E6", color: colors.textSub },
});
