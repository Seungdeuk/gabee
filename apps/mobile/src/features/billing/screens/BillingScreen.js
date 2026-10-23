import { Ionicons } from "@expo/vector-icons";
import { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { isApiConfigured } from "@/shared/api/client";
import Screen from "@/shared/components/Screen";
import Segmented from "@/shared/components/Segmented";
import { colors, font } from "@/theme";

import AllowanceTab from "../components/AllowanceTab";
import BillingPreview from "../components/BillingPreview";
import ExpenseTab from "../components/ExpenseTab";
import ReminderBanner from "../components/ReminderBanner";
import SettlementTab from "../components/SettlementTab";
import SubscriptionTab from "../components/SubscriptionTab";
import { currentMonth, shiftMonth } from "../format";

const SECTIONS = [
  { key: "settle", label: "정산" },
  { key: "expense", label: "지출" },
  { key: "allowance", label: "용돈" },
  { key: "subscription", label: "구독·통신" },
];

/**
 * 가계 탭: 정산, 지출, 용돈, 구독·통신비 가족 할인 상태.
 * 서버 주소(EXPO_PUBLIC_API_URL)가 없으면 임시 데이터 화면을 보여 준다.
 */
export default function BillingScreen() {
  if (!isApiConfigured()) return <BillingPreview />;
  return <BillingLive />;
}

function BillingLive() {
  const [section, setSection] = useState("settle");
  const [month, setMonth] = useState(currentMonth());
  const [message, setMessage] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0); // 무언가 바뀌면 월말 알림도 다시 확인한다
  const timer = useRef(null);

  const notify = useCallback((text, isError = false) => {
    setMessage({ text, isError });
    setRefreshKey((k) => k + 1);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setMessage(null), 3500);
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <Screen title="가계" subtitle="정산 · 지출 · 용돈 · 가족 할인 상태">
      <View style={styles.monthRow}>
        <Pressable onPress={() => setMonth(shiftMonth(month, -1))} accessibilityRole="button" accessibilityLabel="이전 달" style={styles.arrow}>
          <Ionicons name="chevron-back" size={22} color={colors.text} />
        </Pressable>
        <Text style={styles.month} testID="month-label">
          {month}
        </Text>
        <Pressable onPress={() => setMonth(shiftMonth(month, 1))} accessibilityRole="button" accessibilityLabel="다음 달" style={styles.arrow}>
          <Ionicons name="chevron-forward" size={22} color={colors.text} />
        </Pressable>
      </View>

      <ReminderBanner refreshKey={refreshKey} onOpen={() => setSection("settle")} />

      <Segmented options={SECTIONS} value={section} onChange={setSection} />

      {message ? (
        <View style={[styles.message, message.isError && styles.messageError]} accessibilityLiveRegion="polite" testID="message">
          <Text style={[styles.messageText, message.isError && styles.messageTextError]}>{message.text}</Text>
        </View>
      ) : null}

      {section === "settle" ? <SettlementTab month={month} notify={notify} refreshKey={refreshKey} /> : null}
      {section === "expense" ? <ExpenseTab month={month} notify={notify} /> : null}
      {section === "allowance" ? <AllowanceTab notify={notify} /> : null}
      {section === "subscription" ? <SubscriptionTab month={month} notify={notify} /> : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  monthRow: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 16 },
  arrow: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  month: { ...font.title, color: colors.text, minWidth: 96, textAlign: "center" },
  message: { backgroundColor: colors.successSoft, borderRadius: 14, paddingHorizontal: 14, paddingVertical: 10 },
  messageError: { backgroundColor: colors.dangerSoft },
  messageText: { ...font.caption, color: colors.success, fontWeight: "600" },
  messageTextError: { color: colors.danger },
});
