import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { getReminder } from "../api";
import { won } from "../format";

/**
 * 월말 정산 알림 배너. 정산 담당자에게만 보인다(서버가 show 를 정한다).
 * 정산하기를 안 한 지출이 있을 때, 월말 5일 전부터(월초 5일까지는 지난 달이 밀렸을 때) 알려 준다.
 * @param {{ refreshKey: number, onOpen: () => void }} props refreshKey: 바뀌면 다시 불러온다. onOpen: 정산 탭으로 이동
 */
export default function ReminderBanner({ refreshKey, onOpen }) {
  const { data } = useResource(getReminder, refreshKey);
  if (!data?.show) return null;

  const when =
    data.kind === "month_end"
      ? data.days_left === 0
        ? "오늘이 월말이에요"
        : `월말까지 ${data.days_left}일 남았어요`
      : `${data.month} 정산이 아직 남아 있어요`;

  return (
    <Card tone="orange" testID="reminder">
      <View style={styles.row}>
        <View style={styles.text}>
          <Text style={styles.title}>정산 안 한 지출 {data.unsettled_count}건 · {won(data.unsettled_total)}</Text>
          <Text style={styles.caption}>{when} · 담당자에게만 보여요</Text>
        </View>
        <Button small label="정산하기" a11yLabel="정산하러 가기" onPress={onOpen} />
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 12 },
  text: { flex: 1, gap: 2 },
  title: { ...font.bodyStrong, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
});
