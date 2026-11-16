import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import ListItem from "@/shared/components/ListItem";
import SectionTitle from "@/shared/components/SectionTitle";
import { colors, font } from "@/theme";

import { won } from "../format";

/**
 * 송금 완료 내역. 평소에는 접어 두어 화면이 복잡해 보이지 않게 하고, 펼쳐도 취소 버튼은 숨겨 둔다.
 * "설정"을 누르면 줄마다 "취소"가 나타나고, 누르면 한 번 더 확인한 뒤에 송금 완료를 취소한다.
 * @param {{ items: import("../api").Settlement["completed"], onUndo: (id: string) => Promise<void> | void }} props
 */
export default function PaidList({ items, onUndo }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [asking, setAsking] = useState(null); // 취소 확인 중인 송금 id

  const toggleOpen = () => {
    setOpen(!open);
    setEditing(false);
    setAsking(null);
  };
  const toggleEditing = () => {
    setEditing(!editing);
    setAsking(null);
  };
  const confirm = async (id) => {
    setAsking(null);
    await onUndo(id);
  };

  return (
    <View style={styles.wrap}>
      <SectionTitle
        title="송금 완료"
        action={items.length > 0 ? (open ? "접기" : `내역 보기 (${items.length}건)`) : undefined}
        onAction={toggleOpen}
      />
      {items.length === 0 ? (
        <Card tone="white">
          <Text style={styles.muted}>아직 없어요</Text>
        </Card>
      ) : null}
      {open && items.length > 0 ? (
        <Card tone="white">
          <View style={styles.settings}>
            <Button
              small
              variant="ghost"
              label={editing ? "완료" : "설정"}
              a11yLabel={editing ? "송금 완료 설정 닫기" : "송금 완료 설정 열기"}
              onPress={toggleEditing}
            />
          </View>
          {items.map((p) => (
            <View key={p.id}>
              <ListItem
                icon="checkmark-circle"
                tone="green"
                title={`${p.from_name} → ${p.to_name}`}
                subtitle={`✓ 완료 · ${won(p.amount)}`}
                right={
                  editing ? (
                    <Button
                      small
                      variant="secondary"
                      label="취소"
                      a11yLabel={`${p.from_name} → ${p.to_name} 송금 취소`}
                      onPress={() => setAsking(p.id)}
                    />
                  ) : undefined
                }
              />
              {asking === p.id ? (
                <View style={styles.confirm} testID="undo-confirm">
                  <Text style={styles.confirmText}>
                    {p.from_name} → {p.to_name} {won(p.amount)} 송금 완료를 취소할까요?
                  </Text>
                  <View style={styles.confirmButtons}>
                    <Button small variant="secondary" label="아니요" onPress={() => setAsking(null)} />
                    <Button small label="취소하기" a11yLabel={`${p.from_name} → ${p.to_name} 송금 완료 취소하기`} onPress={() => confirm(p.id)} />
                  </View>
                </View>
              ) : null}
            </View>
          ))}
        </Card>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 8 },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 8 },
  settings: { alignItems: "flex-end" },
  confirm: { backgroundColor: colors.surface, borderRadius: 12, padding: 12, gap: 8 },
  confirmText: { ...font.caption, color: colors.text },
  confirmButtons: { flexDirection: "row", justifyContent: "flex-end", gap: 8 },
});
