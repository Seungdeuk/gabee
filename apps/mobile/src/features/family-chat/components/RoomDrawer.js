import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Animated, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import IconButton from "@/shared/components/IconButton";
import { colors, font, spacing } from "@/theme";

import { buildDrawerSections, canNavigateFromDrawer, drawerMembers, drawerTitle, resolveRowAction } from "../mediaUtils";
import DrawerRow from "./DrawerRow";
import MemberStrip from "./MemberStrip";

const MAX_WIDTH = 360;
const DURATION = 180;
const NOTICE_MS = 2500;
const SCRIM_OPACITY = 0.4;
const NATIVE = Platform.OS !== "web";

/**
 * 채팅방 서랍(오른쪽에서 열린다). 방 이름, 구성원 줄, "채팅 관리"·"채팅방 설정" 행들.
 * 동작하는 행: 사진 · 동영상(모음 화면), 구성원 초대 · 관리(가족 전체방만, /family), 대화 내용 검색(onOpenSearch 가 있을 때), 고정 메시지(onOpenPins 가 있을 때: 서랍을 닫고 채팅방 위 고정 바를 펼친다), 가족 일정 · 할 일(onOpenLinks 가 있을 때: 서랍을 닫고 연결 목록 시트를 연다). 나머지는 "준비 중" 안내만 한다.
 * 덮개를 누르거나 X, 안드로이드 뒤로가기로 닫는다.
 * @param {{ visible: boolean, onClose: () => void, room?: { name?: string, members?: object[] } | null, roomId?: string | null, peerId?: string | null, myId?: string | null, onOpenSearch?: () => void, onOpenPins?: () => void, onOpenLinks?: () => void, onClosed?: () => void }} props roomId 가 없으면 가족 전체방, 있으면 1:1
 */
export default function RoomDrawer({ visible, onClose, room, roomId, peerId, myId, onOpenSearch, onOpenPins, onOpenLinks, onClosed }) {
  const router = useRouter();
  const { width: windowWidth } = useWindowDimensions();
  const width = Math.min(MAX_WIDTH, Math.round(windowWidth * 0.85));
  const slide = useRef(new Animated.Value(0)).current; // 0 닫힘, 1 열림
  const [mounted, setMounted] = useState(visible);
  const [notice, setNotice] = useState("");
  const locked = useRef(false); // 이동 행을 한 번 누르면 닫히는 동안 다시 눌러도 이동하지 않는다
  const direct = roomId != null;
  const closedRef = useRef(onClosed); // 닫힘 애니메이션이 끝날 때 최신 콜백을 부른다(효과가 낡은 값을 쥐지 않게)
  closedRef.current = onClosed;

  useEffect(() => {
    if (visible) {
      locked.current = false;
      setMounted(true);
      Animated.timing(slide, { toValue: 1, duration: DURATION, useNativeDriver: NATIVE }).start();
      return undefined;
    }
    setNotice("");
    Animated.timing(slide, { toValue: 0, duration: DURATION, useNativeDriver: NATIVE }).start(({ finished }) => {
      if (finished) {
        setMounted(false);
        closedRef.current?.();
      }
    });
    return undefined;
  }, [visible, slide]);

  useEffect(() => {
    if (!notice) return undefined;
    const timer = setTimeout(() => setNotice(""), NOTICE_MS);
    return () => clearTimeout(timer);
  }, [notice]);

  const title = drawerTitle({ direct, room, peerId });
  const strip = drawerMembers({ direct, room, peerId, myId });
  const sections = buildDrawerSections({ direct, searchReady: typeof onOpenSearch === "function", pinsReady: typeof onOpenPins === "function", linksReady: typeof onOpenLinks === "function" });

  /**
   * 행을 눌렀을 때: 이동 행은 한 번만(닫히는 중이면 무시), 나머지는 안내 문구.
   * @param {{ key: string, state: "open" | "soon", notice?: string }} row
   */
  const press = (row) => {
    if (!visible) return;
    const action = resolveRowAction(row);
    if (action.type === "notice") {
      setNotice(action.text);
      return;
    }
    if (!canNavigateFromDrawer({ visible, locked: locked.current })) return;
    locked.current = true;
    onClose();
    if (action.type === "media") router.push({ pathname: "/chat-media", params: { ...(roomId ? { roomId } : {}), ...(peerId ? { peer: peerId } : {}) } });
    else if (action.type === "invite") router.push("/family");
    else if (action.type === "pins") onOpenPins();
    else if (action.type === "links") onOpenLinks();
    else onOpenSearch();
  };

  return (
    <Modal visible={mounted} transparent animationType="none" onRequestClose={onClose} statusBarTranslucent>
      <View style={styles.root}>
        <Animated.View style={[styles.scrim, { opacity: slide.interpolate({ inputRange: [0, 1], outputRange: [0, SCRIM_OPACITY] }) }]}>
          <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityRole="button" accessibilityLabel="채팅방 메뉴 닫기" />
        </Animated.View>
        <Animated.View style={[styles.panel, { width, transform: [{ translateX: slide.interpolate({ inputRange: [0, 1], outputRange: [width, 0] }) }] }]}>
          <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
            <View style={styles.head}>
              <Text style={styles.title} numberOfLines={1} accessibilityRole="header">
                {title}
              </Text>
              <IconButton name="close" label="채팅방 메뉴 닫기" onPress={onClose} />
            </View>
            <ScrollView contentContainerStyle={styles.content}>
              <MemberStrip heading={strip.heading} members={strip.members} />
              {sections.map((section) => (
                <View key={section.title}>
                  <Text style={styles.section} accessibilityRole="header">
                    {section.title}
                  </Text>
                  {section.rows.map((row) => (
                    <DrawerRow key={row.key} row={row} onPress={() => press(row)} />
                  ))}
                </View>
              ))}
            </ScrollView>
            {notice ? (
              <View style={styles.notice} accessibilityLiveRegion="polite">
                <Text style={styles.noticeText}>{notice}</Text>
              </View>
            ) : null}
          </SafeAreaView>
        </Animated.View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, flexDirection: "row", justifyContent: "flex-end" },
  scrim: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.dark },
  panel: { height: "100%", backgroundColor: colors.background },
  safe: { flex: 1 },
  head: { flexDirection: "row", alignItems: "center", paddingLeft: spacing.lg, paddingRight: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.divider },
  title: { flex: 1, ...font.cardTitle, color: colors.text, paddingVertical: spacing.md },
  content: { paddingBottom: spacing.xxl },
  section: { ...font.caption, color: colors.textMuted, paddingHorizontal: spacing.lg, paddingTop: spacing.lg, paddingBottom: spacing.xs },
  notice: { alignItems: "center", paddingVertical: spacing.sm, backgroundColor: colors.honeySoft },
  noticeText: { ...font.caption, color: colors.textSub },
});
