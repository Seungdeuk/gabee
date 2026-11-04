import { useRouter } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, fonts, radius } from "@/theme";

import PlayScreen from "../components/PlayScreen";
import { SCORE } from "../games";

/** 찰칵! 탐정단 정답 공개: 정답, 원본 사진과 문제로 낸 부분, 딸의 한마디, 누가 맞혔나. */
export default function PhotoResultScreen() {
  const router = useRouter();
  return (
    <PlayScreen
      title="정답 공개"
      close
      footer={
        <>
          <Button label="이 사진 얘기 가족방에서 나누기" onPress={() => router.push("/family-chat")} />
          <Button label="나도 사진 문제 내기" variant="secondary" onPress={() => router.push("/play/photo-create")} />
        </>
      }
    >
      <View style={styles.hero}>
        <Text style={styles.heroSub}>이 사진, 어디서 찍었을까?</Text>
        <Text style={styles.heroBig}>제주도 여행</Text>
        <Text style={styles.heroSub}>내 답 제주도 여행 · 정답 +{SCORE.correct} 받았어요</Text>
      </View>
      <View style={styles.stage}>
        <View style={styles.box} />
        <Text style={styles.badge}>원본 사진</Text>
        <Text style={styles.stageNote}>네모가 문제로 낸 부분이에요</Text>
      </View>
      <View style={styles.memo}>
        <Text style={styles.memoText}>{`딸의 한마디\n"그날 비가 와서 협재 해변에서 우동을 먹었어요"`}</Text>
      </View>
      <Text style={styles.label}>누가 맞혔나요</Text>
      <View style={styles.chips}>
        <Text style={styles.chip}>엄마 정답</Text>
        <Text style={styles.chip}>나 정답</Text>
        <Text style={[styles.chip, styles.chipNo]}>아빠 오답 (돌잔치)</Text>
      </View>
    </PlayScreen>
  );
}

const styles = StyleSheet.create({
  hero: { padding: 18, borderRadius: radius.card, backgroundColor: colors.successSoft, gap: 4 },
  heroBig: { fontSize: 24, fontFamily: fonts.bold, color: "#2F4A3B" },
  heroSub: { ...font.caption, color: "#2F4A3B" },
  stage: { height: 260, borderRadius: radius.card, backgroundColor: "#CDB9A3", overflow: "hidden" },
  box: { position: "absolute", left: 130, top: 80, width: 110, height: 90, borderWidth: 3, borderColor: colors.background, borderRadius: 10, backgroundColor: "rgba(255,252,247,0.25)" },
  badge: { position: "absolute", left: 14, top: 12, paddingVertical: 4, paddingHorizontal: 10, borderRadius: 999, overflow: "hidden", backgroundColor: colors.background, fontSize: 13, fontFamily: fonts.bold, color: colors.text },
  stageNote: { position: "absolute", left: 0, right: 0, bottom: 12, textAlign: "center", fontSize: 13, color: "#3A2719" },
  memo: { padding: 12, borderRadius: radius.md, backgroundColor: colors.surface },
  memoText: { ...font.caption, color: colors.textSub },
  label: { ...font.bodyStrong, color: colors.text },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { paddingVertical: 6, paddingHorizontal: 12, borderRadius: 16, overflow: "hidden", backgroundColor: colors.successSoft, color: "#2F4A3B", fontSize: 13, fontFamily: fonts.regular },
  chipNo: { backgroundColor: colors.surface, color: colors.text },
});
