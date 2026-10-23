import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, radius, spacing } from "@/theme";

import { analyzeChat, getAiSettings, registerScheduleCandidate, setAiEnabled, suggestReplies, suggestTopics } from "../api";
import {
  canRegisterSchedule,
  chatErrorMessage,
  parseAiSettings,
  rangeCaption,
  remainingText,
  resultCaption,
  scheduleMissingNote,
  shouldLoadSettings,
} from "../messages";

/** 후보 한 줄에 붙는 보조 글(날짜·시간·장소 등). */
const joinParts = (parts) => parts.filter(Boolean).join(" · ");

/**
 * 채팅방 안 AI 대화 도우미 시트. 열릴 때 설정만 한 번 읽고, 분석·추천은 버튼을 누를 때만 호출한다(대화·결과는 서버에 저장되지 않음).
 * 닫아도 컴포넌트는 유지되어 마지막 결과를 다시 열면 보여 준다. 닫혀 있는 동안에는 아무 호출도 하지 않는다.
 * @param {{ visible: boolean, onClose: () => void, onPickReply: (text: string) => void }} props
 * @returns {JSX.Element}
 */
export default function AiPanel({ visible, onClose, onPickReply }) {
  const [settings, setSettings] = useState(null); // parseAiSettings 결과
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(""); // "settings" | "analysis" | "replies" | "topics" | ""
  const [error, setError] = useState("");
  const [analysis, setAnalysis] = useState(null);
  const [replies, setReplies] = useState(null);
  const [topics, setTopics] = useState(null);
  const [registered, setRegistered] = useState({}); // 후보 순번 -> "ok" | "sending" | 오류 문구

  const loadSettings = useCallback(async () => {
    try {
      setSettings(parseAiSettings(await getAiSettings()));
      setLoadError("");
    } catch (e) {
      setLoadError(chatErrorMessage(e));
    }
  }, []);

  useEffect(() => {
    if (shouldLoadSettings(visible)) loadSettings();
  }, [visible, loadSettings]);

  /** 요청 하나를 실행하고 오류는 문구로 바꾼다. 끝나면 남은 횟수를 새로 읽는다. */
  const run = async (name, call, onDone) => {
    setBusy(name);
    setError("");
    try {
      onDone(await call());
    } catch (e) {
      setError(chatErrorMessage(e));
    }
    setBusy("");
    loadSettings();
  };

  const register = async (index, candidate) => {
    setRegistered((r) => ({ ...r, [index]: "sending" }));
    try {
      await registerScheduleCandidate(candidate);
      setRegistered((r) => ({ ...r, [index]: "ok" }));
    } catch (e) {
      setRegistered((r) => ({ ...r, [index]: chatErrorMessage(e) }));
    }
  };

  const content = (() => {
  if (!settings) {
    return (
      <>
        {loadError ? (
          <>
            <Text style={styles.error} accessibilityRole="alert">
              {loadError}
            </Text>
            <Button label="다시 불러오기" small variant="secondary" onPress={loadSettings} />
          </>
        ) : (
          <ActivityIndicator color={colors.accent} />
        )}
      </>
    );
  }

  if (!settings.enabled) {
    return (
      <>
        <Text style={styles.sub}>
          켜면 대화 분석·답장 추천·대화 주제 추천을 쓸 수 있어요. 버튼을 눌렀을 때만 최근 대화 일부가 AI로 전달되고, 결과와 대화는 저장되지 않아요.
        </Text>
        {error ? (
          <Text style={styles.error} accessibilityRole="alert">
            {error}
          </Text>
        ) : null}
        {settings.canManage ? (
          <Button
            label={busy === "settings" ? "켜는 중..." : "AI 기능 켜기"}
            small
            onPress={() => run("settings", () => setAiEnabled(true), () => {})}
            disabled={busy !== ""}
            testID="chat-ai-enable"
          />
        ) : (
          <Text style={styles.note} testID="chat-ai-need-manager">
            가족 소유자나 관리자가 켜야 해요
          </Text>
        )}
      </>
    );
  }

  const disabled = busy !== "";
  return (
    <>
      <Text style={styles.sub}>누를 때만 최근 대화가 AI로 전달되고, 결과는 저장되지 않아요.</Text>
      {remainingText(settings) ? <Text style={styles.caption}>{remainingText(settings)}</Text> : null}
      {error ? (
        <Text style={styles.error} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}
      {disabled ? (
        <View style={styles.loading}>
          <ActivityIndicator color={colors.accent} />
          <Text style={styles.caption}>AI가 대화를 살펴보는 중이에요...</Text>
        </View>
      ) : null}

      <Button
        label={busy === "analysis" ? "분석하는 중..." : analysis ? "다시 분석하기" : "대화 분석하기"}
        small
        onPress={() =>
          run("analysis", analyzeChat, (res) => {
            setAnalysis(res);
            setRegistered({});
          })
        }
        disabled={disabled}
        testID="chat-ai-analyze"
      />

      {analysis ? (
        <View style={styles.result} testID="chat-ai-result">
          <Text style={styles.section}>요약</Text>
          <Text style={styles.body} selectable>
            {analysis.summary}
          </Text>

          <Text style={styles.section}>중요 메시지</Text>
          {analysis.important_messages.length === 0 ? (
            <Text style={styles.caption}>중요한 메시지가 없어요</Text>
          ) : (
            analysis.important_messages.map((m) => (
              <Text key={m.message_id} style={styles.body}>
                {`• ${m.reason}`}
              </Text>
            ))
          )}

          <Text style={styles.section}>일정 후보</Text>
          {analysis.schedule_candidates.length === 0 ? (
            <Text style={styles.caption}>일정 후보가 없어요</Text>
          ) : (
            analysis.schedule_candidates.map((c, i) => {
              const state = registered[i];
              return (
                <View key={`${c.title}-${i}`} style={styles.candidate}>
                  <Text style={styles.bodyStrong}>{c.title}</Text>
                  <Text style={styles.caption}>{joinParts([c.date, c.time, c.place]) || "-"}</Text>
                  {scheduleMissingNote(c) ? <Text style={styles.note}>{scheduleMissingNote(c)}</Text> : null}
                  {state === "ok" ? (
                    <Text style={styles.success}>일정으로 등록했어요</Text>
                  ) : (
                    <>
                      {state && state !== "sending" ? (
                        <Text style={styles.error} accessibilityRole="alert">
                          {state}
                        </Text>
                      ) : null}
                      <Button
                        label={state === "sending" ? "등록하는 중..." : "일정으로 등록"}
                        small
                        variant="secondary"
                        onPress={() => register(i, c)}
                        disabled={!canRegisterSchedule(c) || state === "sending"}
                        testID={`chat-ai-register-${i}`}
                      />
                    </>
                  )}
                </View>
              );
            })
          )}

          <Text style={styles.section}>할 일·부탁 후보</Text>
          {analysis.todo_candidates.length === 0 ? (
            <Text style={styles.caption}>할 일 후보가 없어요</Text>
          ) : (
            <>
              {analysis.todo_candidates.map((t, i) => (
                <View key={`${t.title}-${i}`} style={styles.candidate}>
                  <Text style={styles.bodyStrong}>{t.title}</Text>
                  <Text style={styles.caption}>
                    {joinParts([t.assignee_name && `담당 ${t.assignee_name}`, t.due && `기한 ${t.due}`]) || "담당자·기한이 정해지지 않았어요"}
                  </Text>
                </View>
              ))}
              <Text style={styles.note}>공동 할 일은 준비 중이에요</Text>
            </>
          )}

          <Text style={styles.caption}>{[rangeCaption(analysis.meta), resultCaption(analysis.meta)].filter(Boolean).join(" · ")}</Text>
        </View>
      ) : null}

      <View style={styles.row}>
        <Button label="답장 추천" small variant="secondary" onPress={() => run("replies", suggestReplies, setReplies)} disabled={disabled} testID="chat-ai-replies" />
        <Button label="대화 주제 추천" small variant="secondary" onPress={() => run("topics", suggestTopics, setTopics)} disabled={disabled} testID="chat-ai-topics" />
      </View>

      {replies ? (
        <View style={styles.result} testID="chat-ai-replies-result">
          <Text style={styles.section}>답장 추천</Text>
          {replies.replies.map((text, i) => (
            <Pressable
              key={i}
              style={styles.pick}
              onPress={() => {
                onPickReply(text);
                onClose();
              }}
              accessibilityRole="button"
              accessibilityLabel={`이 답장을 입력창에 넣기: ${text}`}
              testID={`chat-ai-reply-${i}`}
            >
              <Text style={styles.body}>{text}</Text>
            </Pressable>
          ))}
          <Text style={styles.caption}>{resultCaption(replies.meta)}</Text>
        </View>
      ) : null}
      {topics ? (
        <View style={styles.result} testID="chat-ai-topics-result">
          <Text style={styles.section}>대화 주제 추천</Text>
          {topics.topics.map((text, i) => (
            <Pressable
              key={i}
              style={styles.pick}
              onPress={() => {
                onPickReply(text);
                onClose();
              }}
              accessibilityRole="button"
              accessibilityLabel={`이 주제를 입력창에 넣기: ${text}`}
              testID={`chat-ai-topic-${i}`}
            >
              <Text style={styles.body}>{text}</Text>
            </Pressable>
          ))}
          <Text style={styles.caption}>{resultCaption(topics.meta)}</Text>
        </View>
      ) : null}
    </>
  );
  })();

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.root}>
        <Pressable style={styles.backdrop} onPress={onClose} accessibilityRole="button" accessibilityLabel="AI 대화 도우미 닫기" testID="chat-ai-backdrop" />
        <View style={styles.sheet} testID="chat-ai">
          <View style={styles.handle} />
          <View style={styles.header}>
            <Text style={styles.title} accessibilityRole="header">
              AI 대화 도우미
            </Text>
            <Pressable onPress={onClose} hitSlop={spacing.sm} accessibilityRole="button" accessibilityLabel="닫기" testID="chat-ai-close">
              <Text style={styles.close}>닫기</Text>
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={styles.content}>{content}</ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.text, opacity: 0.4 },
  sheet: {
    maxHeight: "85%",
    backgroundColor: colors.background,
    borderTopLeftRadius: radius.card,
    borderTopRightRadius: radius.card,
    paddingTop: spacing.sm,
  },
  handle: { alignSelf: "center", width: 40, height: spacing.xs, borderRadius: radius.pill, backgroundColor: colors.disabled },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  close: { ...font.bodyStrong, color: colors.accent },
  content: { gap: spacing.sm, paddingHorizontal: spacing.lg, paddingBottom: spacing.xxl },
  pick: { backgroundColor: colors.peachSoft, borderRadius: radius.md, padding: spacing.md },

  title: { ...font.cardTitle, color: colors.text },
  sub: { ...font.caption, color: colors.textSub },
  section: { ...font.bodyStrong, color: colors.text, marginTop: spacing.xs },
  body: { ...font.body, color: colors.text },
  bodyStrong: { ...font.bodyStrong, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
  note: { ...font.caption, color: colors.warning },
  success: { ...font.caption, color: colors.success },
  error: { ...font.body, color: colors.danger },
  loading: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  row: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  result: { gap: spacing.xs, backgroundColor: colors.card, borderRadius: 14, padding: spacing.md },
  candidate: { gap: spacing.xs, paddingVertical: spacing.xs },
});
