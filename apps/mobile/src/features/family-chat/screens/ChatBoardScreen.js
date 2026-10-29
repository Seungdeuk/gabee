import { useLocalSearchParams, useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { ActivityIndicator, FlatList, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import Button from "@/shared/components/Button";
import IconButton from "@/shared/components/IconButton";
import { colors, font, spacing } from "@/theme";

import BoardDetail from "../components/BoardDetail";
import BoardRow from "../components/BoardRow";
import ChipRow from "../components/ChipRow";
import { BOARD_FILTERS, boardEmptyText, filterBoard, originalRoute } from "../boardUtils";
import { memberName } from "../listUtils";
import { drawerTitle } from "../mediaUtils";
import useChatBoard from "../useChatBoard";
import { useRoomInfo } from "../useChatMessages";

const MAX_WIDTH = 600; // 웹처럼 넓은 화면에서 카드가 지나치게 넓어지지 않게 한다

/**
 * 게시판: 공지로 올린 메시지를 지난 공지까지 최신순으로 모아 본다. 경로 인자 roomId(없으면 가족 전체방)와 peer(1:1 상대 id).
 * 카드를 누르면 전체 본문 상세가 열리고, 거기서 "채팅에서 보기"(원본 위치로 이동)와 "삭제"(구성원 누구나)를 할 수 있다.
 * 채팅방 위의 공지 바(최신 2개, 나만 숨기기)는 그대로이고 이 화면은 그 기록 전체를 보여 준다.
 */
export default function ChatBoardScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const roomId = typeof params.roomId === "string" && params.roomId ? params.roomId : null;
  const peerId = typeof params.peer === "string" ? params.peer : null;
  const { width: windowWidth } = useWindowDimensions();
  const width = Math.min(windowWidth, MAX_WIDTH);
  const board = useChatBoard({ roomId });
  const info = useRoomInfo();
  const [filter, setFilter] = useState("all");
  const [open, setOpen] = useState(null); // 상세로 연 글
  const [busyId, setBusyId] = useState(null); // 삭제 중인 글 id(상세 창이 아니라 글에 묶는다)
  const [failure, setFailure] = useState(null); // { id, text }: 삭제에 실패한 글과 사유
  const [listNotice, setListNotice] = useState(""); // 삭제 결과 한 줄(목록 위)

  const nameOf = useMemo(() => {
    const byId = Object.fromEntries((info.room?.members ?? []).map((m) => [m.id, memberName(m)]));
    return (id) => byId[id];
  }, [info.room]);

  const title = info.room ? drawerTitle({ direct: roomId != null, room: info.room, peerId }) : "";
  const shown = useMemo(() => filterBoard(board.items, filter), [board.items, filter]);

  const back = () => (router.canGoBack() ? router.back() : router.replace("/family-chat"));

  const close = () => setOpen(null);

  const openPost = (item) => {
    setListNotice("");
    setOpen(item);
  };

  /** 원본 메시지 위치의 채팅방으로 간다(검색 결과로 이동할 때와 같은 방식). */
  const openOriginal = (item) => {
    close();
    router.replace(originalRoute({ roomId, peerId, messageId: item.message_id }));
  };

  /** 글을 삭제한다. 성공하면 그 글의 상세를 닫고 결과를 목록 위에 보이고, 실패하면 그 글의 상세에 사유를 보여 준다. 그 사이 다른 글을 열었다면 그 창은 건드리지 않는다. */
  const remove = async (item) => {
    if (busyId) return;
    setBusyId(item.id);
    setFailure(null);
    const outcome = await board.remove(item.id);
    setBusyId(null);
    if (!outcome) return;
    if (outcome.effect === "remove") {
      setListNotice(outcome.notice);
      setOpen((cur) => (cur?.id === item.id ? null : cur));
    } else setFailure({ id: item.id, text: outcome.notice });
  };

  const footer = board.hasMore ? (
    <View style={styles.more}>
      {filter === "current" && shown.length === 0 ? <Text style={styles.emptyText}>받아 둔 목록에는 없어요. 더 보기를 눌러 이어서 찾아 보세요</Text> : null}
      {board.loadingMore ? <ActivityIndicator color={colors.accent} accessibilityLabel="불러오는 중" /> : <Button label="더 보기" variant="secondary" small onPress={board.loadMore} />}
      {board.error ? <Text style={styles.error}>{board.error}</Text> : null}
    </View>
  ) : null;

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.bar}>
        <IconButton name="chevron-back" label="뒤로" onPress={back} />
        <View style={styles.titleBox}>
          <Text style={styles.title} numberOfLines={1} accessibilityRole="header">
            게시판
          </Text>
          {title ? (
            <Text style={styles.subtitle} numberOfLines={1}>
              {title}
            </Text>
          ) : null}
        </View>
      </View>
      <View style={[styles.body, { width }]}>
        <View style={styles.chips}>
          <ChipRow label="보기" options={BOARD_FILTERS} value={filter} onChange={setFilter} />
        </View>
        {listNotice ? (
          <Text style={styles.listNotice} accessibilityLiveRegion="polite">
            {listNotice}
          </Text>
        ) : null}
        {board.status === "loading" ? (
          <View style={styles.center}>
            <ActivityIndicator color={colors.accent} accessibilityLabel="불러오는 중" />
          </View>
        ) : board.status === "error" ? (
          <View style={styles.center}>
            <Text style={styles.emptyText}>{board.error}</Text>
            <Button label="다시 시도" onPress={board.retry} />
          </View>
        ) : (
          <FlatList
            data={shown}
            keyExtractor={(it) => it.id}
            renderItem={({ item }) => <BoardRow item={item} nameOf={nameOf} onPress={openPost} />}
            ItemSeparatorComponent={() => <View style={styles.gap} />}
            contentContainerStyle={styles.list}
            ListEmptyComponent={board.hasMore ? null : <Text style={[styles.emptyText, styles.empty]}>{boardEmptyText(filter)}</Text>}
            ListFooterComponent={footer}
          />
        )}
      </View>
      <BoardDetail item={open} nameOf={nameOf} busy={busyId != null && busyId === open?.id} notice={failure && failure.id === open?.id ? failure.text : ""} onClose={close} onOpenOriginal={openOriginal} onDelete={remove} />
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
  chips: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  listNotice: { ...font.caption, color: colors.textSub, paddingHorizontal: spacing.lg, paddingBottom: spacing.sm },
  list: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xxl },
  gap: { height: spacing.sm },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md, padding: spacing.xl },
  emptyText: { ...font.body, color: colors.textMuted, textAlign: "center" },
  empty: { paddingTop: spacing.xxl },
  more: { alignItems: "center", gap: spacing.xs, paddingVertical: spacing.lg },
  error: { ...font.caption, color: colors.danger },
});
