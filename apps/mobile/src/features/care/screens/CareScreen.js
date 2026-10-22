import { useCallback, useEffect, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { isApiConfigured } from "@/shared/api/client";
import Screen from "@/shared/components/Screen";
import Segmented from "@/shared/components/Segmented";
import { colors, font } from "@/theme";

import CarePreview from "../components/CarePreview";
import DailyCheckTab from "../components/DailyCheckTab";
import LocationTab from "../components/LocationTab";
import MealTab from "../components/MealTab";
import RecommendTab from "../components/RecommendTab";

const SECTIONS = [
  { key: "check", label: "데일리 체크" },
  { key: "recommend", label: "추천" },
  { key: "meal", label: "식단" },
  { key: "location", label: "위치" },
];

/**
 * 돌봄 탭: 데일리 체크, 추천, 식단 추천, 위치 확인(예시).
 * 서버 주소(EXPO_PUBLIC_API_URL)가 없으면 임시 데이터 화면을 보여 준다.
 */
export default function CareScreen() {
  if (!isApiConfigured()) return <CarePreview />;
  return <CareLive />;
}

function CareLive() {
  const [section, setSection] = useState("check");
  const [message, setMessage] = useState(null);
  const timer = useRef(null);

  const notify = useCallback((text, isError = false) => {
    setMessage({ text, isError });
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setMessage(null), 3500);
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <Screen title="돌봄" subtitle="데일리 체크 · 추천 · 식단 · 위치">
      <Segmented options={SECTIONS} value={section} onChange={setSection} />

      {message ? (
        <View style={[styles.message, message.isError && styles.messageError]} accessibilityLiveRegion="polite" testID="message">
          <Text style={[styles.messageText, message.isError && styles.messageTextError]}>{message.text}</Text>
        </View>
      ) : null}

      {section === "check" ? <DailyCheckTab notify={notify} /> : null}
      {section === "recommend" ? <RecommendTab notify={notify} /> : null}
      {section === "meal" ? <MealTab notify={notify} /> : null}
      {section === "location" ? <LocationTab notify={notify} /> : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  message: { backgroundColor: colors.successSoft, borderRadius: 14, paddingHorizontal: 14, paddingVertical: 10 },
  messageError: { backgroundColor: colors.dangerSoft },
  messageText: { ...font.caption, color: colors.success, fontWeight: "600" },
  messageTextError: { color: colors.danger },
});
