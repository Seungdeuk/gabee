import { Ionicons } from "@expo/vector-icons";
import { StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { eventCardView, settlementCardView, shareA11yLabel } from "../shareUtils";

const TONE_COLOR = { receive: colors.success, send: colors.danger, even: colors.textSub };

/**
 * 말풍선 안의 공유 카드(읽기 전용): 일정이면 라벨(약속·할 일)·제목·날짜시간·장소·함께하는 사람, 정산이면 월·내 남은 잔액·송금 줄.
 * 내용은 보낸 시점의 스냅샷이다. 카드 자체는 누름을 받지 않아(안쪽 누름 영역이 터치를 가로채지 않도록) 길게 누르기(메뉴)·두 번 누르기(하트)는 바깥 말풍선이 그대로 받는다. 카드를 눌러 해당 탭으로 가는 "열기"는 아직 없다.
 * @param {{ share: { kind: "event" | "settlement", payload: object } }} props
 */
export default function ShareCard({ share }) {
  return (
    <View accessible accessibilityRole="summary" accessibilityLabel={shareA11yLabel(share)} style={styles.card}>
      {share.kind === "settlement" ? <SettlementBody payload={share.payload} /> : <EventBody payload={share.payload} />}
    </View>
  );
}

/** 일정 카드 본문. @param {{ payload: object }} props */
function EventBody({ payload }) {
  const v = eventCardView(payload);
  return (
    <>
      <View style={styles.head}>
        <View style={styles.icon}>
          <Ionicons name={v.badge === "할 일" ? "checkbox-outline" : "calendar-outline"} size={20} color={colors.accent} />
        </View>
        <Text style={styles.badge}>{v.badge}</Text>
      </View>
      <Text style={styles.title} numberOfLines={2}>
        {v.title}
      </Text>
      <Text style={styles.line}>{v.when}</Text>
      {v.place ? (
        <Text style={styles.sub} numberOfLines={1}>
          {v.place}
        </Text>
      ) : null}
      {v.withText ? (
        <Text style={styles.sub} numberOfLines={1}>
          {v.withText}
        </Text>
      ) : null}
    </>
  );
}

/** 정산 카드 본문. @param {{ payload: object }} props */
function SettlementBody({ payload }) {
  const v = settlementCardView(payload);
  return (
    <>
      <View style={styles.head}>
        <View style={styles.icon}>
          <Ionicons name="wallet-outline" size={20} color={colors.accent} />
        </View>
        <Text style={styles.badge}>{v.month ? `${v.month} 정산` : "정산"}</Text>
      </View>
      <Text style={[styles.title, { color: TONE_COLOR[v.summary.tone] }]}>{v.summary.text}</Text>
      {v.lines.map((line) => (
        <Text key={line.key} style={styles.sub} numberOfLines={1}>
          {line.text}
        </Text>
      ))}
      {v.moreCount ? <Text style={styles.sub}>{`외 ${v.moreCount}건`}</Text> : null}
    </>
  );
}

const styles = StyleSheet.create({
  card: { minWidth: 200, gap: spacing.xs },
  head: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  icon: { width: 32, height: 32, borderRadius: radius.md, backgroundColor: colors.honeySoft, alignItems: "center", justifyContent: "center" },
  badge: { ...font.caption, color: colors.textSub },
  title: { ...font.bodyStrong, color: colors.text },
  line: { ...font.body, color: colors.text },
  sub: { ...font.caption, color: colors.textSub },
});
