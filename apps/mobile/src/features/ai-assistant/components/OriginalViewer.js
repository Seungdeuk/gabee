import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

/** 쪽 그림 한 장. 불러온 뒤 실제 가로세로 비율로 맞추고, 못 불러오면 안내를 보인다. */
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
 * 올린 원본을 전체 화면으로 본다. 사진은 한 장, PDF 는 쪽마다 한 장씩 위아래로 넘겨 본다.
 * @param {{ state: null | { title?: string, loading?: boolean, sources?: { uri: string, headers?: Record<string, string> }[], message?: string }, onClose: () => void }} props
 * state 가 null 이면 닫혀 있다. sources 가 비면 message(앱에서 열 수 없는 이유)를 보여 준다.
 */
export default function OriginalViewer({ state, onClose }) {
  const sources = state?.sources ?? [];
  return (
    <Modal visible={state !== null} animationType="fade" onRequestClose={onClose}>
      <SafeAreaView style={styles.safe}>
        <View style={styles.top}>
          <Text style={styles.title} numberOfLines={1}>
            {state?.title ?? "원본"}
            {sources.length > 1 ? ` · ${sources.length}쪽` : ""}
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
        ) : (
          <ScrollView contentContainerStyle={styles.pages} maximumZoomScale={3} minimumZoomScale={1}>
            {sources.map((s, i) => (
              <Page key={s.uri} source={s} label={sources.length > 1 ? `${i + 1}쪽` : "원본"} />
            ))}
          </ScrollView>
        )}
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#111" },
  top: { height: 52, flexDirection: "row", alignItems: "center", paddingLeft: 16, paddingRight: 6 },
  title: { flex: 1, fontSize: 15, fontWeight: "600", color: "#fff" },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  message: { color: "#fff", fontSize: 15, textAlign: "center", lineHeight: 24 },
  pages: { paddingHorizontal: 8, paddingBottom: 24, gap: 10 },
  page: { width: "100%", backgroundColor: "#222" },
  pageFail: { minHeight: 160, alignItems: "center", justifyContent: "center" },
});
