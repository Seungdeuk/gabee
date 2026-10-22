import { Image } from "expo-image";
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import SectionTitle from "@/shared/components/SectionTitle";
import Tag from "@/shared/components/Tag";
import { colors, font } from "@/theme";

import mascot from "../../../../assets/images/gabee-mascot.png";
import { getRecommendations } from "../api";

// 서버 규칙 이름을 화면에 보일 한글 이름으로 바꾼다.
const RULE_LABEL = { water: "물", walk: "산책", condition: "컨디션", supplement: "영양제", none: "안내" };

/**
 * 추천 버튼: 누르면 지금 기록을 보고 규칙 기반 추천(물, 산책, 컨디션, 영양제)을 보여 준다. 모델을 쓰지 않는다.
 * @param {{ notify: (text: string, isError?: boolean) => void }} props
 */
export default function RecommendTab({ notify }) {
  const [items, setItems] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    try {
      setItems((await getRecommendations()).recommendations);
    } catch (e) {
      notify(e.message, true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.wrap}>
      <Button label="추천 보기" onPress={load} disabled={busy} />
      {items === null ? (
        <Text style={styles.muted}>버튼을 누르면 지금 기록을 보고 규칙 기반 추천을 보여 줘요</Text>
      ) : (
        <>
          <SectionTitle title="오늘의 추천" />
          {items.map((r, i) => (
            <Card key={`${r.rule}-${i}`} tone="blue">
              <View style={styles.head}>
                <Image source={mascot} style={styles.mascot} contentFit="contain" accessibilityLabel="가비" />
                <View style={styles.grow}>
                  <Text style={styles.title}>가비의 다정한 제안</Text>
                  <Text style={styles.caption}>규칙 기반 · 참고용</Text>
                </View>
                <Tag label={RULE_LABEL[r.rule] ?? r.rule} tone="orange" />
              </View>
              <Text style={styles.text}>{r.text}</Text>
            </Card>
          ))}
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
  head: { flexDirection: "row", alignItems: "center", gap: 12 },
  grow: { flex: 1 },
  mascot: { width: 40, height: 40, borderRadius: 14, backgroundColor: colors.card },
  title: { ...font.bodyStrong, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
  text: { ...font.body, color: colors.text },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 16 },
});
