import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

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
import { candidateToRequestBody, dayFromChip, hasCandidateDay, requestErrorText, sendErrorMessage } from "../togetherUtils";
import {
  CONSENT_CANCEL_LABEL,
  CONSENT_DISABLE_BODY,
  CONSENT_DISABLE_CONFIRM_LABEL,
  CONSENT_DISABLE_LABEL,
  CONSENT_DISABLE_TITLE,
  CONSENT_ENABLE_LABEL,
  CONSENT_NEED_MANAGER,
  CONSENT_ON_MEMBER_NOTE,
  PANEL_NOTICE,
  needsEnableConfirm,
} from "../privacyCopy";
import AiConsentCard from "./AiConsentCard";
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
 * 채팅방 안 AI 대화 도우미 시트. 열릴 때 설정만 한 번 읽는다. "대화 분석하기" 버튼을 누르면 곧바로 AI 를 한 번 부른다(개인정보 설명·동의는 "AI 켜기" 동의 카드에서 받는다).
 * 켜진 상태에는 항상 보이는 한 줄 안내(PANEL_NOTICE)를 둔다. 요약·일정·할 일 후보·답장 추천·대화 주제 추천이 한 결과 화면에 나온다.
 * 결과는 서버에 잠시(약 10분) 저장돼 같은 요청에 다시 쓰인다.
 * 닫아도 컴포넌트는 유지되어 마지막 결과를 다시 열면 보여 준다. 닫혀 있는 동안에는 아무 호출도 하지 않는다.
 * 일정·할 일 후보를 등록하면 onLinked 로 알려 원본 메시지와의 연결을 저장하게 한다(연결 저장이 실패해도 등록은 성공으로 둔다).
 * @param {{ visible: boolean, onClose: () => void, onPickReply: (text: string) => void, onLinked?: (link: { kind: "event" | "todo", targetId: string, candidate: object }) => void }} props
 * @returns {JSX.Element}
 */
export default function AiPanel({ visible, onClose, onPickReply, onLinked }) {
  const [settings, setSettings] = useState(null); // parseAiSettings 결과
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(""); // "settings" | "analysis" | ""
  const [error, setError] = useState("");
  const [analysis, setAnalysis] = useState(null);
  const [registered, setRegistered] = useState({}); // 후보 순번 -> "ok" | "sending" | 오류 문구
  const [todoRegistered, setTodoRegistered] = useState({}); // 할 일 후보 순번 -> 같은 형태(함께하기로 보낸 결과)
  const [todoDay, setTodoDay] = useState({}); // 날짜가 없는 할 일 후보 순번 -> 고른 날짜 칩 key
  const [confirmingEnable, setConfirmingEnable] = useState(false); // 켜기 직전 안내 확인 중
  const [confirmingDisable, setConfirmingDisable] = useState(false); // 끄기 직전 확인 중
  const settingBusy = useRef(false); // 켜기·끄기 확인 버튼을 빠르게 두 번 눌러도 한 번만 보낸다
  const todoBusy = useRef(new Set()); // 등록 중이거나 등록된 할 일 후보 순번: 같은 후보를 두 번 등록하지 않는다

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

  /** "AI 기능 켜기" 버튼: 바로 켜지 않고 확인 카드를 연다(이미 켜져 있으면 아무 일도 없다). */
  const startEnable = () => {
    if (needsEnableConfirm(settings?.enabled, true)) setConfirmingEnable(true);
  };

  /** 확인 카드에서 "확인하고 켜기"/"끄기"를 눌렀을 때만 설정을 바꾼다. */
  const changeEnabled = async (enabled) => {
    if (settingBusy.current) return;
    settingBusy.current = true;
    try {
      await run("settings", () => setAiEnabled(enabled), () => {});
    } finally {
      settingBusy.current = false;
      setConfirmingEnable(false);
      setConfirmingDisable(false);
    }
  };

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

  /** "대화 분석하기"/"다시 분석하기": 누르면 곧바로 분석 API 를 한 번 호출한다. */
  const analyze = () =>
    run("analysis", analyzeChat, (res) => {
      setAnalysis(parseAnalysis(res));
      setRegistered({});
      setTodoRegistered({});
      setTodoDay({});
      todoBusy.current.clear();
    });

  /** 등록이 끝난 뒤 원본 메시지 연결을 부탁한다. 연결은 부가 기능이라 여기서 나는 오류는 등록 결과에 영향을 주지 않는다. */
  const notifyLinked = (link) => {
    try {
      onLinked?.(link);
    } catch {
      // 무시
    }
  };

  const register = async (index, candidate) => {
    setRegistered((r) => ({ ...r, [index]: "sending" }));
    try {
      const created = await registerScheduleCandidate(candidate);
      setRegistered((r) => ({ ...r, [index]: "ok" }));
      notifyLinked({ kind: "event", targetId: created?.id, candidate });
    } catch (e) {
      setRegistered((r) => ({ ...r, [index]: chatErrorMessage(e) }));
    }
  };

  /**
   * 사용자가 누른 할 일 후보 하나만 함께하기(일정 탭의 같이 요청)로 보낸다(서버 AI 를 부르지 않는다). 날짜는 후보에 있으면 그것을, 없으면 고른 날짜를 쓰고,
   * 받는 사람은 담당자 이름이 정확히 같은 한 명이면 그 사람, 아니면 가족 모두(나 제외)다.
   */
  const registerTodo = async (index, candidate) => {
    if (todoBusy.current.has(index)) return;
    const chosen = dayFromChip(todoDay[index]);
    if (!hasCandidateDay(candidate) && !chosen) {
      setTodoRegistered((r) => ({ ...r, [index]: requestErrorText("no_date") }));
      return;
    }
    todoBusy.current.add(index);
    setTodoRegistered((r) => ({ ...r, [index]: "sending" }));
    try {
      const group = await getRoomInfo({ raw: true }); // AI 가 돌려준 담당자 이름은 실제 이름이라 별명을 입히지 않은 구성원과 맞춘다
      const made = candidateToRequestBody(candidate, group, chosen);
      if (made.error) {
        todoBusy.current.delete(index);
        setTodoRegistered((r) => ({ ...r, [index]: requestErrorText(made.error) }));
        return;
      }
      const created = await sendTogetherRequest(made.body);
      setTodoRegistered((r) => ({ ...r, [index]: "ok" }));
      notifyLinked({ kind: "todo", targetId: created?.id, candidate });
    } catch (e) {
      todoBusy.current.delete(index); // 실패하면 다시 누를 수 있다
      setTodoRegistered((r) => ({ ...r, [index]: sendErrorMessage(e) }));
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

  if (!settings.enabled) {
    return (
      <>
        {confirmingEnable ? (
          <AiConsentCard
            busy={busy === "settings"}
            defaultOpen
            onConfirm={() => changeEnabled(true)}
            onCancel={() => setConfirmingEnable(false)}
          />
        ) : (
          <>
            <AiConsentCard />
            {settings.canManage ? (
              <Button
                label={CONSENT_ENABLE_LABEL}
                small
                onPress={startEnable}
                disabled={busy !== ""}
                testID="chat-ai-enable"
              />
            ) : (
              <Text style={styles.note} testID="chat-ai-need-manager">
                {CONSENT_NEED_MANAGER}
              </Text>
            )}
          </>
        )}
        {error ? (
          <Text style={styles.error} accessibilityRole="alert">
            {error}
          </Text>
        ) : null}
      </>
    );
  }

  const disabled = busy !== "";
  return (
    <>
      <Text style={styles.sub} testID="chat-ai-notice">
        {PANEL_NOTICE}
      </Text>
      {settings.canManage ? (
        confirmingDisable ? (
          <View style={styles.offCard} testID="chat-ai-disable-confirm">
            <Text style={styles.bodyStrong} accessibilityRole="header">
              {CONSENT_DISABLE_TITLE}
            </Text>
            <Text style={styles.sub}>{CONSENT_DISABLE_BODY}</Text>
            <View style={styles.row}>
              <Button label={busy === "settings" ? "끄는 중..." : CONSENT_DISABLE_CONFIRM_LABEL} small onPress={() => changeEnabled(false)} disabled={busy !== ""} testID="chat-ai-disable-confirm-yes" />
              <Button label={CONSENT_CANCEL_LABEL} small variant="secondary" onPress={() => setConfirmingDisable(false)} disabled={busy !== ""} testID="chat-ai-disable-confirm-no" />
            </View>
          </View>
        ) : (
          <Button label={CONSENT_DISABLE_LABEL} small variant="secondary" onPress={() => setConfirmingDisable(true)} disabled={busy !== ""} testID="chat-ai-disable" />
        )
      ) : (
        <Text style={styles.note} testID="chat-ai-on-member-note">
          {CONSENT_ON_MEMBER_NOTE}
        </Text>
      )}
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
            analysis.todo_candidates.map((t, i) => (
              <TodoCandidateRow key={`${t.title}-${i}`} candidate={t} state={todoRegistered[i]} day={todoDay[i] ?? null} onPickDay={(key) => setTodoDay((d) => ({ ...d, [i]: key }))} onRegister={() => registerTodo(i, t)} testID={`chat-ai-todo-${i}`} />
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
  offCard: { gap: spacing.xs, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md },
  candidate: { gap: spacing.xs, paddingVertical: spacing.xs },
});
