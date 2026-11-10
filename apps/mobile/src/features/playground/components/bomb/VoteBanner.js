import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, fonts } from "@/theme";

import { BOMB_RED, TimeBar } from "./BombParts";

export const VOTE_SEC = 10; // 서버의 투표 시간과 같다

/**
 * 판정 투표 배너: 누가 무엇을 다투는지, 맞아요/아니에요 버튼, 지금 표 수. 투표는 게임 중인 사람만 하고
 * 안 고르면 기권이다. 투표하는 동안 게임 시계는 멈춘다(서버가 남은 시간을 그대로 둔다).
 */
export default function VoteBanner({ vote, left, busy, onVote }) {
  const call = vote.kind === "call";
  const title = `${vote.requester.name}님이 "${call ? "어라?" : "억울해요"}"를 눌렀어요`;
  const what = call ? `"${vote.target.name}의 '${vote.word}'는 끝난 말인데 통과됐어요"` : `"'${vote.word}'는 끝난 말이 아닌데 탈락했어요"`;
  const secs = Math.ceil(left ?? vote.seconds_left);
  return (
    <View style={styles.box} accessibilityLiveRegion="polite">
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.what}>{what}</Text>
      <TimeBar left={left ?? vote.seconds_left} total={VOTE_SEC} danger={(left ?? 0) <= 3} />
      {vote.can_vote ? (
        <View style={styles.btns}>
          <Pressable onPress={() => onVote(true)} disabled={busy} accessibilityRole="button" accessibilityLabel="맞아요" style={[styles.btn, styles.yes, busy && styles.off]}>
            <Text style={styles.btnText}>맞아요</Text>
          </Pressable>
          <Pressable onPress={() => onVote(false)} disabled={busy} accessibilityRole="button" accessibilityLabel="아니에요" style={[styles.btn, styles.no, busy && styles.off]}>
            <Text style={styles.btnText}>아니에요</Text>
          </Pressable>
        </View>
      ) : (
        <Text style={styles.sub}>{vote.my_choice ? `${vote.my_choice === "yes" ? "맞아요" : "아니에요"}로 골랐어요` : "투표는 게임 중인 사람이 해요"}</Text>
      )}
      <View style={styles.tally}>
        <Text style={styles.pill}>맞아요 {vote.yes}</Text>
        <Text style={styles.pill}>아니에요 {vote.no}</Text>
        <Text style={styles.pill}>아직 안 함 {vote.waiting}</Text>
      </View>
      <Text style={styles.sub}>안 고르면 기권이에요 {secs}초 남음</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  box: { marginHorizontal: 20, marginTop: 8, padding: 12, gap: 8, borderRadius: 14, borderWidth: 1, borderColor: BOMB_RED, backgroundColor: "#FBEAE3" },
  title: { fontSize: 14, fontFamily: fonts.bold, color: colors.text },
  what: { ...font.caption, color: colors.textSub },
  btns: { flexDirection: "row", gap: 8 },
  btn: { flex: 1, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  yes: { backgroundColor: colors.success },
  no: { backgroundColor: BOMB_RED },
  off: { opacity: 0.5 },
  btnText: { fontSize: 14, fontFamily: fonts.bold, color: "#FFFFFF" },
  tally: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  pill: { paddingVertical: 1, paddingHorizontal: 8, borderRadius: 999, overflow: "hidden", borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, fontSize: 11, lineHeight: 16, fontFamily: fonts.regular, color: colors.text },
  sub: { ...font.caption, color: colors.textSub },
});
