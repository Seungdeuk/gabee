import { useState } from "react";
import { Pressable, StyleSheet, Text } from "react-native";

import Card from "@/shared/components/Card";
import ConfirmDialog from "@/shared/components/ConfirmDialog";
import { colors, font, radius, spacing } from "@/theme";

import { leaveMode } from "../leaveMode";

const LAST_INFO = "구성원이 나 혼자라서, 나가면 이 가족의 대화·사진·일정·가계·기록이 모두 삭제되고 되돌릴 수 없어요. 계정은 그대로 남아요.";
const INFO = "나가면 이 가족의 대화·일정·가계를 볼 수 없어요. 다시 들어오려면 초대 코드가 필요해요. 이미 남긴 기록은 그대로 남아요.";

/**
 * 화면 맨 아래 '가족 나가기'. 구성원은 확인 팝업을 거쳐 onLeave 를 부른다. 소유자는 다른 구성원이 있으면 나갈 수 없어 안내만 보이고,
 * 나 혼자일 때만 "모든 데이터가 삭제되고 되돌릴 수 없어요" 확인을 거쳐 나간다(가족이 사라진다).
 * @param {{ isOwner: boolean, memberCount?: number, onLeave: () => void, busy?: boolean }} props
 * @returns {import("react").ReactElement}
 */
export default function LeaveFamilySection({ isOwner, memberCount = 2, onLeave, busy = false }) {
  const [open, setOpen] = useState(false);
  const mode = leaveMode({ isOwner, memberCount });
  const last = mode === "last";
  if (mode === "blocked") {
    return (
      <Card tone="white" style={styles.card} testID="leave-family-owner">
        <Text style={styles.text}>소유자는 다른 구성원이 있으면 가족을 나갈 수 없어요. 구성원이 모두 나간 뒤에 나갈 수 있어요.</Text>
      </Card>
    );
  }
  return (
    <Card tone="white" style={styles.card}>
      <Text style={styles.text}>{last ? LAST_INFO : INFO}</Text>
      <Pressable
        style={[styles.button, busy && styles.disabled]}
        onPress={() => setOpen(true)}
        disabled={busy}
        accessibilityRole="button"
        aria-disabled={busy}
        testID="leave-family"
      >
        <Text style={styles.buttonText}>{last ? "삭제하고 나가기" : "가족 나가기"}</Text>
      </Pressable>
      <ConfirmDialog
        visible={open}
        title={last ? "가족을 삭제하고 나갈까요?" : "가족을 나갈까요?"}
        message={last ? LAST_INFO : INFO}
        cancelLabel="취소"
        confirmLabel={last ? "삭제하고 나가기" : "나가기"}
        onCancel={() => setOpen(false)}
        onConfirm={() => {
          setOpen(false);
          onLeave();
        }}
      />
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.md, padding: spacing.lg },
  text: { ...font.caption, color: colors.textMuted },
  button: { height: 48, alignItems: "center", justifyContent: "center", borderRadius: radius.button, borderWidth: 1, borderColor: colors.danger, backgroundColor: colors.card },
  disabled: { opacity: 0.5 },
  buttonText: { ...font.bodyStrong, color: colors.danger },
});
