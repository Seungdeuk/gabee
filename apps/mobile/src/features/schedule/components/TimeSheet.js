import { useState } from "react";
import { Pressable, StyleSheet, Switch, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { addMinutes, time24Blocks, timeFromBlocks, to12h, withPeriod } from "../utils/time";
import BlockInput from "./BlockInput";
import BottomSheet from "./BottomSheet";
import SegmentedControl from "./SegmentedControl";
import TimeWheel from "./TimeWheel";

const TIME_BLOCKS = [
  { key: "h", length: 2, hint: "HH", min: 0, max: 23, padAbove: 2 },
  { key: "m", length: 2, hint: "MM", min: 0, max: 59, padAbove: 5 },
];
const PERIOD_OPTIONS = [
  { key: "오전", label: "오전" },
  { key: "오후", label: "오후" },
];

/**
 * 시간 선택 시트: 왼쪽에 시작·끝을 한 줄씩(라벨, 오전|오후 두 글자 버튼, 작은 HH:MM 입력 칸), 오른쪽에 시·분을 돌려 고르는 시계.
 * 화면은 모두 24시간 표기이고(입력 칸·시계·등록 화면의 시간 칸), 입력 칸과 시계는 같은 값 하나를 보여 줘서 어느 쪽에서 바꿔도 바로 따라온다.
 * - 입력 칸에서 시·분 영역을 터치하면 영역이 선택되고, 숫자를 치면 그 영역이 새로 채워진다.
 * - 오전|오후는 입력할 때의 변환 보조다. 오후를 골라 두고 11을 치면 23:00이 되고, 13~23시로 치면 쓴 그대로 오후다.
 *   버튼을 누르면 지금 시각이 오전·오후로 12시간 옮겨지고, 시각이 12시 이후면 오후 버튼이 켜져 있다.
 * - 시작을 바꾸면 끝이 시작 + 1시간으로 따라가고, 끝을 직접 고친 뒤에는 끝이 시작보다 늦을 때만 맞춘다.
 * - 종일을 켜면 시작·끝·시계는 흐려지고 눌러도 반응하지 않는다.
 * @param {{ visible: boolean, value: { allDay: boolean, startTime: string | null, endTime: string | null }, onClose: () => void, onSelect: (time: { allDay: boolean, startTime: string | null, endTime: string | null }) => void }} props
 */
export default function TimeSheet({ visible, value, onClose, onSelect }) {
  const [allDay, setAllDay] = useState(value.allDay);
  const [times, setTimes] = useState({ start: value.startTime ?? "12:00", end: value.endTime ?? "13:00" });
  const [endTouched, setEndTouched] = useState(value.endTime !== null);
  const [active, setActive] = useState("start");
  const [drafts, setDrafts] = useState({ start: null, end: null }); // 아직 두 자리씩 안 찬 입력 중인 시·분

  const setTime = (field, time) => {
    setDrafts((d) => ({ ...d, [field]: null }));
    if (field === "start") {
      setTimes((t) => ({ start: time, end: !endTouched || t.end <= time ? addMinutes(time, 60) : t.end }));
    } else {
      setEndTouched(true);
      setTimes((t) => ({ ...t, end: time }));
    }
  };
  const type = (field, blocks) => {
    const parsed = timeFromBlocks(blocks[0], blocks[1], to12h(times[field]).period);
    if (parsed) setTime(field, parsed);
    else setDrafts((d) => ({ ...d, [field]: blocks }));
  };
  const setPeriod = (field, period) => setTime(field, withPeriod(times[field], period));

  const line = (field, label) => (
    <View style={styles.line} key={field}>
      <Text style={styles.lineLabel}>{label}</Text>
      <SegmentedControl compact options={PERIOD_OPTIONS} value={to12h(times[field]).period} onChange={(p) => setPeriod(field, p)} />
      <View style={styles.lineInput}>
        <BlockInput
          compact
          blocks={TIME_BLOCKS}
          separators={[":"]}
          values={drafts[field] ?? time24Blocks(times[field])}
          active={active === field}
          onFocus={() => setActive(field)}
          onChange={(blocks) => type(field, blocks)}
        />
      </View>
    </View>
  );

  return (
    <BottomSheet visible={visible} onClose={onClose}>
      <View style={styles.head}>
        <Text style={styles.title}>시간</Text>
        <View style={styles.allDay}>
          <Text style={styles.allDayLabel}>종일</Text>
          <Switch value={allDay} onValueChange={setAllDay} trackColor={{ true: colors.peach, false: colors.border }} thumbColor={colors.card} />
        </View>
      </View>

      <View style={[styles.split, allDay && styles.dimmed]} pointerEvents={allDay ? "none" : "auto"}>
        <View style={styles.inputs}>
          {line("start", "시작")}
          {line("end", "끝")}
        </View>
        <View style={styles.wheel}>
          <TimeWheel
            value={times[active]}
            onChange={(time) => {
              if (time !== times[active]) setTime(active, time);
            }}
          />
        </View>
      </View>

      <Pressable
        onPress={() => onSelect({ allDay, startTime: allDay ? null : times.start, endTime: allDay ? null : times.end })}
        style={styles.save}
        accessibilityRole="button"
      >
        <Text style={styles.saveText}>선택</Text>
      </Pressable>
    </BottomSheet>
  );
}

const styles = StyleSheet.create({
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  title: { ...font.title, color: colors.text },
  allDay: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  allDayLabel: { fontSize: 14, fontWeight: "500", color: colors.text },
  split: { flexDirection: "row", alignItems: "center", gap: 12 },
  dimmed: { opacity: 0.4 },
  inputs: { flex: 1.6, gap: spacing.md },
  line: { flexDirection: "row", alignItems: "center", gap: 6 },
  lineLabel: { width: 26, fontSize: 14, fontWeight: "500", color: colors.text },
  lineInput: { flex: 1 },
  wheel: { flex: 1 },
  save: {
    minHeight: 56,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.button,
    backgroundColor: colors.peach,
  },
  saveText: { fontSize: 16, fontWeight: "700", color: colors.text },
});
