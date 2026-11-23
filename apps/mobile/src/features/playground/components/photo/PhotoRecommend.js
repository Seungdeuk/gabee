import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, fonts } from "@/theme";

import { photoRecView, stepIndex } from "../../adapt";
import { photoRecLabel } from "../../photoRec";
import PhotoStage from "../PhotoStage";

const TONES = { album: ["#E6F0F8", "#3A6E99"], common: [colors.surface, colors.textSub] }; // 사진 출처 알약 색

/**
 * 찰칵! 탐정단 가비 추천: 카드 한 장을 `<` `>` 로 넘겨 보고(끝에서 처음으로), "이 문제로 쓰기"를 누르면 그 카드의 사진·질문·보기 자리가 editor(사진 네모·배율 고치기)로 바뀌어 그 자리에서 고친다. 못 보여 줄 때는 상태별 안내.
 * @param {{ recs: { data: any, error: string, loading: boolean }, index: number, onIndex: (i: number) => void, pickedId: string | null, onPick: (item: any) => void, refreshing: boolean, onRefresh: () => void, editor?: import("react").ReactNode }} props
 */
export default function PhotoRecommend({ recs, index, onIndex, pickedId, onPick, refreshing, onRefresh, editor }) {
  const view = photoRecView(recs.error && !recs.data ? { state: "failed" } : recs.data);
  if (recs.loading && !recs.data) {
    return (
      <View style={styles.empty}>
        <Text style={styles.notice}>가비가 문제를 준비 중이에요</Text>
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
      </View>
    );
  }
  const count = view.items.length;
  const at = Math.min(index, count - 1);
  const r = view.items[at];
  const on = pickedId === r.id;
  const [pillBg, pillFg] = TONES[r.source] ?? TONES.common;
  return (
    <>
      <View style={styles.noteBlock}>
        <Text style={styles.note}>가비가 사진 문제를 만들어 줘요</Text>
        <Text style={styles.note}>마음에 드는 문제를 골라 고쳐서 낼 수 있어요</Text>
      </View>
      <View style={[styles.card, on && styles.cardOn]}>
        <View style={styles.cardHead}>
          <Text style={[styles.pill, { backgroundColor: pillBg, color: pillFg }]}>{photoRecLabel(r)}</Text>
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
        {on ? <Text style={styles.picked}>이 문제를 고치는 중이에요</Text> : null}
        {on ? (
          editor
        ) : (
            <>
            <PhotoStage path={r.image_url} box={{ x: r.box_x, y: r.box_y, zoom: r.zoom }} label="추천 사진 미리보기" />
            <Text style={styles.question}>{r.question}</Text>
            {r.options.map((o, i) => {
              const isAns = i === r.answer_index;
              return (
                <View key={i} style={[styles.opt, isAns && styles.optAns]}>
                  <Text style={[styles.optText, isAns && styles.optAnsText]} accessibilityLabel={isAns ? `보기 ${i + 1} ${o} 정답` : `보기 ${i + 1} ${o}`}>
                    {o}
                  </Text>
                  {isAns ? <Text style={styles.optMark}>정답</Text> : null}
                </View>
              );
            })}
          </>
        )}
        <Pressable onPress={() => onPick(r)} accessibilityRole="button" accessibilityLabel={on ? "처음 문제로 되돌리기" : "이 문제로 쓰기"} style={styles.useBtn}>
          <Text style={styles.useText}>{on ? "처음 문제로 되돌리기" : "이 문제로 쓰기"}</Text>
        </Pressable>
      </View>
    </>
  );
}

const styles = StyleSheet.create({
  empty: { alignItems: "center", gap: 12, paddingVertical: 24 },
  notice: { ...font.body, color: colors.textSub, textAlign: "center", lineHeight: 24 },
  sub: { fontSize: 13, fontFamily: fonts.regular, color: colors.textSub },
  refreshBtn: { minHeight: 40, paddingHorizontal: 18, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  refreshText: { fontSize: 14, fontFamily: fonts.medium, color: colors.text },
  noteBlock: { gap: 2 },
  note: { ...font.caption, color: colors.textSub },
  card: { padding: 16, borderRadius: 18, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, gap: 10 },
  cardOn: { backgroundColor: colors.surfaceStrong, borderColor: colors.surfaceStrong },
  picked: { fontSize: 13, fontFamily: fonts.bold, color: "#8A5A2B" },
  cardHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  pill: { paddingVertical: 4, paddingHorizontal: 10, borderRadius: 999, overflow: "hidden", fontSize: 12, fontFamily: fonts.bold },
  pager: { flexDirection: "row", alignItems: "center", gap: 8 },
  arrow: { width: 32, height: 32, borderRadius: 16, borderWidth: 1, borderColor: colors.textSub, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  pageText: { fontSize: 14, fontFamily: fonts.medium, color: colors.textSub },
  question: { ...font.bodyStrong, color: colors.text },
  opt: { minHeight: 44, paddingHorizontal: 14, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  optAns: { backgroundColor: "#F2F8F4", borderColor: colors.success },
  optText: { flex: 1, fontSize: 15, lineHeight: 20, fontFamily: fonts.regular, color: colors.text },
  optAnsText: { fontFamily: fonts.bold },
  optMark: { fontSize: 12, fontFamily: fonts.bold, color: colors.success },
  useBtn: { alignSelf: "stretch", height: 44, borderRadius: 12, backgroundColor: colors.surfaceStrong, alignItems: "center", justifyContent: "center" },
  useText: { fontSize: 15, fontFamily: fonts.bold, color: colors.text },
});
