import { useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, fonts, radius } from "@/theme";

import LoadNote from "../components/LoadNote";
import PlayScreen from "../components/PlayScreen";
import SectionHead from "../components/SectionHead";
import TurnRow from "../components/TurnRow";
import { usePlayBoard } from "../hooks";

/** 놀이터 현황: 받은/보낸 토글. 받은 = 내가 할 차례 + 내가 참여했어요 + 지난 결과(최근 3일), 보낸 = 내가 낸 문제 + 지난 결과. */
export default function PlayBoardScreen() {
  const board = usePlayBoard(); // 서버 주소가 없으면 시안 데이터(닫은 폭탄 방은 뺀 채)
  const { tab: startTab } = useLocalSearchParams();
  const [tab, setTab] = useState(startTab === "sent" ? "sent" : "recv");
  const { todo, waiting, past, sent, sentPast } = board.data ?? {};
  return (
    <PlayScreen title="놀이터 현황" close>
      <View style={styles.toggle}>
        <Tab label="받은" on={tab === "recv"} onPress={() => setTab("recv")} />
        <Tab label="보낸" on={tab === "sent"} onPress={() => setTab("sent")} />
      </View>
      <LoadNote {...board} what="현황" />
      {!board.data ? null : tab === "recv" ? (
        <>
          <SectionHead title="내가 할 차례" right={`${todo.length}개`} />
          {todo.map((item) => (
            <TurnRow key={item.id} item={recvProgress(item, false)} strong={item.strong} />
          ))}
          <SectionHead title="내가 참여했어요" right={`${waiting.length}개`} />
          {waiting.map((item) => (
            <TurnRow key={item.id} item={recvProgress(item, true)} done />
          ))}
          <SectionHead title="지난 결과" right="최근 3일" />
          {past.map((item) => (
            <TurnRow key={item.id} item={item} />
          ))}
        </>
      ) : (
        <>
          <SectionHead title="내가 낸 문제" right={`${sent.length}개`} />
          {sent.map((item) => (
            <TurnRow key={item.id} item={progressSub(item)} strong={item.game === "bomb"} />
          ))}
          <SectionHead title="지난 결과" right="최근 3일" />
          {sentPast.map((item) => (
            <TurnRow key={item.id} item={item} />
          ))}
          <Text style={styles.note}>같은 게임도 여러 개 낼 수 있어요</Text>
        </>
      )}
    </PlayScreen>
  );
}

/** 보낸 문제의 둘째 줄에 "공개 시각 N/M"를 붙인다(가족별 칩 대신). 진행 정보가 없는 항목(폭탄 방)은 그대로. */
function progressSub(item) {
  if (!item.done && !item.pending) return item;
  const total = item.done.length + item.pending.length;
  return { ...item, progress: `${item.done.length}/${total}` };
}

/** 받은 문제의 둘째 줄에 "공개 시각 N/M". M 은 문제를 낸 사람을 뺀 가족(나 포함), 내가 끝냈으면 N 에 나도 센다. 폭탄 방은 그대로. */
function recvProgress(item, mineDone) {
  if (!item.done) return item;
  const total = item.done.length + item.pending.length + 1;
  const count = item.done.length + (mineDone ? 1 : 0);
  return { ...item, sub: `${item.reveal} 공개`, progress: `${count}/${total}` };
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
  note: { ...font.caption, color: colors.textSub, textAlign: "center" },
});
