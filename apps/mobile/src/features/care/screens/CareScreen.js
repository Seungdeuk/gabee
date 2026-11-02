import { useCallback, useEffect, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

// 지갑 탭에서는 정산·지출·용돈만 쓴다. 나머지 가져오기는 주석 처리해 두었다(다시 켤 때 되돌린다).
import { MoneySection, MonthSwitcher, ReminderBanner, currentMonth } from "@/features/billing/public";
// import { SettleSummary, SubscriptionTab, UpcomingBanner } from "@/features/billing/public"; // 정산 요약·공동구독·결제일 알림은 뺐다
// import { isApiConfigured } from "@/shared/api/client";
// import useResource from "@/shared/hooks/useResource";
import Screen from "@/shared/components/Screen";
// import Segmented from "@/shared/components/Segmented";
import { colors, font } from "@/theme";

// import { getDaily } from "../api";
// import CarePreview from "../components/CarePreview";
// import LocationDisabled from "../components/LocationDisabled";
// import StatusBoard from "../components/StatusBoard";
import { LOCATION_ENABLED } from "../location/enabled";
import { stopBackground } from "../location/sharing";

// 돌봄 구역(현황판·공동구독·위치)은 팀 회의 결과로 지갑 탭에서 뺐다. 코드는 지우지 않고 주석으로 남긴다.
// const SECTIONS = [
//   { key: "board", label: "현황판" },
//   { key: "money", label: "정산·용돈" },
//   { key: "subscription", label: "공동구독" },
//   { key: "location", label: "위치" },
// ];

/**
 * 지갑 탭: 정산·지출·용돈(엔빵).
 * 서버 주소가 없을 때 돌봄 임시 데이터 화면(CarePreview)을 보여 주던 것은 내렸다(주석 처리).
 */
export default function CareScreen() {
  // if (!isApiConfigured()) return <CarePreview />;
  return <CareLive />;
}

function CareLive() {
  // const [section, setSection] = useState("board");
  const [month, setMonth] = useState(currentMonth());
  const [message, setMessage] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0); // 무언가 바뀌면 월말 정산 알림과 정산 화면도 다시 확인한다
  const [moneyKey, setMoneyKey] = useState(0); // 알림의 "정산하기"를 누르면 정산 구역으로 돌아가도록 정산·지출·용돈 구역을 다시 연다
  const timer = useRef(null);
  // const daily = useResource(getDaily); // 현황판의 끼니·체크가 같이 쓰던 것
  // const { reload: reloadDaily } = daily;

  // 시각에 따라 다가오는 일정·누락이 바뀌므로 1분마다 다시 불러오던 것(현황판용)
  // useEffect(() => {
  //   const id = setInterval(reloadDaily, 60 * 1000);
  //   return () => clearInterval(id);
  // }, [reloadDaily]);

  // 위치 기능을 꺼 두었으면, 이전에 켜 둔 백그라운드 위치 공유도 멈춘다(앱을 업데이트한 기기를 위해 남겨 둔다)
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

  return (
    <Screen title="지갑">
      {/* <Segmented options={SECTIONS} value={section} onChange={setSection} /> */}

      {message ? (
        <View style={[styles.message, message.isError && styles.messageError]} accessibilityLiveRegion="polite" testID="message">
          <Text style={[styles.messageText, message.isError && styles.messageTextError]}>{message.text}</Text>
        </View>
      ) : null}

      <MonthSwitcher month={month} onChange={setMonth} />
      <ReminderBanner refreshKey={refreshKey} onOpen={() => setMoneyKey((k) => k + 1)} />

      {/* {section === "board" && !daily.data ? <Text style={styles.muted}>{daily.error || "불러오는 중…"}</Text> : null}
      {section === "board" && daily.data ? (
        <StatusBoard daily={daily.data} reload={reloadDaily} notify={notify}>
          <SettleSummary month={month} refreshKey={refreshKey} onOpen={() => setSection("money")} />
          <UpcomingBanner refreshKey={`${refreshKey}-${section}`} onOpen={() => setSection("subscription")} />
        </StatusBoard>
      ) : null} */}
      <MoneySection key={moneyKey} month={month} notify={notify} refreshKey={refreshKey} />
      {/* {section === "subscription" ? <SubscriptionTab month={month} notify={notify} /> : null} */}
      {/* {section === "location" ? <LocationDisabled /> : null} */}
    </Screen>
  );
}

const styles = StyleSheet.create({
  message: { backgroundColor: colors.successSoft, borderRadius: 14, paddingHorizontal: 14, paddingVertical: 10 },
  messageError: { backgroundColor: colors.dangerSoft },
  messageText: { ...font.caption, color: colors.success, fontWeight: "600" },
  messageTextError: { color: colors.danger },
  // muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 8 },
});
