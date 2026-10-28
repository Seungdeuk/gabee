import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useRef, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { isApiConfigured } from "@/shared/api/client";
import SettingsButton from "@/shared/components/SettingsButton";
import { colors, font, radius, spacing } from "@/theme";

import DaySection from "../components/DaySection";
import SuggestionCard from "../components/SuggestionCard";
import TogetherRow from "../components/TogetherRow";
import WeekStrip from "../components/WeekStrip";
import { useNewReceivedCount } from "../requests";
import { toggleChecked, useScheduleItems } from "../store";
import { draftDateOf, suggestionExtras } from "../suggestion_convert";
import { MOCK_SUGGESTIONS, SUGGESTIONS_DONE_TEXT, pickCheckCard } from "../suggestions";
import { useSuggestions } from "../suggestions_store";
import { addDays, formatDateLong, formatMonthDay, formatSlashDate, todayKey } from "../utils/date";

// 서버 주소가 있으면 추가 카드는 서버 추천을, 없으면 임시(mock) 제안을 쓴다.
const useServer = isApiConfigured();

const TOGETHER_SAMPLES = ["장 같이 봐줘", "병원 같이 가줘"];

/** 확인 버튼이 복숭아색으로 바뀐 걸 보여 준 뒤 다음 항목으로 넘어가기까지의 시간(ms). */
const CONFIRM_DELAY_MS = 200;

/** 같은 카드의 새로고침을 연달아 눌러도 이 시간(ms) 안에는 한 번만 바뀐다. */
const REFRESH_GAP_MS = 300;

/**
 * 일정 탭 메인: 헤더 + 주간 스트립 / 오늘·내일 / 함께하기 / 먼저 권해드려요 / 채팅 입력.
 * 카드를 누르면 상세로, 함께하기의 샘플·같이하기는 같이 보내기로, "주고 받은"은 같이의 메인 화면(주고 받은)으로 간다. 채팅으로 가는 이동은 채팅을 만들 때 연결한다.
 */
export default function ScheduleScreen() {
  const router = useRouter();
  const items = useScheduleItems();
  const newCount = useNewReceivedCount();
  const today = todayKey();
  const tomorrow = addDays(today, 1);

  // 카드마다 자기 새로고침이 있다(전체 새로고침은 없다). 확인 카드는 확인하지 않고 다른 항목을, 추가 카드는 다른 제안을 보여 준다.
  const [checkCursor, setCheckCursor] = useState(0);
  const [addCursor, setAddCursor] = useState(0);
  // "나중에"를 누른 카드는 복숭아색으로 표시된 채 그대로 남는다(다시 누르면 해제).
  const [later, setLater] = useState([]);
  // 방금 확인 버튼을 누른 항목. 복숭아색을 잠깐 보여 준 뒤 체크하고 다음 항목으로 넘어간다.
  const [pressed, setPressed] = useState(null);

  const server = useSuggestions();

  const checkCard = pickCheckCard(items, today, checkCursor);
  const draftDate = (suggestion) => draftDateOf(suggestion.draft, today);
  const isAdded = (suggestion) => items.some((item) => item.title === suggestion.draft.title && item.date === draftDate(suggestion));
  // 이미 추가한 제안은 빠지고 다음 제안이 바로 나온다. 저장하지 않고 돌아오면 그대로다.
  const candidates = (useServer ? server.list : MOCK_SUGGESTIONS).filter((suggestion) => !isAdded(suggestion));
  const addCard = candidates.length > 0 ? candidates[addCursor % candidates.length] : null;
  // 서버 추천은 불러오는 동안에는 카드를 숨기고, 불러온 뒤 보여 줄 게 없으면(다 씀·소진·못 불러옴) 마무리 카드를 보인다.
  const showAddArea = !useServer || addCard !== null || server.loaded;
  const toggleLater = (id) => {
    if (pressed === id) return;
    setLater((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };
  // 같은 카드의 두 버튼은 하나만 선택된 것으로 보인다. 확인 버튼을 누르면 나중에 표시는 바로 풀리고,
  // 확인 버튼은 복숭아색을 잠깐 보여 준 뒤 action 을 한다.
  const press = (id, action) => {
    if (pressed) return;
    setLater((prev) => prev.filter((x) => x !== id));
    setPressed(id);
    setTimeout(() => {
      action();
      setPressed(null);
    }, CONFIRM_DELAY_MS);
  };
  const lastRefresh = useRef({});
  // 카드마다 새로고침 연타를 막는다.
  const gated = (key, action) => () => {
    const now = Date.now();
    if (now - (lastRefresh.current[key] ?? 0) < REFRESH_GAP_MS) return;
    lastRefresh.current[key] = now;
    action();
  };
  const openCalendar = (date) => router.push({ pathname: "/schedule/calendar", params: { date } });
  const openDetail = (id) => router.push({ pathname: "/schedule/detail", params: { id } });
  const openTogether = (params) => router.push({ pathname: "/schedule/together", params });
  const openRegister = (params) => router.push({ pathname: "/schedule/register", params });
  // 제안으로 여는 등록 화면은 형태·제목·날짜가 미리 채워지고, 저장은 사용자가 확인한 뒤에만 된다.
  const openSuggested = (draft) => openRegister({ ...draft, suggested: "1" });
  const openDraft = (suggestion) => {
    setLater((prev) => prev.filter((x) => x !== suggestion.id));
    openSuggested({
      kind: suggestion.draft.kind,
      title: suggestion.draft.title,
      date: draftDate(suggestion),
      ...suggestionExtras(suggestion),
    });
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.body}>
          <View style={styles.topSection}>
            <View style={styles.head}>
              <View style={styles.headText}>
                <Text style={styles.title} accessibilityRole="header">
                  오늘도 차근차근
                </Text>
              </View>
              <Pressable
                onPress={() => openCalendar(today)}
                accessibilityRole="button"
                accessibilityLabel="달력 열기"
                style={styles.plus}
              >
                <Ionicons name="add" size={28} color={colors.text} />
              </Pressable>
              <SettingsButton />
            </View>
            <WeekStrip selected={today} markedDates={new Set(items.map((item) => item.date))} onSelect={openCalendar} />
          </View>

          <View style={styles.section}>
            <Text style={styles.heading}>{formatDateLong(today)}</Text>
            <DaySection
              label="오늘"
              items={items.filter((item) => item.date === today)}
              onPressItem={openDetail}
              onToggleItem={toggleChecked}
            />
            <DaySection
              label={`내일 · ${formatMonthDay(tomorrow)}`}
              items={items.filter((item) => item.date === tomorrow)}
              onPressItem={openDetail}
              onToggleItem={toggleChecked}
            />
            <Pressable onPress={() => openRegister({})} style={styles.addButton} accessibilityRole="button">
              <Text style={styles.addText}>+ 약속 · 할 일 추가하기</Text>
            </Pressable>
          </View>

          <View style={styles.section}>
            <View style={styles.caption}>
              <Text style={styles.heading}>함께하기</Text>
              <Pressable
                onPress={() => router.push("/schedule/together-status")}
                hitSlop={10}
                style={styles.statusPress}
                accessibilityRole="button"
                accessibilityLabel={newCount > 0 ? `주고 받은, 새로 받은 ${newCount}개` : "주고 받은"}
              >
                {newCount > 0 ? (
                  <View style={styles.newBadge}>
                    <Text style={styles.newBadgeText}>{newCount}</Text>
                  </View>
                ) : null}
                <Text style={styles.statusLink}>주고 받은 ›</Text>
              </Pressable>
            </View>
            <TogetherRow
              samples={TOGETHER_SAMPLES}
              onPressSample={(sample) => openTogether({ title: sample, suggested: "1" })}
              onPressTogether={() => openTogether({})}
            />
          </View>

          <View style={styles.section}>
            <Text style={styles.heading}>먼저 권해드려요</Text>
            <View style={styles.feed}>
              {checkCard ? (
                <SuggestionCard
                  text={checkCard.text}
                  primary={checkCard.label}
                  secondary={checkCard.laterLabel}
                  primarySelected={Boolean(checkCard.target) && pressed === checkCard.target.id}
                  secondarySelected={Boolean(checkCard.target) && later.includes(checkCard.target.id)}
                  onPrimary={() => press(checkCard.target.id, () => toggleChecked(checkCard.target.id))}
                  onSecondary={() => toggleLater(checkCard.target.id)}
                  onRefresh={checkCard.target ? gated("check", () => setCheckCursor((c) => c + 1)) : undefined}
                />
              ) : null}
              {addCard ? (
                <SuggestionCard
                  text={`${formatSlashDate(draftDate(addCard))} ${addCard.name}`}
                  subtext="일정으로 추가해 드릴까요?"
                  primary="추가"
                  secondary="나중에"
                  secondarySelected={later.includes(addCard.id)}
                  onPrimary={() => openDraft(addCard)}
                  onSecondary={() => toggleLater(addCard.id)}
                  onRefresh={gated("add", () => setAddCursor((c) => c + 1))}
                />
              ) : showAddArea ? (
                <SuggestionCard text={SUGGESTIONS_DONE_TEXT} />
              ) : null}
            </View>
            <Text style={styles.notice}>추천은 참고용이에요. 내용을 확인 후 저장해 주세요 📝</Text>
          </View>

        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingBottom: spacing.xxl },
  body: { paddingHorizontal: spacing.xxl, paddingTop: spacing.xl, gap: 14 },
  section: { gap: 4 },
  topSection: { gap: 0 },
  head: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", gap: spacing.md },
  headText: { flex: 1 },
  title: { ...font.page, color: colors.text },
  plus: {
    width: 48,
    height: 48,
    borderRadius: radius.button,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.peach,
  },
  heading: { ...font.title, color: colors.text },
  addButton: {
    minHeight: 56,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.button,
    backgroundColor: colors.peach,
  },
  addText: { fontSize: 16, fontWeight: "700", color: colors.text },
  caption: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  feed: { gap: 10 },
  notice: { ...font.caption, color: colors.textMuted, textAlign: "center", marginTop: 10 },
  statusPress: { flexDirection: "row", alignItems: "center", gap: 6 },
  statusLink: { ...font.bodyStrong, fontWeight: "500", color: colors.textMuted },
  newBadge: {
    minWidth: 20,
    height: 20,
    paddingHorizontal: 6,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.peach,
  },
  newBadgeText: { fontSize: 12, fontWeight: "700", color: colors.text },
});
