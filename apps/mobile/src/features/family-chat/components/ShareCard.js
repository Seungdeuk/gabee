import { Ionicons } from "@expo/vector-icons";
import { StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { eventCardView, settlementCardView, shareTextTone } from "../shareUtils";

/**
 * shareTextTone 이 돌려준 이름을 theme 색으로.
 * @param {{ mine: boolean, tone: string }} args
 * @returns {string}
 */
const toneColor = (args) => colors[shareTextTone(args)];

/**
 * 말풍선 안의 공유 카드(읽기 전용): 일정이면 라벨(약속·할 일)·제목·날짜시간·장소·함께하는 사람, 정산이면 월·내 남은 잔액·송금 줄.
 * 내용은 보낸 시점의 스냅샷이다. 카드 자체는 누름을 받지 않아(안쪽 누름 영역이 터치를 가로채지 않도록) 길게 누르기(메뉴)·두 번 누르기(하트)는 바깥 말풍선이 그대로 받는다. 카드를 눌러 해당 탭으로 가는 "열기"는 아직 없다.
 * 읽어 주는 문구는 바깥 말풍선이 붙이므로(TalkBack 이 두 번 읽지 않게) 카드 자체에는 접근성 속성을 두지 않는다.
 * 내 말풍선(mine)은 복숭아색 바탕이라 글자색을 모두 본문색으로 한다(정산의 받을/보낼 돈은 문구로 가린다).
 * 정산 카드는 보낸 사람 기준이라 남의 카드는 senderName(비면 "보낸 사람")을 주어로 보이고, 받을 돈·보낼 돈은 색이 아니라 글자로 구분한다.
 * @param {{ share: { kind: "event" | "settlement", payload: object }, mine?: boolean, senderName?: string }} props
 * @returns {import("react").ReactElement}
 */
export default function ShareCard({ share, mine = false, senderName = "" }) {
  return (
    <View style={styles.card}>
      {share.kind === "settlement" ? <SettlementBody payload={share.payload} mine={mine} senderName={senderName} /> : <EventBody payload={share.payload} mine={mine} />}
    </View>
  );
}

/**
 * 일정 카드 본문.
 * @param {{ payload: object, mine: boolean }} props
 * @returns {import("react").ReactElement}
 */
function EventBody({ payload, mine }) {
  const v = eventCardView(payload);
  return (
    <>
      <View style={styles.head}>
        <View style={styles.icon}>
          <Ionicons name={v.badge === "할 일" ? "checkbox-outline" : "calendar-outline"} size={20} color={colors.accent} />
        </View>
        <Text style={[styles.badge, { color: toneColor({ mine, tone: "sub" }) }]}>{v.badge}</Text>
      </View>
      <Text style={styles.title} numberOfLines={2}>
        {v.title}
      </Text>
      <Text style={styles.line}>{v.when}</Text>
      {v.place ? (
        <Text style={[styles.sub, { color: toneColor({ mine, tone: "sub" }) }]} numberOfLines={1}>
          {v.place}
        </Text>
      ) : null}
      {v.withText ? (
        <Text style={[styles.sub, { color: toneColor({ mine, tone: "sub" }) }]} numberOfLines={1}>
          {v.withText}
        </Text>
      ) : null}
    </>
  );
}

/**
 * 정산 카드 본문.
 * @param {{ payload: object, mine: boolean, senderName: string }} props
 * @returns {import("react").ReactElement}
 */
function SettlementBody({ payload, mine, senderName }) {
  const v = settlementCardView(payload, { mine, senderName });
  return (
    <>
      <View style={styles.head}>
        <View style={styles.icon}>
          <Ionicons name="wallet-outline" size={20} color={colors.accent} />
        </View>
        <Text style={[styles.badge, { color: toneColor({ mine, tone: "sub" }) }]}>{v.month ? `${v.month} 정산` : "정산"}</Text>
      </View>
      <Text style={[styles.title, { color: toneColor({ mine, tone: v.summary.tone }) }]}>{v.summary.text}</Text>
      {v.lines.map((line) => (
        <Text key={line.key} style={[styles.sub, { color: toneColor({ mine, tone: "sub" }) }]} numberOfLines={1}>
          {line.text}
        </Text>
      ))}
      {v.moreCount ? <Text style={[styles.sub, { color: toneColor({ mine, tone: "sub" }) }]}>{`외 ${v.moreCount}건`}</Text> : null}
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
