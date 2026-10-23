import { Ionicons } from "@expo/vector-icons";
import { useEffect, useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors } from "@/theme";

import { getRecord, originalImageSource } from "../api";
import OriginalViewer from "./OriginalViewer";

/** 저장된 글의 첫 두 줄(# 제목, 분류)은 위에 따로 보여 주므로 뺀다. */
const bodyOf = (md) => md.split("\n").slice(2).join("\n").trim();

/**
 * 올린 기록 한 건의 상세: 분류·날짜, 읽어 낸 글(개인정보는 가려진 상태), 원본 보기.
 * @param {{ record: object | null, onClose: () => void }} props record: 목록의 한 항목
 */
export default function RecordDetail({ record, onClose }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [viewer, setViewer] = useState(null);

  useEffect(() => {
    setDetail(null);
    setError("");
    if (!record) return undefined;
    let alive = true;
    getRecord(record.id)
      .then((d) => alive && setDetail(d))
      .catch((e) => alive && setError(e?.message || "내용을 불러오지 못했어요."));
    return () => {
      alive = false;
    };
  }, [record]);

  const original = record?.hasOriginal ? originalImageSource(record.id) : null;

  return (
    <Modal visible={record !== null} animationType="slide" onRequestClose={onClose}>
      <SafeAreaView style={styles.safe}>
        <View style={styles.top}>
          <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="닫기" style={styles.close}>
            <Ionicons name="chevron-down" size={24} color={colors.text} />
          </Pressable>
          <Text style={styles.topTitle} numberOfLines={1}>
            {record?.title}
          </Text>
        </View>

        <ScrollView contentContainerStyle={styles.body}>
          <Text style={styles.meta}>{[record?.kind_label, record?.occurred_on].filter(Boolean).join(" · ")}</Text>
          {record?.has_unread_parts ? <Text style={styles.warn}>읽지 못한 부분이 있어요. 원본과 비교해 확인해 주세요.</Text> : null}
          {original ? (
            <Pressable onPress={() => setViewer(original)} accessibilityRole="button" style={styles.originalBtn}>
              <Ionicons name="image-outline" size={18} color={colors.text} />
              <Text style={styles.originalText}>원본 보기</Text>
            </Pressable>
          ) : null}
          <Text style={styles.section}>읽어 낸 내용</Text>
          {detail ? (
            <Text style={styles.content} selectable>
              {bodyOf(detail.body_md) || "읽어 낸 글이 없어요."}
            </Text>
          ) : error ? (
            <Text style={styles.warn}>{error}</Text>
          ) : (
            <ActivityIndicator color={colors.textMuted} />
          )}
          <Text style={styles.note}>개인정보(주민번호·전화·카드 등)는 가려진 상태로 저장돼요. 원본은 위 버튼으로 볼 수 있어요.</Text>
        </ScrollView>
        <OriginalViewer source={viewer} title={record?.title} onClose={() => setViewer(null)} />
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  top: { height: 52, flexDirection: "row", alignItems: "center", paddingRight: 16 },
  close: { width: 52, height: 52, alignItems: "center", justifyContent: "center" },
  topTitle: { flex: 1, fontSize: 17, fontWeight: "700", color: colors.text },
  body: { paddingHorizontal: 20, paddingBottom: 40, gap: 12 },
  meta: { fontSize: 13, color: colors.textMuted },
  warn: { fontSize: 13, lineHeight: 20, color: colors.warning },
  originalBtn: {
    alignSelf: "flex-start",
    minHeight: 40,
    paddingHorizontal: 14,
    borderRadius: 20,
    backgroundColor: colors.surface,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  originalText: { fontSize: 14, fontWeight: "600", color: colors.text },
  section: { marginTop: 8, fontSize: 13, fontWeight: "700", color: colors.textSub },
  content: { fontSize: 14, lineHeight: 22, color: colors.text },
  note: { marginTop: 8, fontSize: 12, lineHeight: 18, color: colors.textMuted },
});
