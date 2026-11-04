import { useRouter } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius } from "@/theme";

import { GAMES } from "../games";
import PlayIcon from "./PlayIcon";

/**
 * 게임 한 줄(내 차례/참여 완료/지난 결과 공통).
 * strong 이면 노란 카드, done 이면 오른쪽에 초록 "참여 완료" 칩, 아니면 action 글자.
 */
export default function TurnRow({ item, strong = false, done = false }) {
  const router = useRouter();
  const game = GAMES[item.game];
  return (
    <Pressable
      onPress={() => router.push(item.route)}
      accessibilityRole="button"
      accessibilityLabel={`${item.title}. ${item.sub}`}
      style={[styles.row, strong ? styles.strong : styles.plain]}
    >
      <View style={[styles.icon, { backgroundColor: strong ? colors.background : colors.surfaceStrong }]}>
        <PlayIcon icon={game.icon} />
      </View>
      <View style={styles.text}>
        <Text style={styles.title}>{item.title}</Text>
        <Text style={styles.sub}>{item.sub}</Text>
      </View>
      {done ? <Text style={styles.chip}>참여 완료</Text> : item.action ? <Text style={styles.action}>{item.action}</Text> : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: { paddingVertical: 14, paddingHorizontal: 16, borderRadius: radius.lg, flexDirection: "row", alignItems: "center", gap: 12 },
  strong: { backgroundColor: colors.surfaceStrong },
  plain: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  icon: { width: 44, height: 44, borderRadius: 12, alignItems: "center", justifyContent: "center" },
  text: { flex: 1 },
  title: { ...font.bodyStrong, color: colors.text },
  sub: { ...font.caption, color: colors.textSub },
  action: { fontSize: 14, fontFamily: font.bodyStrong.fontFamily, color: colors.text },
  chip: { paddingVertical: 4, paddingHorizontal: 10, borderRadius: 12, overflow: "hidden", backgroundColor: colors.successSoft, color: "#2F4A3B", fontSize: 12, fontFamily: font.bodyStrong.fontFamily },
});
