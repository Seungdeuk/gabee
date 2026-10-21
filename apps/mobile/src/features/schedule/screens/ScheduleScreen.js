import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text } from "react-native";

import Card from "@/shared/components/Card";
import ListItem from "@/shared/components/ListItem";
import Screen from "@/shared/components/Screen";
import SectionTitle from "@/shared/components/SectionTitle";
import { colors, font } from "@/theme";

import { events } from "../mock";

/** 일정 탭: 가족 공동 일정 목록. */
export default function ScheduleScreen() {
  return (
    <Screen
      title="일정"
      subtitle="함께하는 하루를 챙겨요"
      right={
        <Pressable accessibilityLabel="일정 추가" style={styles.add}>
          <Ionicons name="add" size={24} color={colors.text} />
        </Pressable>
      }
    >
      <SectionTitle title="오늘과 내일 일정" action="전체 보기" />
      <Card tone="white">
        {events.map((event) => (
          <ListItem
            key={event.id}
            icon={event.icon}
            tone={event.tone}
            title={`${event.when} · ${event.title}`}
            subtitle={event.note}
          />
        ))}
      </Card>

      <Card tone="orange">
        <Text style={styles.cardTitle}>확인이 필요한 일 1건</Text>
        <Text style={styles.cardSub}>10.11 저녁 약 복용 여부 미확인. 미확인은 미복용을 뜻하지 않아요.</Text>
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({
  add: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  cardTitle: {
    ...font.cardTitle,
    color: colors.text,
  },
  cardSub: {
    ...font.body,
    color: colors.textSub,
  },
});
