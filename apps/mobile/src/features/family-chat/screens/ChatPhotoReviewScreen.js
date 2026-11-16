import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import AuthImage from "@/shared/components/AuthImage";
import Button from "@/shared/components/Button";
import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import { confirmGeneralPhoto, getPhotoLibraryState } from "../api";
import PhotoReviewSheet from "../components/PhotoReviewSheet";
import { REVIEW_EMPTY, REVIEW_TITLE, cellLabel, reviewBodyKind, runConfirm, runDocumentSave } from "../photoChecks";
import { saveToLibrary } from "../saveToLibrary";
import useChatPhotoChecks from "../useChatPhotoChecks";

const MAX_WIDTH = 600; // 웹처럼 넓은 화면에서 격자가 지나치게 커지지 않게 한다
const COLUMNS = 3;
const GAP = 2;
const NOTICE_MS = 3000;

/**
 * 확인이 필요한 사진: 내가 올린 가족 전체방 사진 중 자동 판별이 끝나지 않았거나(처리 지연) 판단하지 못한(확인 필요·판별 실패) 것만 모아 보인다.
 * 사진을 누르면 시트가 열려, 안내를 읽고 확인란을 체크한 뒤에만 "일반 사진이에요"로 확인할 수 있다. 문서·서류가 찍힌 사진은 "문서로 저장"으로 문서함에 넣는다.
 * 자동으로 일반 사진이 되는 일은 없고(서버가 업로더의 명시적 확인만 받는다), 푸시 알림도 없다. 서버가 막는 경우(문서·이미 지운 사진 등)는 문구로 알려 준다.
 */
export default function ChatPhotoReviewScreen() {
  const router = useRouter();
  const { width: windowWidth } = useWindowDimensions();
  const width = Math.min(windowWidth, MAX_WIDTH);
  const list = useChatPhotoChecks();
  const [selected, setSelected] = useState(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [busyById, setBusyById] = useState({}); // 사진 id 별 처리 중: "confirm" | "doc" (한 사진의 처리 끝이 다른 사진의 표시를 풀지 않게 사진별로 둔다)
  const [msgs, setMsgs] = useState({}); // 사진 id 별 시트 안 오류·안내(다른 사진의 결과가 지금 보는 사진의 문구를 지우지 않는다)
  const [notice, setNotice] = useState(""); // 화면 위 결과 안내(시트를 닫은 뒤에도 보인다)
  const [docStates, setDocStates] = useState({}); // 사진 id 별 문서함 저장 진행: "checking" | "not_registered"
  const working = useRef(new Set()); // 처리 중인 사진 id: 상태가 반영되기 전에 두 번 눌러도 한 번만 보낸다
  const mounted = useRef(true);
  const selectedId = selected?.attachment_id ?? null;
  const busy = selectedId ? (busyById[selectedId] ?? null) : null; // 지금 보는 사진의 처리 중 표시

  /** 한 사진의 처리 중 표시를 켜고(kind) 끈다(null). */
  const setBusyFor = (id, kind) =>
    setBusyById((prev) => (kind == null ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== id)) : { ...prev, [id]: kind }));
  /** 한 사진의 시트 문구를 바꾼다(빈 글자면 지운다). */
  const setMsgFor = (id, text) => setMsgs((prev) => ({ ...prev, [id]: text }));

  useEffect(() => {
    mounted.current = true; // 개발 중 Fast Refresh·StrictMode 로 효과가 다시 돌아도 false 로 굳지 않게 한다
    return () => {
      mounted.current = false;
    };
  }, []);

  const kind = reviewBodyKind(list);
  const { loadMore, loadingMore } = list;
  useEffect(() => {
    if (kind === "more" && !loadingMore) loadMore(); // 보이는 사진을 모두 처리했는데 서버에 더 남았으면 이어서 불러온다(실패하면 more_error 로 멈춘다)
  }, [kind, loadingMore, loadMore]);

  useEffect(() => {
    if (!notice) return undefined;
    const timer = setTimeout(() => setNotice(""), NOTICE_MS);
    return () => clearTimeout(timer);
  }, [notice]);

  const back = () => (router.canGoBack() ? router.back() : router.replace("/family-chat"));

  /** 시트를 연다(확인란은 사진마다 처음에는 비어 있다). */
  const open = (item) => {
    setSelected(item);
    setAcknowledged(false);
    setMsgFor(item.attachment_id, "");
  };
  const close = () => {
    if (busy != null || docStates[selectedId] === "checking") return; // 처리 중에는 시트의 다른 닫기(덮개·뒤로가기)와 같이 막는다
    setSelected(null);
  };

  /** 일반 사진으로 확인한다. 안내를 확인하지 않았거나(확인란 미체크) 이미 처리 중이면 아무 일도 하지 않는다(흐름은 photoChecks.runConfirm). */
  const confirm = async () => {
    const id = selectedId;
    if (!id || !acknowledged || busy != null || working.current.has(id)) return;
    setBusyFor(id, "confirm");
    setMsgFor(id, "");
    const out = await runConfirm({ id, acknowledged, busy: null, working: working.current, confirm: confirmGeneralPhoto });
    if (!mounted.current) return;
    setBusyFor(id, null);
    if (out.kind === "confirmed") {
      list.remove(id);
      setSelected((cur) => (cur?.attachment_id === id ? null : cur));
      setNotice(out.message);
    } else if (out.kind === "gone") {
      list.remove(id); // 더 이상 확인할 수 없는 사진(지워짐·문서·내 사진 아님)은 목록에서 뺀다
      setSelected((cur) => (cur?.attachment_id === id ? null : cur));
      setNotice(out.message);
    } else if (out.kind === "failed") {
      setMsgFor(id, out.message); // 일시 오류는 시트를 열어 둔 채 다시 시도할 수 있게 한다
    }
  };

  /** 문서로 저장한 뒤 실제로 문서함에 등록됐는지 다시 확인한다(등록을 확인하기 전에는 성공으로 보이지 않는다. 흐름은 photoChecks.runDocumentSave). */
  const saveDocument = async () => {
    const id = selectedId;
    if (!id || busy != null || working.current.has(id)) return;
    setBusyFor(id, "doc");
    setMsgFor(id, "");
    const out = await runDocumentSave({
      id,
      busy: null,
      working: working.current,
      save: saveToLibrary,
      getState: getPhotoLibraryState,
      shouldStop: () => !mounted.current,
      onQueued: () => {
        if (!mounted.current) return;
        setBusyFor(id, null);
        setDocStates((prev) => ({ ...prev, [id]: "checking" }));
      },
    });
    if (!mounted.current || out.kind === "stopped") return;
    setBusyFor(id, null);
    if (out.kind === "save_failed") {
      setMsgFor(id, out.message);
    } else if (out.kind === "registered") {
      setDocStates((prev) => Object.fromEntries(Object.entries(prev).filter(([key]) => key !== id)));
      list.remove(id);
      setSelected((cur) => (cur?.attachment_id === id ? null : cur));
      setNotice(out.message);
    } else if (out.kind === "not_registered") {
      setDocStates((prev) => ({ ...prev, [id]: "not_registered" }));
      setMsgFor(id, out.message);
    }
  };

  const cell = Math.floor((width - GAP * (COLUMNS - 1)) / COLUMNS);

  let body;
  if (kind === "loading" || kind === "more") {
    body = (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} accessibilityLabel="불러오는 중" />
      </View>
    );
  } else if (kind === "error") {
    body = (
      <View style={styles.center}>
        <Text style={styles.emptyText}>{list.error}</Text>
        <Button label="다시 시도" onPress={list.retry} />
      </View>
    );
  } else if (kind === "more_error") {
    body = (
      <View style={styles.center}>
        <Text style={styles.emptyText}>{list.error}</Text>
        <Button label="다시 시도" onPress={list.loadMore} />
      </View>
    );
  } else if (kind === "empty") {
    body = (
      <View style={styles.center}>
        <Text style={styles.emptyText}>{REVIEW_EMPTY}</Text>
      </View>
    );
  } else {
    body = (
      <FlatList
        data={list.items}
        key={COLUMNS}
        numColumns={COLUMNS}
        keyExtractor={(it) => it.attachment_id}
        columnWrapperStyle={{ gap: GAP }}
        ItemSeparatorComponent={() => <View style={{ height: GAP }} />}
        renderItem={({ item }) => {
          const label = cellLabel(item, docStates[item.attachment_id]);
          return (
            <Pressable onPress={() => open(item)} accessibilityRole="imagebutton" accessibilityLabel={`${label} 사진, 누르면 확인해요`}>
              <AuthImage path={item.thumb_url} style={{ width: cell, height: cell }} />
              <View style={styles.label} pointerEvents="none">
                <Text style={styles.labelText}>{label}</Text>
              </View>
            </Pressable>
          );
        }}
        onEndReached={() => {
          if (list.hasMore && !list.error) list.loadMore();
        }}
        onEndReachedThreshold={0.6}
        ListFooterComponent={
          list.loadingMore ? (
            <ActivityIndicator style={styles.footer} color={colors.accent} accessibilityLabel="더 불러오는 중" />
          ) : list.error ? (
            <View style={styles.footer}>
              <Text style={styles.emptyText}>{list.error}</Text>
              <Button label="다시 시도" onPress={list.loadMore} />
            </View>
          ) : null
        }
      />
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.bar}>
        <IconButton name="chevron-back" label="뒤로" onPress={back} />
        <View style={styles.titleBox}>
          <Text style={styles.title} numberOfLines={1} accessibilityRole="header">
            {REVIEW_TITLE}
          </Text>
          {list.status === "ready" && list.total > 0 ? <Text style={styles.subtitle}>{`${list.total}장`}</Text> : null}
        </View>
      </View>
      <View style={[styles.body, { width }]}>{body}</View>
      {notice ? (
        <View style={styles.notice} accessibilityLiveRegion="polite">
          <Text style={styles.noticeText}>{notice}</Text>
        </View>
      ) : null}
      <PhotoReviewSheet
        item={selected}
        acknowledged={acknowledged}
        busy={busy}
        docState={selected ? (docStates[selected.attachment_id] ?? null) : null}
        message={selectedId ? (msgs[selectedId] ?? "") : ""}
        onToggleAck={() => setAcknowledged((v) => !v)}
        onConfirm={confirm}
        onSaveDocument={saveDocument}
        onClose={close}
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
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md, padding: spacing.xxl },
  emptyText: { ...font.body, color: colors.textSub, textAlign: "center" },
  footer: { alignItems: "center", gap: spacing.sm, padding: spacing.lg },
  label: { position: "absolute", left: spacing.xs, bottom: spacing.xs, paddingHorizontal: spacing.sm, borderRadius: radius.pill, backgroundColor: colors.honeySoft },
  labelText: { ...font.tab, color: colors.text },
  notice: { alignSelf: "stretch", alignItems: "center", paddingVertical: spacing.sm, backgroundColor: colors.honeySoft },
  noticeText: { ...font.caption, color: colors.textSub },
});
