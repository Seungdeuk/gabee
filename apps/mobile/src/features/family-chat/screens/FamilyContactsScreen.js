import { useRouter, useFocusEffect } from "expo-router";
import { useCallback, useMemo, useRef, useState } from "react";
import { ActivityIndicator, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import Button from "@/shared/components/Button";
import IconButton from "@/shared/components/IconButton";
import { colors, font, spacing } from "@/theme";

import { getRoomInfo, listNicknames, openDirectRoom, setNickname } from "../api";
import { isNoGroup, roomErrorMessage } from "../chatUtils";
import { applySavedNickname, contactErrorMessage, contactRows, nicknameMap } from "../contactUtils";
import ContactRow from "../components/ContactRow";
import NicknameModal from "../components/NicknameModal";

/**
 * 가족 연락처: 구성원 이름·관계·사진, 내가 붙인 별명·메모, 1:1 대화 시작. 전화번호는 다루지 않는다.
 * 화면이 보일 때와 당겨서 새로고침할 때만 불러온다(폴링 없음).
 */
export default function FamilyContactsScreen() {
  const router = useRouter();
  const [state, setState] = useState({ status: "loading", group: null, error: "" });
  const [nicknames, setNicknames] = useState({});
  const [nickError, setNickError] = useState("");
  const [nickReady, setNickReady] = useState(false); // 별명 목록을 받았을 때만 편집할 수 있다(PUT 이 별명·메모를 통째로 덮어쓰므로)
  const [refreshing, setRefreshing] = useState(false);
  const [editing, setEditing] = useState(null); // 별명을 고치는 구성원 id
  const [opening, setOpening] = useState(null);
  const [talkError, setTalkError] = useState("");
  const openingRef = useRef(false); // 같은 순간의 두 번째 누름은 ref 로 막는다
  const back = () => (router.canGoBack() ? router.back() : router.replace("/family-chat"));

  const load = useCallback(async () => {
    try {
      // 별명은 곁다리라 실패해도 연락처는 보여 준다
      const [group, nicks] = await Promise.all([getRoomInfo({ raw: true }), listNicknames().catch((e) => ({ failed: e }))]);
      setNickError(Array.isArray(nicks) ? "" : contactErrorMessage(nicks.failed));
      setNickReady(Array.isArray(nicks));
      if (Array.isArray(nicks)) setNicknames(nicknameMap(nicks));
      setState({ status: "ready", group, error: "" });
    } catch (e) {
      setState((s) => (isNoGroup(e) ? { status: "none", group: null, error: "" } : s.status === "ready" ? { ...s, error: roomErrorMessage(e) } : { status: "error", group: null, error: roomErrorMessage(e) }));
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const rows = useMemo(() => contactRows(state.group?.members, state.group?.my_id, nicknames), [state.group, nicknames]);
  const editRow = rows.find((r) => r.id === editing);

  const talk = async (row) => {
    if (openingRef.current) return;
    openingRef.current = true;
    setOpening(row.id);
    setTalkError("");
    try {
      const room = await openDirectRoom(row.id);
      router.push({ pathname: "/chat-room", params: { roomId: room.id, peer: row.id } });
    } catch (e) {
      setTalkError(roomErrorMessage(e));
    } finally {
      openingRef.current = false;
      setOpening(null);
    }
  };

  const saveNickname = async (id, value) => {
    try {
      const saved = await setNickname(id, value);
      setNicknames((cur) => applySavedNickname(cur, id, saved));
      return "";
    } catch (e) {
      return contactErrorMessage(e);
    }
  };

  let body;
  if (state.status === "loading") {
    body = (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} accessibilityLabel="불러오는 중" />
      </View>
    );
  } else if (state.status === "none") {
    body = (
      <View style={styles.center}>
        <Text style={styles.emptyTitle}>가족을 먼저 만들어 주세요</Text>
        <Button label="가족 만들기 · 참여하기" onPress={() => router.push("/family")} />
      </View>
    );
  } else if (state.status === "error") {
    body = (
      <View style={styles.center}>
        <Text style={styles.emptyText}>{state.error}</Text>
        <Button label="다시 시도" onPress={load} />
      </View>
    );
  } else {
    body = (
      <ScrollView contentContainerStyle={styles.content} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />}>
        <Text style={styles.hint}>별명과 메모는 나에게만 보여요.</Text>
        {nickError || talkError || state.error ? (
          <Text style={styles.error} accessibilityRole="alert">
            {talkError || state.error || nickError}
          </Text>
        ) : null}
        {!nickReady ? (
          <View style={styles.nickRetry}>
            <Text style={styles.error}>별명을 불러온 뒤에 고칠 수 있어요</Text>
            <Button label="다시 불러오기" small variant="secondary" onPress={load} />
          </View>
        ) : null}
        {rows.map((r) => (
          <ContactRow key={r.id} row={r} canEdit={nickReady} busy={opening === r.id} onTalk={() => talk(r)} onEdit={() => setEditing(r.id)} />
        ))}
        {editRow ? <NicknameModal key={editRow.id} row={{ ...editRow, memo: nicknames[editRow.id]?.memo ?? "" }} onClose={() => setEditing(null)} onSave={(value) => saveNickname(editRow.id, value)} /> : null}
      </ScrollView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.bar}>
        <IconButton name="chevron-back" label="뒤로" onPress={back} />
        <Text style={styles.barTitle} accessibilityRole="header">
          가족 연락처
        </Text>
      </View>
      {body}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  bar: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, borderBottomWidth: 1, borderBottomColor: colors.divider },
  barTitle: { ...font.cardTitle, color: colors.text, flex: 1 },
  content: { paddingHorizontal: spacing.lg, paddingVertical: spacing.md, gap: spacing.xs },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md, padding: spacing.xxl },
  emptyTitle: { ...font.cardTitle, color: colors.text, textAlign: "center" },
  emptyText: { ...font.body, color: colors.textSub, textAlign: "center" },
  nickRetry: { gap: spacing.sm, alignItems: "flex-start" },
  hint: { ...font.caption, color: colors.textMuted },
  error: { ...font.caption, color: colors.danger },
});
