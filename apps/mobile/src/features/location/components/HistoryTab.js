import { useState } from "react";
import { StyleSheet, View } from "react-native";

import Card from "@/shared/components/Card";

import { todayKst } from "../timelineView";
import TimelineCard from "./TimelineCard";
import WeekCalendar from "./WeekCalendar";

/**
 * '이동 기록' 하위 탭: 일주일 달력으로 날짜를 고르면 그날의 타임라인을 보인다. 고른 날짜는 다른 탭에 갔다 와도 유지된다(이 탭이 계속 살아 있다).
 * @param {{ members: import("../api").MemberLocation[], canSeeFamily: boolean, refreshKey: number, notify: (text: string, isError?: boolean) => void }} props
 */
export default function HistoryTab({ members, canSeeFamily, refreshKey, notify }) {
  const [date, setDate] = useState(todayKst());
  return (
    <View style={styles.wrap}>
      <Card tone="white">
        <WeekCalendar date={date} onChange={setDate} />
      </Card>
      <TimelineCard date={date} members={members} canSeeFamily={canSeeFamily} refreshKey={refreshKey} notify={notify} />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
});
