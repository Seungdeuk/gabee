import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, font, radius, spacing } from "@/theme";

import ChatInputBar from "../components/ChatInputBar";
import DaySection from "../components/DaySection";
import SuggestionCard from "../components/SuggestionCard";
import TogetherRow from "../components/TogetherRow";
import WeekStrip from "../components/WeekStrip";
import { toggleChecked, useScheduleItems } from "../store";
import { MOCK_ADD, MOCK_CARRY, pickAppointmentCard, pickTodoCard } from "../suggestions";
import { addDays, formatDateLong, formatMonthDay, todayKey } from "../utils/date";

const TOGETHER_SAMPLES = ["장 같이 봐줘", "병원 같이 가줘"];

/**
 * 일정 탭 메인: 헤더 + 주간 스트립 / 오늘·내일 / 함께하기 / 먼저 권해드려요 / 채팅 입력.
 * 등록·상세·같이·채팅으로 가는 이동은 각 화면을 만들 때 연결한다.
 */
export default function ScheduleScreen() {
  const router = useRouter();
  const items = useScheduleItems();
  const today = todayKey();
  const tomorrow = addDays(today, 1);

  // "나중에"를 누른 카드는 그대로 남고, 새로고침하면 다른 항목으로 바뀌거나 사라진다.
  const [later, setLater] = useState([]);
  const [skipped, setSkipped] = useState([]);
  const [carryDone, setCarryDone] = useState([]);

  const appointmentCard = pickAppointmentCard(items, today, skipped);
  const todoCard = pickTodoCard(items, today, MOCK_CARRY, carryDone, skipped);
  const showAdd = !skipped.includes(MOCK_ADD.id);
  const addLater = (id) => setLater((prev) => [...prev, id]);
  const confirmTodo = ({ type, id }) => (type === "todo" ? toggleChecked(id) : setCarryDone((prev) => [...prev, id]));
  const openCalendar = (date) => router.push({ pathname: "/schedule/calendar", params: { date } });

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.body}>
          <View style={styles.section}>
            <View style={styles.head}>
              <View style={styles.headText}>
                <Text style={styles.greeting}>바쁜 날도, 여유로운 날도</Text>
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
            </View>
            <WeekStrip selected={today} markedDates={new Set(items.map((item) => item.date))} onSelect={openCalendar} />
          </View>

          <View style={styles.section}>
            <Text style={styles.heading}>{formatDateLong(today)}</Text>
            <DaySection
              label="오늘"
              items={items.filter((item) => item.date === today)}
              onToggleItem={toggleChecked}
            />
            <DaySection
              label={`내일 · ${formatMonthDay(tomorrow)}`}
              items={items.filter((item) => item.date === tomorrow)}
              onToggleItem={toggleChecked}
            />
            <Pressable style={styles.addButton} accessibilityRole="button">
              <Text style={styles.addText}>+ 약속 · 할 일 추가하기</Text>
            </Pressable>
          </View>

          <View style={styles.section}>
            <Text style={styles.heading}>함께하기</Text>
            <TogetherRow samples={TOGETHER_SAMPLES} />
          </View>

          <View style={styles.section}>
            <View style={styles.caption}>
              <Text style={styles.heading}>먼저 권해드려요</Text>
              <Pressable
                onPress={() => setSkipped(later)}
                accessibilityRole="button"
                accessibilityLabel="새로고침"
                style={styles.refresh}
              >
                <Ionicons name="refresh" size={18} color={colors.text} />
              </Pressable>
            </View>
            <View style={styles.feed}>
              {appointmentCard ? (
                <SuggestionCard
                  text={appointmentCard.text}
                  primary={appointmentCard.label}
                  secondary={appointmentCard.itemId ? "나중에" : undefined}
                  onPrimary={() => toggleChecked(appointmentCard.itemId)}
                  onSecondary={() => addLater(appointmentCard.itemId)}
                />
              ) : null}
              {todoCard ? (
                <SuggestionCard
                  text={todoCard.text}
                  primary={todoCard.label}
                  secondary={todoCard.laterLabel}
                  onPrimary={() => confirmTodo(todoCard.target)}
                  onSecondary={() => addLater(todoCard.target.id)}
                />
              ) : null}
              {showAdd ? (
                <SuggestionCard
                  text={MOCK_ADD.text}
                  primary="추가"
                  secondary="나중에"
                  onSecondary={() => addLater(MOCK_ADD.id)}
                />
              ) : null}
            </View>
            <Text style={styles.notice}>제안은 참고용이에요. 내용을 확인 후 저장해 주세요 📝</Text>
          </View>

          <ChatInputBar />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingBottom: spacing.xxl },
  body: { paddingHorizontal: spacing.xxl, paddingTop: spacing.xl, gap: 28 },
  section: { gap: spacing.md },
  head: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", gap: spacing.md },
  headText: { flex: 1 },
  greeting: { ...font.caption, color: colors.textMuted },
  title: { ...font.page, color: colors.text, marginTop: 2 },
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
  refresh: {
    width: 32,
    height: 32,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  feed: { gap: 10 },
  notice: { ...font.caption, color: colors.textMuted, textAlign: "center" },
});
