import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { getManager, getMembers, setManager } from "../api";

/**
 * 정산 담당자 표시와 변경. 월말 정산 알림은 담당자에게만 간다.
 * 변경은 지금 담당자나 그룹을 만든 사람만 할 수 있고, 권한이 없으면 서버가 거절한다.
 * @param {{ notify: (text: string, isError?: boolean) => void }} props
 */
export default function ManagerRow({ notify }) {
  const manager = useResource(getManager);
  const members = useResource(getMembers);
  const [open, setOpen] = useState(false);

  const choose = async (user) => {
    try {
      await setManager(user.id);
      notify(`정산 담당자를 ${user.name}(으)로 바꿨어요`);
      setOpen(false);
      await manager.reload();
    } catch (e) {
      notify(e.message, true);
    }
  };

  if (!manager.data) return null;
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
              onPress={() => choose(m)}
            />
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 8 },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  text: { ...font.caption, fontWeight: "600", color: colors.text, flex: 1 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
});
