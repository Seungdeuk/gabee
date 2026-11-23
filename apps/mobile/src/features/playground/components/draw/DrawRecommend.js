import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";
import Svg, { Path, Rect } from "react-native-svg";

import { colors, font, fonts } from "@/theme";

import { drawRecLabel, drawRecView, stepIndex } from "../../adapt";

const TONES = { schedule: ["#E6F0F8", "#3A6E99"], chat: ["#E4F0E8", "#2F4A3B"], common: [colors.surface, colors.textSub] }; // 단어를 어디서 가져왔는지 알약 색
const PREVIEW_HEIGHT = 220;

const toPath = (pts) => pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x} ${y}`).join(" ");

/** 추천 그림 미리보기(읽기 전용). 선 좌표는 0~255 이다. */
function Preview({ strokes }) {
  return (
    <Svg width="100%" height={PREVIEW_HEIGHT} viewBox="0 0 255 255" accessibilityLabel="추천 그림 미리보기">
      <Rect width="255" height="255" fill={colors.card} />
      {strokes.map((s, i) => (
        <Path key={i} d={toPath(s)} stroke={colors.text} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" fill="none" />
      ))}
    </Svg>
  );
}

/**
 * 이게 뭐게 가비 추천: 카드 한 장을 `<` `>` 로 넘겨 보고(끝에서 처음으로), "이 그림으로 쓰기"를 누르면 그 카드의 그림 자리가 editor(그림이 들어 있는 그림판)로 바뀐다. 못 보여 줄 때는 상태별 안내.
 * @param {{ recs: { data: any, error: string, loading: boolean }, index: number, onIndex: (i: number) => void, pickedId: string | null, onPick: (item: any) => void, refreshing: boolean, onRefresh: () => void, onManual?: () => void, editor?: import("react").ReactNode }} props
 */
export default function DrawRecommend({ recs, index, onIndex, pickedId, onPick, refreshing, onRefresh, onManual, editor }) {
  const view = drawRecView(recs.error && !recs.data ? { state: "failed" } : recs.data);
  if (recs.loading && !recs.data) {
    return (
      <View style={styles.empty}>
        <Text style={styles.notice}>가비가 그림을 준비 중이에요</Text>
        <Text style={styles.sub}>처음 열 때는 조금 걸려요</Text>
      </View>
    );
  }
  if (view.items.length === 0) {
    return (
      <View style={styles.empty}>
        <Text style={styles.notice}>{view.notice}</Text>
        {view.refresh ? (
          <Pressable onPress={onRefresh} disabled={refreshing} accessibilityRole="button" accessibilityLabel="추천 새로고침" style={styles.refreshBtn}>
            <Text style={styles.refreshText}>{refreshing ? "불러오는 중…" : "새로고침"}</Text>
          </Pressable>
        ) : null}
        {view.manual && onManual ? (
          <Pressable onPress={onManual} accessibilityRole="button" accessibilityLabel="직접 그리기" style={styles.refreshBtn}>
            <Text style={styles.refreshText}>직접 그리기</Text>
          </Pressable>
        ) : null}
      </View>
    );
  }
  const count = view.items.length;
  const at = Math.min(index, count - 1);
  const r = view.items[at];
  const on = pickedId === r.id;
  const [pillBg, pillFg] = TONES[r.source] ?? TONES.common;
  const alts = (r.alt_answers ?? []).join(", ");
  return (
    <>
      <View style={styles.noteBlock}>
        <Text style={styles.note}>가비가 그림을 그려 줘요</Text>
        <Text style={styles.note}>마음에 드는 그림을 골라 고쳐서 낼 수 있어요</Text>
      </View>
      <View style={[styles.card, on && styles.cardOn]}>
        <View style={styles.cardHead}>
          <Text style={[styles.pill, { backgroundColor: pillBg, color: pillFg }]}>{drawRecLabel(r)}</Text>
          <View style={styles.pager}>
            <Pressable onPress={() => onIndex(stepIndex(at, count, -1))} accessibilityRole="button" accessibilityLabel="이전 추천" hitSlop={8} style={styles.arrow}>
              <Ionicons name="chevron-back" size={16} color={colors.textSub} />
            </Pressable>
            <Text style={styles.pageText} accessibilityLabel={`추천 ${count}개 중 ${at + 1}번째`}>
              {at + 1} / {count}
            </Text>
            <Pressable onPress={() => onIndex(stepIndex(at, count, 1))} accessibilityRole="button" accessibilityLabel="다음 추천" hitSlop={8} style={styles.arrow}>
              <Ionicons name="chevron-forward" size={16} color={colors.textSub} />
            </Pressable>
          </View>
        </View>
        {on ? <Text style={styles.picked}>이 그림을 고치는 중이에요</Text> : null}
        {on ? editor : <Preview strokes={r.strokes} />}
        {on ? null : (
          <Text style={styles.answer}>
            정답 {r.word}
            {alts ? <Text style={styles.sub}>  (이것도 정답: {alts})</Text> : null}
          </Text>
        )}
        <Pressable onPress={() => onPick(r)} accessibilityRole="button" accessibilityLabel={on ? "처음 그림으로 되돌리기" : "이 그림으로 쓰기"} style={styles.useBtn}>
          <Text style={styles.useText}>{on ? "처음 그림으로 되돌리기" : "이 그림으로 쓰기"}</Text>
        </Pressable>
      </View>
      {view.more ? (
        <Pressable onPress={onRefresh} disabled={refreshing} accessibilityRole="button" accessibilityLabel="그림 더 불러오기" style={styles.moreBtn}>
          <Text style={styles.refreshText}>{refreshing ? "그림을 더 그리는 중…" : "그림 더 불러오기"}</Text>
        </Pressable>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  empty: { alignItems: "center", gap: 12, paddingVertical: 24 },
  notice: { ...font.body, color: colors.textSub, textAlign: "center", lineHeight: 24 },
  sub: { fontSize: 13, fontFamily: fonts.regular, color: colors.textSub },
  refreshBtn: { minHeight: 40, paddingHorizontal: 18, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  refreshText: { fontSize: 14, fontFamily: fonts.medium, color: colors.text },
  moreBtn: { alignSelf: "center", minHeight: 40, paddingHorizontal: 18, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  noteBlock: { gap: 2 },
  note: { ...font.caption, color: colors.textSub },
  card: { padding: 16, borderRadius: 18, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, gap: 10 },
  cardOn: { backgroundColor: colors.surfaceStrong, borderColor: colors.surfaceStrong },
  cardHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  pill: { paddingVertical: 4, paddingHorizontal: 10, borderRadius: 999, overflow: "hidden", fontSize: 12, fontFamily: fonts.bold },
  pager: { flexDirection: "row", alignItems: "center", gap: 8 },
  arrow: { width: 32, height: 32, borderRadius: 16, borderWidth: 1, borderColor: colors.textSub, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  pageText: { fontSize: 14, fontFamily: fonts.medium, color: colors.textSub },
  picked: { fontSize: 13, fontFamily: fonts.bold, color: "#8A5A2B" },
  answer: { ...font.bodyStrong, color: colors.text },
  useBtn: { alignSelf: "stretch", height: 44, borderRadius: 12, backgroundColor: colors.surfaceStrong, alignItems: "center", justifyContent: "center" },
  useText: { fontSize: 15, fontFamily: fonts.bold, color: colors.text },
});
