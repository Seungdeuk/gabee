import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import AuthImage from "@/shared/components/AuthImage";
import { colors, fonts, radius } from "@/theme";

import { zoomBoxStyle } from "../adapt";

/**
 * 탐정단 사진 틀. 서버가 준 사진(풀이 중에는 확대한 조각, 결과에서는 원본)을 보여 준다.
 * box 가 있으면 원본 위에 문제로 낸 부분을 네모로 겹친다(사진 크기를 알게 되면 비율에 맞춰 네모 위치를 잡는다).
 * @param {{ path: string | null | undefined, box?: { x: number, y: number, zoom: number } | null, badge?: string, note?: string, label?: string }} props
 */
export default function PhotoStage({ path, box = null, badge, note, label }) {
  const [ratio, setRatio] = useState(null); // 가로 ÷ 세로
  const onLoad = (event) => {
    const { width, height } = event?.source ?? {};
    if (width && height) setRatio(width / height);
  };
  // 원본을 보여 줄 때는 사진 비율대로, 확대한 조각은 정해진 높이 안에 맞춘다
  const shape = box ? { aspectRatio: ratio ?? 4 / 3 } : { height: 260 };
  return (
    <View style={[styles.stage, shape]}>
      <AuthImage path={path} contentFit="contain" style={StyleSheet.absoluteFill} accessibilityLabel={label} onLoad={onLoad} />
      {box ? <View style={[styles.box, zoomBoxStyle(box)]} pointerEvents="none" /> : null}
      {badge ? <Text style={styles.badge}>{badge}</Text> : null}
      {note ? <Text style={styles.note}>{note}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  stage: { width: "100%", borderRadius: radius.card, backgroundColor: "#CDB9A3", overflow: "hidden" },
  box: { position: "absolute", borderWidth: 3, borderColor: colors.background, borderRadius: 6, backgroundColor: "rgba(255,252,247,0.25)" },
  badge: { position: "absolute", left: 14, top: 12, paddingVertical: 4, paddingHorizontal: 10, borderRadius: 999, overflow: "hidden", backgroundColor: colors.background, fontSize: 13, fontFamily: fonts.bold, color: colors.text },
  note: { position: "absolute", left: 0, right: 0, bottom: 12, textAlign: "center", fontSize: 13, color: "#3A2719" },
});
