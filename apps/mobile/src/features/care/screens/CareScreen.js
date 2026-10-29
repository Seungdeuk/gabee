import { useCallback, useEffect, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { isApiConfigured } from "@/shared/api/client";
import useResource from "@/shared/hooks/useResource";
import Screen from "@/shared/components/Screen";
import Segmented from "@/shared/components/Segmented";
import { colors, font } from "@/theme";

import { getDaily } from "../api";
import CarePreview from "../components/CarePreview";
import DailyCheckTab from "../components/DailyCheckTab";
import MealBar from "../components/MealBar";
import MealTab from "../components/MealTab";
import MissingBanner from "../components/MissingBanner";
import RecommendTab from "../components/RecommendTab";

const SECTIONS = [
  { key: "check", label: "데일리 체크" },
  { key: "recommend", label: "추천" },
  { key: "meal", label: "식단" },
  // 위치 탭은 출시 전 임시로 끔(백그라운드 위치 권한 심사 대응). 다시 켤 때 LocationTab 과 app.json 위치 권한을 함께 되돌린다
];

/**
 * 돌봄 탭: 데일리 체크, 추천, 식단 추천.
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
  const daily = useResource(getDaily); // 상단 고정 끼니 바와 데일리 체크가 같이 쓴다
  const { reload: reloadDaily } = daily;

  // 시각에 따라 다가오는 일정·누락이 바뀌므로 1분마다 다시 불러온다
  useEffect(() => {
    const id = setInterval(reloadDaily, 60 * 1000);
    return () => clearInterval(id);
  }, [reloadDaily]);

  const notify = useCallback((text, isError = false) => {
    setMessage({ text, isError });
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setMessage(null), 3500);
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <Screen
      title="일상의 안녕"
      settings
      pinned={
        <View>
          <View style={styles.tabsRow}>
            <Segmented options={SECTIONS} value={section} onChange={setSection} />
          </View>
          <MealBar meals={daily.data?.meals ?? []} />
        </View>
      }
    >
      {message ? (
        <View style={[styles.message, message.isError && styles.messageError]} accessibilityLiveRegion="polite" testID="message">
          <Text style={[styles.messageText, message.isError && styles.messageTextError]}>{message.text}</Text>
        </View>
      ) : null}

      {section !== "check" && daily.data ? <MissingBanner daily={daily.data} onOpen={() => setSection("check")} /> : null}
      {section === "check" && !daily.data ? <Text style={styles.muted}>{daily.error || "불러오는 중…"}</Text> : null}
      {section === "check" && daily.data ? <DailyCheckTab daily={daily.data} reload={reloadDaily} notify={notify} /> : null}
      {section === "recommend" ? <RecommendTab notify={notify} /> : null}
      {section === "meal" ? <MealTab notify={notify} onChanged={reloadDaily} /> : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  tabsRow: { paddingHorizontal: 20, paddingTop: 4, backgroundColor: colors.background },
  message: { backgroundColor: colors.successSoft, borderRadius: 14, paddingHorizontal: 14, paddingVertical: 10 },
  messageError: { backgroundColor: colors.dangerSoft },
  messageText: { ...font.caption, color: colors.success, fontWeight: "600" },
  messageTextError: { color: colors.danger },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 8 },
});
