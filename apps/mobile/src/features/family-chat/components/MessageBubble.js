import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { Platform, Pressable, StyleSheet, Text, View } from "react-native";

import AuthImage from "@/shared/components/AuthImage";
import UserAvatar from "@/shared/components/UserAvatar";
import { colors, font, radius, spacing } from "@/theme";

import { formatTime } from "../chatUtils";
import { unreadByA11yLabel } from "../listUtils";
import { fitSize } from "../photo";
import { bubbleSelectable, bubbleTextStyle } from "../pinUtils";
import AssistantAvatar from "./AssistantAvatar";
import PhotoViewer from "./PhotoViewer";

const AVATAR = 36;

/**
 * 말풍선 한 줄. 내 말은 오른쪽(복숭아색, 시각은 왼쪽 아래), 상대는 왼쪽(아바타·이름·카드색, 시각은 오른쪽 아래).
 * 내 말풍선은 아직 읽지 않은 사람이 있을 때만 시각 위에 작은 숫자(unread)를 보여 준다(모두 읽으면 표시 없음).
 * 사진 메시지(attachment)는 글자 대신 썸네일을 말풍선 안에 보여 주고(원본 비율로 크기를 미리 정해 레이아웃이 점프하지 않는다), 누르면 전체 화면으로 본다.
 * 전송 중이면 "전송 중…", 실패하면 "전송 실패 · 다시 보내기"(누르면 재전송, 길게 누르거나 "삭제" 로 지움).
 * 가비(AI)가 @가비 호출에 답해 올린 메시지(is_assistant)는 반짝이 아바타와 꿀색 말풍선으로 사람과 구분한다.
 * 검색 결과로 이동했을 때 그 메시지는 highlighted 로 잠깐 배경색을 입힌다.
 * linkBadges 가 있으면(이 메시지에서 일정·할 일로 등록됨) 글 아래에 작은 표시를 붙인다(표시만, 눌러도 아무 일 없다).
 * onActions 가 있으면(서버에 저장된 텍스트 메시지) 말풍선을 길게 눌러 메뉴(복사·고정)를 연다. 네이티브에서는 길게 누르기가 글자 선택과 겹치지 않도록 이 경우 글자 선택을 끈다(복사는 메뉴에서 한다).
 * onSaveToRecord 가 있으면(가족 전체방의 사진) 전체 화면 사진 보기에 "가비 기록에 저장" 버튼이 붙고, 누르면 그 사진을 AI 비서의 가족 기록으로 올린다(결과 문구는 사진 보기에 보인다).
 * @param {{ message: object, mine: boolean, showName: boolean, showTime?: boolean, unread?: number, photoUrl?: string | null, highlighted?: boolean, onRetry?: (clientId: string) => void, onDiscard?: (clientId: string) => void, onActions?: (message: object) => void, linkBadges?: { kind: "event" | "todo", label: string }[], onSaveToRecord?: (attachment: object) => Promise<{ ok: boolean, message: string }> }} props
 */
export default function MessageBubble({ message, mine, showName, showTime = true, unread = 0, photoUrl, highlighted = false, onRetry, onDiscard, onActions, linkBadges, onSaveToRecord }) {
  const failed = message.status === "failed";
  const sending = message.status === "sending";
  const attachment = message.attachment ?? null;
  const [viewing, setViewing] = useState(false);
  const [record, setRecord] = useState({ saving: false, done: false, notice: "" }); // 가비 기록에 저장한 상태(이 사진 하나의 것)
  const size = attachment ? fitSize(attachment.width, attachment.height) : null;

  /** "가비 기록에 저장"을 눌렀을 때: 저장 중이거나 이미 저장했으면 다시 올리지 않는다(같은 사진이 기록에 두 번 쌓이지 않게). */
  const saveRecord = async () => {
    if (!onSaveToRecord || record.saving || record.done) return;
    setRecord({ saving: true, done: false, notice: "" });
    const result = await onSaveToRecord(attachment);
    setRecord({ saving: false, done: result.ok, notice: result.message });
  };

  const selectable = bubbleSelectable({ canAct: Boolean(onActions), os: Platform.OS });
  const Box = onActions ? Pressable : View;
  const boxProps = onActions
    ? {
        onLongPress: () => onActions(message),
        accessibilityHint: "길게 누르면 메뉴가 열려요",
        accessibilityActions: [{ name: "menu", label: "메뉴 열기" }],
        onAccessibilityAction: (e) => {
          if (e.nativeEvent.actionName === "menu") onActions(message);
        },
      }
    : null;
  const bubble = (
    <Box {...boxProps} style={[styles.bubble, attachment && styles.photoBubble, mine ? styles.mineBubble : styles.otherBubble, message.is_assistant && styles.assistantBubble, sending && styles.dim]}>
      {attachment ? (
        <>
          <Pressable onPress={() => setViewing(true)} accessibilityRole="imagebutton" accessibilityLabel="사진, 누르면 크게 봐요">
            <AuthImage path={attachment.thumb_url} style={[styles.photo, { width: size.width, aspectRatio: size.width / size.height }]} />
          </Pressable>
          <PhotoViewer
            path={attachment.url}
            visible={viewing}
            onClose={() => setViewing(false)}
            onSaveToRecord={onSaveToRecord ? saveRecord : undefined}
            recordSaving={record.saving}
            recordDone={record.done}
            recordNotice={record.notice}
          />
        </>
      ) : null}
      {message.text ? (
        <Text style={bubbleTextStyle({ selectable, base: styles.text, photo: attachment ? styles.photoText : null, noSelect: styles.noSelect })} selectable={selectable}>
          {message.text}
        </Text>
      ) : null}
      {(linkBadges ?? []).map((b) => (
        <View key={b.kind} style={styles.linkChip} accessible accessibilityLabel={b.label}>
          <Ionicons name={b.kind === "event" ? "calendar-outline" : "checkbox-outline"} size={12} color={colors.accent} />
          <Text style={styles.linkChipText}>{b.label}</Text>
        </View>
      ))}
    </Box>
  );

  let meta = null;
  if (failed) {
    meta = (
      <View style={styles.failRow}>
        <Pressable
          onPress={() => onRetry?.(message.clientId)}
          onLongPress={() => onDiscard?.(message.clientId)}
          accessibilityRole="button"
          accessibilityLabel="전송 실패. 다시 보내기. 길게 누르면 지워요"
          style={styles.failBox}
        >
          <Text style={styles.fail}>전송 실패 · 다시 보내기</Text>
        </Pressable>
        <Pressable onPress={() => onDiscard?.(message.clientId)} accessibilityRole="button" accessibilityLabel="보내지 못한 메시지 삭제" style={styles.failBox}>
          <Text style={styles.discard}>삭제</Text>
        </Pressable>
      </View>
    );
  } else if (sending) {
    meta = <Text style={styles.time}>전송 중…</Text>;
  } else if (showTime) {
    meta = <Text style={styles.time}>{formatTime(message.created_at)}</Text>;
  }

  const unreadNode =
    mine && !failed && !sending && unread > 0 ? (
      <Text style={styles.unread} accessibilityLabel={unreadByA11yLabel(unread)}>
        {unread}
      </Text>
    ) : null;

  if (mine) {
    return (
      <View style={[styles.row, styles.mineRow, highlighted && styles.highlight]}>
        {meta || unreadNode ? (
          <View style={styles.metaMine}>
            {unreadNode}
            {meta}
          </View>
        ) : null}
        {bubble}
      </View>
    );
  }
  return (
    <View style={[styles.row, highlighted && styles.highlight]}>
      {showName ? (
        message.is_assistant ? (
          <AssistantAvatar size={AVATAR} />
        ) : (
          <UserAvatar name={message.user_name || "?"} userId={message.user_id} photoUrl={photoUrl} size={AVATAR} />
        )
      ) : (
        <View style={styles.spacer} />
      )}
      <View style={styles.column}>
        {showName ? <Text style={styles.name}>{message.user_name}</Text> : null}
        <View style={styles.line}>
          {bubble}
          {meta ? <View style={styles.metaOther}>{meta}</View> : null}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: 2 },
  mineRow: { justifyContent: "flex-end" },
  highlight: { backgroundColor: colors.honeySoft },
  spacer: { width: AVATAR },
  column: { flexShrink: 1, maxWidth: "80%", gap: spacing.xs, alignItems: "flex-start" }, // 폭 기준은 row(확정된 폭)의 %. 안쪽 말풍선은 이 폭 안에서만 줄어든다
  line: { flexDirection: "row", alignItems: "flex-end", gap: spacing.xs, maxWidth: "100%" },
  name: { ...font.tab, fontFamily: font.bodyStrong.fontFamily, color: colors.textSub },
  bubble: { flexShrink: 1, maxWidth: "70%", paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, borderRadius: radius.bubble },
  mineBubble: { backgroundColor: colors.peach, borderBottomRightRadius: spacing.xs },
  otherBubble: { maxWidth: "100%", backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, borderTopLeftRadius: spacing.xs },
  assistantBubble: { backgroundColor: colors.honeySoft, borderColor: colors.accent },
  photoBubble: { paddingHorizontal: spacing.xs, paddingVertical: spacing.xs }, // 위쪽 bubble 의 가로·세로 여백(longhand)이 padding 보다 우선해서 같은 방향으로 덮어쓴다
  photo: { maxWidth: "100%", borderRadius: radius.md }, // 좁은 화면에서는 말풍선 안으로 비율을 지키며 줄어든다
  photoText: { paddingHorizontal: spacing.sm, paddingVertical: spacing.xs },
  dim: { opacity: 0.6 },
  linkChip: { flexDirection: "row", alignItems: "center", gap: spacing.xs, alignSelf: "flex-start", marginTop: spacing.xs, paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.pill, backgroundColor: colors.honeySoft },
  linkChipText: { ...font.tab, color: colors.accent },
  noSelect: { userSelect: "none" }, // styles.text 의 userSelect 가 selectable prop 을 이기므로 스타일에서도 끈다
  text: { ...font.body, color: colors.text, userSelect: "text" },
  time: { ...font.tab, color: colors.textMuted },
  unread: { ...font.tab, fontFamily: font.bodyStrong.fontFamily, color: colors.accent },
  metaMine: { alignItems: "flex-end", justifyContent: "flex-end", flexShrink: 0 },
  metaOther: { justifyContent: "flex-end", flexShrink: 0 },
  failRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  failBox: { minHeight: 32, justifyContent: "center" },
  fail: { ...font.tab, color: colors.danger },
  discard: { ...font.tab, color: colors.textMuted },
});
