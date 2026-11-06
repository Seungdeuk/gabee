import { useCallback, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import Segmented from "@/shared/components/Segmented";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { deletePlace, getPlaces, getTimeline, namePlace } from "../api";
import { dayLabel, describeSegment, shiftDay, todayKst } from "../timelineView";

/**
 * 하루 이동 기록(머묾·이동·기록 없음). 날짜를 앞뒤로 넘기고, 부모는 가족 구성원을 골라 본다.
 * 자주 간 이름 없는 곳에는 이름을 붙일 수 있다(본인 기록에서만). 좌표는 서버가 주지 않는다.
 * @param {{ members: import("../api").MemberLocation[], canSeeFamily: boolean, refreshKey?: number, notify: (text: string, isError?: boolean) => void }} props
 */
export default function TimelineCard({ members, canSeeFamily, refreshKey, notify }) {
  const [date, setDate] = useState(todayKst());
  const [target, setTarget] = useState(null); // null 이면 나
  const [naming, setNaming] = useState(null); // 이름을 붙이는 중인 후보 id
  const [draft, setDraft] = useState("");
  const [tick, setTick] = useState(0);
  const load = useCallback(() => getTimeline(date, target), [date, target]);
  const { data, error } = useResource(load, `${refreshKey}-${tick}`);
  const loadPlaces = useCallback(() => getPlaces(), []);
  const places = useResource(loadPlaces, tick);

  const others = canSeeFamily ? members.filter((m) => !m.is_me) : [];
  const options = [{ key: "me", label: "나" }, ...others.map((m) => ({ key: m.user_id, label: m.name }))];
  const isToday = date >= todayKst();

  const save = async (candidateId) => {
    try {
      await namePlace(candidateId, draft);
      setNaming(null);
      setDraft("");
      setTick((t) => t + 1);
      notify("장소 이름을 붙였어요");
    } catch (e) {
      notify(e.message || "이름을 붙이지 못했어요", true);
    }
  };
  const remove = async (id) => {
    try {
      await deletePlace(id);
      setTick((t) => t + 1);
    } catch (e) {
      notify(e.message || "지우지 못했어요", true);
    }
  };

  return (
    <Card tone="white">
      <Text style={styles.title}>이동 기록</Text>
      {options.length > 1 ? (
        <Segmented options={options} value={target ?? "me"} onChange={(key) => setTarget(key === "me" ? null : key)} />
      ) : null}
      <View style={styles.dayRow}>
        <Pressable onPress={() => setDate(shiftDay(date, -1))} accessibilityRole="button" accessibilityLabel="이전 날" style={styles.dayBtn}>
          <Text style={styles.dayArrow}>‹</Text>
        </Pressable>
        <Text style={styles.dayText}>{dayLabel(date)}</Text>
        <Pressable
          onPress={() => setDate(shiftDay(date, 1))}
          disabled={isToday}
          accessibilityRole="button"
          accessibilityLabel="다음 날"
          style={[styles.dayBtn, isToday && styles.dayBtnOff]}
        >
          <Text style={styles.dayArrow}>›</Text>
        </Pressable>
      </View>

      {error && !data ? <Text style={styles.error}>{error}</Text> : null}
      {data && !data.sharing ? <Text style={styles.caption}>{data.name}님은 위치 공유에 동의하지 않아 기록이 없어요.</Text> : null}
      {data?.sharing && data.segments.length === 0 ? <Text style={styles.caption}>이 날의 기록이 없어요.</Text> : null}

      {data?.segments.map((seg) => {
        const view = describeSegment(seg);
        const canName = data.can_name && seg.candidate_id;
        return (
          <View key={`${seg.kind}-${seg.start}`} style={styles.row}>
            <Text style={styles.time}>{view.time}</Text>
            <View style={styles.rowBody}>
              <Text style={[styles.rowTitle, view.tone === "muted" && styles.muted, view.tone === "warn" && styles.warn]}>{view.title}</Text>
              <Text style={styles.caption}>{view.sub}</Text>
              {canName && naming !== seg.candidate_id ? (
                <Button
                  label="이 장소에 이름 붙이기"
                  variant="ghost"
                  small
                  onPress={() => {
                    setNaming(seg.candidate_id);
                    setDraft("");
                  }}
                />
              ) : null}
              {canName && naming === seg.candidate_id ? (
                <View style={styles.nameRow}>
                  <Field value={draft} onChangeText={setDraft} placeholder="예: 학원, 할머니 댁" maxLength={20} style={styles.nameField} />
                  <Button label="저장" small onPress={() => save(seg.candidate_id)} disabled={!draft.trim()} />
                </View>
              ) : null}
            </View>
          </View>
        );
      })}

      {data?.can_name && places.data?.places.length ? (
        <View style={styles.places}>
          <Text style={styles.caption}>내가 이름 붙인 장소</Text>
          {places.data.places.map((p) => (
            <View key={p.id} style={styles.placeRow}>
              <Text style={styles.rowTitle}>{p.name}</Text>
              <Button label="지우기" variant="ghost" small onPress={() => remove(p.id)} />
            </View>
          ))}
        </View>
      ) : null}
    </Card>
  );
}

const styles = StyleSheet.create({
  title: { ...font.bodyStrong, color: colors.text },
  caption: { ...font.caption, color: colors.textSub },
  error: { ...font.caption, color: colors.danger },
  dayRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  dayBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: 22, backgroundColor: colors.surface },
  dayBtnOff: { opacity: 0.35 },
  dayArrow: { fontSize: 24, color: colors.text },
  dayText: { ...font.bodyStrong, color: colors.text },
  row: { flexDirection: "row", gap: 12, paddingVertical: 6 },
  time: { ...font.caption, color: colors.textMuted, width: 104 },
  rowBody: { flex: 1, gap: 2 },
  rowTitle: { ...font.body, color: colors.text, fontWeight: "600" },
  muted: { color: colors.textMuted, fontWeight: "400" },
  warn: { color: colors.danger },
  nameRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  nameField: { flex: 1 },
  places: { gap: 6, paddingTop: 6 },
  placeRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
});
