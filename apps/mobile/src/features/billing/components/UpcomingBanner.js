import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { getUpcomingPayments } from "../api";
import { won } from "../format";

/** @param {number} days 남은 일수 @returns {string} */
const whenText = (days) => (days === 0 ? "오늘 결제" : `${days}일 뒤 결제`);

/**
 * 구독 결제일 알림 배너. 결제일이 3일 안(오늘 포함)으로 다가온 구독을 그 항목의 결제한 사람에게만 알린다(서버가 정한다).
 * 앱 안 배너만이다(푸시는 후속). 이번 달 구독료 지출을 아직 안 만들었으면 그것도 알려 준다.
 * @param {{ refreshKey: string | number, onOpen: () => void }} props refreshKey: 바뀌면 다시 불러온다. onOpen: 구독 탭으로 이동
 */
export default function UpcomingBanner({ refreshKey, onOpen }) {
  const { data } = useResource(getUpcomingPayments, refreshKey);
  if (!data?.show) return null;

  return (
    <Card tone="orange" testID="upcoming">
      <View style={styles.row}>
        <View style={styles.text}>
          <Text style={styles.title}>곧 결제일이에요 · {data.items.length}건</Text>
          {data.items.map((i) => (
            <Text key={i.id} style={styles.caption} testID={`upcoming-${i.name}`}>
              {i.name} · {whenText(i.days_left)} ({i.due_date.slice(5)}) · {i.amount == null ? "금액 미입력" : won(i.amount)}
              {i.expense_made ? " · 지출 만들었어요" : " · 지출 아직 안 만들었어요"}
            </Text>
          ))}
          <Text style={styles.caption}>결제한 사람에게만 보여요</Text>
        </View>
        <Button small label="구독 보기" a11yLabel="구독 보러 가기" onPress={onOpen} />
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
