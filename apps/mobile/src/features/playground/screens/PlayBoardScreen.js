import { useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, fonts, radius } from "@/theme";

import PlayScreen from "../components/PlayScreen";
import SectionHead from "../components/SectionHead";
import TurnRow from "../components/TurnRow";
import { openSent, PAST, SENT_PAST, TODO, WAITING } from "../mock";

/** 놀이터 현황: 받은/보낸 토글. 받은 = 내가 할 차례 + 내가 참여했어요 + 지난 결과(최근 3일), 보낸 = 내가 낸 문제 + 지난 결과. */
export default function PlayBoardScreen() {
  const sent = openSent(); // 닫은 방은 빼고 보여 준다
  const { tab: startTab } = useLocalSearchParams();
  const [tab, setTab] = useState(startTab === "sent" ? "sent" : "recv");
  return (
    <PlayScreen title="놀이터 현황" close>
      <View style={styles.toggle}>
        <Tab label={`받은 ${TODO.length}`} on={tab === "recv"} onPress={() => setTab("recv")} />
        <Tab label={`보낸 ${sent.length}`} on={tab === "sent"} onPress={() => setTab("sent")} />
      </View>
      {tab === "recv" ? (
        <>
          <SectionHead title="내가 할 차례" right={`${TODO.length}개`} />
          {TODO.map((item) => (
            <View key={item.id} style={styles.sentBox}>
              <TurnRow item={item} strong={item.strong} />
              <PeopleChips done={item.done} pending={item.pending} />
            </View>
          ))}
          <SectionHead title="내가 참여했어요" right={`${WAITING.length}개`} />
          {WAITING.map((item) => (
            <View key={item.id} style={styles.sentBox}>
              <TurnRow item={item} done />
              <PeopleChips done={item.done} pending={item.pending} />
            </View>
          ))}
          <SectionHead title="지난 결과" right="최근 3일" />
          {PAST.map((item) => (
            <TurnRow key={item.id} item={item} />
          ))}
        </>
      ) : (
        <>
          <SectionHead title="내가 낸 문제" right={`${sent.length}개`} />
          {sent.map((item) => (
            <View key={item.id} style={styles.sentBox}>
              <TurnRow item={item} />
              <PeopleChips done={item.done} pending={item.pending} />
            </View>
          ))}
          <SectionHead title="지난 결과" right="최근 3일" />
          {SENT_PAST.map((item) => (
            <TurnRow key={item.id} item={item} />
          ))}
          <Text style={styles.note}>같은 게임도 여러 개 낼 수 있어요</Text>
        </>
      )}
    </PlayScreen>
  );
}

/** 가족별 진행 칩: 한 사람은 초록 "완료", 아직 안 한 사람은 회색 "대기". 가족 전원을 모두 보여 준다. */
function PeopleChips({ done = [], pending = [] }) {
  if (!done.length && !pending.length) return null;
  return (
    <View style={styles.chips}>
      {done.map((n) => (
        <Text key={n} style={[styles.chip, styles.chipDone]}>
          {n} 완료
        </Text>
      ))}
      {pending.map((n) => (
        <Text key={n} style={styles.chip}>
          {n} 대기
        </Text>
      ))}
    </View>
  );
}

function Tab({ label, on, onPress }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="tab" accessibilityState={{ selected: on }} style={[styles.tab, on && styles.tabOn]}>
      <Text style={[styles.tabText, on && styles.tabTextOn]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  toggle: { flexDirection: "row", gap: 4, padding: 4, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card },
  tab: { flex: 1, height: 44, borderRadius: 12, alignItems: "center", justifyContent: "center" },
  tabOn: { backgroundColor: colors.surfaceStrong },
  tabText: { fontSize: 15, fontFamily: fonts.regular, color: colors.textSub },
  tabTextOn: { fontFamily: fonts.bold, color: colors.text },
  sentBox: { gap: 6 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6, paddingHorizontal: 4 },
  chip: { paddingVertical: 4, paddingHorizontal: 10, borderRadius: 12, overflow: "hidden", backgroundColor: colors.surface, color: colors.textSub, fontSize: 12, fontFamily: fonts.regular },
  chipDone: { backgroundColor: colors.successSoft, color: "#2F4A3B", fontFamily: fonts.bold },
  note: { ...font.caption, color: colors.textSub, textAlign: "center" },
});
