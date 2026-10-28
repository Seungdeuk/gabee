import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import SegmentedControl from "../components/SegmentedControl";
import StatusBadge from "../components/StatusBadge";
import { DOT_COLOR, KIND } from "../constants";
import { ME_ID, members } from "../mock";
import { findConflict, receivedStatus, whoLabels } from "../model";
import { acceptRequest, canAnswer, declineRequest, useRequest } from "../requests";
import { useScheduleItems } from "../store";
import { formatDateWithYear, formatTimeConfirmed } from "../utils/date";
import { subjectParticle } from "../utils/korean";

const KIND_OPTIONS = [
  { key: KIND.appointment, label: "약속" },
  { key: KIND.todo, label: "할 일" },
];

const CHOICES = [
  { key: "accepted", label: "수락할게요" },
  { key: "declined", label: "어렵겠어요" },
];

const nameOf = (id) => members.find((m) => m.id === id)?.name ?? "";

/**
 * 받은 같이(받는 사람 화면). 누가 보냈는지, 날짜·시간·장소·메모, 같은 시간의 내 일정, 먼저 함께하는 사람을 보여 주고
 * 수락하기 전에 "내 일정에 어떻게 넣을까요?"(약속 | 할 일, 기본은 할 일)를 고르게 한다.
 * "수락할게요"와 "어렵겠어요"는 같은 너비의 선택 버튼(고른 쪽이 노랑, 처음엔 수락)이고, "저장"(복숭아)을 눌러야 정해지며 저장하면 주고 받은으로 돌아간다. 답한 뒤에도 날짜가 지나기 전에는 "답 바꾸기"로 다시 정할 수 있고(수락했다 어렵게 되면 만든 내 일정이 지워진다),
 * 어렵다고 해도 보낸 사람에게는 알리지 않는다.
 */
export default function ReceiveScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams();
  const request = useRequest(typeof id === "string" ? id : "");
  const items = useScheduleItems();
  const [kind, setKind] = useState(KIND.todo);
  const [changing, setChanging] = useState(false);
  const [choice, setChoice] = useState("accepted");

  const leave = () => (router.canGoBack() ? router.back() : router.replace("/schedule/together-status"));

  if (!request || request.cancelled) {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <View style={styles.body}>
          <View style={styles.back}>
            <IconButton name="chevron-back" label="뒤로" onPress={leave} />
          </View>
        </View>
      </SafeAreaView>
    );
  }

  const status = receivedStatus(request, ME_ID);
  const sender = nameOf(request.fromId);
  const time = formatTimeConfirmed(request);
  const labels = whoLabels(request.whoIds, members);
  // 나 말고 먼저 수락한 사람. 여러 명에게 보낸 경우 "OO가 함께해요"로 알려 준다.
  const others = request.toIds.filter((toId) => toId !== ME_ID && request.replies[toId] === "accepted").map(nameOf);
  const conflict = status !== "accepted" ? findConflict(items, request) : undefined;
  const changeable = status !== "pending" && canAnswer(request);
  // 답을 바꾸려고 열 때, 이미 수락했던 것이면 그때 고른 약속·할 일이 먼저 선택돼 있게 한다.
  const startChange = () => {
    setKind(items.find((item) => item.id === request.itemId)?.kind ?? KIND.todo);
    setChoice(status);
    setChanging(true);
  };
  // 수락할게요 / 어렵겠어요는 고르기만 하고, 저장을 눌러야 답이 정해진다. 저장하면 주고 받은으로 돌아간다.
  const save = () => {
    if (choice === "accepted") acceptRequest(request.id, kind);
    else declineRequest(request.id);
    leave();
  };
  const rows = [
    ["날짜", formatDateWithYear(request.date)],
    time ? ["시간", time] : null,
    request.place ? ["장소", request.place] : null,
    labels.length > 0 ? ["누구", labels.join(", ")] : null,
    request.memo ? ["메모", request.memo] : null,
  ].filter(Boolean);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.body}>
          <View style={styles.back}>
            <IconButton name="chevron-back" label="뒤로" onPress={leave} />
          </View>

          <View style={styles.head}>
            {status !== "pending" ? <StatusBadge status={status} /> : null}
            <Text style={styles.title} accessibilityRole="header">
              {request.title}
            </Text>
            <Text style={styles.by}>{`${sender}${subjectParticle(sender)} 보냈어요`}</Text>
          </View>

          <View style={styles.info}>
            {rows.map(([label, value], i) => (
              <View key={label} style={[styles.row, i > 0 && styles.rowBorder]}>
                <Text style={styles.label}>{label}</Text>
                <Text style={styles.value}>{value}</Text>
              </View>
            ))}
          </View>

          {conflict ? (
            <View style={styles.notice}>
              <Text style={styles.noticeText}>{`같은 시간에 "${conflict.title}" 일정이 있어요`}</Text>
              <Pressable
                onPress={() => router.push({ pathname: "/schedule/detail", params: { id: conflict.id } })}
                accessibilityRole="button"
              >
                <Text style={styles.noticeLink}>일정 보기 ›</Text>
              </Pressable>
            </View>
          ) : null}
          {others.length > 0 ? (
            <View style={styles.notice}>
              <Text style={styles.noticeText}>{`${others.join(", ")}${subjectParticle(others[others.length - 1])} 함께해요`}</Text>
            </View>
          ) : null}

          {status === "pending" || changing ? (
            <>
              <View style={styles.group}>
                <Text style={styles.groupLabel}>내 일정에 어떻게 넣을까요?</Text>
                <SegmentedControl options={KIND_OPTIONS} value={kind} onChange={setKind} full dark />
              </View>

              <View style={styles.buttons}>
                {CHOICES.map(({ key, label }) => (
                  <Pressable
                    key={key}
                    onPress={() => setChoice(key)}
                    style={[styles.button, styles.choice, choice === key && styles.choiceOn]}
                    accessibilityRole="button"
                    accessibilityState={{ selected: choice === key }}
                  >
                    <Text style={styles.buttonText}>{label}</Text>
                  </Pressable>
                ))}
              </View>
              <Pressable
                onPress={save}
                style={[styles.button, styles.save]}
                accessibilityRole="button"
              >
                <Text style={styles.buttonText}>저장</Text>
              </Pressable>
              <Text style={styles.sub}>
                {changing
                  ? "다시 정하면 바뀐 답이 내 일정에 반영돼요\n어렵다고 해도 상대에게는 알리지 않아요"
                  : "수락하면 내 일정에도 들어가요\n어렵다고 해도 상대에게는 알리지 않아요"}
              </Text>
            </>
          ) : (
            <>
              <Text style={styles.sub}>
                {status === "accepted" ? "내 일정에 들어갔어요" : "어렵다고 답했어요. 상대에게는 알리지 않았어요"}
              </Text>
              {changeable ? (
                <>
                  <Pressable onPress={startChange} style={[styles.button, styles.decline]} accessibilityRole="button">
                    <Text style={[styles.buttonText, styles.declineText]}>답 바꾸기</Text>
                  </Pressable>
                  <Text style={styles.sub}>날짜가 지나기 전까지 바꿀 수 있어요</Text>
                </>
              ) : null}
            </>
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingBottom: spacing.xxl },
  body: { paddingHorizontal: spacing.xxl, paddingTop: spacing.xl, gap: 18 },
  back: { marginLeft: -spacing.md, alignSelf: "flex-start" },
  head: { gap: 3 },
  title: { ...font.page, color: colors.text },
  by: { ...font.bodyStrong, fontWeight: "400", color: colors.textMuted },
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
  label: { width: 62, fontSize: 14, fontWeight: "500", color: colors.textMuted, paddingTop: 2 },
  value: { flex: 1, fontSize: 16, color: colors.text },
  notice: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    backgroundColor: colors.surfaceStrong,
    borderRadius: radius.button,
    paddingVertical: 10,
    paddingHorizontal: 14,
  },
  noticeText: { ...font.caption, flexShrink: 1, color: colors.text },
  noticeLink: { fontSize: 13, fontWeight: "500", color: DOT_COLOR },
  group: { gap: 4 },
  groupLabel: { fontSize: 14, fontWeight: "500", color: colors.text },
  buttons: { flexDirection: "row", gap: spacing.sm },
  button: { flex: 1, minHeight: 56, alignItems: "center", justifyContent: "center", borderRadius: radius.button },
  choice: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  choiceOn: { backgroundColor: colors.surfaceStrong, borderColor: colors.surfaceStrong },
  save: { backgroundColor: colors.peach },
  decline: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  buttonText: { fontSize: 16, fontWeight: "700", color: colors.text },
  declineText: { fontWeight: "500" },
  sub: { ...font.caption, textAlign: "center", color: colors.textMuted },
});
