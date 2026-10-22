import { StyleSheet, Text } from "react-native";

import Card from "@/shared/components/Card";
import ListItem from "@/shared/components/ListItem";
import Screen from "@/shared/components/Screen";
import SectionTitle from "@/shared/components/SectionTitle";
import Tag from "@/shared/components/Tag";
import { colors, font } from "@/theme";

import { checks, today } from "../mock";

/** 서버 주소(EXPO_PUBLIC_API_URL)가 없을 때 보여 주는 임시 데이터 화면. */
export default function CarePreview() {
  return (
    <Screen title="돌봄" subtitle="부모님의 오늘을 함께 살펴봐요">
      <Card tone="blue">
        <Text style={styles.date}>{today.date}</Text>
        <Text style={styles.heading}>{today.person}의 오늘을 함께 살펴봐요</Text>
        <Text style={styles.quote}>“{today.quote}”</Text>
        <Text style={styles.source}>{today.source}</Text>
      </Card>

      <SectionTitle title="오늘 체크" />
      <Card tone="white">
        {checks.map((item) => (
          <ListItem
            key={item.id}
            icon={item.icon}
            tone={item.tone}
            title={item.title}
            subtitle={item.note}
            right={<Tag label={item.status} tone={item.tone} />}
          />
        ))}
      </Card>

      <Text style={styles.notice}>오늘 기록이 없어도 건강에 문제가 있다는 뜻은 아니에요.</Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  date: {
    ...font.caption,
    color: colors.primaryDark,
    fontWeight: "600",
  },
  heading: {
    ...font.h1,
    color: colors.text,
  },
  quote: {
    ...font.body,
    color: colors.textSub,
  },
  source: {
    ...font.caption,
    color: colors.textMuted,
  },
  notice: {
    ...font.caption,
    color: colors.textMuted,
  },
});
