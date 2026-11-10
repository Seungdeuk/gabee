import { Ionicons } from "@expo/vector-icons";
import { useCallback, useState } from "react";
import { Modal, Pressable, Share, StyleSheet, Text, View } from "react-native";

import { sendMessage } from "@/features/family-chat/api";
import { colors, font, fonts, radius } from "@/theme";

import { playLive } from "../hooks";
import { inviteMessage } from "../invite";

/**
 * 초대 시트: "소통방으로 보내기"(가족 소통방에 문구+링크 글자 메시지) / "다른 앱으로 공유"(카카오톡·문자 등).
 * 서버 주소가 없으면 소통방에는 실제로 보내지 않고 보냈다는 안내만 한다(시안).
 */
export function InviteSheet({ target, onClose }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const message = target ? inviteMessage(target.name, target.kind) : "";

  const toRoom = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      if (playLive()) await sendMessage(message);
      setSent(true);
      setTimeout(() => {
        setSent(false);
        onClose();
      }, 1200);
    } catch (e) {
      setError(e?.message || "보내지 못했어요. 잠시 뒤 다시 해 주세요");
    } finally {
      setBusy(false);
    }
  };

  const toApp = () => {
    onClose();
    // 외부 앱으로 보내는 링크는 앞부분을 바꿀 수 있다(EXPO_PUBLIC_PLAY_LINK_BASE, 예: Expo Go 시험용 exp://<PC 주소>:8081/--). 소통방은 항상 gabee:// 라 앱이 직접 연다
    Share.share({ message: inviteMessage(target?.name, target?.kind, process.env.EXPO_PUBLIC_PLAY_LINK_BASE) }).catch(() => {});
  };

  return (
    <Modal visible={Boolean(target)} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} accessibilityLabel="닫기">
        <Pressable style={styles.sheet} onPress={() => {}}>
          {sent ? (
            <Text style={styles.sent}>소통방에 초대 링크를 보냈어요</Text>
          ) : (
            <>
              <Text style={styles.title}>어디로 초대할까요?</Text>
              <Option icon="chatbubble-ellipses-outline" label="소통방으로 보내기" sub="가족 소통방에 게임 링크가 올라가요" onPress={toRoom} disabled={busy} />
              <Option icon="share-outline" label="다른 앱으로 공유" sub="카카오톡, 문자 등" onPress={toApp} disabled={busy} />
              {error ? <Text style={styles.error}>{error}</Text> : null}
            </>
          )}
        </Pressable>
      </Pressable>
    </Modal>
  );
}

function Option({ icon, label, sub, onPress, disabled }) {
  return (
    <Pressable onPress={onPress} disabled={disabled} accessibilityRole="button" accessibilityLabel={label} style={[styles.option, disabled && styles.optionOff]}>
      <View style={styles.optionIcon}>
        <Ionicons name={icon} size={18} color="#8A5A2B" />
      </View>
      <View style={styles.optionText}>
        <Text style={styles.optionLabel}>{label}</Text>
        <Text style={styles.optionSub}>{sub}</Text>
      </View>
    </Pressable>
  );
}

/** 초대 시트를 쓰는 화면용 훅. `ask({ name, kind })` 로 시트를 열고, 화면은 `sheet` 를 아무 데나 렌더링한다. */
export function useInvite() {
  const [target, setTarget] = useState(null);
  const ask = useCallback((t) => setTarget(t), []);
  const close = useCallback(() => setTarget(null), []);
  const sheet = <InviteSheet target={target} onClose={close} />;
  return { ask, sheet };
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(85,59,41,0.35)" },
  sheet: { gap: 10, padding: 18, paddingBottom: 28, backgroundColor: colors.card, borderTopLeftRadius: radius.card, borderTopRightRadius: radius.card },
  title: { ...font.cardTitle, color: colors.text, marginBottom: 2 },
  option: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, borderRadius: 14, backgroundColor: "#F7F0E6" },
  optionOff: { opacity: 0.5 },
  optionIcon: { width: 36, height: 36, borderRadius: 10, backgroundColor: colors.surfaceStrong, alignItems: "center", justifyContent: "center" },
  optionText: { flex: 1, gap: 2 },
  optionLabel: { fontSize: 15, fontFamily: fonts.bold, color: colors.text },
  optionSub: { ...font.caption, color: colors.textSub },
  error: { ...font.caption, color: colors.danger },
  sent: { ...font.bodyStrong, color: colors.text, textAlign: "center", paddingVertical: 24 },
});
