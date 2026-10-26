import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors } from "@/theme";

import { deleteRecord, getRecord, originalImageSource, submitDescription, updateRecord } from "../api";
import useOriginal from "../hooks/useOriginal";
import OriginalViewer from "./OriginalViewer";

const DATE_FORMAT = /^\d{4}-\d{2}-\d{2}$/;

/**
 * 올린 기록 한 건의 상세. 읽어 낸 글(개인정보는 가려진 상태)을 원본과 비교하며 고칠 수 있다.
 * - 확인 필요 기록: 위에 안내가 뜨고, 맞으면 "확인 완료", 틀렸으면 고쳐서 "저장"한다.
 * - 저장하면 서버가 검색용으로 다시 만들어서 이후 질문에 고친 내용이 쓰인다.
 * @param {{ record: object | null, onClose: () => void, onChanged: () => void }} props record: 목록의 한 항목
 */
export default function RecordDetail({ record, onClose, onChanged }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const viewer = useOriginal();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ title: "", kind_label: "", occurred_on: "", body: "" });
  const [saving, setSaving] = useState(false);
  const [descText, setDescText] = useState(""); // "설명 추가" 칸의 글
  const [described, setDescribed] = useState(false); // 이 화면에서 설명을 저장했는지(저장하면 영역을 숨긴다)

  useEffect(() => {
    setDetail(null);
    setError("");
    setEditing(false);
    setDescText("");
    setDescribed(false);
    if (!record) return undefined;
    let alive = true;
    getRecord(record.id)
      .then((d) => alive && setDetail(d))
      .catch((e) => alive && setError(e?.message || "내용을 불러오지 못했어요."));
    return () => {
      alive = false;
    };
  }, [record]);

  const isImage = /\.(jpe?g|png|webp|gif|bmp|heic|heif)$/i.test(record?.source_path ?? "");
  const preview = record?.hasOriginal && isImage ? originalImageSource(record.id) : null;
  const needsReview = detail ? detail.needs_review : record?.needs_review;
  const needsDescription = !described && (detail ? detail.needs_description : record?.needs_description) === true;

  const startEdit = () => {
    if (!detail) return;
    setDraft({
      title: detail.title,
      kind_label: detail.kind_label,
      occurred_on: detail.occurred_on ?? "",
      body: detail.body_md,
    });
    setEditing(true);
  };

  const finish = (next) => {
    setDetail(next);
    setEditing(false);
    onChanged?.();
  };

  /** changes 가 비어 있으면 고치지 않고 확인만 한다. */
  const submit = async (changes) => {
    setSaving(true);
    try {
      finish(await updateRecord(record.id, changes));
    } catch (e) {
      Alert.alert("저장하지 못했어요", e?.message || "잠시 후 다시 시도해 주세요.");
    } finally {
      setSaving(false);
    }
  };

  /** 글자 없는 사진에 한 줄 설명을 단다. 저장하면 목록을 새로 불러오고 상세는 다시 읽는다. */
  const saveDescription = async () => {
    setSaving(true);
    try {
      await submitDescription(record.id, descText.trim());
      setDescribed(true);
      setDetail(await getRecord(record.id));
      onChanged?.();
    } catch (e) {
      Alert.alert("저장하지 못했어요", e?.message || "잠시 후 다시 시도해 주세요.");
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = () =>
    Alert.alert(
      "기록을 지울까요?",
      "읽어 낸 글과 서버에 둔 원본 파일이 모두 지워지고 되돌릴 수 없어요. 가족 모두에게서 사라져요.",
      [
        { text: "취소", style: "cancel" },
        {
          text: "지우기",
          style: "destructive",
          onPress: async () => {
            setSaving(true);
            try {
              await deleteRecord(record.id);
              onChanged?.();
              onClose();
            } catch (e) {
              Alert.alert("지우지 못했어요", e?.message || "잠시 후 다시 시도해 주세요.");
            } finally {
              setSaving(false);
            }
          },
        },
      ],
    );

  const save = () => {
    const day = draft.occurred_on.trim();
    if (!draft.title.trim() || !draft.kind_label.trim() || !draft.body.trim()) {
      Alert.alert("비워 둘 수 없어요", "제목, 종류, 내용은 비워 둘 수 없어요.");
      return;
    }
    if (day && !DATE_FORMAT.test(day)) {
      Alert.alert("날짜 모양이 달라요", "2026-10-15 처럼 숫자와 하이픈으로 적어 주세요. 비워 두면 날짜 없음이에요.");
      return;
    }
    submit({ title: draft.title.trim(), kind_label: draft.kind_label.trim(), occurred_on: day || null, body_md: draft.body });
  };

  return (
    <Modal visible={record !== null} animationType="slide" onRequestClose={onClose}>
      <SafeAreaView style={styles.safe}>
        <View style={styles.top}>
          <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="닫기" style={styles.close}>
            <Ionicons name="chevron-down" size={24} color={colors.text} />
          </Pressable>
          <Text style={styles.topTitle} numberOfLines={1}>
            {editing ? "고치기" : record?.title}
          </Text>
        </View>

        <KeyboardAvoidingView style={styles.flex} behavior="padding">
          <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
            {needsReview ? (
              <View style={styles.review}>
                <Ionicons name="alert-circle-outline" size={18} color={colors.warning} />
                <Text style={styles.reviewText}>
                  {"글자가 흐리거나 종류가 확실하지 않아요. 원본과 비교해서 맞으면 '확인 완료', 틀렸으면 고쳐 주세요."}
                </Text>
              </View>
            ) : null}

            {needsDescription && !editing ? (
              <View style={styles.describe}>
                <Text style={styles.label}>설명 추가</Text>
                <Text style={styles.note}>글자가 없는 사진이에요. 한 줄로 알려 주시면 나중에 말로 찾을 수 있어요.</Text>
                <TextInput
                  style={styles.input}
                  value={descText}
                  onChangeText={setDescText}
                  editable={!saving}
                  maxLength={200}
                  placeholder="예: 할머니 생신 케이크"
                  placeholderTextColor={colors.placeholder}
                  accessibilityLabel="사진 설명 입력"
                />
                <Text style={styles.count}>{200 - descText.length}자 남음</Text>
                <Pressable
                  onPress={saveDescription}
                  disabled={saving || descText.trim().length === 0}
                  accessibilityRole="button"
                  accessibilityLabel="설명 저장"
                  style={[styles.btn, styles.btnMain, (saving || descText.trim().length === 0) && styles.off]}
                >
                  {saving ? <ActivityIndicator color={colors.onDark} /> : <Text style={styles.btnMainText}>저장</Text>}
                </Pressable>
              </View>
            ) : null}

            {preview ? (
              <Pressable onPress={() => viewer.open(record.id, record.source_path, record.title)} accessibilityRole="button" accessibilityLabel="원본 크게 보기">
                <Image source={preview} style={styles.preview} contentFit="contain" />
                <Text style={styles.previewHint}>눌러서 원본 크게 보기</Text>
              </Pressable>
            ) : record?.hasOriginal ? (
              <Pressable onPress={() => viewer.open(record.id, record.source_path, record.title)} accessibilityRole="button" style={styles.originalBtn}>
                <Ionicons name="document-text-outline" size={18} color={colors.text} />
                <Text style={styles.originalText}>원본 보기</Text>
              </Pressable>
            ) : null}

            {editing ? (
              <View style={styles.form}>
                <Text style={styles.label}>제목</Text>
                <TextInput style={styles.input} value={draft.title} onChangeText={(v) => setDraft({ ...draft, title: v })} maxLength={200} />
                <Text style={styles.label}>종류 (예: 영수증, 고지서)</Text>
                <TextInput style={styles.input} value={draft.kind_label} onChangeText={(v) => setDraft({ ...draft, kind_label: v })} maxLength={100} />
                <Text style={styles.label}>날짜 (2026-10-15 형식, 없으면 비워 두기)</Text>
                <TextInput
                  style={styles.input}
                  value={draft.occurred_on}
                  onChangeText={(v) => setDraft({ ...draft, occurred_on: v })}
                  keyboardType="numbers-and-punctuation"
                  maxLength={10}
                  placeholder="YYYY-MM-DD"
                  placeholderTextColor={colors.placeholder}
                />
                <Text style={styles.label}>읽어 낸 내용</Text>
                <TextInput
                  style={[styles.input, styles.bodyInput]}
                  value={draft.body}
                  onChangeText={(v) => setDraft({ ...draft, body: v })}
                  multiline
                  textAlignVertical="top"
                  maxLength={50000}
                />
                <Text style={styles.note}>주민번호·전화번호·카드번호는 저장할 때 다시 가려져요. 원본 파일에는 그대로 남아 있어요.</Text>
                <View style={styles.row}>
                  <Pressable onPress={() => setEditing(false)} disabled={saving} accessibilityRole="button" style={[styles.btn, styles.btnGhost]}>
                    <Text style={styles.btnGhostText}>취소</Text>
                  </Pressable>
                  <Pressable onPress={save} disabled={saving} accessibilityRole="button" style={[styles.btn, styles.btnMain]}>
                    {saving ? <ActivityIndicator color={colors.onDark} /> : <Text style={styles.btnMainText}>저장</Text>}
                  </Pressable>
                </View>
              </View>
            ) : (
              <>
                <Text style={styles.meta}>{[detail?.kind_label ?? record?.kind_label, detail?.occurred_on ?? record?.occurred_on].filter(Boolean).join(" · ")}</Text>
                <Text style={styles.section}>읽어 낸 내용</Text>
                {detail ? (
                  <Text style={styles.content} selectable>
                    {detail.body_md}
                  </Text>
                ) : error ? (
                  <Text style={styles.warn}>{error}</Text>
                ) : (
                  <ActivityIndicator color={colors.textMuted} />
                )}
                <Text style={styles.note}>개인정보(주민번호·전화·카드 등)는 가려진 상태로 저장돼요.</Text>
                <View style={styles.row}>
                  <Pressable onPress={startEdit} disabled={!detail || saving} accessibilityRole="button" style={[styles.btn, styles.btnGhost]}>
                    <Ionicons name="create-outline" size={17} color={colors.text} />
                    <Text style={styles.btnGhostText}>고치기</Text>
                  </Pressable>
                  {needsReview ? (
                    <Pressable onPress={() => submit({})} disabled={!detail || saving} accessibilityRole="button" style={[styles.btn, styles.btnMain]}>
                      {saving ? <ActivityIndicator color={colors.onDark} /> : <Text style={styles.btnMainText}>확인 완료</Text>}
                    </Pressable>
                  ) : null}
                </View>
                <Pressable onPress={confirmDelete} disabled={!detail || saving} accessibilityRole="button" style={styles.deleteBtn}>
                  <Ionicons name="trash-outline" size={16} color={colors.danger} />
                  <Text style={styles.deleteText}>이 기록 지우기</Text>
                </Pressable>
              </>
            )}
          </ScrollView>
        </KeyboardAvoidingView>
        <OriginalViewer state={viewer.state} onClose={viewer.close} />
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  top: { height: 52, flexDirection: "row", alignItems: "center", paddingRight: 16 },
  close: { width: 52, height: 52, alignItems: "center", justifyContent: "center" },
  topTitle: { flex: 1, fontSize: 17, fontWeight: "700", color: colors.text },
  body: { paddingHorizontal: 20, paddingBottom: 40, gap: 12 },
  review: { flexDirection: "row", gap: 8, padding: 12, borderRadius: 12, backgroundColor: colors.honeySoft },
  reviewText: { flex: 1, fontSize: 13, lineHeight: 20, color: colors.text },
  preview: { width: "100%", height: 220, borderRadius: 12, backgroundColor: colors.surface },
  deleteBtn: { alignSelf: "center", marginTop: 16, minHeight: 40, paddingHorizontal: 14, flexDirection: "row", alignItems: "center", gap: 6 },
  deleteText: { fontSize: 14, color: colors.danger },
  originalBtn: { alignSelf: "flex-start", minHeight: 40, paddingHorizontal: 14, borderRadius: 20, backgroundColor: colors.surface, flexDirection: "row", alignItems: "center", gap: 6 },
  originalText: { fontSize: 14, fontWeight: "600", color: colors.text },
  previewHint: { marginTop: 4, textAlign: "center", fontSize: 12, color: colors.textMuted },
  meta: { fontSize: 13, color: colors.textMuted },
  warn: { fontSize: 13, lineHeight: 20, color: colors.warning },
  section: { marginTop: 8, fontSize: 13, fontWeight: "700", color: colors.textSub },
  content: { fontSize: 14, lineHeight: 22, color: colors.text },
  note: { fontSize: 12, lineHeight: 18, color: colors.textMuted },
  describe: { gap: 8, padding: 12, borderRadius: 12, backgroundColor: colors.honeySoft },
  count: { alignSelf: "flex-end", fontSize: 11, color: colors.textMuted },
  off: { opacity: 0.4 },
  form: { gap: 8 },
  label: { marginTop: 4, fontSize: 13, fontWeight: "600", color: colors.textSub },
  input: { minHeight: 44, paddingHorizontal: 12, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, fontSize: 15, color: colors.text },
  bodyInput: { minHeight: 220, paddingTop: 12, lineHeight: 22 },
  row: { flexDirection: "row", gap: 10, marginTop: 8 },
  btn: { flex: 1, minHeight: 46, borderRadius: 23, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6 },
  btnGhost: { backgroundColor: colors.surface },
  btnGhostText: { fontSize: 15, fontWeight: "600", color: colors.text },
  btnMain: { backgroundColor: colors.dark },
  btnMainText: { fontSize: 15, fontWeight: "600", color: colors.onDark },
});
