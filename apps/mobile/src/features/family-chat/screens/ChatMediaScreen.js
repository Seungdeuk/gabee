import { useLocalSearchParams, useRouter } from "expo-router";
import { useMemo, useRef, useState } from "react";
import { Platform, Pressable, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import MediaGrid from "../components/MediaGrid";
import MediaViewer from "../components/MediaViewer";
import { drawerTitle, mediaCaption, mediaTabs, saveFileName } from "../mediaUtils";
import { memberName } from "../listUtils";
import { savePhoto } from "../savePhoto";
import useChatMedia from "../useChatMedia";
import { useRoomInfo } from "../useChatMessages";

const MAX_WIDTH = 600; // 웹처럼 넓은 화면에서 격자가 지나치게 커지지 않게 한다

/**
 * 사진 · 동영상 모음. 경로 인자 roomId(없으면 가족 전체방)와 peer(1:1 상대 id). 방 이름은 주소에 싣지 않고 화면 안에서 계산한다.
 * 탭은 사진 · 파일 · 동영상이고 개수는 서버 counts 다. 파일·동영상은 아직 보낼 수 없어 안내만 보인다.
 * 사진을 누르면 전체 화면으로 보고 저장할 수 있다(웹은 내려받기, 네이티브는 사진 앱에 저장).
 */
export default function ChatMediaScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const roomId = typeof params.roomId === "string" && params.roomId ? params.roomId : null;
  const peerId = typeof params.peer === "string" ? params.peer : null;
  const { width: windowWidth } = useWindowDimensions();
  const width = Math.min(windowWidth, MAX_WIDTH);
  const [kind, setKind] = useState("image");
  const media = useChatMedia({ roomId, kind });
  const info = useRoomInfo();
  const [viewing, setViewing] = useState(null);
  const [saveState, setSaveState] = useState({ id: null, saving: false, notice: "" }); // 저장은 사진(id)별로 기억한다

  const savingIds = useRef(new Set()); // 저장 중인 모든 사진 id: 다른 사진을 보다 돌아와도 같은 사진을 동시에 두 번 저장하지 않는다

  const nameOf = useMemo(() => {
    const byId = Object.fromEntries((info.room?.members ?? []).map((m) => [m.id, memberName(m)]));
    return (id) => byId[id];
  }, [info.room]);

  const title = info.room ? drawerTitle({ direct: roomId != null, room: info.room, peerId }) : "";

  const back = () => (router.canGoBack() ? router.back() : router.replace("/family-chat"));

  /**
   * 사진을 전체 화면으로 연다.
   * @param {object} item 모음 항목
   */
  const open = (item) => setViewing(item);

  /** 보고 있는 사진을 저장한다. 결과는 저장을 시작한 사진에만 붙고, 그 사이 다른 사진으로 넘어갔다면 새 사진에는 보이지 않는다. */
  const save = async () => {
    if (!viewing || savingIds.current.has(viewing.attachment_id)) return;
    const id = viewing.attachment_id;
    savingIds.current.add(id);
    setSaveState({ id, saving: true, notice: "" });
    let result;
    try {
      result = await savePhoto(viewing, saveFileName(viewing), Platform.OS);
    } finally {
      savingIds.current.delete(id);
    }
    setSaveState((prev) => (prev.id === id ? { id, saving: false, notice: result.message } : prev));
  };
  const current = saveState.id === viewing?.attachment_id ? saveState : { saving: false, notice: "" };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.bar}>
        <IconButton name="chevron-back" label="뒤로" onPress={back} />
        <View style={styles.titleBox}>
          <Text style={styles.title} numberOfLines={1} accessibilityRole="header">
            사진 · 동영상
          </Text>
          {title ? (
            <Text style={styles.subtitle} numberOfLines={1}>
              {title}
            </Text>
          ) : null}
        </View>
      </View>
      <View style={[styles.body, { width }]}>
        <View style={styles.tabs} accessibilityRole="tablist">
          {mediaTabs(media.counts).map((tab) => (
            <Pressable
              key={tab.kind}
              onPress={() => setKind(tab.kind)}
              accessibilityRole="tab"
              accessibilityState={{ selected: tab.kind === kind }}
              style={[styles.tab, tab.kind === kind && styles.tabOn]}
            >
              <Text style={[styles.tabText, tab.kind === kind && styles.tabTextOn]}>{tab.label}</Text>
            </Pressable>
          ))}
        </View>
        <MediaGrid
          kind={kind}
          items={media.items}
          status={media.status}
          error={media.error}
          loadingMore={media.loadingMore}
          hasMore={media.hasMore}
          width={width}
          onEndReached={media.loadMore}
          onRetry={media.retry}
          onOpen={open}
        />
      </View>
      <MediaViewer
        item={viewing}
        caption={viewing ? mediaCaption(viewing, nameOf) : ""}
        visible={viewing != null}
        onClose={() => setViewing(null)}
        onSave={save}
        saving={current.saving}
        notice={current.notice}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background, alignItems: "center" },
  bar: { flexDirection: "row", alignItems: "center", alignSelf: "stretch", paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, borderBottomWidth: 1, borderBottomColor: colors.divider },
  titleBox: { flex: 1, minWidth: 0 },
  title: { ...font.cardTitle, color: colors.text },
  subtitle: { ...font.caption, color: colors.textMuted },
  body: { flex: 1 },
  tabs: { flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  tab: { minHeight: 36, justifyContent: "center", paddingHorizontal: spacing.md, borderRadius: radius.pill, backgroundColor: colors.surface },
  tabOn: { backgroundColor: colors.surfaceStrong },
  tabText: { ...font.caption, color: colors.textSub },
  tabTextOn: { fontFamily: font.bodyStrong.fontFamily, color: colors.text },
});
