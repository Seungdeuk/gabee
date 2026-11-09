import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { useEffect, useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaView } from "react-native-safe-area-context";

import ZoomableImage from "./ZoomableImage";

/** 쪽 그림 한 장(목록용). 불러온 뒤 실제 가로세로 비율로 맞추고, 못 불러오면 안내를 보인다. */
function Page({ source, label }) {
  const [ratio, setRatio] = useState(0.72); // 불러오기 전에는 A4 정도 비율
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <View style={[styles.page, styles.pageFail]}>
        <Text style={styles.message}>{label} 을(를) 불러오지 못했어요.</Text>
      </View>
    );
  }
  return (
    <Image
      source={source}
      style={[styles.page, { aspectRatio: ratio }]}
      contentFit="contain"
      onLoad={(e) => e?.source?.width && e?.source?.height && setRatio(e.source.width / e.source.height)}
      onError={() => setFailed(true)}
      accessibilityLabel={label}
    />
  );
}

/**
 * 올린 원본·사진을 전체 화면으로 본다. 한 장이면 바로 손가락으로 확대(핀치·드래그·두 번 탭)하며 볼 수 있고,
 * PDF 처럼 여러 쪽이면 쪽마다 한 장씩 위아래로 이어서 보여 주다가 쪽을 누르면 그 쪽을 전체 화면에서 확대해 본다(이전·다음 쪽으로 이동).
 * @param {{ state: null | { title?: string, loading?: boolean, sources?: { uri: string, headers?: Record<string, string> }[], message?: string }, onClose: () => void }} props
 * state 가 null 이면 닫혀 있다. sources 가 비면 message(앱에서 열 수 없는 이유)를 보여 준다.
 */
export default function OriginalViewer({ state, onClose }) {
  const sources = state?.sources ?? [];
  const [focus, setFocus] = useState(null); // 여러 쪽에서 확대해 보고 있는 쪽 번호(목록이면 null)
  useEffect(() => {
    if (state === null) setFocus(null); // 닫으면 다음에 열 때 목록부터
  }, [state]);

  const single = sources.length === 1;
  const zoomIndex = single ? 0 : focus;
  const inPage = !single && focus !== null; // 여러 쪽 중 한 쪽을 확대해 보는 중

  const back = () => (inPage ? setFocus(null) : onClose());
  const move = (step) => setFocus((i) => Math.min(sources.length - 1, Math.max(0, (i ?? 0) + step)));

  return (
    <Modal visible={state !== null} animationType="fade" onRequestClose={back}>
      {/* 안드로이드는 Modal 안에서 제스처를 받으려면 Modal 안쪽에 GestureHandlerRootView 가 있어야 한다 */}
      <GestureHandlerRootView style={styles.root}>
        <SafeAreaView style={styles.safe}>
          <View style={styles.top}>
            {inPage ? (
              <Pressable onPress={() => setFocus(null)} accessibilityRole="button" accessibilityLabel="쪽 목록으로" style={styles.close}>
                <Ionicons name="chevron-back" size={24} color="#fff" />
              </Pressable>
            ) : null}
            <Text style={[styles.title, inPage && styles.titleShifted]} numberOfLines={1}>
              {state?.title ?? "원본"}
              {sources.length > 1 ? (inPage ? ` · ${focus + 1} / ${sources.length}쪽` : ` · ${sources.length}쪽`) : ""}
            </Text>
            <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="원본 닫기" style={styles.close}>
              <Ionicons name="close" size={24} color="#fff" />
            </Pressable>
          </View>
          {state?.loading ? (
            <View style={styles.center}>
              <ActivityIndicator color="#fff" />
            </View>
          ) : sources.length === 0 ? (
            <View style={styles.center}>
              <Text style={styles.message}>{state?.message ?? "원본을 찾지 못했어요."}</Text>
            </View>
          ) : zoomIndex !== null ? (
            <>
              <ZoomableImage key={sources[zoomIndex].uri} source={sources[zoomIndex]} label={single ? "사진" : `${zoomIndex + 1}쪽`} />
              <View style={styles.bottom}>
                {inPage ? (
                  <Pressable onPress={() => move(-1)} disabled={focus === 0} accessibilityRole="button" accessibilityLabel="이전 쪽" style={[styles.step, focus === 0 && styles.stepOff]}>
                    <Ionicons name="chevron-back" size={22} color="#fff" />
                  </Pressable>
                ) : null}
                <Text style={styles.hint}>두 손가락으로 벌려 확대하고, 두 번 누르면 확대·원래 크기로 바뀌어요</Text>
                {inPage ? (
                  <Pressable
                    onPress={() => move(1)}
                    disabled={focus === sources.length - 1}
                    accessibilityRole="button"
                    accessibilityLabel="다음 쪽"
                    style={[styles.step, focus === sources.length - 1 && styles.stepOff]}
                  >
                    <Ionicons name="chevron-forward" size={22} color="#fff" />
                  </Pressable>
                ) : null}
              </View>
            </>
          ) : (
            <ScrollView contentContainerStyle={styles.pages}>
              {sources.map((s, i) => (
                <Pressable key={s.uri} onPress={() => setFocus(i)} accessibilityRole="button" accessibilityLabel={`${i + 1}쪽 크게 보기`}>
                  <Page source={s} label={`${i + 1}쪽`} />
                </Pressable>
              ))}
            </ScrollView>
          )}
        </SafeAreaView>
      </GestureHandlerRootView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  safe: { flex: 1, backgroundColor: "#111" },
  top: { height: 52, flexDirection: "row", alignItems: "center", paddingLeft: 16, paddingRight: 6 },
  title: { flex: 1, fontSize: 15, fontWeight: "600", color: "#fff" },
  titleShifted: { paddingLeft: 0 },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  message: { color: "#fff", fontSize: 15, textAlign: "center", lineHeight: 24 },
  pages: { paddingHorizontal: 8, paddingBottom: 24, gap: 10 },
  page: { width: "100%", backgroundColor: "#222" },
  pageFail: { minHeight: 160, alignItems: "center", justifyContent: "center" },
  bottom: { minHeight: 48, flexDirection: "row", alignItems: "center", justifyContent: "center", paddingHorizontal: 8 },
  hint: { flex: 1, color: "#bbb", fontSize: 12, textAlign: "center" },
  step: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  stepOff: { opacity: 0.3 },
});
