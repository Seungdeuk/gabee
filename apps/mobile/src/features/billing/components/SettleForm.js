import { useCallback, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import ListItem from "@/shared/components/ListItem";
import SectionTitle from "@/shared/components/SectionTitle";
import Tag from "@/shared/components/Tag";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { getExpenses, getMembers, getSettleTags, settleExpenses } from "../api";
import { TAG_LABEL, won } from "../format";
import TagBadge from "./TagBadge";

/**
 * 정산하기: 정산하는 사람이 지출을 고르고 대상 태그를 걸어 정산한다. 태그는 이 버튼을 누를 때 걸린다.
 * 기본은 고정 태그(부모님 대상·자녀 대상·가족 전체)이고, "직접 고르기"를 켜면 고정 태그로 채워진 인원을
 * 그대로 두고 사람을 더하거나 뺄 수 있다. 고정 태그로 돌아오는 버튼이 늘 보인다.
 * @param {{ month: string, notify: (text: string, isError?: boolean) => void, onSettled: () => Promise<void> | void }} props
 */
export default function SettleForm({ month, notify, onSettled }) {
  const loadExpenses = useCallback(() => getExpenses(month), [month]);
  const expenses = useResource(loadExpenses);
  const tags = useResource(getSettleTags);
  const members = useResource(getMembers);

  const [selected, setSelected] = useState([]); // 정산할 지출 id
  const [tagKey, setTagKey] = useState("parents");
  const [free, setFree] = useState(false); // 직접 고르기 모드
  const [picks, setPicks] = useState([]); // 직접 고르기에서 고른 나눌 사람
  const [busy, setBusy] = useState(false);

  const fixedTags = tags.data ?? [];
  const people = members.data ?? [];
  const list = expenses.data ?? [];
  const fixed = fixedTags.find((t) => t.key === tagKey);
  const participants = free ? picks : (fixed?.participants ?? []);

  const turnOnFree = () => {
    setPicks(fixed?.participants ?? []); // 고정 태그로 채워진 인원을 그대로 가져간다
    setFree(true);
  };
  const backToFixed = () => setFree(false);
  const togglePick = (id) => setPicks(picks.includes(id) ? picks.filter((x) => x !== id) : [...picks, id]);
  const toggleExpense = (id) => setSelected(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  const allSelected = list.length > 0 && selected.length === list.length;

  const submit = async () => {
    setBusy(true);
    try {
      await settleExpenses({
        month,
        expense_ids: selected,
        tag: free ? "custom" : tagKey,
        participants: free ? picks : undefined,
      });
      notify(`정산하기를 마쳤어요 · ${selected.length}건 · ${free ? TAG_LABEL.custom : fixed.label}`);
      setSelected([]);
      setFree(false); // 다음 정산에 이번 직접 선택이 따라가지 않도록 고정 태그로 되돌린다
      await Promise.all([expenses.reload(), onSettled()]);
    } catch (e) {
      notify(e.message, true);
    } finally {
      setBusy(false);
    }
  };

  const canSubmit = selected.length > 0 && participants.length > 0 && !busy;

  return (
    <View style={styles.wrap}>
      <SectionTitle title="정산하기" />
      <Card tone="white">
        <Text style={styles.caption}>정산할 지출을 고르고, 누구 몫인지 대상 태그를 걸어 주세요.</Text>

        <View style={styles.rowBetween}>
          <Text style={styles.label}>정산할 지출</Text>
          <Button
            small
            variant="secondary"
            label={allSelected ? "전체 해제" : "전체 선택"}
            a11yLabel="지출 전체 선택"
            onPress={() => setSelected(allSelected ? [] : list.map((e) => e.id))}
          />
        </View>
        {list.length === 0 ? <Text style={styles.muted}>이 달 지출이 없어요</Text> : null}
        {list.map((e) => (
          <ListItem
            key={e.id}
            title={e.title}
            subtitle={`${e.date} · ${e.paid_by_name} 결제 · ${won(e.amount)}`}
            right={
              <View style={styles.right}>
                <TagBadge tag={e.target_tag} />
                <Button
                  small
                  variant="secondary"
                  selected={selected.includes(e.id)}
                  label={selected.includes(e.id) ? "선택됨" : "선택"}
                  a11yLabel={`${e.title} 선택`}
                  onPress={() => toggleExpense(e.id)}
                />
              </View>
            }
          />
        ))}

        <View style={styles.rowBetween}>
          <Text style={styles.label}>대상 태그</Text>
          <Pressable
            onPress={free ? backToFixed : turnOnFree}
            accessibilityRole="switch"
            accessibilityLabel="직접 고르기"
            aria-checked={free}
            hitSlop={8}
            style={styles.toggle}
            testID="free-toggle"
          >
            <View style={styles.toggleText}>
              <Text style={styles.toggleTitle}>직접</Text>
              <Text style={[styles.toggleHint, free && styles.toggleHintOn]}>{free ? "켜짐" : "켜기"}</Text>
            </View>
            <View style={[styles.track, free && styles.trackOn]}>
              <View style={[styles.thumb, free && styles.thumbOn]} />
            </View>
          </Pressable>
        </View>
        {free ? (
          <View style={styles.freeBanner} testID="free-banner">
            <Text style={styles.freeText}>직접 선택 중 · {fixed?.label ?? ""}에서</Text>
            <Button
              small
              variant="secondary"
              label="← 고정 태그로"
              a11yLabel="고정 태그로 돌아가기"
              onPress={backToFixed}
            />
          </View>
        ) : (
          <>
            <View style={styles.chips}>
              {fixedTags.map((t) => (
                <Button
                  key={t.key}
                  small
                  variant="secondary"
                  selected={t.key === tagKey}
                  label={t.label}
                  a11yLabel={`대상 태그 ${t.label}`}
                  onPress={() => setTagKey(t.key)}
                />
              ))}
            </View>
            {fixed ? <Text style={styles.caption}>{fixed.description}</Text> : null}
          </>
        )}

        <View style={styles.rowBetween}>
          <Text style={styles.label}>나눌 사람</Text>
          <Text style={styles.caption}>{participants.length}명</Text>
        </View>
        <View style={styles.chips}>
          {people.map((m) =>
            free ? (
              <Button
                key={m.id}
                small
                variant="secondary"
                selected={picks.includes(m.id)}
                label={m.name}
                a11yLabel={`나눌 사람 ${m.name}`}
                onPress={() => togglePick(m.id)}
              />
            ) : (
              <Tag
                key={m.id}
                label={participants.includes(m.id) ? `✓ ${m.name}` : `${m.name} 제외`}
                tone={participants.includes(m.id) ? "green" : "gray"}
              />
            ),
          )}
        </View>

        <Button label="정산하기" onPress={submit} disabled={!canSubmit} />
      </Card>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
  label: { fontSize: 14, fontWeight: "500", color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 8 },
  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  right: { alignItems: "flex-end", gap: 6 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  freeBanner: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    backgroundColor: colors.surfaceStrong,
    borderRadius: 12,
    paddingVertical: 6,
    paddingLeft: 12,
    paddingRight: 6,
  },
  freeText: { ...font.caption, fontWeight: "600", color: colors.text, flex: 1 },
  // 작은 스위치: 라벨(+힌트)과 36x20 트랙
  toggle: { flexDirection: "row", alignItems: "center", gap: 8 },
  toggleText: { alignItems: "flex-end" },
  toggleTitle: { fontSize: 13, fontWeight: "600", color: colors.text },
  toggleHint: { fontSize: 11, color: colors.textMuted },
  toggleHintOn: { color: colors.success, fontWeight: "700" },
  track: { width: 36, height: 20, borderRadius: 10, backgroundColor: colors.disabled, justifyContent: "center", paddingHorizontal: 2 },
  trackOn: { backgroundColor: colors.peach },
  thumb: { width: 16, height: 16, borderRadius: 8, backgroundColor: colors.card },
  thumbOn: { alignSelf: "flex-end" },
});
