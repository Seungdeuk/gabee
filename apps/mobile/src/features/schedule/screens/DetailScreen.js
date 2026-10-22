import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import ConfirmDialog from "../components/ConfirmDialog";
import FormTag from "../components/FormTag";
import { KIND, KIND_COLOR, TOPIC_TEXT } from "../constants";
import { ME_ID, members, topics } from "../mock";
import { whoLabels } from "../model";
import { removeItem, toggleChecked, useScheduleItem } from "../store";
import { formatDateWithYear, formatTimeConfirmed } from "../utils/date";
import { subjectParticle } from "../utils/korean";

const nameOf = (id) => (id === ME_ID ? "나" : members.find((m) => m.id === id)?.name ?? "");

/**
 * 약속·할 일 상세. 값이 없는 항목은 줄 자체를 숨기고, 수정·삭제는 만든 사람에게만 보인다.
 * 공유받은 사람은 보기와 확인·완료 체크만 할 수 있다. 확인·완료 버튼은 목록 카드의 체크와 같이 움직이고 다시 누르면 해제된다.
 * 수정은 등록 화면을 현재 값이 채워진 채로 열고, 삭제는 화면 가운데 확인 팝업을 거친다.
 */
export default function DetailScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams();
  const item = useScheduleItem(typeof id === "string" ? id : "");
  const [confirming, setConfirming] = useState(false);

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

  const mine = item.createdBy === ME_ID;
  const isAppointment = item.kind === KIND.appointment;
  const topic = topics.find((t) => t.id === item.topicId);
  const labels = whoLabels(item.whoIds, members);
  // 공유받은 사람이 보면 "나"가 들어가고, 만든 사람은 공유 대상에서 뺀다.
  const sharedIds = [...new Set([...item.sharedWith, ...(mine ? [] : [ME_ID])])].filter((x) => x !== item.createdBy);
  const sharedNames = [...sharedIds].sort((a) => (a === ME_ID ? -1 : 0)).map(nameOf);
  const creator = nameOf(item.createdBy);
  const time = formatTimeConfirmed(item);

  const rows = [
    ["날짜", <Text key="d" style={styles.value}>{formatDateWithYear(item.date)}</Text>],
    time ? ["시간", <Text key="t" style={styles.value}>{time}</Text>] : null,
    item.place ? ["장소", <Text key="p" style={styles.value}>{item.place}</Text>] : null,
    labels.length > 0 ? ["누구", <Text key="w" style={styles.value}>{labels.join(", ")}</Text>] : null,
    sharedNames.length > 0 ? ["공유", <Text key="s" style={styles.value}>{sharedNames.join(", ")}</Text>] : null,
    item.memo ? ["메모", <Text key="m" style={styles.value}>{item.memo}</Text>] : null,
  ].filter(Boolean);

  const checkText = isAppointment
    ? item.checked ? "확인했어요" : "아직 확인 전이에요"
    : item.checked ? "완료했어요" : "아직 완료 전이에요";
  const checkButton = item.checked ? "되돌리기" : isAppointment ? "확인했어요" : "완료했어요";
  const sharedForDelete = item.sharedWith.map(nameOf).filter(Boolean);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.body}>
          <View style={styles.top}>
            <View style={styles.back}>
              <IconButton name="chevron-back" label="뒤로" onPress={leave} />
            </View>
            {mine ? (
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
            ) : null}
          </View>

          <View style={styles.head}>
            <View style={styles.badges}>
              <FormTag kind={item.kind} />
              {topic ? <Text style={[styles.topic, { color: TOPIC_TEXT[topic.color] }]}>{topic.name}</Text> : null}
            </View>
            <Text style={styles.title} accessibilityRole="header">
              {labels.length > 0 ? <Text style={styles.who}>{` ${labels.join("·")} `}</Text> : null}
              {labels.length > 0 ? " " : null}
              {item.title}
            </Text>
            <Text style={styles.by}>{mine ? "내가 만들었어요" : `${creator}${subjectParticle(creator)} 공유했어요`}</Text>
          </View>

          <View style={styles.info}>
            {rows.map(([label, content], i) => (
              <View key={label} style={[styles.row, i > 0 && styles.rowBorder]}>
                <Text style={styles.label}>{label}</Text>
                <View style={styles.content2}>{content}</View>
              </View>
            ))}
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
        message={sharedForDelete.length > 0 ? `공유한 ${sharedForDelete.join(", ")} 화면에서도 사라져요.` : undefined}
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
  body: { paddingHorizontal: spacing.xxl, paddingTop: spacing.xl, gap: 18 },
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
  head: { gap: 8 },
  badges: { flexDirection: "row", alignItems: "center", gap: 8 },
  topic: { ...font.caption, fontWeight: "500" },
  title: { ...font.page, color: colors.text },
  who: {
    ...font.caption,
    fontWeight: "500",
    color: colors.text,
    backgroundColor: colors.surfaceStrong,
    borderRadius: radius.pill,
    overflow: "hidden",
  },
  by: { ...font.caption, color: colors.textMuted },
  info: {
    paddingHorizontal: spacing.lg,
    paddingVertical: 6,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.card,
  },
  row: { flexDirection: "row", gap: 10, paddingVertical: 11 },
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
