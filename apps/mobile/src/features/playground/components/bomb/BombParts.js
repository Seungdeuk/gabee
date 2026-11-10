import { Ionicons } from "@expo/vector-icons";
import { StyleSheet, Text, View } from "react-native";
import Svg, { Circle } from "react-native-svg";

import Avatar from "@/shared/components/Avatar";
import { colors, font, fonts } from "@/theme";

export const BOMB_RED = "#C2503A";
export const BOMB_RING = "#D9381E";

/** 하트: 남은 생명은 채운 하트, 잃은 생명은 빈 하트. */
export function Hearts({ left, total, size = 13 }) {
  return (
    <View style={styles.hearts} accessibilityLabel={`생명 ${total}개 중 ${left}개 남음`}>
      {Array.from({ length: total }, (_, i) => (
        <Ionicons key={i} name={i < left ? "heart" : "heart-outline"} size={size} color={i < left ? BOMB_RED : colors.disabled} />
      ))}
    </View>
  );
}

/** 지금 차례인 사람: 붉은 몸통 + 붉은 점선 테두리(지지직). 아니면 평범한 아바타. size 는 몸통 지름. */
export function PlayerAvatar({ player, active, size = 44 }) {
  const box = size + 16;
  if (!active) {
    return (
      <View style={{ width: box, height: box, alignItems: "center", justifyContent: "center" }}>
        <Avatar name={player.name} userId={player.id} size={size} />
      </View>
    );
  }
  return (
    <View style={{ width: box, height: box, alignItems: "center", justifyContent: "center" }}>
      <Svg width={box} height={box} style={StyleSheet.absoluteFill}>
        <Circle cx={box / 2} cy={box / 2} r={box / 2 - 3} stroke={BOMB_RING} strokeWidth={3} strokeDasharray="5 4" fill="none" />
      </Svg>
      <View style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: BOMB_RED, alignItems: "center", justifyContent: "center" }}>
        <Text style={[styles.fuseText, { fontSize: size * 0.34 }]}>{player.name.slice(0, 1)}</Text>
      </View>
    </View>
  );
}

/** 위쪽 선수 줄. 칸마다 아바타·이름·하트(탈락이면 "탈락"). compact 는 키보드가 올라왔을 때 아바타와 하트만 낮게. */
export function PlayerStrip({ players, activeId, compact = false }) {
  return (
    <View style={styles.strip}>
      {players.map((p) => (
        <View key={p.id} style={[styles.col, compact && styles.colCompact]}>
          <PlayerAvatar player={p} active={p.id === activeId && !p.out} size={compact ? 24 : 44} />
          {compact ? null : <Text style={[styles.name, p.out && styles.nameOut]}>{p.name}</Text>}
          {p.out ? <Text style={styles.out}>탈락</Text> : <Hearts left={p.lives} total={p.total} size={compact ? 11 : 13} />}
        </View>
      ))}
    </View>
  );
}

/** 채팅 말풍선(작게): 남은 왼쪽 크림, 나는 오른쪽 노랑. cheer 는 관전 응원. */
export function Bubble({ msg, mine }) {
  return (
    <View style={[styles.msgRow, mine && styles.msgRowMine]}>
      {!mine ? <Avatar name={msg.name} userId={msg.id} size={26} /> : null}
      <View style={styles.msgBody}>
        {!mine ? <Text style={styles.msgName}>{msg.name}</Text> : null}
        <Text style={[styles.bubble, mine ? styles.bubbleMine : styles.bubbleOther, msg.chat && styles.bubbleChat]}>{msg.text}</Text>
      </View>
    </View>
  );
}

/** 남은 시간 막대. */
export function TimeBar({ left, total, danger }) {
  const pct = Math.max(0, Math.min(1, left / total));
  return (
    <View style={styles.track} accessibilityRole="progressbar" accessibilityValue={{ min: 0, max: total, now: Math.max(0, left) }}>
      <View style={[styles.fill, { width: `${pct * 100}%` }, danger && styles.fillDanger]} />
    </View>
  );
}

/** 문장을 끝내는 말(종결어미)인지 간단히 본다. 실제 판정은 서버 모델이 하게 된다. */
export function endsSentence(text) {
  return /(다|요|죠|네|까|니다|어|아|야|지|군|구나|래|세요|습니다)[.!?~\s]*$/.test(text.trim());
}

const styles = StyleSheet.create({
  hearts: { flexDirection: "row", gap: 1 },
  strip: { flexDirection: "row" },
  col: { flex: 1, alignItems: "center", gap: 2, minHeight: 96 },
  colCompact: { minHeight: 44, gap: 0 },
  fuseText: { fontFamily: fonts.bold, color: "#FFFFFF" },
  name: { ...font.caption, fontFamily: fonts.bold, color: colors.text },
  nameOut: { color: colors.disabled },
  out: { fontSize: 12, fontFamily: fonts.bold, color: colors.textMuted },
  msgRow: { flexDirection: "row", alignItems: "flex-end", gap: 6 },
  msgRowMine: { justifyContent: "flex-end" },
  msgBody: { maxWidth: "78%", gap: 1 },
  msgName: { fontSize: 11, lineHeight: 14, fontFamily: fonts.regular, color: colors.textSub },
  bubble: { paddingVertical: 5, paddingHorizontal: 12, borderRadius: 15, overflow: "hidden", fontSize: 14, lineHeight: 20, fontFamily: fonts.regular, color: colors.text },
  bubbleOther: { backgroundColor: "#F7F0E6" },
  bubbleMine: { backgroundColor: colors.surfaceStrong },
  bubbleChat: { backgroundColor: colors.card, borderWidth: 1, borderStyle: "dashed", borderColor: colors.border }, // 탈락·구경하는 사람끼리의 채팅은 게임 말과 구분한다
  track: { height: 8, borderRadius: 4, backgroundColor: colors.border, overflow: "hidden" },
  fill: { height: 8, borderRadius: 4, backgroundColor: colors.accent },
  fillDanger: { backgroundColor: BOMB_RED },
});
