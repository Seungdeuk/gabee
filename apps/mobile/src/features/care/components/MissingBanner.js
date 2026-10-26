import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import { colors, font } from "@/theme";

/**
 * 누락 알림 배너: 예정 시각 + 60분이 지나도 기록하지 않은 항목이 있으면 다른 탭(추천·식단·위치)에서도 알려 준다.
 * 앱 안 배너만이다(푸시는 후속). 누락은 서버가 계산한 `missing_ids` 를 그대로 쓴다.
 * @param {{ daily: import("../api").Daily, onOpen: () => void }} props onOpen: 데일리 체크로 이동
 */
export default function MissingBanner({ daily, onOpen }) {
  const missing = daily.items.filter((i) => daily.missing_ids.includes(i.id));
  if (missing.length === 0) return null;

  const names = missing.map((i) => i.name);
  const shown = names.length > 3 ? `${names.slice(0, 3).join(", ")} 외 ${names.length - 3}개` : names.join(", ");

  return (
    <View testID="missing-banner">
      <Card tone="orange">
        <View style={styles.row}>
          <View style={styles.text}>
            <Text style={styles.title}>기록하지 못한 항목 {missing.length}개</Text>
            <Text style={styles.caption}>{shown} · 소급 입력하거나 건너뛸 수 있어요</Text>
          </View>
          <Button small label="확인하기" a11yLabel="누락 항목 확인하기" onPress={onOpen} />
        </View>
      </Card>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 12 },
  text: { flex: 1, gap: 2 },
  title: { ...font.bodyStrong, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
});
