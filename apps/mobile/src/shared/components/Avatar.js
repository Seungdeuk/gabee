import { StyleSheet, Text, View } from "react-native";

import { colors } from "@/theme";

// 디자인의 아바타 색: 복숭아, 연한 복숭아, 꿀색
const tones = {
  blue: { backgroundColor: colors.peach, color: colors.text },
  purple: { backgroundColor: colors.peachSoft, color: colors.text },
  orange: { backgroundColor: colors.honeySoft, color: colors.text },
  green: { backgroundColor: colors.successSoft, color: colors.success },
};

/**
 * 이름 첫 글자를 보여주는 원형 아바타.
 * @param {{ name: string, tone?: keyof typeof tones, size?: number, ring?: boolean }} props ring: 겹쳐 놓을 때 흰 테두리
 */
export default function Avatar({ name, tone = "blue", size = 44, ring = false }) {
  const { backgroundColor, color } = tones[tone];
  return (
    <View
      style={[
        styles.avatar,
        { width: size, height: size, borderRadius: size / 2, backgroundColor },
        ring && styles.ring,
      ]}
    >
      <Text style={[styles.text, { color, fontSize: size * 0.34 }]}>{name.slice(0, 1)}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  avatar: {
    alignItems: "center",
    justifyContent: "center",
  },
  ring: {
    borderWidth: 2,
    borderColor: colors.card,
  },
  text: {
    fontWeight: "600",
  },
});
