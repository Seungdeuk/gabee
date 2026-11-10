import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, fonts, radius } from "@/theme";

import { MAKE_LIMIT, SCORE } from "../../games";
import { closeLabel } from "../../adapt";
import { playLive, useAudience, useMakeLeft } from "../../hooks";

/** 문제 번호 탭: 한 줄(문제 1~5 + 추가). 눌러서 문제를 바꾼다. */
export function QuestionTabs({ count = 3, active = 0, onSelect, onAdd, onRemove, flags = [], max = 5 }) {
  return (
    <View style={styles.tabsWrap}>
      <View style={styles.tabs}>
        {Array.from({ length: count }, (_, i) => (
          <Pressable key={i} onPress={() => onSelect?.(i)} accessibilityRole="tab" accessibilityState={{ selected: i === active }} style={[styles.qTab, i === active && styles.qTabOn]}>
            <Text style={[styles.qTabText, i === active && styles.qTabTextOn]}>문제 {i + 1}</Text>
            {flags[i] ? <View style={styles.flag} accessibilityLabel="덜 채웠어요" /> : null}
          </Pressable>
        ))}
        {count < max ? (
          <Pressable onPress={onAdd} accessibilityRole="button" accessibilityLabel="문제 추가" style={styles.add}>
            <Ionicons name="add" size={20} color={colors.text} />
          </Pressable>
        ) : null}
      </View>
      <View style={styles.countRow}>
        <Text style={styles.count}>
          {count} / {max}문제
        </Text>
        {onRemove && count > 1 ? (
          <Pressable onPress={onRemove} accessibilityRole="button" accessibilityLabel={`문제 ${active + 1} 삭제`} hitSlop={8} style={styles.remove}>
            <Ionicons name="trash-outline" size={15} color={colors.textSub} />
            <Text style={styles.removeText}>문제 {active + 1} 삭제</Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

/** 알약 선택 버튼: 평소엔 흰색, 고른 것만 노란색. */
export function Chip({ label, on, onPress }) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected: on }}
      style={[styles.chip, on && styles.chipOn]}
    >
      <Text style={[styles.chipText, on && styles.chipTextOn]}>{label}</Text>
    </Pressable>
  );
}

/** 두 칸 전환 토글(가비 추천/직접 내기, OX/선택). */
export function Toggle({ options, value, onChange }) {
  return (
    <View style={styles.toggle}>
      {options.map((o) => (
        <Pressable
          key={o.key}
          onPress={() => onChange(o.key)}
          accessibilityRole="tab"
          accessibilityState={{ selected: value === o.key }}
          style={[styles.toggleItem, value === o.key && styles.toggleOn]}
        >
          <Text style={[styles.toggleText, value === o.key && styles.toggleTextOn]}>{o.label}</Text>
        </Pressable>
      ))}
    </View>
  );
}

/** "누구에게 낼까요" 대상 칩. 지정하지 않으면 모두. */
export function AudiencePicker({ value, onChange }) {
  const members = useAudience(); // value 는 고른 가족의 id 목록(비어 있으면 모두)
  const all = value.length === 0;
  const toggle = (id) => onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id]);
  return (
    <View style={styles.block}>
      <Text style={styles.label}>누구에게 낼까요</Text>
      <View style={styles.row}>
        <Chip label="모두" on={all} onPress={() => onChange([])} />
        {members.map((m) => (
          <Chip key={m.id} label={m.name} on={value.includes(m.id)} onPress={() => toggle(m.id)} />
        ))}
      </View>
    </View>
  );
}

export function RevealNote({ children }) {
  // 서버에 연결되면 실제로 닫히는 시각(지금부터 24시간 뒤)을 보여 준다
  return <Text style={styles.reveal}>{playLive() ? `${closeLabel()}에 정답이 공개돼요, 모두 답하면 바로 열려요` : children}</Text>;
}

export function MakeQuotaNote() {
  const left = useMakeLeft();
  if (left == null) return null;
  return <Text style={styles.reveal}>{left > 0 ? `오늘 문제 출제로 받는 +${SCORE.make}은 ${left}회 남았어요` : `오늘은 문제 출제로 +${SCORE.make} 받는 ${MAKE_LIMIT}회를 다 썼어요. 문제는 보낼 수 있지만 점수는 없어요`}</Text>;
}

const styles = StyleSheet.create({
  tabsWrap: { gap: 6 },
  tabs: { flexDirection: "row", gap: 6, alignItems: "center" },
  qTab: { flex: 1, height: 36, borderRadius: 18, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  qTabOn: { backgroundColor: colors.surfaceStrong, borderColor: colors.surfaceStrong },
  qTabText: { fontSize: 13, fontFamily: fonts.regular, color: colors.textSub },
  qTabTextOn: { fontFamily: fonts.bold, color: colors.text },
  add: { width: 36, height: 36, borderRadius: 18, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  flag: { position: "absolute", top: 5, right: 7, width: 6, height: 6, borderRadius: 3, backgroundColor: colors.danger },
  countRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 28 },
  remove: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 28 },
  removeText: { fontSize: 13, fontFamily: fonts.regular, color: colors.textSub },
  count: { ...font.caption, color: colors.textSub },
  chip: { height: 36, paddingHorizontal: 14, borderRadius: 18, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  chipOn: { backgroundColor: colors.surfaceStrong, borderColor: colors.surfaceStrong },
  chipText: { fontSize: 14, fontFamily: fonts.regular, color: colors.text },
  chipTextOn: { fontFamily: fonts.bold },
  toggle: { flexDirection: "row", gap: 4, padding: 4, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card },
  toggleItem: { flex: 1, height: 44, borderRadius: 12, alignItems: "center", justifyContent: "center" },
  toggleOn: { backgroundColor: colors.surfaceStrong },
  toggleText: { fontSize: 15, fontFamily: fonts.regular, color: colors.textSub },
  toggleTextOn: { fontFamily: fonts.bold, color: colors.text },
  block: { gap: 8 },
  row: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  label: { ...font.bodyStrong, color: colors.text },
  reveal: { ...font.caption, color: colors.textSub, textAlign: "center" },
});
