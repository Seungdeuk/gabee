import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { pinA11yLabel, pinBarView, pinLine, pinMeta } from "../pinUtils";

/**
 * 채팅방 헤더 아래 게시판 바. 보일 공지(내가 숨기지 않은 것)도, 숨긴 공지도, 안내 문구도 없으면 아무것도 그리지 않는다.
 * 펼치면 최근 공지 2개를 한 줄씩(핀 아이콘, 본문 한 줄 말줄임, 보낸 사람 이름, 아래 보조 줄에 올린 사람·시각과 원본 삭제 표시), 접으면 가장 최근 1개만 보인다.
 * 줄을 누르면 그 메시지로 이동하고, 오른쪽 화살표로 접고 펼치며(공지가 2개일 때만), 눈 아이콘으로 그 공지를 나만 숨긴다. 숨긴 공지가 있으면 맨 아래에 "숨긴 공지 N개 · 다시 보기"가 있다.
 * @param {{ pins: object[], expanded: boolean, onToggle: () => void, onPick: (messageId: number) => void, onHide?: (messageId: number) => void, onShowHidden?: () => void, notice?: string, nameOf?: (userId: string) => string | undefined }} props
 */
export default function PinnedBar({ pins, expanded, onToggle, onPick, onHide, onShowHidden, notice = "", nameOf }) {
  const view = pinBarView(pins, expanded);
  if (view.rows.length === 0 && view.hiddenByMe === 0 && !notice) return null;
  return (
    <View style={styles.wrap}>
      {view.rows.map((pin, index) => (
        <View key={pin.message_id} style={styles.line}>
          <Pressable
            onPress={() => onPick(pin.message_id)}
            accessibilityRole="button"
            accessibilityLabel={pinA11yLabel(pin, nameOf)}
            style={({ pressed }) => [styles.main, pressed && styles.pressed]}
          >
            <Ionicons name="pin" size={16} color={colors.accent} />
            <View style={styles.texts}>
              <View style={styles.row}>
                <Text style={styles.who} numberOfLines={1}>
                  {nameOf?.(pin.user_id) || pin.user_name}
                </Text>
                <Text style={styles.text} numberOfLines={1}>
                  {pinLine(pin)}
                </Text>
              </View>
              {expanded ? (
                <Text style={styles.meta} numberOfLines={1}>
                  {pinMeta(pin, nameOf)}
                </Text>
              ) : null}
            </View>
          </Pressable>
          {index === 0 && view.canToggle ? (
            <Pressable
              onPress={onToggle}
              accessibilityRole="button"
              accessibilityLabel={expanded ? "게시판 접기" : `게시판 공지 ${view.hidden}개 더 보기`}
              accessibilityState={{ expanded }}
              style={styles.toggle}
            >
              <Ionicons name={expanded ? "chevron-up" : "chevron-down"} size={18} color={colors.textSub} />
            </Pressable>
          ) : null}
          {onHide ? (
            <Pressable onPress={() => onHide(pin.message_id)} accessibilityRole="button" accessibilityLabel={`${pinLine(pin).slice(0, 20)} 공지 나만 숨기기`} hitSlop={spacing.xs} style={styles.toggle}>
              <Ionicons name="eye-off-outline" size={18} color={colors.textSub} />
            </Pressable>
          ) : null}
        </View>
      ))}
      {view.hiddenByMe > 0 && onShowHidden ? (
        <Pressable onPress={onShowHidden} accessibilityRole="button" accessibilityLabel={`숨긴 공지 ${view.hiddenByMe}개 다시 보기`} hitSlop={spacing.sm} style={styles.hiddenLine}>
          <Ionicons name="eye-outline" size={14} color={colors.textMuted} />
          <Text style={styles.hiddenText}>{`숨긴 공지 ${view.hiddenByMe}개 · 다시 보기`}</Text>
        </Pressable>
      ) : null}
      {notice ? (
        <View style={styles.notice} accessibilityLiveRegion="polite">
          <Text style={styles.noticeText}>{notice}</Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.divider },
  line: { flexDirection: "row", alignItems: "center" },
  main: { flex: 1, minWidth: 0, minHeight: 40, flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.xs },
  pressed: { backgroundColor: colors.surfaceStrong },
  texts: { flex: 1, minWidth: 0 },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  who: { ...font.caption, fontFamily: font.bodyStrong.fontFamily, color: colors.textSub, flexShrink: 0, maxWidth: "35%" },
  text: { ...font.caption, color: colors.text, flex: 1 },
  meta: { ...font.tab, color: colors.textMuted },
  toggle: { width: 44, minHeight: 40, alignItems: "center", justifyContent: "center" },
  hiddenLine: { minHeight: spacing.xxl + spacing.md, flexDirection: "row", alignItems: "center", gap: spacing.xs, paddingHorizontal: spacing.lg }, // 터치 영역은 hitSlop 으로 넓힌다
  hiddenText: { ...font.tab, color: colors.textMuted },
  notice: { alignItems: "center", paddingVertical: spacing.xs, paddingHorizontal: spacing.lg, backgroundColor: colors.honeySoft, borderRadius: radius.sm },
  noticeText: { ...font.caption, color: colors.textSub },
});
