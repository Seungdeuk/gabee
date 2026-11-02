import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import Button from "@/shared/components/Button";
import { colors, font, radius, spacing } from "@/theme";

import { analyzeChat, getAiSettings, getRoomInfo, registerScheduleCandidate, sendTogetherRequest, setAiEnabled } from "../api";
import {
  canRegisterSchedule,
  chatErrorMessage,
  parseAiSettings,
  parseAnalysis,
  rangeCaption,
  remainingText,
  resultCaption,
  scheduleMissingNote,
  shouldLoadSettings,
} from "../messages";
import { privacyCaption } from "../privacyPreview";
import { candidateKey, isCandidateDone, markCandidateDone } from "../candidateKey";
import { candidateToRequestBody, dayFromChip, hasCandidateDay, requestErrorText, sendErrorMessage } from "../togetherUtils";
import { CONSENT_CANCEL_LABEL, ENABLE_ON_ANALYZE_BODY, ENABLE_ON_ANALYZE_CONFIRM_LABEL, ENABLE_ON_ANALYZE_TITLE, PANEL_NOTICE } from "../privacyCopy";
import TodoCandidateRow from "./TodoCandidateRow";

/** 후보 한 줄에 붙는 보조 글(날짜·시간·장소 등). */
const joinParts = (parts) => parts.filter(Boolean).join(" · ");

/**
 * 추천 문장 목록. 한 줄을 누르면 onPick 으로 알린다(비어 있으면 안내 글).
 * @param {{ items: string[], emptyText: string, labelPrefix: string, testIDPrefix: string, onPick: (text: string) => void }} props
 * @returns {JSX.Element}
 */
function PickList({ items, emptyText, labelPrefix, testIDPrefix, onPick }) {
  if (items.length === 0) return <Text style={styles.caption}>{emptyText}</Text>;
  return items.map((text, i) => (
    <Pressable key={i} style={styles.pick} onPress={() => onPick(text)} accessibilityRole="button" accessibilityLabel={`${labelPrefix}: ${text}`} testID={`${testIDPrefix}-${i}`}>
      <Text style={styles.body}>{text}</Text>
    </Pressable>
  ));
}

/**
 * 채팅방 안 AI 대화 도우미 시트. 열릴 때 설정만 한 번 읽는다. "대화 분석하기" 버튼을 누르면 곧바로 AI 를 한 번 부른다(AI 동의는 회원가입 때 받는다).
 * 켜진 상태에는 항상 보이는 한 줄 안내(PANEL_NOTICE)를 둔다. 요약·일정·할 일 후보·답장 추천·대화 주제 추천이 한 결과 화면에 나온다.
 * 결과는 서버에 잠시(약 10분) 저장돼 같은 요청에 다시 쓰인다.
 * 닫아도 컴포넌트는 유지되어 마지막 결과를 다시 열면 보여 준다. 닫혀 있는 동안에는 아무 호출도 하지 않는다.
 * 일정·할 일 후보를 등록하면 onLinked 로 알려 원본 메시지와의 연결을 저장하게 한다(연결 저장이 실패해도 등록은 성공으로 둔다).
 * @param {{ visible: boolean, onClose: () => void, onPickReply: (text: string) => void, onLinked?: (link: { kind: "event" | "todo", targetId: string, candidate: object }) => void }} props
 * @returns {JSX.Element}
 */
export default function AiPanel({ visible, onClose, onPickReply, onLinked }) {
  const insets = useSafeAreaInsets(); // 안드로이드 내비게이션 바에 시트 아래쪽(버튼)이 가려지지 않게
  const [settings, setSettings] = useState(null); // parseAiSettings 결과
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(""); // "analysis" | ""
  const [error, setError] = useState("");
  const [analysis, setAnalysis] = useState(null);
  const [registered, setRegistered] = useState({}); // 후보 내용 식별자(candidateKey) -> "ok" | "sending" | 오류 문구. 다시 분석해도 같은 후보는 등록한 표시가 이어진다
  const [todoRegistered, setTodoRegistered] = useState({}); // 할 일 후보 식별자 -> 같은 형태(함께하기로 보낸 결과)
  const [todoDay, setTodoDay] = useState({}); // 날짜가 없는 할 일 후보 순번 -> 고른 날짜 칩 key
  const [todoCustom, setTodoCustom] = useState({}); // 직접 입력을 고른 후보 순번 -> 적은 날짜 글자
  const [confirmingEnable, setConfirmingEnable] = useState(false); // 꺼져 있는 가족 AI 를 켜고 분석할지 묻는 중
  const analyzing = useRef(false); // 분석(필요하면 켜기 포함)을 빠르게 두 번 눌러도 한 번만 보낸다
  const todoBusy = useRef(new Set()); // 등록 중이거나 등록된 할 일 후보 식별자(candidateKey): 같은 후보를 두 번 등록하지 않는다

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

  /**
   * "대화 분석하기"/"다시 분석하기": 누르면 곧바로 분석 API 를 한 번 호출한다. AI 동의는 회원가입 때 받으므로 켜기·끄기 버튼은 없다.
   * 이 가족의 AI 설정이 꺼져 있으면(예전에 꺼 둔 경우) 켜는 것이 가족 전체에 적용되므로 확인 카드(ENABLE_ON_ANALYZE_*)를 먼저 보이고, "켜고 분석하기"를 눌렀을 때만 켠 뒤 분석한다(안 켜면 서버가 ai_not_enabled 로 막는다).
   */
  const analyze = async () => {
    if (analyzing.current) return;
    if (settings?.enabled === false) {
      setConfirmingEnable(true); // 꺼져 있으면 켜는 것이 가족 전체에 적용된다는 확인을 먼저 받는다
      return;
    }
    analyzing.current = true;
    try {
      await analyzeNow();
    } finally {
      analyzing.current = false;
    }
  };
  /** 확인 카드에서 "켜고 분석하기"를 눌렀을 때만 켠 뒤 분석한다. */
  const confirmEnableAndAnalyze = async () => {
    if (analyzing.current) return;
    analyzing.current = true;
    setConfirmingEnable(false);
    try {
      await analyzeNow();
    } finally {
      analyzing.current = false;
    }
  };
  const analyzeNow = () =>
    run("analysis", async () => {
      if (settings?.enabled === false) await setAiEnabled(true);
      return analyzeChat();
    }, (res) => {
      setAnalysis(parseAnalysis(res));
      setTodoDay({});
      setTodoCustom({});
    });

  /** 등록이 끝난 뒤 원본 메시지 연결을 부탁한다. 연결은 부가 기능이라 여기서 나는 오류는 등록 결과에 영향을 주지 않는다. */
  const notifyLinked = (link) => {
    try {
      onLinked?.(link);
    } catch {
      // 무시
    }
  };

  const register = async (candidate) => {
    const key = candidateKey("schedule", candidate);
    setRegistered((r) => ({ ...r, [key]: "sending" }));
    try {
      const created = await registerScheduleCandidate(candidate);
      markCandidateDone(key);
      setRegistered((r) => ({ ...r, [key]: "ok" }));
      notifyLinked({ kind: "event", targetId: created?.id, candidate });
    } catch (e) {
      setRegistered((r) => ({ ...r, [key]: chatErrorMessage(e) }));
    }
  };

  /**
   * 사용자가 누른 할 일 후보 하나만 함께하기(일정 탭의 같이 요청)로 보낸다(서버 AI 를 부르지 않는다). 날짜는 후보에 있으면 그것을, 없으면 고른 날짜를 쓰고,
   * 받는 사람은 담당자 이름이 정확히 같은 한 명이면 그 사람, 아니면 가족 모두(나 제외)다.
   */
  const registerTodo = async (index, candidate) => {
    const key = candidateKey("todo", candidate);
    if (todoBusy.current.has(key)) return;
    const chosen = dayFromChip(todoDay[index], new Date(), todoCustom[index]);
    if (!hasCandidateDay(candidate) && !chosen) {
      setTodoRegistered((r) => ({ ...r, [key]: requestErrorText(todoDay[index] === "custom" ? "bad_date" : "no_date") }));
      return;
    }
    todoBusy.current.add(key);
    setTodoRegistered((r) => ({ ...r, [key]: "sending" }));
    try {
      const group = await getRoomInfo({ raw: true }); // AI 가 돌려준 담당자 이름은 실제 이름이라 별명을 입히지 않은 구성원과 맞춘다
      const made = candidateToRequestBody(candidate, group, chosen);
      if (made.error) {
        todoBusy.current.delete(key);
        setTodoRegistered((r) => ({ ...r, [key]: requestErrorText(made.error) }));
        return;
      }
      await sendTogetherRequest(made.body); // 원본 대화 연결은 만들지 않는다(서버 연결은 공동 할 일 id 만 받는다)
      markCandidateDone(key);
      setTodoRegistered((r) => ({ ...r, [key]: "ok" }));
    } catch (e) {
      todoBusy.current.delete(key); // 실패하면 다시 누를 수 있다
      setTodoRegistered((r) => ({ ...r, [key]: sendErrorMessage(e) }));
    }
  };

  /** 추천 한 줄을 눌렀을 때: 입력창에 넣기만 하고(보내지 않는다) 패널을 닫는다. */
  const pickText = (text) => {
    onPickReply(text);
    onClose();
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

  const disabled = busy !== "";
  return (
    <>
      <Text style={styles.sub} testID="chat-ai-notice">
        {PANEL_NOTICE}
      </Text>
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

      {confirmingEnable ? (
        <View style={styles.confirmCard} testID="chat-ai-enable-confirm">
          <Text style={styles.bodyStrong} accessibilityRole="header">
            {ENABLE_ON_ANALYZE_TITLE}
          </Text>
          <Text style={styles.sub}>{ENABLE_ON_ANALYZE_BODY}</Text>
          <Button label={ENABLE_ON_ANALYZE_CONFIRM_LABEL} small onPress={confirmEnableAndAnalyze} disabled={disabled} testID="chat-ai-enable-confirm-yes" />
          <Button label={CONSENT_CANCEL_LABEL} small variant="secondary" onPress={() => setConfirmingEnable(false)} disabled={disabled} testID="chat-ai-enable-confirm-no" />
        </View>
      ) : null}

      <Button
        label={busy === "analysis" ? "분석하는 중..." : analysis ? "다시 분석하기" : "대화 분석하기"}
        small
        onPress={analyze}
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
                {"• "}
                <Text style={styles.marker}>{m.reason}</Text>
              </Text>
            ))
          )}

          <Text style={styles.section}>일정 후보</Text>
          {analysis.schedule_candidates.length === 0 ? (
            <Text style={styles.caption}>일정 후보가 없어요</Text>
          ) : (
            analysis.schedule_candidates.map((c, i) => {
              const key = candidateKey("schedule", c);
              const state = registered[key] ?? (isCandidateDone(key) ? "ok" : undefined);
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
                        onPress={() => register(c)}
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
            analysis.todo_candidates.map((t, i) => (
              <TodoCandidateRow key={`${t.title}-${i}`} candidate={t} state={todoRegistered[candidateKey("todo", t)] ?? (isCandidateDone(candidateKey("todo", t)) ? "ok" : undefined)} day={todoDay[i] ?? null} customText={todoCustom[i] ?? ""} onChangeCustom={(text) => setTodoCustom((c) => ({ ...c, [i]: text }))} onPickDay={(key) => setTodoDay((d) => ({ ...d, [i]: key }))} onRegister={() => registerTodo(i, t)} testID={`chat-ai-todo-${i}`} />
            ))
          )}

          <Text style={styles.section}>답장 추천</Text>
          <PickList items={analysis.replies} emptyText="추천할 답장이 없어요" labelPrefix="이 답장을 입력창에 넣기" testIDPrefix="chat-ai-reply" onPick={pickText} />

          <Text style={styles.section}>대화 주제 추천</Text>
          <PickList items={analysis.topics} emptyText="추천할 대화 주제가 없어요" labelPrefix="이 주제를 입력창에 넣기" testIDPrefix="chat-ai-topic" onPick={pickText} />

          <Text style={styles.caption}>{[rangeCaption(analysis.meta), resultCaption(analysis.meta)].filter(Boolean).join(" · ")}</Text>
          {privacyCaption(analysis.meta?.privacy) ? <Text style={styles.caption}>{privacyCaption(analysis.meta?.privacy)}</Text> : null}
        </View>
      ) : null}
    </>
  );
  })();

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.root}>
        <Pressable style={styles.backdrop} onPress={onClose} accessibilityRole="button" accessibilityLabel="AI 대화 도우미 닫기" testID="chat-ai-backdrop" />
        <View style={[styles.sheet, { paddingBottom: insets.bottom }]} testID="chat-ai">
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
  marker: { backgroundColor: colors.surfaceStrong, color: colors.text, fontFamily: font.bodyStrong.fontFamily }, // 중요 메시지 형광펜
  body: { ...font.body, color: colors.text },
  bodyStrong: { ...font.bodyStrong, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
  note: { ...font.caption, color: colors.warning },
  success: { ...font.caption, color: colors.success },
  error: { ...font.body, color: colors.danger },
  confirmCard: { gap: spacing.sm, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md },
  loading: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  result: { gap: spacing.xs, backgroundColor: colors.card, borderRadius: 14, padding: spacing.md },
  candidate: { gap: spacing.xs, paddingVertical: spacing.xs },
});
