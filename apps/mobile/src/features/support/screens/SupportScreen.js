import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import IconButton from "@/shared/components/IconButton";
import Screen from "@/shared/components/Screen";
import Segmented from "@/shared/components/Segmented";
import Tag from "@/shared/components/Tag";
import { colors, font, spacing } from "@/theme";

import { createTicket, listMyTickets } from "../api";
import { BODY_MAX, KIND_OPTIONS, PRIVACY_NOTE, SENT_NOTICE, TITLE_MAX, supportErrorMessage, ticketView, validateTicket } from "../messages";

const TABS = [
  { key: "write", label: "문의하기" },
  { key: "mine", label: "내 문의" },
];

/**
 * 보낸 문의·신고 한 건. 누르면 내용이 펼쳐지고, 답변이 있으면 답변이 함께 보인다.
 * @param {{ row: object }} props TicketOut
 * @returns {import("react").ReactElement}
 */
function TicketCard({ row }) {
  const t = ticketView(row);
  const [open, setOpen] = useState(t.answered);
  return (
    <Card tone="white" testID={`ticket-${t.id}`}>
      <Pressable onPress={() => setOpen((v) => !v)} accessibilityRole="button" accessibilityLabel={`${t.kindLabel}, ${t.statusLabel}, ${t.title}`} accessibilityState={{ expanded: open }}>
        <View style={styles.tags}>
          <Tag label={t.kindLabel} tone="blue" />
          <Tag label={t.statusLabel} tone={t.answered ? "green" : "orange"} />
          <Text style={styles.date}>{t.sentOn}</Text>
        </View>
        <Text style={styles.ticketTitle}>{t.title}</Text>
      </Pressable>
      {open ? <Text style={styles.body}>{t.body}</Text> : null}
      {open && t.answered ? (
        <View style={styles.answer}>
          <Text style={styles.answerHead}>{t.answeredOn ? `답변 · ${t.answeredOn}` : "답변"}</Text>
          <Text style={styles.body}>{t.answer}</Text>
        </View>
      ) : null}
    </Card>
  );
}

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
      setNotice(SENT_NOTICE);
      setTab("mine");
    } catch (e) {
      setSendError(supportErrorMessage(e));
    }
    setSending(false);
  };

  return (
    <Screen
      title="고객센터"
      left={<IconButton name="chevron-back" label="뒤로" onPress={() => (router.canGoBack() ? router.back() : router.replace("/my"))} />}
    >
      <Segmented options={TABS} value={tab} onChange={(key) => { setNotice(""); setTab(key); }} />
      {tab === "write" ? (
        <View style={styles.form}>
          <Segmented options={KIND_OPTIONS} value={kind} onChange={setKind} />
          {errors.kind ? <Text style={styles.error} accessibilityRole="alert">{errors.kind}</Text> : null}
          <Field label="제목" value={title} onChangeText={setTitle} maxLength={TITLE_MAX} error={errors.title} editable={!sending} placeholder="어떤 내용인지 짧게 적어 주세요" testID="support-title" />
          <Field label="내용" value={body} onChangeText={setBody} maxLength={BODY_MAX} multiline error={errors.body} editable={!sending} hint={`${body.length} / ${BODY_MAX}`} placeholder="자세히 적어 주세요" testID="support-body" />
          <Text style={styles.note}>{PRIVACY_NOTE}</Text>
          {sendError ? <Text style={styles.error} accessibilityRole="alert">{sendError}</Text> : null}
          <Button label={sending ? "보내는 중..." : "보내기"} onPress={send} disabled={sending} testID="support-send" />
        </View>
      ) : (
        <View style={styles.list}>
          {notice ? <Text style={styles.notice} accessibilityLiveRegion="polite">{notice}</Text> : null}
          {rows === null ? <ActivityIndicator color={colors.accent} /> : null}
          {listError ? (
            <View style={styles.center}>
              <Text style={styles.error} accessibilityRole="alert">{listError}</Text>
              <Button label="다시 시도" variant="secondary" small onPress={load} testID="support-retry" />
            </View>
          ) : null}
          {rows && rows.length === 0 && !listError ? <Text style={styles.empty}>아직 보낸 문의가 없어요</Text> : null}
          {rows ? rows.map((row) => <TicketCard key={String(row.id)} row={row} />) : null}
        </View>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  form: { gap: spacing.md },
  list: { gap: spacing.md },
  center: { gap: spacing.sm, alignItems: "flex-start" },
  tags: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.xs },
  date: { ...font.caption, color: colors.textMuted },
  ticketTitle: { ...font.cardTitle, color: colors.text },
  body: { ...font.body, color: colors.textSub },
  answer: { gap: spacing.xs, padding: spacing.md, borderRadius: 14, backgroundColor: colors.peachSoft },
  answerHead: { ...font.caption, color: colors.accent },
  note: { ...font.caption, color: colors.textMuted },
  notice: { ...font.body, color: colors.success },
  error: { ...font.caption, color: colors.danger },
  empty: { ...font.body, color: colors.textMuted },
});
