import { Ionicons } from "@expo/vector-icons";
import { StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

/**
 * 채팅 메시지 하나. 사용자는 오른쪽 말풍선, 비서는 왼쪽에 아이콘과 함께 보여준다.
 * @param {{ role: "user" | "assistant", text: string }} props
 */
export default function MessageBubble({ role, text }) {
  if (role === "user") {
    return (
      <View style={styles.userRow}>
        <Text style={styles.userText}>{text}</Text>
      </View>
    );
  }

  return (
    <View style={styles.assistantRow}>
      <View style={styles.avatar}>
        <Ionicons name="sparkles" size={14} color={colors.primary} />
      </View>
      <Text style={styles.assistantText}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  userRow: {
    alignSelf: "flex-end",
    maxWidth: "80%",
    backgroundColor: colors.surfaceStrong,
    borderRadius: 20,
    paddingVertical: 10,
    paddingHorizontal: 16,
  },
  userText: {
    ...font.body,
    fontSize: 16,
    color: colors.text,
  },
  assistantRow: {
    flexDirection: "row",
    gap: 10,
    alignSelf: "flex-start",
    maxWidth: "92%",
  },
  avatar: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: colors.primarySoft,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 2,
  },
  assistantText: {
    ...font.body,
    fontSize: 16,
    lineHeight: 24,
    color: colors.text,
    flexShrink: 1,
  },
});
