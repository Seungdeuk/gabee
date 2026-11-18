import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { FlatList, Modal, Pressable, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import AuthImage from "@/shared/components/AuthImage";
import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import { PHOTO_SAVE_LABEL } from "../fileUtils";
import { LIBRARY_BUTTON_LABEL, LIBRARY_DONE_LABEL, LIBRARY_SAVING_LABEL } from "../saveToLibrary";

/**
 * 앨범 전체 화면 보기. 좌우로 넘기며 묶음의 사진을 모두 본다(맨 위에 "2 / 5"). 닫기 버튼(또는 뒤로 가기)으로 닫는다.
 * 아래 버튼은 지금 보고 있는 사진 한 장에 적용된다: "사진첩에 저장"(onSaveToDevice), "문서로 저장"(onSaveToLibrary, 저장 중·저장함·결과 문구는 libraryOf 가 사진 id 별로 알려 준다), 맨 위 오른쪽 "메뉴"(onMenu: 답장·삭제 같은 메시지 메뉴, 뷰어를 닫고 연다).
 * 타임라인용 선택 옵션(주지 않으면 채팅 앨범 동작 그대로): captionFor 는 지금 사진 아래 한 줄(날짜), actionsFor 는 지금 사진에 적용할 버튼들(key·label·icon(Ionicons 이름)·onPress·disabled)을 돌려주고 저장 버튼 위에 한 줄로 놓이며, actionNoticeFor 는 지금 사진의 그 버튼들의 결과·오류 문구다(옆 사진으로 넘기면 그 사진의 문구가 보인다).
 * actionsFor 를 주면 사진 수가 줄 때(사진을 뺐을 때) 목록을 새로 그려 startIndex 가 가리키는 사진에서 다시 시작한다.
 * @param {{ photos: { id: string, url: string, inLibrary?: boolean }[], startIndex?: number, visible: boolean, onClose: () => void, onSaveToDevice?: (photo: { id: string, url: string }, index: number) => void, saving?: boolean, notice?: string, onSaveToLibrary?: (photo: { id: string, url: string }, index: number) => void, libraryOf?: (photoId: string) => { saving: boolean, done: boolean, notice: string }, onMenu?: (index: number) => void, captionFor?: (photo: object, index: number) => string, actionsFor?: (photo: object, index: number) => { key: string, label: string, icon: string, onPress: () => void, disabled?: boolean }[], actionNoticeFor?: (photo: object, index: number) => string }} props photos 의 url 은 서버가 준 attachment.url
 */
export default function AlbumViewer({ photos, startIndex = 0, visible, onClose, onSaveToDevice, saving = false, notice = "", onSaveToLibrary, libraryOf, onMenu, captionFor, actionsFor, actionNoticeFor }) {
  const { width } = useWindowDimensions();
  // 사진 칸의 높이는 목록이 잰 높이로 정한다: 칸에 높이가 없으면 웹에서 사진 영역이 0 으로 접혀 사진이 보이지 않는다
  const [listHeight, setListHeight] = useState(0);
  const [page, setPage] = useState({ start: startIndex, index: startIndex });
  // 열 때마다(startIndex 가 바뀔 때) 그 사진부터 시작한다. 효과 대신 렌더 중에 맞춰 첫 프레임에 이전 번호가 보이지 않게 한다
  if (page.start !== startIndex) setPage({ start: startIndex, index: startIndex });
  const last = Math.max(0, photos.length - 1);
  const index = Math.min(last, Math.max(0, page.index)); // 보는 동안 사진이 지워져 줄어도 범위를 넘지 않는다
  const current = photos[index];
  const library = current && libraryOf ? libraryOf(current.id) : { saving: false, done: false, notice: "" };
  const caption = current && captionFor ? captionFor(current, index) : "";
  const actions = current && actionsFor ? actionsFor(current, index) : [];
  const actionNotice = current && actionNoticeFor ? actionNoticeFor(current, index) : "";

  // 네이티브는 넘김이 끝날 때(onMomentumScrollEnd), 웹은 스크롤하는 동안(onScroll) 몇 번째 사진인지 갱신한다(웹은 momentum 이벤트가 없다).
  // 번호가 그대로면 다시 그리지 않는다.
  const onScrollEnd = (e) => {
    const next = Math.round(e.nativeEvent.contentOffset.x / Math.max(1, width));
    const index = Math.min(last, Math.max(0, next));
    setPage((prev) => (prev.index === index ? prev : { ...prev, index }));
  };

  return (
    <Modal visible={visible} animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <SafeAreaView style={styles.safe}>
        <View style={styles.bar}>
          <IconButton name="close" label="사진 닫기" onPress={onClose} color={colors.onDark} />
          <Text style={styles.count} accessibilityLiveRegion="polite">{`${index + 1} / ${photos.length}`}</Text>
          {onMenu ? <IconButton name="ellipsis-horizontal" label="이 사진의 메뉴" onPress={() => onMenu(index)} color={colors.onDark} /> : <View style={styles.spacer} />}
        </View>
        <FlatList
          key={actionsFor ? `n${photos.length}` : undefined}
          style={styles.list}
          onLayout={(e) => setListHeight(e.nativeEvent.layout.height)}
          data={photos}
          horizontal
          pagingEnabled
          // 안드로이드는 기본으로 화면 밖 칸을 떼어 내는데, 다시 넘기면 사진이 그려지지 않고 바탕만 보이는 경우가 있다(앨범은 사진 몇 장뿐이라 떼어 낼 필요가 없다)
          removeClippedSubviews={false}
          showsHorizontalScrollIndicator={false}
          keyExtractor={(p) => p.id}
          initialScrollIndex={Math.min(startIndex, last)}
          getItemLayout={(_, i) => ({ length: width, offset: width * i, index: i })}
          onMomentumScrollEnd={onScrollEnd}
          onScroll={onScrollEnd}
          scrollEventThrottle={32}
          renderItem={({ item }) => (
            <View style={{ width, height: listHeight > 0 ? listHeight : undefined }}>
              <AuthImage path={item.url} contentFit="contain" style={styles.image} accessibilityLabel="사진" />
            </View>
          )}
        />
        {current && (onSaveToDevice || onSaveToLibrary || caption || actions.length > 0) ? (
          <View style={styles.footer}>
            {caption ? <Text style={styles.notice}>{caption}</Text> : null}
            {actions.length > 0 ? (
              <View style={styles.buttons}>
                {actions.map((action) => (
                  <Pressable
                    key={action.key}
                    onPress={action.onPress}
                    disabled={action.disabled}
                    accessibilityRole="button"
                    accessibilityLabel={action.label}
                    accessibilityState={{ disabled: !!action.disabled }}
                    style={({ pressed }) => [styles.button, (pressed || action.disabled) && styles.pressed]}
                    testID={`album-viewer-${action.key}`}
                  >
                    <Ionicons name={action.icon} size={18} color={colors.text} />
                    <Text style={styles.buttonText}>{action.label}</Text>
                  </Pressable>
                ))}
              </View>
            ) : null}
            {actionNotice ? (
              <Text style={styles.notice} accessibilityLiveRegion="polite">
                {actionNotice}
              </Text>
            ) : null}
            <View style={styles.buttons}>
              {onSaveToDevice ? (
                <Pressable
                  onPress={() => onSaveToDevice(current, index)}
                  disabled={saving}
                  accessibilityRole="button"
                  accessibilityLabel={PHOTO_SAVE_LABEL}
                  accessibilityState={{ disabled: saving }}
                  style={({ pressed }) => [styles.button, (pressed || saving) && styles.pressed]}
                >
                  <Ionicons name="download-outline" size={18} color={colors.text} />
                  <Text style={styles.buttonText}>{saving ? "저장하는 중…" : PHOTO_SAVE_LABEL}</Text>
                </Pressable>
              ) : null}
              {onSaveToLibrary && !current.inLibrary ? (
                <Pressable
                  onPress={() => onSaveToLibrary(current, index)}
                  disabled={library.saving || library.done}
                  accessibilityRole="button"
                  accessibilityLabel={LIBRARY_BUTTON_LABEL}
                  accessibilityState={{ disabled: library.saving || library.done }}
                  style={({ pressed }) => [styles.button, (pressed || library.saving || library.done) && styles.pressed]}
                >
                  <Ionicons name={library.done ? "checkmark-circle-outline" : "document-text-outline"} size={18} color={colors.text} />
                  <Text style={styles.buttonText}>{library.saving ? LIBRARY_SAVING_LABEL : library.done ? LIBRARY_DONE_LABEL : LIBRARY_BUTTON_LABEL}</Text>
                </Pressable>
              ) : null}
            </View>
            {notice ? (
              <Text style={styles.notice} accessibilityLiveRegion="polite">
                {notice}
              </Text>
            ) : null}
            {library.notice ? (
              <Text style={styles.notice} accessibilityLiveRegion="polite">
                {library.notice}
              </Text>
            ) : null}
          </View>
        ) : null}
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.dark },
  bar: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.sm },
  count: { ...font.body, flex: 1, textAlign: "center", color: colors.onDark },
  spacer: { width: 44 },
  list: { flex: 1 },
  image: { flex: 1, width: "100%" },
  footer: { alignItems: "center", gap: spacing.xs, paddingVertical: spacing.md },
  buttons: { flexDirection: "row", flexWrap: "wrap", justifyContent: "center", gap: spacing.sm },
  button: { flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: 44, paddingHorizontal: spacing.lg, borderRadius: radius.pill, backgroundColor: colors.honeySoft },
  buttonText: { ...font.body, color: colors.text },
  pressed: { opacity: 0.6 },
  notice: { ...font.caption, color: colors.onDark },
});
