import { useCallback, useEffect, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

// 지갑 탭에서는 정산·지출·용돈과 월말 정산 알림만 쓴다. 공동구독·정산 요약·결제일 알림·위치 가져오기는 주석 처리해 두었다(다시 켤 때 되돌린다).
import { MoneySection, MonthSwitcher, ReminderBanner, currentMonth } from "@/features/billing/public";
// import { SettleSummary, SubscriptionTab, UpcomingBanner } from "@/features/billing/public"; // 정산 요약·공동구독·결제일 알림은 뺐다
import Screen from "@/shared/components/Screen";
import { colors, font } from "@/theme";

// import LocationDisabled from "../components/LocationDisabled";
import { LOCATION_ENABLED } from "../location/enabled";
import { stopBackground } from "../location/sharing";

/**
 * 지갑 탭: 정산·지출·용돈(엔빵)과 월말 정산 알림.
 * 데일리 체크(현황판)와 돌봄 임시 화면은 지갑 탭 개편 때 지웠다.
 */
export default function CareScreen() {
  const [month, setMonth] = useState(currentMonth());
  const [message, setMessage] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0); // 무언가 바뀌면 월말 정산 알림과 정산 화면도 다시 확인한다
  const [moneyKey, setMoneyKey] = useState(0); // 알림의 "정산하기"를 누르면 정산 구역으로 돌아가도록 정산·지출·용돈 구역을 다시 연다
  const timer = useRef(null);

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
      {message ? (
        <View style={[styles.message, message.isError && styles.messageError]} accessibilityLiveRegion="polite" testID="message">
          <Text style={[styles.messageText, message.isError && styles.messageTextError]}>{message.text}</Text>
        </View>
      ) : null}

      <MonthSwitcher month={month} onChange={setMonth} />
      <ReminderBanner refreshKey={refreshKey} onOpen={() => setMoneyKey((k) => k + 1)} />

      <MoneySection key={moneyKey} month={month} notify={notify} refreshKey={refreshKey} />
      {/* 공동구독·위치 구역은 뺐다.
      {section === "subscription" ? <SubscriptionTab month={month} notify={notify} /> : null}
      {section === "location" ? <LocationDisabled /> : null} */}
    </Screen>
  );
}

const styles = StyleSheet.create({
  message: { backgroundColor: colors.successSoft, borderRadius: 14, paddingHorizontal: 14, paddingVertical: 10 },
  messageError: { backgroundColor: colors.dangerSoft },
  messageText: { ...font.caption, color: colors.success, fontWeight: "600" },
  messageTextError: { color: colors.danger },
});
