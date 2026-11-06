import { StyleSheet, Text } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import { colors, font } from "@/theme";

/**
 * 위치 공유에 동의하기 전에 보이는 유일한 화면(지도·기록 없음). 동의해야 하위 탭이 열린다.
 * @param {{ onAgree: () => void, busy: boolean }} props
 */
export default function ConsentGate({ onAgree, busy }) {
  return (
    <Card tone="white">
      <Text style={styles.title}>위치 공유(베타)</Text>
      <Text style={styles.caption}>
        시연용 베타예요. 동의한 사람의 위치만 모으고, 평소 활동 구역을 벗어나면 부모님께 알려요. 알림에는 위치가 담기지 않아요.
      </Text>
      <Text style={styles.caption}>언제든 끄고 내 기록을 지울 수 있어요. 급한 일은 112로 연락하세요.</Text>
      <Button label="위치 공유에 동의하고 시작" onPress={onAgree} disabled={busy} testID="location-agree" />
    </Card>
  );
}

const styles = StyleSheet.create({
  title: { ...font.bodyStrong, color: colors.text },
  caption: { ...font.caption, color: colors.textSub },
});
