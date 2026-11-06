import { useCallback, useEffect, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

// 지갑 탭에서는 정산 요약·정산·지출·용돈과 월말 정산 알림만 쓴다. 공동구독·결제일 알림·위치 가져오기는 주석 처리해 두었다(다시 켤 때 되돌린다).
import { MoneySection, MonthSwitcher, ReminderBanner, SettleSummary, currentMonth } from "@/features/billing/public";
// import { SubscriptionTab, UpcomingBanner } from "@/features/billing/public"; // 공동구독·결제일 알림은 뺐다
import { LocationSection } from "@/features/location/public";
import Screen from "@/shared/components/Screen";
import Segmented from "@/shared/components/Segmented";
import { colors, font } from "@/theme";

const PARTS = [
  { key: "wallet", label: "지갑" },
  { key: "location", label: "위치" },
];

/**
 * 돌봄 탭(위치 베타 브랜치): 지갑(정산·지출·용돈과 월말 정산 알림)과 위치 공유(베타).
 * 위치 구역은 feature/hojenn-location-beta 에만 있고 release/1.2 에 병합하지 않는다.
 */
export default function CareScreen() {
  const [part, setPart] = useState("wallet");
  const [month, setMonth] = useState(currentMonth());
  const [message, setMessage] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0); // 무언가 바뀌면 월말 정산 알림과 정산 화면도 다시 확인한다
  const [moneyKey, setMoneyKey] = useState(0); // 알림의 "정산하기"를 누르면 정산 구역으로 돌아가도록 정산·지출·용돈 구역을 다시 연다
  const timer = useRef(null);

  const notify = useCallback((text, isError = false) => {
    setMessage({ text, isError });
    setRefreshKey((k) => k + 1);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setMessage(null), 3500);
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <Screen title="돌봄">
      {message ? (
        <View style={[styles.message, message.isError && styles.messageError]} accessibilityLiveRegion="polite" testID="message">
          <Text style={[styles.messageText, message.isError && styles.messageTextError]}>{message.text}</Text>
        </View>
      ) : null}

      <Segmented options={PARTS} value={part} onChange={setPart} />

      {part === "wallet" ? (
        <>
          <MonthSwitcher month={month} onChange={setMonth} />
          <SettleSummary month={month} refreshKey={refreshKey} onOpen={() => setMoneyKey((k) => k + 1)} />
          <ReminderBanner refreshKey={refreshKey} onOpen={() => setMoneyKey((k) => k + 1)} />

          <MoneySection key={moneyKey} month={month} notify={notify} refreshKey={refreshKey} />
        </>
      ) : (
        <LocationSection notify={notify} />
      )}
      {/* 공동구독 구역은 뺐다.
      {section === "subscription" ? <SubscriptionTab month={month} notify={notify} /> : null} */}
    </Screen>
  );
}

const styles = StyleSheet.create({
  message: { backgroundColor: colors.successSoft, borderRadius: 14, paddingHorizontal: 14, paddingVertical: 10 },
  messageError: { backgroundColor: colors.dangerSoft },
  messageText: { ...font.caption, color: colors.success, fontWeight: "600" },
  messageTextError: { color: colors.danger },
});
