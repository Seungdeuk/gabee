import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import AlbumViewer from "@/features/family-chat/components/AlbumViewer";
import Button from "@/shared/components/Button";
import AuthImage from "@/shared/components/AuthImage";
import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import {
  MEMORIES_EMPTY,
  MEMORIES_EMPTY_HINT,
  MEMORIES_HINT,
  MEMORIES_TITLE,
  MEMORIES_UNAVAILABLE_HINT,
  bodyKind,
  candidateSubtitle,
  candidateTitle,
  photoCaption,
  selectedCandidate,
  viewerPhotos,
} from "../memories";
import { memoryUiMode } from "@/shared/memoryFlag";
import useFamilyMemories from "../useFamilyMemories";

const MAX_WIDTH = 600; // 웹처럼 넓은 화면에서 카드가 지나치게 커지지 않게 한다
const COLUMNS = 3;

/**
 * 가족 추억 후보(읽기 전용 미리보기). 서버가 묶어 준 **비공개** 후보를 보여 줄 뿐 게시·공유·채팅 전송은 하지 않는다. 제목은 촬영 날짜로만 만든 중립 문구이고
 * 장소·인물·감정을 추론하지 않는다. 미출시(404)는 "추억 없음"이 아니라 "아직 열려 있지 않음"으로 보인다. 사진은 기존 채팅 사진 주소·로그인 이미지 처리를 그대로 쓴다.
 * 개발용 mock 모드(EXPO_PUBLIC_FAMILY_MEMORY_UI=mock)는 합성 데이터로만 화면을 확인한다.
 */
export default function FamilyMemoriesScreen() {
  const router = useRouter();
  const { width: windowWidth } = useWindowDimensions();
  const width = Math.min(windowWidth, MAX_WIDTH);
  const { state, refresh, photoGone } = useFamilyMemories();
  const [selectedId, setSelectedId] = useState(null);
  const [viewer, setViewer] = useState(null); // { index }
  const kind = bodyKind(state);
  const selected = useMemo(() => selectedCandidate(state.items, selectedId), [state.items, selectedId]);
  const refreshing = state.status === "loading" && state.items.length > 0;
  const mock = memoryUiMode() === "mock";

  // 가족·사용자가 바뀌어 후보가 비워지거나 새로 고침으로 후보가 사라지면 상세와 뷰어를 닫는다(사라진 후보의 사진이 남지 않게)
  useEffect(() => {
    if (selectedId != null && !selected) {
      setSelectedId(null);
      setViewer(null);
    }
  }, [selected, selectedId]);

  // 화면을 떠나거나 가족이 바뀌면 메모리에 올라온 이미지를 비운다(디스크 캐시는 기존 채팅 사진과 같은 정책을 따른다)
  useEffect(
    () => () => {
      try {
        Image.clearMemoryCache();
      } catch {
        // 네이티브 모듈이 없는 환경(시험·웹)에서는 건너뛴다
      }
    },
    [state.scope],
  );

  const back = () => {
    if (viewer) setViewer(null);
    else if (selectedId != null) setSelectedId(null);
    else if (router.canGoBack()) router.back();
    else router.replace("/family-chat");
  };

  let body;
  if (kind === "loading") {
    body = (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} accessibilityLabel="불러오는 중" />
      </View>
    );
  } else if (kind === "unavailable") {
    body = (
      <View style={styles.center}>
        <Text style={styles.emptyText}>{state.error.message}</Text>
        <Text style={styles.hintText}>{MEMORIES_UNAVAILABLE_HINT}</Text>
      </View>
    );
  } else if (kind === "error") {
    body = (
      <View style={styles.center}>
        <Text style={styles.emptyText}>{state.error.message}</Text>
        {state.error.retryable ? <Button label="다시 시도" onPress={refresh} /> : null}
      </View>
    );
  } else if (kind === "empty") {
    body = (
      <View style={styles.center}>
        <Text style={styles.emptyText}>{MEMORIES_EMPTY}</Text>
        <Text style={styles.hintText}>{MEMORIES_EMPTY_HINT}</Text>
        <Button label="새로 고침" variant="secondary" onPress={refresh} />
      </View>
    );
  } else if (selected) {
    const cell = Math.floor((width - spacing.lg * 2 - 2 * (COLUMNS - 1)) / COLUMNS);
    body = (
      <ScrollView contentContainerStyle={styles.detail} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} />}>
        <Text style={styles.detailTitle}>{candidateTitle(selected)}</Text>
        <Text style={styles.detailSub}>{candidateSubtitle(selected)}</Text>
        <View style={styles.grid}>
          {selected.photos.map((photo, index) => (
            <Pressable
              key={photo.attachment_id}
              onPress={() => setViewer({ index })}
              accessibilityRole="imagebutton"
              accessibilityLabel={`사진 ${selected.photo_count}장 중 ${index + 1}번째${photo.is_representative ? ", 대표 사진" : ""}, 누르면 크게 봐요`}
              style={{ width: cell, height: cell }}
            >
              <AuthImage path={photo.thumb_url} style={{ width: cell, height: cell, borderRadius: radius.sm }} onError={() => photoGone(selected.id, photo.attachment_id)} />
              {photo.is_representative ? (
                <View style={styles.repBadge}>
                  <Text style={styles.repText}>대표</Text>
                </View>
              ) : null}
            </Pressable>
          ))}
        </View>
      </ScrollView>
    );
  } else {
    body = (
      <FlatList
        data={state.items}
        keyExtractor={(c) => c.id}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} />}
        ListHeaderComponent={<Text style={styles.hint}>{MEMORIES_HINT}</Text>}
        renderItem={({ item: c }) => (
          <Pressable
            style={styles.card}
            onPress={() => setSelectedId(c.id)}
            accessibilityRole="button"
            accessibilityLabel={`${candidateTitle(c)}, ${candidateSubtitle(c)}, 누르면 사진을 모아 봐요`}
          >
            <AuthImage path={c.representative.thumb_url} style={[styles.cover, { height: Math.round((width - spacing.lg * 2) * 0.62) }]} onError={() => photoGone(c.id, c.representative.attachment_id)} />
            <View style={styles.cardText}>
              <Text style={styles.cardTitle} numberOfLines={1}>
                {candidateTitle(c)}
              </Text>
              <Text style={styles.cardSub} numberOfLines={2}>
                {candidateSubtitle(c)}
              </Text>
            </View>
          </Pressable>
        )}
        ListFooterComponent={mock ? <Text style={styles.mockNote}>개발용 합성 데이터예요(실제 가족 사진이 아니에요)</Text> : null}
      />
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.bar}>
        <IconButton name="chevron-back" label="뒤로" onPress={back} />
        <Text style={styles.title} numberOfLines={1} accessibilityRole="header">
          {MEMORIES_TITLE}
        </Text>
      </View>
      <View style={[styles.body, { width }]}>{body}</View>
      <AlbumViewer
        visible={viewer != null && selected != null}
        photos={selected ? viewerPhotos(selected) : []}
        startIndex={viewer?.index ?? 0}
        onClose={() => setViewer(null)}
        captionFor={(photo) => photoCaption(photo.item)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background, alignItems: "center" },
  bar: { flexDirection: "row", alignItems: "center", alignSelf: "stretch", paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, borderBottomWidth: 1, borderBottomColor: colors.divider },
  title: { ...font.cardTitle, color: colors.text, flex: 1, minWidth: 0 },
  body: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md, padding: spacing.xxl },
  emptyText: { ...font.body, color: colors.textSub, textAlign: "center" },
  hintText: { ...font.caption, color: colors.textMuted, textAlign: "center" },
  hint: { ...font.caption, color: colors.textMuted, paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  card: { marginHorizontal: spacing.lg, marginBottom: spacing.md, borderRadius: radius.md, backgroundColor: colors.card, overflow: "hidden", borderWidth: 1, borderColor: colors.border },
  cover: { width: "100%" },
  cardText: { padding: spacing.md, gap: spacing.xs },
  cardTitle: { ...font.cardTitle, color: colors.text },
  cardSub: { ...font.caption, color: colors.textSub },
  detail: { padding: spacing.lg, gap: spacing.sm },
  detailTitle: { ...font.section, color: colors.text },
  detailSub: { ...font.caption, color: colors.textSub, marginBottom: spacing.sm },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 2 },
  repBadge: { position: "absolute", left: spacing.xs, top: spacing.xs, paddingHorizontal: spacing.xs, borderRadius: radius.sm, backgroundColor: "rgba(0,0,0,0.55)" },
  repText: { ...font.caption, color: colors.onDark },
  mockNote: { ...font.caption, color: colors.textMuted, textAlign: "center", padding: spacing.lg },
});
