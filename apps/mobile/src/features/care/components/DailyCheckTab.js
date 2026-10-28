import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import SectionTitle from "@/shared/components/SectionTitle";
import Tag from "@/shared/components/Tag";
import { formatTime } from "@/shared/components/TimePicker";
import { colors, font } from "@/theme";

import { deleteEntry, deleteItem, putEntry } from "../api";
import { agoText, toMinutes, untilText } from "../format";
import AddItemForm from "./AddItemForm";
import HoldToDelete from "./HoldToDelete";
import ItemInput, { entryText } from "./ItemInput";

/**
 * 데일리 체크. 위에서부터
 * 1) 다가오는 일정: 지금 해야 할 것 → 곧 다가오는 순서(현재 시각 기준, 서버가 정렬)
 * 2) 완료한 항목
 * 3) 지난 시간 정리: 예정 시각이 지났는데 기록이 없는 항목을 모아 소급 입력 또는 건너뛰기로 처리한다
 * 누락은 예정 시각 + 60분을 기준으로 서버가 계산한다. 건강 이상을 뜻하지 않는다.
 * @param {{ daily: import("../api").Daily, reload: () => Promise<void>, notify: (text: string, isError?: boolean) => void }} props
 */
export default function DailyCheckTab({ daily, reload, notify }) {
  const [retro, setRetro] = useState(null); // 소급 입력을 펼친 항목 id
  const [retroError, setRetroError] = useState(null); // 소급 입력 패널 안에 보여 줄 저장 실패 문구

  /** 저장 성공이면 펼친 패널을 접고, 실패하면 패널은 그대로 두고 오류를 알린다(패널 안: inPanel). */
  const act = async (run, doneText, inPanel = false) => {
    try {
      await run();
      if (doneText) notify(doneText);
      setRetro(null);
      setRetroError(null);
      await reload();
    } catch (e) {
      if (inPanel) setRetroError(e.message);
      else notify(e.message, true);
    }
  };
  const actInPanel = (run, doneText) => act(run, doneText, true);
  const toggleRetro = (id) => {
    setRetroError(null);
    setRetro(retro === id ? null : id);
  };

  const byId = Object.fromEntries(daily.items.map((i) => [i.id, i]));
  const pick = (ids) => ids.map((id) => byId[id]).filter(Boolean);
  const upcoming = pick(daily.upcoming_ids);
  const done = pick(daily.done_ids);
  const cleanup = pick(daily.cleanup_ids);
  const skipped = pick(daily.skipped_ids);
  const nowMin = toMinutes(daily.now);

  const skipAll = () =>
    act(async () => {
      for (const i of cleanup) await putEntry(i.id, { skipped: true });
    }, `${cleanup.length}개를 모두 건너뛰었어요`);

  return (
    <View style={styles.wrap}>
      <Card tone="blue">
        <Text style={styles.notice}>누락은 아직 기록되지 않았다는 뜻이에요. 건강에 이상이 있다는 뜻은 아니에요.</Text>
        <Text style={styles.caption}>항목을 길게 누르면 삭제할 수 있어요.</Text>
        <View style={styles.clockRow}>
          <Text style={styles.caption}>기준 시각</Text>
          <Text style={styles.statValue}>{daily.now}</Text>
        </View>
        <View style={styles.stats}>
          <Stat label="완료" value={`${done.length}/${daily.items.length}`} testID="done-count" />
          <Stat label="누락" value={String(cleanup.length)} testID="missing-count" />
        </View>
      </Card>

      <SectionTitle title="다가오는 일정" />
      {upcoming.length === 0 ? <Text style={styles.muted}>남은 일정이 없어요</Text> : null}
      {upcoming.map((item, index) => (
        <Card key={item.id} tone="white" testID={`feed-${item.name}`}>
          <HoldToDelete label={`${item.name} 삭제`} onDelete={() => act(() => deleteItem(item.id), "항목을 삭제했어요")} style={styles.holdBody}>
          <View style={styles.head}>
            <View style={styles.grow}>
              <Text style={styles.name}>{item.name}</Text>
              <Text style={styles.caption}>
                {formatTime(item.scheduled_time)} 예정{item.target ? ` · 목표 ${item.target}${item.unit}` : ""}
                {item.entry ? ` · 기록: ${entryText(item)}` : ""}
              </Text>
            </View>
            <Tag
              label={item.status === "due" ? `지금 · ${untilText(item.minutes_until)}` : `${index === 0 ? "다음 · " : ""}${untilText(item.minutes_until)}`}
              tone={item.status === "due" ? "orange" : "gray"}
            />
          </View>
          <ItemInput item={item} act={act} notify={notify} />
          </HoldToDelete>
        </Card>
      ))}

      {done.length > 0 ? (
        <>
          <SectionTitle title={`완료한 항목 (${done.length})`} />
          <Card tone="white" testID="done-list">
            {done.map((item) => (
              <HoldToDelete key={item.id} label={`${item.name} 기록 지우기`} onDelete={() => act(() => deleteEntry(item.id), "기록을 지웠어요")}>
                <View style={styles.doneRow}>
                  <View style={styles.grow}>
                    <Text style={styles.name}>{item.name}</Text>
                    <Text style={styles.caption}>
                      {formatTime(item.scheduled_time)} 예정 · {entryText(item)}
                    </Text>
                  </View>
                  {item.entry?.late ? <Tag label="소급" tone="orange" /> : null}
                  <Tag label="✓ 완료" tone="green" />
                </View>
              </HoldToDelete>
            ))}
          </Card>
        </>
      ) : null}

      <SectionTitle title={`지난 시간 정리 (${cleanup.length})`} />
      <Card tone="white" testID="cleanup">
        <Text style={styles.caption}>예정 시각이 지났는데 기록이 없는 항목이에요. 지금 기록하거나(소급 입력) 건너뛸 수 있어요.</Text>
        {cleanup.length === 0 ? <Text style={styles.muted}>정리할 항목이 없어요</Text> : null}
        {cleanup.map((item) => (
          <HoldToDelete key={item.id} label={`${item.name} 삭제`} onDelete={() => act(() => deleteItem(item.id), "항목을 삭제했어요")} style={styles.cleanRow}>
          <View testID={`cleanup-${item.name}`} style={styles.cleanInner}>
            <View style={styles.head}>
              <View style={styles.grow}>
                <Text style={styles.name}>{item.name}</Text>
                <Text style={styles.caption}>
                  {formatTime(item.scheduled_time)} 예정 · {agoText(nowMin - toMinutes(item.scheduled_time))}
                  {item.entry ? ` · 기록: ${entryText(item)}` : ""}
                </Text>
              </View>
              <Tag label="미기록 · 누락" tone="orange" />
            </View>
            <View style={styles.rowEnd}>
              <Button small label="소급 입력" a11yLabel={`${item.name} 소급 입력`} onPress={() => toggleRetro(item.id)} />
              <Button small variant="secondary" label="건너뛰기" a11yLabel={`${item.name} 건너뛰기`} onPress={() => act(() => putEntry(item.id, { skipped: true }), `건너뛰었어요 · ${item.name}`)} />
            </View>
            {retro === item.id ? (
              <View style={styles.retro}>
                <Text style={styles.caption}>지금 기록하면 늦게 기록한 것으로 표시돼요</Text>
                <ItemInput item={item} act={actInPanel} notify={(text) => setRetroError(text)} doneText="소급해서 기록했어요" />
                {retroError ? (
                  <Text style={styles.panelError} accessibilityRole="alert" testID="retro-error">
                    {retroError}
                  </Text>
                ) : null}
              </View>
            ) : null}
          </View>
          </HoldToDelete>
        ))}
        {cleanup.length >= 2 ? <Button small variant="secondary" label="모두 건너뛰기" a11yLabel="지난 항목 모두 건너뛰기" onPress={skipAll} /> : null}

        {skipped.length > 0 ? (
          <View style={styles.skippedBox} testID="skipped-list">
            <Text style={styles.label}>건너뛴 항목 ({skipped.length})</Text>
            {skipped.map((item) => (
              <View key={item.id} style={styles.doneRow}>
                <View style={styles.grow}>
                  <Text style={styles.name}>{item.name}</Text>
                  <Text style={styles.caption}>{formatTime(item.scheduled_time)} 예정</Text>
                </View>
                <Tag label="건너뜀" tone="gray" />
                <Button small variant="secondary" label="되돌리기" a11yLabel={`${item.name} 되돌리기`} onPress={() => act(() => deleteEntry(item.id), "건너뛰기를 되돌렸어요")} />
              </View>
            ))}
          </View>
        ) : null}
      </Card>

      <AddItemForm notify={notify} onAdded={reload} />
    </View>
  );
}

function Stat({ label, value, testID }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.caption}>{label}</Text>
      <Text style={styles.statValue} testID={testID}>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
  head: { flexDirection: "row", alignItems: "center", gap: 12 },
  grow: { flex: 1, gap: 2 },
  name: { ...font.cardTitle, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
  label: { fontSize: 14, fontWeight: "500", color: colors.text },
  notice: { ...font.caption, color: colors.text },
  clockRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  stats: { flexDirection: "row", justifyContent: "space-between" },
  stat: { flex: 1, alignItems: "center", gap: 4 },
  statValue: { ...font.bodyStrong, fontWeight: "700", color: colors.text },
  rowEnd: { flexDirection: "row", justifyContent: "flex-end", gap: 8, flexWrap: "wrap" },
  doneRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 6 },
  holdBody: { gap: 12 },
  cleanRow: { paddingVertical: 12, borderTopWidth: 1, borderTopColor: colors.divider },
  cleanInner: { gap: 10 },
  panelError: { ...font.caption, color: colors.danger, fontWeight: "600" },
  retro: { gap: 8, padding: 12, borderRadius: 14, backgroundColor: colors.surface },
  skippedBox: { gap: 4, paddingTop: 12, borderTopWidth: 1, borderTopColor: colors.divider },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 8 },
});
