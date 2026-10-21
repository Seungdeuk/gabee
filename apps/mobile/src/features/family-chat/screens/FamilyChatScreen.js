import { StyleSheet, Text } from "react-native";

import Card from "@/shared/components/Card";
import Screen from "@/shared/components/Screen";
import SectionTitle from "@/shared/components/SectionTitle";
import { colors, font } from "@/theme";

import MemberRow from "../components/MemberRow";
import { members, suggestion } from "../mock";

/** 소통 탭: 가족 구성원 목록과 오늘 건네기 좋은 말. */
export default function FamilyChatScreen() {
  return (
    <Screen title="소통">
      <SectionTitle title={`우리 가족 · ${members.length}명`} action="가족 초대" />
      <Card tone="white">
        {members.map((member) => (
          <MemberRow key={member.id} member={member} />
        ))}
      </Card>

      <Card tone="blue">
        <Text style={styles.label}>오늘 건네기 좋은 말</Text>
        <Text style={styles.quote}>“{suggestion.text}”</Text>
        <Text style={styles.source}>출처 · {suggestion.source}</Text>
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
  quote: {
    ...font.cardTitle,
    color: colors.text,
    lineHeight: 24,
  },
  source: {
    ...font.caption,
    color: colors.primaryDark,
  },
});
