import { useCallback, useEffect, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

// 지갑 탭에서는 정산 요약·정산·지출·용돈과 월말 정산 알림만 쓴다. 공동구독·결제일 알림·위치 가져오기는 주석 처리해 두었다(다시 켤 때 되돌린다).
import { MoneySection, MonthSwitcher, ReminderBanner, SettleSummary, currentMonth } from "@/features/billing/public";
// import { SubscriptionTab, UpcomingBanner } from "@/features/billing/public"; // 공동구독·결제일 알림은 뺐다
import Screen from "@/shared/components/Screen";
import { colors, font } from "@/theme";

/**
 * 지갑 탭: 정산·지출·용돈(엔빵)과 월말 정산 알림.
 * 돌봄(데일리 체크·현황판·위치)은 지웠다.
 * bell 은 상단 오른쪽 끝 알림 종이다(라우트에서 조립한다).
 * @param {{ bell?: import("react").ReactNode }} props
 */
export default function CareScreen({ bell = null }) {
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
    <Screen title="지갑" right={bell}>
      {message ? (
        <View style={[styles.message, message.isError && styles.messageError]} accessibilityLiveRegion="polite" testID="message">
          <Text style={[styles.messageText, message.isError && styles.messageTextError]}>{message.text}</Text>
        </View>
      ) : null}

      <MonthSwitcher month={month} onChange={setMonth} />
      <SettleSummary month={month} refreshKey={refreshKey} onOpen={() => setMoneyKey((k) => k + 1)} />
      <ReminderBanner refreshKey={refreshKey} onOpen={() => setMoneyKey((k) => k + 1)} />

      <MoneySection key={moneyKey} month={month} notify={notify} refreshKey={refreshKey} />
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
