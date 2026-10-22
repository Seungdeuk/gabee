import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { getManager, getMembers, setManager, setMinors } from "../api";

/**
 * 정산 설정: 정산 담당자(월말 알림을 받는 사람)와 미성년 자녀 표시.
 * 미성년 자녀가 있으면 "자녀 대상" 정산은 부모님이 부담한다. 변경은 지금 담당자나 그룹을 만든 사람만 할 수 있고,
 * 권한이 없으면 서버가 거절한다.
 * @param {{ notify: (text: string, isError?: boolean) => void }} props
 */
export default function ManagerRow({ notify }) {
  const manager = useResource(getManager);
  const members = useResource(getMembers);
  const [open, setOpen] = useState(false);

  const run = async (fn, done) => {
    try {
      await fn();
      notify(done);
      await manager.reload();
    } catch (e) {
      notify(e.message, true);
    }
  };

  if (!manager.data) return null;
  const minors = manager.data.minor_ids;
  const children = (members.data ?? []).filter((m) => m.role !== "parent");

  const toggleMinor = (m) => {
    const next = minors.includes(m.id) ? minors.filter((x) => x !== m.id) : [...minors, m.id];
    run(() => setMinors(next), `${m.name} ${next.includes(m.id) ? "미성년으로 표시했어요" : "미성년 표시를 지웠어요"}`);
  };

  return (
    <View style={styles.wrap}>
      <View style={styles.row}>
        <Text style={styles.text} testID="manager-name">
          정산 담당 · {manager.data.manager_name}
          {manager.data.is_me ? " (나)" : ""}
        </Text>
        <Button small variant="secondary" label={open ? "닫기" : "바꾸기"} a11yLabel="정산 담당자 바꾸기" onPress={() => setOpen(!open)} />
      </View>
      {open ? (
        <View style={styles.chips}>
          {(members.data ?? []).map((m) => (
            <Button
              key={m.id}
              small
              variant="secondary"
              selected={m.id === manager.data.manager_id}
              label={m.name}
              a11yLabel={`정산 담당자 ${m.name}`}
              onPress={() => run(() => setManager(m.id), `정산 담당자를 ${m.name}(으)로 바꿨어요`)}
            />
          ))}
        </View>
      ) : null}
      {children.length > 0 ? (
        <View style={styles.minorRow}>
          <Text style={styles.caption}>미성년 자녀</Text>
          <View style={styles.chips}>
            {children.map((m) => (
              <Button
                key={m.id}
                small
                variant="secondary"
                selected={minors.includes(m.id)}
                label={m.name}
                a11yLabel={`미성년 ${m.name}`}
                onPress={() => toggleMinor(m)}
              />
            ))}
          </View>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 8 },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  text: { ...font.caption, fontWeight: "600", color: colors.text, flex: 1 },
  caption: { ...font.caption, color: colors.textMuted },
  minorRow: { gap: 6 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
});
