import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { confirmCardAction } from "../api";
import { CARD_CANCELLED, CARD_DONE, CARD_PENDING, buildShareText, cancelledText, cardButtons } from "../scheduleCard";

/**
 * 가족방의 공유 선택 카드(share_select): 일정 조회 결과 중 방에 공유할 항목을 체크해 고르면 선택한 줄만 내 이름의 일반 메시지로 보낸다.
 * 서버를 따로 부르지 않고 onShareToRoom(text) 로 방의 기존 전송 경로를 쓴다. 보내지 못하면 오류를 보여 주고 다시 누를 수 있다.
 * onShareToRoom 이 없는 화면(개인 AI 채팅)에서는 공유할 수 없으니 카드를 그리지 않는다.
 */
function ShareSelectCard({ card, onResolve, onShareToRoom }) {
  const [selected, setSelected] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const status = card.status ?? CARD_PENDING;

  if (status === CARD_DONE || status === CARD_CANCELLED) return <ResolvedLine card={card} status={status} />;
  if (!onShareToRoom) return null;

  const toggle = (id) => {
    if (busy) return;
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };
  const text = buildShareText(card.items, selected);
  const count = selected.length;

  const share = async () => {
    if (busy || !text) return;
    setBusy(true);
    setError("");
    try {
      await onShareToRoom(text);
      onResolve?.(CARD_DONE, `${count}개를 방에 공유했어요`);
    } catch (e) {
      setError(e?.message || "방에 보내지 못했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.card} accessibilityLabel="방에 공유할 항목 선택 카드">
      <View style={styles.head}>
        <Ionicons name="share-outline" size={16} color={colors.accent} />
        <Text style={styles.title}>{card.title}</Text>
      </View>
      {card.items.map((item) => {
        const on = selected.includes(item.id);
        return (
          <Pressable
            key={item.id}
            onPress={() => toggle(item.id)}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: on, disabled: busy }}
            accessibilityLabel={item.line}
            style={styles.item}
          >
            <Ionicons name={on ? "checkbox" : "square-outline"} size={22} color={on ? colors.accent : colors.textMuted} />
            <Text style={styles.itemText}>{item.line}</Text>
          </Pressable>
        );
      })}
      {error ? (
        <Text style={styles.error} accessibilityLiveRegion="polite">
          {error}
        </Text>
      ) : null}
      <View style={styles.row}>
        {cardButtons(card).map((b) => {
          const disabled = busy || (b.key === "share" && !text);
          return (
            <Pressable
              key={b.key}
              onPress={() => (b.key === "cancel" ? onResolve?.(CARD_CANCELLED, "") : share())}
              disabled={disabled}
              accessibilityRole="button"
              accessibilityLabel={b.label}
              accessibilityState={{ disabled }}
              style={[styles.btn, b.tone === "ghost" ? styles.ghost : styles.main, disabled && styles.off]}
            >
              {busy && b.key === "share" ? <ActivityIndicator color={colors.onDark} /> : <Text numberOfLines={1} style={b.tone === "ghost" ? styles.ghostText : styles.mainText}>{b.label}</Text>}
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

/** 처리했거나 닫은 카드: 결과 한 줄 */
function ResolvedLine({ card, status }) {
  const done = status === CARD_DONE;
  return (
    <View style={[styles.card, styles.resolved]} accessibilityLiveRegion="polite">
      <Ionicons name={done ? "checkmark-circle" : "close-circle-outline"} size={18} color={done ? colors.success : colors.textMuted} />
      <Text style={styles.resolvedText}>{done ? card.resultText || "반영했어요." : cancelledText(card)}</Text>
    </View>
  );
}

/**
 * 채팅의 확인 카드: 일정(가족에게 공유해서 등록 / 수정 / 삭제)과 정산·돌봄 에이전트의 쓰기 제안(지출·식단·돌봄 기록). 서버는 채팅에서 바로 실행하지 않고, 사용자가 이 버튼을 눌러야 반영된다.
 * 처리했거나 취소하면 카드가 결과 한 줄로 바뀌고(onResolve 로 대화에 저장돼 다시 열어도 두 번 실행되지 않는다) 버튼은 사라진다.
 * 서버 오류(예: 등록에 필요한 제목이나 날짜가 없어요)는 카드 아래에 보여 주고 다시 누를 수 있게 둔다.
 * 가족방의 공유 선택 카드(share_select)는 onShareToRoom(text) → Promise 로 선택한 줄을 방에 보낸다(서버 확인 요청을 부르지 않는다).
 * @param {{ card: object, onResolve?: (status: "done" | "cancelled", text: string) => void, onShareToRoom?: (text: string) => Promise<unknown> }} props
 */
export default function ScheduleConfirmCard({ card, onResolve, onShareToRoom }) {
  if (card.action === "share_select") return <ShareSelectCard card={card} onResolve={onResolve} onShareToRoom={onShareToRoom} />;
  return <ServerConfirmCard card={card} onResolve={onResolve} />;
}

function ServerConfirmCard({ card, onResolve }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const status = card.status ?? CARD_PENDING;

  if (status === CARD_DONE || status === CARD_CANCELLED) {
    return <ResolvedLine card={card} status={status} />;
  }

  const press = async (button) => {
    if (busy) return;
    if (button.key === "cancel") {
      onResolve?.(CARD_CANCELLED, "");
      return;
    }
    setBusy(button.key);
    setError("");
    try {
      const { text } = await confirmCardAction(card, button.share);
      onResolve?.(CARD_DONE, text);
    } catch (e) {
      setError(e?.message || "처리하지 못했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      setBusy("");
    }
  };

  return (
    <View style={styles.card} accessibilityLabel={card.kind === "proposal" ? "제안 확인 카드" : "일정 확인 카드"}>
      <View style={styles.head}>
        <Ionicons name={card.kind === "proposal" ? "create-outline" : "calendar-outline"} size={16} color={colors.accent} />
        <Text style={styles.title}>{card.title}</Text>
      </View>
      {card.lines.map((line, i) => (
        <Text key={`${i}-${line}`} style={styles.line}>
          {line}
        </Text>
      ))}
      {card.sharedWith.length > 0 ? <Text style={styles.share}>공유 대상 · {card.sharedWith.join(", ")}</Text> : null}
      {error ? (
        <Text style={styles.error} accessibilityLiveRegion="polite">
          {error}
        </Text>
      ) : null}
      <View style={styles.row}>
        {cardButtons(card).map((b) => (
          <Pressable
            key={b.key}
            onPress={() => press(b)}
            disabled={Boolean(busy)}
            accessibilityRole="button"
            accessibilityLabel={b.label}
            style={[styles.btn, b.tone === "ghost" ? styles.ghost : b.tone === "danger" ? styles.danger : styles.main, busy && styles.off]}
          >
            {busy === b.key ? <ActivityIndicator color={b.tone === "ghost" ? colors.text : colors.onDark} /> : <Text numberOfLines={1} style={b.tone === "ghost" ? styles.ghostText : styles.mainText}>{b.label}</Text>}
          </Pressable>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { marginTop: spacing.sm, padding: spacing.md, gap: spacing.xs, borderRadius: radius.md, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  head: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  title: { ...font.body, fontFamily: font.bodyStrong.fontFamily, color: colors.text, flexShrink: 1 },
  line: { ...font.body, color: colors.text },
  share: { ...font.caption, color: colors.textSub },
  item: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 44 },
  itemText: { ...font.body, color: colors.text, flexShrink: 1 },
  error: { ...font.caption, color: colors.danger },
  row: { flexDirection: "row", flexWrap: "nowrap", gap: spacing.xs, marginTop: spacing.sm }, // 버튼은 한 줄에 가로로(줄바꿈 없이)
  btn: { flexGrow: 1, flexShrink: 1, minHeight: 40, paddingHorizontal: spacing.sm, borderRadius: radius.pill, alignItems: "center", justifyContent: "center" }, // 글자 길이에 맞춰 나누고 남는 폭을 고르게 채운다
  main: { backgroundColor: colors.accent },
  danger: { backgroundColor: colors.danger },
  ghost: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  off: { opacity: 0.6 },
  mainText: { ...font.caption, fontFamily: font.bodyStrong.fontFamily, color: colors.onDark },
  ghostText: { ...font.caption, fontFamily: font.bodyStrong.fontFamily, color: colors.text },
  resolved: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.surface },
  resolvedText: { ...font.caption, color: colors.textSub, flexShrink: 1 },
});
