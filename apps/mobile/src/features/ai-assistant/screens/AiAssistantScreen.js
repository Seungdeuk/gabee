import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { FlatList, KeyboardAvoidingView, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import AppHeader from "@/shared/components/AppHeader";
import { colors } from "@/theme";

import AnswerView from "../components/AnswerView";
import ChatInput from "../components/ChatInput";
import DraftCard from "../components/DraftCard";
import PromptChips from "../components/PromptChips";
import Sidebar from "../components/Sidebar";
import ThinkingSteps from "../components/ThinkingSteps";
import UserBubble from "../components/UserBubble";
import WaveBars from "../components/WaveBars";
import useChat from "../hooks/useChat";
import useSessions from "../hooks/useSessions";
import { listRecords } from "../api";
import mascot from "../../../../assets/images/gabee-mascot.png";

/**
 * 홈: AI 채팅. 상태는 빈 화면 → (음성 입력) → 처리 중 → 답변/초안 승인 순으로 바뀐다.
 * 상단 ⋮ 는 기타 화면(가족 그룹·설정)으로 들어간다.
 */
export default function AiAssistantScreen() {
  const router = useRouter();
  const { messages, phase, send, sendPhoto, startListening, stopListening, editDraft, reset, load } = useChat();
  const { sessions, currentId, startNew, open, remove } = useSessions({ messages, load, reset });
  const [menuOpen, setMenuOpen] = useState(false);
  const [reviewCount, setReviewCount] = useState(0); // 확인이 필요한 기록 수(메뉴 점·기록 탭 숫자)
  const [focusRecordId, setFocusRecordId] = useState(null);

  const countReview = useCallback((items) => setReviewCount(items.filter((r) => r.needs_review).length), []);
  const refreshReview = useCallback(() => {
    listRecords().then(countReview).catch(() => {}); // 서버가 안 되면 점만 못 띄운다
  }, [countReview]);
  useEffect(() => {
    if (phase === "idle") refreshReview(); // 처음 열 때와, 파일을 올려 읽기가 끝난 뒤에 새로 센다
  }, [phase, refreshReview]);
  const listRef = useRef(null);
  const [atBottom, setAtBottom] = useState(true);
  const stick = useRef(true); // 맨 아래를 따라가는 중인지(사용자가 위로 올리면 멈춘다)

  const empty = messages.length === 0 && phase === "idle";
  const listening = phase === "listening";
  const inputMode = phase === "thinking" || phase === "reading" ? "disabled" : listening ? "listening" : "idle";

  const scrollToEnd = () => {
    stick.current = true;
    listRef.current?.scrollToEnd({ animated: true });
  };
  const onScroll = ({ nativeEvent: e }) => {
    const near = e.contentOffset.y + e.layoutMeasurement.height >= e.contentSize.height - 48;
    if (near) stick.current = true;
    setAtBottom(near);
  };

  const renderItem = ({ item, index }) => {
    if (item.role === "user") return <UserBubble text={item.text} voice={item.voice} imageUri={item.imageUri} />;
    const isReport = item.sources.length > 1; // 여러 기록을 모은 답에는 저장·복사 버튼을 붙인다
    return (
      <View style={styles.answer}>
        <AnswerView text={item.text} sources={item.sources} showActions={isReport && index === messages.length - 1}>
          {item.draft ? (
            <DraftCard to={item.draft.to} text={item.draftText} onChangeText={(t) => editDraft(item.id, t)} />
          ) : null}
        </AnswerView>
        {item.reviewId ? (
          <Pressable
            onPress={() => {
              setFocusRecordId(item.reviewId);
              setMenuOpen(true);
            }}
            accessibilityRole="button"
            style={styles.reviewBtn}
          >
            <Ionicons name="create-outline" size={16} color={colors.text} />
            <Text style={styles.reviewBtnText}>지금 확인하기</Text>
          </Pressable>
        ) : null}
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <AppHeader onMenu={() => setMenuOpen(true)} onNew={startNew} onMore={() => router.push("/more")} menuBadge={reviewCount > 0} />
      <Sidebar
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        sessions={sessions}
        currentId={currentId}
        onNew={startNew}
        onOpenSession={open}
        onDeleteSession={remove}
        reviewCount={reviewCount}
        focusRecordId={focusRecordId}
        onFocusHandled={() => setFocusRecordId(null)}
        onRecordsLoaded={countReview}
      />

      {/* Android(SDK 54)는 화면 전체 모드라 키보드가 화면을 줄여 주지 않는다. 양쪽 모두 직접 피한다. */}
      <KeyboardAvoidingView style={styles.flex} behavior="padding">
        <View style={styles.main}>
          {listening ? (
            <>
              {/* 음성 입력 중에는 가비가 양쪽에서 귀를 기울인다 */}
              <Image source={mascot} style={[styles.bee, styles.beeLeft]} contentFit="contain" pointerEvents="none" />
              <Image source={mascot} style={[styles.bee, styles.beeRight]} contentFit="contain" pointerEvents="none" />
            </>
          ) : null}
          {empty ? (
            <View style={styles.center}>
              <Text style={styles.hello}>무엇을 도와드릴까요?</Text>
            </View>
          ) : messages.length === 0 && listening ? (
            <View style={styles.center}>
              <WaveBars />
              <Text style={styles.listening}>듣고 있어요</Text>
            </View>
          ) : (
            <>
              <FlatList
                ref={listRef}
                data={messages}
                keyExtractor={(m) => m.id}
                renderItem={renderItem}
                onScroll={onScroll}
                onScrollBeginDrag={() => {
                  stick.current = false;
                }}
                scrollEventThrottle={64}
                onContentSizeChange={() => stick.current && scrollToEnd()}
                contentContainerStyle={styles.list}
                ItemSeparatorComponent={() => <View style={styles.gap} />}
                ListFooterComponent={
                  phase === "thinking" ? (
                    <View style={styles.footer}>
                      <ThinkingSteps />
                    </View>
                  ) : phase === "reading" ? (
                    <View style={styles.footer}>
                      <Text style={styles.listening}>읽는 중…</Text>
                    </View>
                  ) : listening ? (
                    <View style={[styles.footer, styles.centerRow]}>
                      <WaveBars />
                      <Text style={styles.listening}>듣고 있어요</Text>
                    </View>
                  ) : null
                }
                keyboardShouldPersistTaps="handled"
              />
              {!atBottom ? (
                <Pressable onPress={scrollToEnd} style={styles.toBottom} accessibilityLabel="맨 아래로">
                  <Ionicons name="arrow-down" size={18} color={colors.textSub} />
                </Pressable>
              ) : null}
            </>
          )}
        </View>

        <View style={styles.bottom}>
          {empty ? (
            <>
              <View style={styles.disclaimer}>
                <Ionicons name="information-circle-outline" size={13} color={colors.textMuted} />
                <Text style={styles.disclaimerText}>AI가 생성한 대화는 사실과 다를 수 있어요.</Text>
              </View>
              <PromptChips onPick={send} />
            </>
          ) : null}
          {listening ? (
            <Text style={styles.note}>폰 기본 음성 인식으로 받아 적어요. 말이 끝나면 보내기를 눌러 주세요.</Text>
          ) : null}
          <ChatInput mode={inputMode} onSend={send} onAttach={sendPhoto} onMic={listening ? stopListening : startListening} />
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  main: { flex: 1, overflow: "hidden" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 16, paddingHorizontal: 24 },
  centerRow: { alignItems: "center", gap: 12 },
  bee: { position: "absolute", width: 200, height: 121, opacity: 0.9 },
  beeLeft: { left: -82, top: 60, transform: [{ rotate: "8deg" }] },
  beeRight: { right: -82, bottom: 40, transform: [{ scaleX: -1 }, { rotate: "8deg" }] },
  hello: { fontSize: 20, fontWeight: "700", color: colors.text, textAlign: "center" },
  listening: { fontSize: 13, color: colors.textMuted },
  list: { paddingHorizontal: 20, paddingTop: 12, paddingBottom: 24 },
  gap: { height: 24 },
  answer: { gap: 16 },
  reviewBtn: { alignSelf: "flex-start", minHeight: 40, paddingHorizontal: 16, borderRadius: 20, backgroundColor: colors.peach, flexDirection: "row", alignItems: "center", gap: 6 },
  reviewBtnText: { fontSize: 14, fontWeight: "600", color: colors.text },
  footer: { marginTop: 24 },
  toBottom: {
    position: "absolute",
    right: 16,
    bottom: 12,
    width: 36,
    height: 36,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#000",
    shadowOpacity: 0.08,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
  },
  bottom: { paddingTop: 8, paddingBottom: 12, gap: 12 },
  disclaimer: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4 },
  disclaimerText: { fontSize: 12, color: colors.textMuted },
  note: { textAlign: "center", fontSize: 12, color: colors.textMuted, paddingHorizontal: 24 },
});
