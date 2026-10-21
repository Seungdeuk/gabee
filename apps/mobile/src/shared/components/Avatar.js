import { StyleSheet, Text, View } from "react-native";

import { colors } from "@/theme";

const tones = {
  blue: { backgroundColor: colors.primarySoft, color: colors.primaryDark },
  purple: { backgroundColor: colors.purpleSoft, color: "#5B3CC4" },
  orange: { backgroundColor: colors.warningSoft, color: "#A35400" },
  green: { backgroundColor: colors.successSoft, color: "#137A41" },
};

/**
 * 이름 첫 글자를 보여주는 원형 아바타.
 * @param {{ name: string, tone?: keyof typeof tones, size?: number }} props
 */
export default function Avatar({ name, tone = "blue", size = 40 }) {
  const { backgroundColor, color } = tones[tone];
  return (
    <View
      style={[styles.avatar, { width: size, height: size, borderRadius: size / 2, backgroundColor }]}
    >
      <Text style={[styles.text, { color, fontSize: size * 0.35 }]}>{name.slice(0, 1)}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  avatar: {
    alignItems: "center",
    justifyContent: "center",
  },
  text: {
    fontWeight: "700",
  },
});
