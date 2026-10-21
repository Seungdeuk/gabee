import { Pressable, StyleSheet, Text, View } from "react-native";

import Avatar from "@/shared/components/Avatar";
import { colors, font, radius } from "@/theme";

function ActionButton({ label, primary }) {
  return (
    <Pressable style={[styles.button, primary && styles.primary]}>
      <Text style={[styles.buttonText, primary && styles.primaryText]}>{label}</Text>
    </Pressable>
  );
}

/**
 * 가족 구성원 한 줄. 전화·안부 버튼을 함께 보여준다.
 * @param {{ member: { name: string, relation: string, status: string, tone: "blue" | "purple" | "orange" | "green" } }} props
 */
export default function MemberRow({ member }) {
  return (
    <View style={styles.row}>
      <Avatar name={member.name} tone={member.tone} />
      <View style={styles.main}>
        <Text style={styles.title}>{member.relation}</Text>
        <Text style={styles.subtitle}>{member.status}</Text>
      </View>
      <ActionButton label="전화" />
      <ActionButton label="안부" primary />
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 12,
  },
  main: {
    flex: 1,
    gap: 2,
  },
  title: {
    ...font.bodyStrong,
    color: colors.text,
  },
  subtitle: {
    ...font.caption,
    color: colors.textMuted,
  },
  button: {
    height: 36,
    paddingHorizontal: 12,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceStrong,
    alignItems: "center",
    justifyContent: "center",
  },
  primary: {
    backgroundColor: colors.primarySoft,
  },
  buttonText: {
    fontSize: 13,
    fontWeight: "600",
    color: colors.textSub,
  },
  primaryText: {
    color: colors.primaryDark,
  },
});
