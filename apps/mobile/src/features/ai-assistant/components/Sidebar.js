import { Ionicons } from "@expo/vector-icons";
import { useEffect, useRef, useState } from "react";
import { Animated, Modal, Pressable, StyleSheet, Text, useWindowDimensions, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors } from "@/theme";

import RecordsList from "./RecordsList";
import SessionList from "./SessionList";

const TABS = [
  { key: "chats", label: "대화" },
  { key: "records", label: "기록" },
];

/**
 * 왼쪽에서 열리는 작은 패널. 위에서 "대화"(이전 대화 목록)와 "기록"(올린 사진·파일)을 바꿔 본다.
 * reviewCount: 확인이 필요한 기록 수("기록" 탭에 숫자로 표시) / focusRecordId: 열자마자 상세를 띄울 기록(채팅의 "지금 확인하기")
 * @param {{ open: boolean, onClose: () => void, sessions: object[], currentId: string | null, onNew: () => void, onOpenSession: (id: string) => void, onDeleteSession: (id: string) => void, reviewCount?: number, focusRecordId?: string | null, onFocusHandled?: () => void, onRecordsLoaded?: (items: object[]) => void }} props
 */
export default function Sidebar({
  open,
  onClose,
  sessions,
  currentId,
  onNew,
  onOpenSession,
  onDeleteSession,
  reviewCount = 0,
  focusRecordId = null,
  onFocusHandled,
  onRecordsLoaded,
}) {
  const { width } = useWindowDimensions();
  const panelWidth = Math.min(320, Math.round(width * 0.78));
  const slide = useRef(new Animated.Value(-panelWidth)).current;
  const [shown, setShown] = useState(false); // 닫는 애니메이션이 끝날 때까지 화면에 둔다
  const [tab, setTab] = useState("chats");

  useEffect(() => {
    if (open && focusRecordId) setTab("records");
  }, [open, focusRecordId]);

  useEffect(() => {
    if (open) {
      setShown(true);
      Animated.timing(slide, { toValue: 0, duration: 200, useNativeDriver: true }).start();
    } else if (shown) {
      Animated.timing(slide, { toValue: -panelWidth, duration: 160, useNativeDriver: true }).start(() => setShown(false));
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Modal visible={shown} transparent animationType="none" onRequestClose={onClose}>
      <View style={styles.root}>
        <Animated.View style={[styles.panel, { width: panelWidth, transform: [{ translateX: slide }] }]}>
          <SafeAreaView style={styles.flex} edges={["top", "bottom"]}>
            <View style={styles.top}>
              <Text style={styles.title}>가비</Text>
              <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="닫기" style={styles.close}>
                <Ionicons name="close" size={22} color={colors.text} />
              </Pressable>
            </View>

            <View style={styles.tabs}>
              {TABS.map((t) => (
                <Pressable
                  key={t.key}
                  onPress={() => setTab(t.key)}
                  accessibilityRole="tab"
                  accessibilityState={{ selected: tab === t.key }}
                  style={[styles.tab, tab === t.key && styles.tabOn]}
                >
                  <Text style={[styles.tabText, tab === t.key && styles.tabTextOn]}>{t.label}</Text>
                  {t.key === "records" && reviewCount > 0 ? (
                    <View style={styles.count}>
                      <Text style={styles.countText}>{reviewCount}</Text>
                    </View>
                  ) : null}
                </Pressable>
              ))}
            </View>

            <View style={styles.flex}>
              {tab === "chats" ? (
                <SessionList
                  sessions={sessions}
                  currentId={currentId}
                  onNew={() => {
                    onNew();
                    onClose();
                  }}
                  onOpen={(id) => {
                    onOpenSession(id);
                    onClose();
                  }}
                  onDelete={onDeleteSession}
                />
              ) : (
                <RecordsList active={open && tab === "records"} focusId={focusRecordId} onFocusHandled={onFocusHandled} onLoaded={onRecordsLoaded} />
              )}
            </View>
          </SafeAreaView>
        </Animated.View>
        <Pressable style={styles.backdrop} onPress={onClose} accessibilityLabel="메뉴 닫기" />
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, flexDirection: "row" },
  flex: { flex: 1 },
  panel: { backgroundColor: colors.background, borderRightWidth: 1, borderRightColor: colors.border },
  backdrop: { flex: 1, backgroundColor: "rgba(60,40,20,0.35)" },
  top: { height: 52, paddingLeft: 18, paddingRight: 6, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  title: { fontSize: 18, fontWeight: "700", color: colors.text },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  tabs: { flexDirection: "row", gap: 8, paddingHorizontal: 14, paddingBottom: 10 },
  tab: { flex: 1, minHeight: 38, borderRadius: 19, flexDirection: "row", gap: 6, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  count: { minWidth: 20, height: 20, paddingHorizontal: 5, borderRadius: 10, backgroundColor: colors.peach, alignItems: "center", justifyContent: "center" },
  countText: { fontSize: 11, fontWeight: "700", color: colors.text },
  tabOn: { backgroundColor: colors.surfaceStrong },
  tabText: { fontSize: 14, color: colors.textMuted },
  tabTextOn: { fontWeight: "700", color: colors.text },
});
