import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { colors, radius } from "@/theme";

import {
  allCheersHandled,
  cheerBannerText,
  cheerCaption,
  cheerCardTitle,
  cheerKindLabel,
  cheerTone,
  formatClock,
  openCheersOf,
} from "../logic";

const CARD_WIDTH = 312;
const GAP = 10;
const STRIDE = CARD_WIDTH + GAP;
const KIND_ICON = { love: "heart", best: "thumbs-up", well: "star" };

/**
 * 받은 응원(내 탭 전용). 시안 CheerReceived 대로 "오늘 나의 체크" 진행률 카드 바로 아래에 둔다.
 * - 고마워도 안 하고 닫지도 않은 응원은 가로로 넘기는 카드로 보인다. 카드 오른쪽 위 X 는 서버에 닫기를 보내고 그 카드만 닫는다(고마워 보냄이 되지 않는다).
 * - 모두 처리(고마워 또는 닫기)하면 한 줄 배너 "오늘 받은 응원 N개 · 이름, 이름"으로 바뀐다.
 * - 오늘 받은 응원이 하나도 없으면 아무것도 그리지 않는다.
 * @param {{ cheers: object[], today: string, onThank: (id: string) => void, onDismiss: (id: string) => void, onOpenHistory: () => void, onReplyInfo?: () => void }} props
 */
export default function CheerStrip({ cheers, today, onThank, onDismiss, onOpenHistory, onReplyInfo }) {
  const [index, setIndex] = useState(0);
  const open = openCheersOf(cheers, today);
  if (allCheersHandled(cheers, today)) {
    return (
      <Pressable
        onPress={onOpenHistory}
        style={styles.banner}
        accessibilityRole="button"
        accessibilityLabel={cheerBannerText(cheers, today)}
      >
        <Ionicons name="heart" size={22} color={colors.danger} />
        <Text style={styles.bannerText}>{cheerBannerText(cheers, today)}</Text>
        <Ionicons name="chevron-forward" size={20} color={colors.textSub} />
      </Pressable>
    );
  }
  if (!open.length) return null;

  const current = Math.min(index, open.length - 1);
  return (
    <View style={styles.wrap}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        snapToInterval={STRIDE}
        decelerationRate="fast"
        contentContainerStyle={styles.row}
        onMomentumScrollEnd={(e) => setIndex(Math.round(e.nativeEvent.contentOffset.x / STRIDE))}
      >
        {open.map((c) => (
          <CheerCard
            key={c.id}
            cheer={c}
            onThank={() => onThank(c.id)}
            onDismiss={() => onDismiss(c.id)}
            onReply={() => onReplyInfo?.()}
          />
        ))}
      </ScrollView>

      <View style={styles.dots}>
        {open.map((c, i) => (
          <View key={c.id} style={[styles.dot, i === current && styles.dotOn]} />
        ))}
      </View>
      <View style={styles.footer}>
        <Text style={styles.caption}>{cheerCaption(cheers, today)}</Text>
        <Pressable onPress={onOpenHistory} hitSlop={8} accessibilityRole="button" accessibilityLabel="지난 응원 보기">
          <Text style={styles.link}>지난 응원 보기</Text>
        </Pressable>
      </View>
    </View>
  );
}

function CheerCard({ cheer, onThank, onDismiss, onReply }) {
  const tone = cheerTone(cheer.kind);
  return (
    <View style={[styles.card, { backgroundColor: tone.bg, borderColor: tone.border }]}>
      <View style={styles.cardTop}>
        <View style={styles.icon}>
          <Ionicons name={KIND_ICON[cheer.kind] ?? "heart"} size={24} color={tone.icon} />
        </View>
        <View style={styles.cardText}>
          <Text style={styles.cardTitle}>{cheerCardTitle(cheer.fromName)}</Text>
          <Text style={styles.cardSub}>{`${formatClock(cheer.time)} · ${cheerKindLabel(cheer.kind)}`}</Text>
        </View>
        <Pressable
          onPress={onDismiss}
          style={styles.close}
          hitSlop={4}
          accessibilityRole="button"
          accessibilityLabel={`${cheer.fromName} 응원 카드 닫기`}
        >
          <Ionicons name="close" size={20} color={colors.textSub} />
        </Pressable>
      </View>
      <Text style={styles.quote}>{`“${cheer.text}”`}</Text>
      <View style={styles.buttons}>
        <Pressable
          onPress={onThank}
          style={styles.btn}
          accessibilityRole="button"
          accessibilityLabel={`${cheer.fromName} 응원에 고마워`}
        >
          <Text style={styles.btnText}>고마워</Text>
        </Pressable>
        <Pressable onPress={onReply} style={styles.btn} accessibilityRole="button" accessibilityLabel={`${cheer.fromName} 응원에 답장하기`}>
          <Text style={styles.btnText}>답장하기</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 8 },
  row: { paddingHorizontal: 24, gap: GAP },
  card: {
    width: CARD_WIDTH,
    padding: 18,
    borderRadius: 20,
    borderWidth: 1,
    gap: 12,
    shadowColor: colors.text,
    shadowOpacity: 0.04,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 1,
  },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 12 },
  icon: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  cardText: { flex: 1, gap: 2 },
  cardTitle: { fontSize: 16, fontWeight: "700", color: colors.text },
  cardSub: { fontSize: 14, color: colors.textSub },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center", marginRight: -10, marginTop: -10 },
  quote: { fontSize: 16, lineHeight: 24, fontWeight: "500", color: colors.text },
  buttons: { flexDirection: "row", gap: 8 },
  btn: {
    flex: 1,
    height: 44,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    alignItems: "center",
    justifyContent: "center",
  },
  btnText: { fontSize: 15, fontWeight: "700", color: colors.text },
  dots: { flexDirection: "row", justifyContent: "center", gap: 6 },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.disabled },
  dotOn: { backgroundColor: colors.primary, width: 16 },
  footer: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 24, minHeight: 44 },
  caption: { fontSize: 13, color: colors.textSub },
  link: { fontSize: 14, fontWeight: "500", color: colors.accent },
  banner: {
    marginHorizontal: 24,
    height: 56,
    borderRadius: radius.button,
    backgroundColor: colors.peachSoft,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 16,
  },
  bannerText: { flex: 1, fontSize: 15, fontWeight: "500", color: colors.text },
});
