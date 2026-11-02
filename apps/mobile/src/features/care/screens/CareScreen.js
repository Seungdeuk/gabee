import { useCallback, useEffect, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { MoneySection, MonthSwitcher, ReminderBanner, SettleSummary, SubscriptionTab, UpcomingBanner, currentMonth } from "@/features/billing/public";
import { isApiConfigured } from "@/shared/api/client";
import useResource from "@/shared/hooks/useResource";
import Screen from "@/shared/components/Screen";
import Segmented from "@/shared/components/Segmented";
import { colors, font } from "@/theme";

import { getDaily } from "../api";
import CarePreview from "../components/CarePreview";
import LocationDisabled from "../components/LocationDisabled";
import StatusBoard from "../components/StatusBoard";
import { LOCATION_ENABLED } from "../location/enabled";
import { stopBackground } from "../location/sharing";

const SECTIONS = [
  { key: "board", label: "현황판" },
  { key: "money", label: "정산·용돈" },
  { key: "subscription", label: "공동구독" },
  { key: "location", label: "위치" },
];

/**
 * 돌봄 탭(가계 병합): 현황판, 정산·용돈(엔빵), 공동구독(OTT·통신비), 위치(지금은 사용 불가).
 * 서버 주소(EXPO_PUBLIC_API_URL)가 없으면 임시 데이터 화면을 보여 준다.
 */
export default function CareScreen() {
  if (!isApiConfigured()) return <CarePreview />;
  return <CareLive />;
}

function CareLive() {
  const [section, setSection] = useState("board");
  const [month, setMonth] = useState(currentMonth());
  const [message, setMessage] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0); // 무언가 바뀌면 월말·결제 알림과 정산 요약도 다시 확인한다
  const timer = useRef(null);
  const daily = useResource(getDaily); // 현황판의 끼니·체크가 같이 쓴다
  const { reload: reloadDaily } = daily;

  // 시각에 따라 다가오는 일정·누락이 바뀌므로 1분마다 다시 불러온다
  useEffect(() => {
    const id = setInterval(reloadDaily, 60 * 1000);
    return () => clearInterval(id);
  }, [reloadDaily]);

  // 위치 기능을 꺼 두었으면, 이전에 켜 둔 백그라운드 위치 공유도 멈춘다
  useEffect(() => {
    if (!LOCATION_ENABLED) stopBackground().catch(() => {});
  }, []);

  const notify = useCallback((text, isError = false) => {
    setMessage({ text, isError });
    setRefreshKey((k) => k + 1);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setMessage(null), 3500);
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);

  const money = section === "money";
  return (
    <Screen title="일상의 안녕" settings>
      <Segmented options={SECTIONS} value={section} onChange={setSection} />

      {message ? (
        <View style={[styles.message, message.isError && styles.messageError]} accessibilityLiveRegion="polite" testID="message">
          <Text style={[styles.messageText, message.isError && styles.messageTextError]}>{message.text}</Text>
        </View>
      ) : null}

      {money || section === "subscription" ? <MonthSwitcher month={month} onChange={setMonth} /> : null}
      {section !== "location" ? <ReminderBanner refreshKey={refreshKey} onOpen={() => setSection("money")} /> : null}

      {section === "board" && !daily.data ? <Text style={styles.muted}>{daily.error || "불러오는 중…"}</Text> : null}
      {section === "board" && daily.data ? (
        <StatusBoard daily={daily.data} reload={reloadDaily} notify={notify}>
          <SettleSummary month={month} refreshKey={refreshKey} onOpen={() => setSection("money")} />
          <UpcomingBanner refreshKey={`${refreshKey}-${section}`} onOpen={() => setSection("subscription")} />
        </StatusBoard>
      ) : null}
      {money ? <MoneySection month={month} notify={notify} refreshKey={refreshKey} /> : null}
      {section === "subscription" ? <SubscriptionTab month={month} notify={notify} /> : null}
      {section === "location" ? <LocationDisabled /> : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  message: { backgroundColor: colors.successSoft, borderRadius: 14, paddingHorizontal: 14, paddingVertical: 10 },
  messageError: { backgroundColor: colors.dangerSoft },
  messageText: { ...font.caption, color: colors.success, fontWeight: "600" },
  messageTextError: { color: colors.danger },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 8 },
});
