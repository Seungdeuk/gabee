import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Field from "@/shared/components/Field";
import IconButton from "@/shared/components/IconButton";
import Screen from "@/shared/components/Screen";
import Segmented from "@/shared/components/Segmented";
import { colors, font, radius, spacing } from "@/theme";

import { createTicket, listMyTickets } from "../api";
import KindPicker from "../components/KindPicker";
import TicketCard from "../components/TicketCard";
import {
  BODY_MAX,
  EMPTY_TEXT,
  FILTERS,
  KIND_OPTIONS,
  PRIVACY_NOTE,
  SENT_NOTICE,
  TITLE_MAX,
  WRITE_INTRO,
  filterTickets,
  supportErrorMessage,
  ticketCounts,
  validateTicket,
} from "../messages";

const TABS = [
  { key: "write", label: "문의하기" },
  { key: "mine", label: "내 문의" },
];

/**
 * 마이 > 고객센터: 문의·신고를 보내고(문의하기), 보낸 것과 관리자 답변을 본다(내 문의).
 * `?tab=mine` 으로 열면 내 문의가 먼저 보인다(답변 알림을 눌렀을 때).
 * @returns {import("react").ReactElement}
 */
export default function SupportScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const [tab, setTab] = useState(params?.tab === "mine" ? "mine" : "write");
  const [kind, setKind] = useState("inquiry");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [errors, setErrors] = useState({});
  const [sendError, setSendError] = useState("");
  const [notice, setNotice] = useState("");
  const [sending, setSending] = useState(false);
  const [rows, setRows] = useState(null); // null: 불러오는 중
  const [listError, setListError] = useState("");
  const [filter, setFilter] = useState("all");

  const load = useCallback(async () => {
    setListError("");
    try {
      const res = await listMyTickets();
      setRows(Array.isArray(res?.rows) ? res.rows : []);
    } catch (e) {
      setRows([]);
      setListError(supportErrorMessage(e));
    }
  }, []);

  useEffect(() => {
    if (tab === "mine") load();
  }, [tab, load]);

  const counts = useMemo(() => ticketCounts(rows), [rows]);
  const shown = useMemo(() => filterTickets(rows, filter), [rows, filter]);

  const send = async () => {
    const checked = validateTicket({ kind, title, body });
    if (!checked.ok) {
      setErrors(checked.errors);
      return;
    }
    setErrors({});
    setSendError("");
    setSending(true);
    try {
      await createTicket(checked.value);
      setTitle("");
      setBody("");
      setFilter("all");
      setNotice(SENT_NOTICE);
      setTab("mine");
    } catch (e) {
      setSendError(supportErrorMessage(e));
    }
    setSending(false);
  };

  const empty = EMPTY_TEXT[filter] ?? EMPTY_TEXT.all;

  return (
    <Screen
      title="고객센터"
      left={<IconButton name="chevron-back" label="뒤로" onPress={() => (router.canGoBack() ? router.back() : router.replace("/my"))} />}
      right={tab === "mine" ? <IconButton name="refresh-outline" label="새로고침" onPress={load} /> : undefined}
    >
      <Segmented options={TABS} value={tab} onChange={(key) => { setNotice(""); setTab(key); }} />
      {tab === "write" ? (
        <View style={styles.form}>
          <View style={styles.intro}>
            <Text style={styles.introTitle}>{WRITE_INTRO.title}</Text>
            <Text style={styles.introSub}>{WRITE_INTRO.sub}</Text>
          </View>
          <KindPicker options={KIND_OPTIONS} value={kind} onChange={setKind} error={errors.kind} />
          <Field label="제목" value={title} onChangeText={setTitle} maxLength={TITLE_MAX} error={errors.title} editable={!sending} placeholder="어떤 내용인지 짧게 적어 주세요" testID="support-title" />
          <Field label="내용" value={body} onChangeText={setBody} maxLength={BODY_MAX} multiline error={errors.body} editable={!sending} hint={`${body.length} / ${BODY_MAX}`} placeholder="자세히 적어 주세요" testID="support-body" />
          <View style={styles.info}>
            <Ionicons name="information-circle-outline" size={18} color={colors.textMuted} />
            <Text style={styles.infoText}>{PRIVACY_NOTE}</Text>
          </View>
          {sendError ? <Text style={styles.error} accessibilityRole="alert">{sendError}</Text> : null}
          <Button label={sending ? "보내는 중..." : "보내기"} onPress={send} disabled={sending} testID="support-send" />
        </View>
      ) : (
        <View style={styles.list}>
          {notice ? (
            <View style={styles.notice} accessibilityLiveRegion="polite">
              <Ionicons name="checkmark-circle" size={18} color={colors.success} />
              <Text style={styles.noticeText}>{notice}</Text>
            </View>
          ) : null}
          <View style={styles.filters} accessibilityRole="tablist">
            {FILTERS.map((f) => {
              const active = f.key === filter;
              return (
                <Pressable
                  key={f.key}
                  onPress={() => setFilter(f.key)}
                  accessibilityRole="tab"
                  accessibilityState={{ selected: active }}
                  testID={`support-filter-${f.key}`}
                  style={[styles.chip, active && styles.chipActive]}
                >
                  <Text style={[styles.chipText, active && styles.chipTextActive]}>{f.label} {counts[f.key]}</Text>
                </Pressable>
              );
            })}
          </View>
          {rows === null ? <ActivityIndicator color={colors.accent} /> : null}
          {listError ? (
            <View style={styles.center}>
              <Text style={styles.error} accessibilityRole="alert">{listError}</Text>
              <Button label="다시 시도" variant="secondary" small onPress={load} testID="support-retry" />
            </View>
          ) : null}
          {rows && shown.length === 0 && !listError ? (
            <View style={styles.empty}>
              <View style={styles.emptyIcon}>
                <Ionicons name="chatbubble-ellipses-outline" size={28} color={colors.accent} />
              </View>
              <Text style={styles.emptyTitle}>{empty.title}</Text>
              {empty.sub ? <Text style={styles.emptySub}>{empty.sub}</Text> : null}
              {filter === "all" ? <Button label="문의하기" small onPress={() => { setNotice(""); setTab("write"); }} testID="support-empty-write" /> : null}
            </View>
          ) : null}
          {shown.map((row) => <TicketCard key={String(row.id)} row={row} />)}
        </View>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  form: { gap: spacing.lg },
  intro: { gap: spacing.xs, marginTop: spacing.xs },
  introTitle: { ...font.title, color: colors.text },
  introSub: { ...font.caption, color: colors.textMuted },
  info: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start", padding: spacing.md, borderRadius: radius.md, backgroundColor: colors.surface },
  infoText: { ...font.caption, color: colors.textMuted, flex: 1 },
  list: { gap: spacing.md },
  notice: { flexDirection: "row", gap: spacing.sm, alignItems: "center", padding: spacing.md, borderRadius: radius.md, backgroundColor: colors.successSoft },
  noticeText: { ...font.caption, color: colors.success, flex: 1 },
  filters: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" },
  chip: { paddingHorizontal: spacing.md, paddingVertical: 7, borderRadius: radius.pill, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.divider },
  chipActive: { backgroundColor: colors.dark, borderColor: colors.dark },
  chipText: { ...font.caption, color: colors.textMuted },
  chipTextActive: { color: colors.onDark, fontWeight: "700" },
  center: { gap: spacing.sm, alignItems: "flex-start" },
  empty: { alignItems: "center", gap: spacing.sm, paddingVertical: spacing.xxl },
  emptyIcon: { width: 64, height: 64, borderRadius: 32, alignItems: "center", justifyContent: "center", backgroundColor: colors.honeySoft, marginBottom: spacing.xs },
  emptyTitle: { ...font.cardTitle, color: colors.text },
  emptySub: { ...font.caption, color: colors.textMuted, marginBottom: spacing.sm },
  error: { ...font.caption, color: colors.danger },
});
