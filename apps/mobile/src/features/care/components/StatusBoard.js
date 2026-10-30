import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import { colors, font } from "@/theme";

import DailyCheckTab from "./DailyCheckTab";
import MealBar from "./MealBar";
import MissingBanner from "./MissingBanner";

/**
 * 현황판: 오늘 끼니와 체크 진행을 크게 보여 주는 첫 화면. 데일리 체크 입력은 "기록하기"로 펼친다.
 * 기록이 없어도 건강에 문제가 있다는 뜻은 아니다(누락은 서버가 예정 시각 + 60분으로 계산).
 * @param {{ daily: import("../api").Daily, reload: () => Promise<void>, notify: (text: string, isError?: boolean) => void, children?: import("react").ReactNode }} props children: 끼니·체크 아래에 붙일 카드(정산 요약 등)
 */
export default function StatusBoard({ daily, reload, notify, children }) {
  const [open, setOpen] = useState(false);
  const total = daily.items.length;
  const done = daily.done_ids.length;
  const missing = daily.missing_ids.length;

  return (
    <View style={styles.wrap} testID="status-board">
      <MealBar meals={daily.meals ?? []} large />

      <Card tone="blue">
        <Text style={styles.label}>오늘 체크</Text>
        <Text style={styles.big} testID="check-progress">
          {total === 0 ? "항목이 없어요" : `${done} / ${total} 완료`}
        </Text>
        {missing > 0 ? <Text style={styles.caption}>기록하지 못한 항목 {missing}개</Text> : null}
        <Button small label={open ? "접기" : "기록하기"} a11yLabel={open ? "체크 입력 접기" : "체크 기록하기"} onPress={() => setOpen(!open)} />
      </Card>

      {open ? <DailyCheckTab daily={daily} reload={reload} notify={notify} /> : <MissingBanner daily={daily} onOpen={() => setOpen(true)} />}

      {children}
      <Text style={styles.notice}>오늘 기록이 없어도 건강에 문제가 있다는 뜻은 아니에요.</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
  label: { ...font.caption, color: colors.primaryDark, fontWeight: "600" },
  big: { ...font.h1, color: colors.text },
  caption: { ...font.caption, color: colors.textSub },
  notice: { ...font.caption, color: colors.textMuted },
});
