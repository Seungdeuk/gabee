import { useEffect, useRef, useState } from "react";
import { FlatList, Modal, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import AuthImage from "@/shared/components/AuthImage";
import IconButton from "@/shared/components/IconButton";
import { colors, font, spacing } from "@/theme";

/**
 * 앨범 전체 화면 보기. 좌우로 넘기며 묶음의 사진을 모두 본다(맨 위에 "2 / 5"). 닫기 버튼(또는 뒤로 가기)으로 닫는다.
 * onSaveToDevice 가 있으면 아래 "사진첩에 저장"이 지금 보고 있는 사진을 저장한다(저장 중·결과 문구는 saving·notice).
 * @param {{ photos: { id: string, url: string }[], startIndex?: number, visible: boolean, onClose: () => void, onSaveToDevice?: (photo: { id: string, url: string }) => void, saving?: boolean, notice?: string }} props photos 의 url 은 서버가 준 attachment.url
 */
export default function AlbumViewer({ photos, startIndex = 0, visible, onClose, onSaveToDevice, saving = false, notice = "" }) {
  const { width } = useWindowDimensions();
  const [index, setIndex] = useState(startIndex);
  const listRef = useRef(null);
  useEffect(() => {
    if (visible) setIndex(startIndex);
  }, [visible, startIndex]);

  const onScrollEnd = (e) => {
    const next = Math.round(e.nativeEvent.contentOffset.x / Math.max(1, width));
    setIndex(Math.min(photos.length - 1, Math.max(0, next)));
  };
  const current = photos[index];

  return (
    <Modal visible={visible} animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <SafeAreaView style={styles.safe}>
        <View style={styles.bar}>
          <IconButton name="close" label="사진 닫기" onPress={onClose} color={colors.onDark} />
          <Text style={styles.count} accessibilityLiveRegion="polite">{`${index + 1} / ${photos.length}`}</Text>
          <View style={styles.spacer} />
        </View>
        <FlatList
          ref={listRef}
          data={photos}
          horizontal
          pagingEnabled
          showsHorizontalScrollIndicator={false}
          keyExtractor={(p) => p.id}
          initialScrollIndex={Math.min(startIndex, Math.max(0, photos.length - 1))}
          getItemLayout={(_, i) => ({ length: width, offset: width * i, index: i })}
          onMomentumScrollEnd={onScrollEnd}
          renderItem={({ item }) => (
            <View style={{ width }}>
              <AuthImage path={item.url} contentFit="contain" style={styles.image} accessibilityLabel="사진" />
            </View>
          )}
        />
        {onSaveToDevice && current ? (
          <View style={styles.footer}>
            <Text
              onPress={saving ? undefined : () => onSaveToDevice(current)}
              accessibilityRole="button"
              accessibilityState={{ disabled: saving }}
              style={[styles.save, saving && styles.saving]}
            >
              {saving ? "저장하는 중…" : "사진첩에 저장"}
            </Text>
            {notice ? (
              <Text style={styles.notice} accessibilityLiveRegion="polite">
                {notice}
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
  image: { flex: 1, width: "100%" },
  footer: { alignItems: "center", gap: spacing.xs, paddingVertical: spacing.md },
  save: { ...font.body, color: colors.onDark, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  saving: { opacity: 0.6 },
  notice: { ...font.caption, color: colors.onDark },
});
