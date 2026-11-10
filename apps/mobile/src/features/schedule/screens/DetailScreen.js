import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import ConfirmDialog from "@/shared/components/ConfirmDialog";
import FormTag from "../components/FormTag";
import SharedTag from "../components/SharedTag";
import { KIND, KIND_COLOR, TOPIC_TEXT } from "../constants";
import { ME_ID, members, topics } from "../mock";
import { isShared } from "../model";
import { loadSharing, removeItem, toggleChecked, useScheduleItem } from "../store";
import { formatDateWithYear, formatTimeConfirmed } from "../utils/date";
import { subjectParticle } from "../utils/korean";

const nameOf = (id) => (id === ME_ID ? "나" : members.find((m) => m.id === id)?.name ?? "");

/**
 * 약속·할 일 상세. 값이 없는 항목은 줄 자체를 숨긴다. 화면에 보이는 일정은 모두 내 줄이라(공유받은 일정도 받은 사람의 것)
 * 수정·삭제를 할 수 있고, 바꿀 수 없는 것은 공유 대상뿐이다. 확인·완료 버튼은 목록 카드의 체크와 같이 움직이고 다시 누르면 해제된다.
 * 수정은 등록 화면을 현재 값이 채워진 채로 열고, 삭제는 화면 가운데 확인 팝업을 거친다.
 * 누가 공유했는지·누구에게 공유했는지는 서버에 물어 채운다(서버가 없거나 실패하면 항목에 든 값을 쓴다).
 */
export default function DetailScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams();
  const item = useScheduleItem(typeof id === "string" ? id : "");
  const [confirming, setConfirming] = useState(false);
  const [sharing, setSharing] = useState(null);

  useEffect(() => {
    let alive = true;
    if (typeof id === "string") loadSharing(id).then((value) => alive && setSharing(value));
    return () => {
      alive = false;
    };
    // 수정해서 공유가 바뀌면 항목이 새로 만들어지므로 다시 읽는다.
  }, [id, item]);

  const leave = () => (router.canGoBack() ? router.back() : router.replace("/(tabs)/schedule"));

  if (!item) {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <View style={styles.body}>
          <IconButton name="chevron-back" label="뒤로" onPress={leave} />
        </View>
      </SafeAreaView>
    );
  }

  const sharedBy = sharing ? sharing.sharedBy : item.createdBy === ME_ID ? null : item.createdBy;
  const sharedWith = sharing ? sharing.sharedWith : item.sharedWith;
  const isAppointment = item.kind === KIND.appointment;
  const topic = topics.find((t) => t.id === item.topicId);
  // 공유받은 사람이 보면 "나"가 들어가고, 공유한 사람은 공유 대상에서 뺀다.
  const sharedIds = [...new Set([...sharedWith, ...(sharedBy ? [ME_ID] : [])])].filter((x) => x !== sharedBy);
  const sharedNames = [...sharedIds].sort((a) => (a === ME_ID ? -1 : 0)).map(nameOf);
  const creator = sharedBy ? nameOf(sharedBy) : "";
  const time = formatTimeConfirmed(item);

  const rows = [
    ["날짜", <Text key="d" style={styles.value}>{formatDateWithYear(item.date)}</Text>],
    time ? ["시간", <Text key="t" style={styles.value}>{time}</Text>] : null,
    item.place ? ["장소", <Text key="p" style={styles.value}>{item.place}</Text>] : null,
    sharedNames.length > 0 ? ["공유", <Text key="s" style={styles.value}>{sharedNames.join(", ")}</Text>] : null,
    item.memo ? ["메모", <Text key="m" style={styles.value}>{item.memo}</Text>] : null,
  ].filter(Boolean);

  const checkText = isAppointment
    ? item.checked ? "확인했어요" : "아직 확인 전이에요"
    : item.checked ? "완료했어요" : "아직 완료 전이에요";
  const checkButton = item.checked ? "되돌리기" : isAppointment ? "확인했어요" : "완료했어요";
  const hasShare = sharedWith.length > 0 || sharedBy !== null;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.body}>
          <View style={styles.top}>
            <View style={styles.back}>
              <IconButton name="chevron-back" label="뒤로" onPress={leave} />
            </View>
            <View style={styles.acts}>
              <Pressable
                onPress={() => router.push({ pathname: "/schedule/register", params: { id: item.id } })}
                style={styles.pill}
                accessibilityRole="button"
              >
                <Text style={styles.pillText}>수정</Text>
              </Pressable>
              <Pressable onPress={() => setConfirming(true)} style={styles.pill} accessibilityRole="button">
                <Text style={[styles.pillText, styles.delete]}>삭제</Text>
              </Pressable>
            </View>
          </View>

          <View style={styles.head}>
            <View style={styles.badges}>
              <FormTag kind={item.kind} />
              {isShared(item) ? <SharedTag label="공동" /> : null}
            </View>
            <View style={styles.titleRow}>
              <Text style={styles.title} accessibilityRole="header">
                {item.title}
              </Text>
              {topic ? (
                <View style={[styles.topicTag, { backgroundColor: TOPIC_TEXT[topic.color] }]}>
                  <Text style={styles.topicTagText}>{topic.name}</Text>
                </View>
              ) : null}
            </View>
          </View>

          <View style={styles.infoBlock}>
            <Text style={styles.by}>{sharedBy ? `${creator}${subjectParticle(creator)} 공유했어요` : "내가 만들었어요"}</Text>
            <View style={styles.info}>
              {rows.map(([label, content], i) => (
                <View key={label} style={[styles.row, i > 0 && styles.rowBorder]}>
                  <Text style={styles.label}>{label}</Text>
                  <View style={styles.content2}>{content}</View>
                </View>
              ))}
            </View>
          </View>

          <View style={styles.status}>
            <Text style={styles.statusText}>{checkText}</Text>
            <Pressable
              onPress={() => toggleChecked(item.id)}
              style={[styles.statusButton, { backgroundColor: item.checked ? colors.card : KIND_COLOR[item.kind] }]}
              accessibilityRole="button"
            >
              <Text style={[styles.statusButtonText, !isAppointment && !item.checked && styles.onDark]}>{checkButton}</Text>
            </Pressable>
          </View>
        </View>
      </ScrollView>

      <ConfirmDialog
        visible={confirming}
        title="이 일정을 삭제할까요?"
        message={hasShare ? "내 일정에서만 지워지고, 공유한 가족의 일정은 그대로 남아요." : undefined}
        confirmLabel="삭제"
        onCancel={() => setConfirming(false)}
        onConfirm={() => {
          setConfirming(false);
          removeItem(item.id);
          leave();
        }}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingBottom: spacing.xxl },
  body: { paddingHorizontal: spacing.xxl, paddingTop: spacing.xl, gap: 12 },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  back: { marginLeft: -spacing.md },
  acts: { flexDirection: "row", gap: 6 },
  pill: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: radius.pill,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  pillText: { fontSize: 14, fontWeight: "500", color: colors.text },
  delete: { color: colors.danger },
  head: { gap: 6 },
  badges: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 6 },
  titleRow: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 8 },
  title: { ...font.page, flexShrink: 1, color: colors.text },
  topicTag: { paddingHorizontal: 10, paddingVertical: 2, borderRadius: radius.pill },
  topicTagText: { ...font.caption, lineHeight: 18, fontWeight: "500", color: colors.onDark, includeFontPadding: false },
  infoBlock: { gap: 4 }, // "내가 만들었어요" 줄은 아래 정보 카드에 붙인다
  by: { ...font.caption, color: colors.textMuted },
  info: {
    paddingHorizontal: spacing.lg,
    paddingVertical: 6,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.card,
  },
  row: { flexDirection: "row", gap: 10, paddingVertical: 8 },
  rowBorder: { borderTopWidth: 1, borderTopColor: colors.border },
  label: { width: 78, fontSize: 14, fontWeight: "500", color: colors.textMuted, paddingTop: 2 },
  content2: { flex: 1 },
  value: { fontSize: 16, color: colors.text },
  status: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    paddingVertical: 12,
    paddingLeft: spacing.lg,
    paddingRight: 14,
    backgroundColor: colors.surfaceStrong,
    borderRadius: radius.card,
  },
  statusText: { flex: 1, fontSize: 15, color: colors.text },
  statusButton: { paddingHorizontal: spacing.lg, paddingVertical: 9, borderRadius: 14, borderWidth: 1, borderColor: "transparent" },
  statusButtonText: { fontSize: 14, fontWeight: "700", color: colors.text },
  onDark: { color: colors.onDark },
});
