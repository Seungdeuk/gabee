import { Ionicons } from "@expo/vector-icons";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { FILE_SAVE_LABEL, formatFileSize } from "../fileUtils";

/**
 * 말풍선 안의 파일 카드: 문서 아이콘, 파일명(1~2줄 말줄임), 크기. 카드 본문을 누르면 열기/공유(onOpen), 오른쪽 다운로드 아이콘을 누르면 내 파일/드라이브에 저장(onSave).
 * 길게 누르면 말풍선 메뉴(onLongPress). 열기·저장 중에는 해당 버튼에 진행 표시를 보이고 다시 누를 수 없다.
 * @param {{ attachment: { filename?: string | null, size_bytes?: number | null }, busy?: "open" | "save" | null, onOpen: () => void, onSave: () => void, onLongPress?: (e: object) => void }} props
 */
export default function FileCard({ attachment, busy = null, onOpen, onSave, onLongPress }) {
  const name = attachment.filename || "파일";
  const size = formatFileSize(attachment.size_bytes);
  return (
    <View style={styles.card}>
      <Pressable
        onPress={onOpen}
        onLongPress={onLongPress}
        disabled={Boolean(busy)}
        accessibilityRole="button"
        accessibilityLabel={`파일 ${name}${size ? `, ${size}` : ""}, 누르면 열거나 공유해요`}
        style={({ pressed }) => [styles.body, pressed && styles.pressed]}
      >
        <View style={styles.icon}>
          {busy === "open" ? <ActivityIndicator color={colors.accent} /> : <Ionicons name="document-text-outline" size={24} color={colors.accent} />}
        </View>
        <View style={styles.texts}>
          <Text style={styles.name} numberOfLines={2} ellipsizeMode="middle">
            {name}
          </Text>
          {size ? <Text style={styles.size}>{size}</Text> : null}
        </View>
      </Pressable>
      <Pressable
        onPress={onSave}
        onLongPress={onLongPress}
        disabled={Boolean(busy)}
        accessibilityRole="button"
        accessibilityLabel={FILE_SAVE_LABEL}
        hitSlop={spacing.xs}
        style={({ pressed }) => [styles.save, pressed && styles.pressed]}
      >
        {busy === "save" ? <ActivityIndicator color={colors.accent} /> : <Ionicons name="download-outline" size={22} color={colors.textSub} />}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { flexDirection: "row", alignItems: "center", gap: spacing.xs, minWidth: 200 },
  body: { flex: 1, flexDirection: "row", alignItems: "center", gap: spacing.sm, minWidth: 0 },
  icon: { width: 40, height: 40, borderRadius: radius.md, backgroundColor: colors.honeySoft, alignItems: "center", justifyContent: "center" },
  texts: { flex: 1, minWidth: 0 },
  name: { ...font.body, color: colors.text },
  size: { ...font.caption, color: colors.textMuted },
  save: { width: 40, height: 40, borderRadius: radius.pill, alignItems: "center", justifyContent: "center" },
  pressed: { opacity: 0.7 },
});
