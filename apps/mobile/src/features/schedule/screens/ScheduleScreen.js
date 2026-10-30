import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useRef, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { isApiConfigured } from "@/shared/api/client";
import SettingsButton, { SETTINGS_EDGE_GAP } from "@/shared/components/SettingsButton";
import { colors, font, radius, spacing } from "@/theme";

import DaySection from "../components/DaySection";
import SuggestionCard from "../components/SuggestionCard";
import TogetherRow from "../components/TogetherRow";
import WeekStrip from "../components/WeekStrip";
import { briefingLabels } from "../briefing";
import { ME_ID } from "../mock";
import { useNewReceivedCount, useRequests } from "../requests";
import { briefingRequests } from "../request_view";
import { toggleChecked, useScheduleItems } from "../store";
import { draftDateOf, suggestionExtras } from "../suggestion_convert";
import { MOCK_SUGGESTIONS, SUGGESTIONS_DONE_TEXT, SUGGESTIONS_LOADING_TEXT, emptySlotView, pickCheckCard } from "../suggestions";
import { reloadSuggestions, setSuggestionLater, useSuggestions } from "../suggestions_store";
import { addDays, formatDateLong, formatSlashDate, todayKey } from "../utils/date";

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
  const requests = useRequests();
  const today = todayKey();
  // 주간 스트림에서 고른 날. 아래 브리핑이 이 날과 그 다음 날로 바뀐다(처음엔 오늘).
  const [selected, setSelected] = useState(today);
  const [nextFolded, setNextFolded] = useState(false); // 다음 날(내일) 구역을 접었는지
  const nextDay = addDays(selected, 1);
  const [selectedLabel, nextLabel] = briefingLabels(selected, today);

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
  // 추가 카드 자리의 상태. 서버 추천은 불러오는 동안 "찾고 있어요", 비었으면 서버 상태에 따라
  // 데이터 없음 🌱 / 새로 줄 게 없음 🌙 / 준비 중 ⏳(새로고침) / 오늘 추천은 여기까지(전부 확정, 호출 소진).
  const empty = useServer ? emptySlotView(server) : { kind: "message", text: SUGGESTIONS_DONE_TEXT, refresh: false };
  const addState = addCard ? "card" : empty.kind === "loading" ? "loading" : "message";
  // 서버 추천의 "나중에"는 서버에 기록하고, 예전 임시 제안은 화면 표시만 한다.
  const addCardLater = addCard ? (useServer ? Boolean(addCard.later) : later.includes(addCard.id)) : false;
  const toggleAddLater = () => {
    if (pressed === addCard.id) return;
    if (useServer) setSuggestionLater(addCard.id, !addCard.later);
    else toggleLater(addCard.id);
  };
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
  const openRequest = (id) => router.push({ pathname: "/schedule/together-detail", params: { id } });
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
              <View style={styles.actions}>
                <Pressable
                  onPress={() => openCalendar(selected)}
                  accessibilityRole="button"
                  accessibilityLabel="달력 열기"
                  style={styles.plus}
                >
                  <Ionicons name="add" size={28} color={colors.text} />
                </Pressable>
                <SettingsButton />
              </View>
            </View>
            <WeekStrip selected={selected} markedDates={new Set(items.map((item) => item.date))} onSelect={setSelected} />
          </View>

          <View style={styles.section}>
            <Text style={styles.heading}>{formatDateLong(selected)}</Text>
            <DaySection
              label={selectedLabel}
              items={items.filter((item) => item.date === selected)}
              requests={briefingRequests(requests, ME_ID, selected, today)}
              onPressItem={openDetail}
              onPressRequest={openRequest}
              onToggleItem={toggleChecked}
            />
            <DaySection
              label={nextLabel}
              items={items.filter((item) => item.date === nextDay)}
              requests={briefingRequests(requests, ME_ID, nextDay, today)}
              onPressItem={openDetail}
              onPressRequest={openRequest}
              onToggleItem={toggleChecked}
              collapsed={nextFolded}
              onToggle={() => setNextFolded((v) => !v)}
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
              {addState === "card" ? (
                <SuggestionCard
                  text={`${formatSlashDate(draftDate(addCard))} ${addCard.name}`}
                  subtext="일정으로 추가해 드릴까요?"
                  primary="추가"
                  secondary="나중에"
                  secondarySelected={addCardLater}
                  onPrimary={() => openDraft(addCard)}
                  onSecondary={toggleAddLater}
                  onRefresh={gated("add", () => {
                    // 서버 추천은 새로고침마다 서버에서 다시 받아(대기가 있으면 AI 호출 없이 섞어서) 보여 준다
                    if (useServer) reloadSuggestions();
                    else setAddCursor((c) => c + 1);
                  })}
                />
              ) : addState === "loading" ? (
                <SuggestionCard text={SUGGESTIONS_LOADING_TEXT} />
              ) : (
                <SuggestionCard text={empty.text} onRefresh={empty.refresh ? gated("ask", reloadSuggestions) : undefined} />
              )}
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
  // 48 높이 묶음의 중심(44)을 상단바 가운데(28)로 올리고, 오른쪽 끝에서 6 만큼 띄운다
  actions: { flexDirection: "row", alignItems: "center", marginRight: SETTINGS_EDGE_GAP - spacing.xxl, transform: [{ translateY: -16 }] },
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
