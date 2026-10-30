import { StyleSheet, Text } from "react-native";

import Card from "@/shared/components/Card";
import { colors, font } from "@/theme";

/** 위치 구역 자리에 보이는 안내. 위치 공유는 지금 쓸 수 없다(location/enabled.js). */
export default function LocationDisabled() {
  return (
    <Card tone="white" testID="location-disabled">
      <Text style={styles.title}>위치 확인은 준비 중이에요</Text>
      <Text style={styles.caption}>지금은 내 위치를 보내지도, 가족 위치를 보지도 않아요. 이미 켜 둔 위치 공유는 자동으로 꺼져요.</Text>
    </Card>
  );
}

const styles = StyleSheet.create({
  title: { ...font.bodyStrong, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
});
