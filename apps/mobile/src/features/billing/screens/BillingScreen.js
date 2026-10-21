import { StyleSheet, Text } from "react-native";

import Card from "@/shared/components/Card";
import ListItem from "@/shared/components/ListItem";
import Screen from "@/shared/components/Screen";
import SectionTitle from "@/shared/components/SectionTitle";
import { colors, font } from "@/theme";

import { expenses, summary } from "../mock";

/** 가계 탭: 이번 달 공동 지출 요약과 내역. */
export default function BillingScreen() {
  return (
    <Screen title="가계">
      <Card tone="blue">
        <Text style={styles.label}>{summary.month} 공동 지출</Text>
        <Text style={styles.total}>{summary.total}</Text>
        <Text style={styles.note}>{summary.note}</Text>
      </Card>

      <SectionTitle title="최근 내역" action="전체 보기" />
      <Card tone="white">
        {expenses.map((item) => (
          <ListItem
            key={item.id}
            icon={item.icon}
            tone={item.tone}
            title={item.title}
            subtitle={item.note}
            right={item.amount}
          />
        ))}
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({
  label: {
    ...font.caption,
    color: colors.primaryDark,
    fontWeight: "600",
  },
  total: {
    fontSize: 30,
    fontWeight: "700",
    color: colors.text,
  },
  note: {
    ...font.caption,
    color: colors.textMuted,
  },
});
