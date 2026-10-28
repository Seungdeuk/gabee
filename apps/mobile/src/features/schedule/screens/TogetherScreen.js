import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { isApiConfigured } from "@/shared/api/client";
import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import DateSheet from "../components/DateSheet";
import FilterChip from "../components/FilterChip";
import { FormField, PressBox, TextBox } from "../components/FormControls";
import TimeSheet from "../components/TimeSheet";
import { ME_ID, members } from "../mock";
import { sendRequest } from "../requests";
import { formatDateWithYear, formatTimeConfirmed } from "../utils/date";

const OTHERS = members.filter((m) => m.id !== ME_ID);
const RECEIVERS = OTHERS.filter((m) => m.hasAccount);

const toggle = (list, id) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

/**
 * 같이 보내기 화면. 일정 하나를 가족에게 "같이 해 주세요" 하고 보낸다. 필수는 내용·날짜이고
 * 받는 사람(안 고르면 모두에게 간다)·시간·장소·메모·관련된 사람은 선택이다. 날짜·시간 입력은 등록 화면과 같은 시트를 쓴다.
 * 메인의 추천 샘플로 열리면(suggested) 안내 문구와 함께 내용이 미리 채워진다. 취소하면 아무것도 보내지 않는다.
 * 취소하거나 보내면 주고 받은(현황)으로 간다. 현황에서 열었으면(from=status) 이미 쌓여 있는 현황으로 돌아온다.
 */
export default function TogetherScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const [title, setTitle] = useState(typeof params.title === "string" ? params.title : "");
  const [toIds, setToIds] = useState([]);
  const [whoIds, setWhoIds] = useState([]);
  const [date, setDate] = useState(/^\d{4}-\d{2}-\d{2}$/.test(params.date ?? "") ? params.date : "");
  const [time, setTime] = useState({ allDay: false, startTime: null, endTime: null });
  const [place, setPlace] = useState("");
  const [memo, setMemo] = useState("");
  const [dateOpen, setDateOpen] = useState(false);
  const [timeOpen, setTimeOpen] = useState(false);
  const [triedSend, setTriedSend] = useState(false);

  const valid = title.trim() !== "" && date !== "";

  const goBack = () => (router.canGoBack() ? router.back() : router.replace("/(tabs)/schedule"));
  // 메인에서 열었으면 이 화면을 현황으로 바꿔 끼워 "메인 → 현황"만 남기고, 현황에서 열었으면 그 현황으로 돌아간다.
  const toStatus = () => (params.from === "status" ? router.back() : router.replace("/schedule/together-status"));
  // 보낸 뒤에는 방금 보낸 것이 보이도록 보낸 탭으로 연다(at 은 같은 탭이어도 다시 옮기게 하는 표시).
  const toSent = () => {
    const target = { pathname: "/schedule/together-status", params: { tab: "sent", at: String(Date.now()) } };
    if (params.from === "status") router.dismissTo(target);
    else router.replace(target);
  };
  const send = () => {
    if (!valid) {
      setTriedSend(true);
      return;
    }
    // 받는 사람을 하나도 고르지 않으면 모두에게 간다.
    const receivers = toIds.length > 0 ? toIds : RECEIVERS.map((m) => m.id);
    sendRequest({ fromId: ME_ID, toIds: receivers, title: title.trim(), date, ...time, place: place.trim(), memo: memo.trim(), whoIds });
    toSent();
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
        <View style={styles.body}>
          <View style={styles.top}>
            <View style={styles.titleBox}>
              <IconButton name="chevron-back" label="뒤로" onPress={goBack} />
              <Text style={styles.title} accessibilityRole="header">
                같이, 곁에
              </Text>
            </View>
            <View style={styles.topActions}>
              <Pressable onPress={send} hitSlop={10} accessibilityRole="button">
                <Text style={styles.cancel}>보내기</Text>
              </Pressable>
              <Pressable onPress={toStatus} hitSlop={10} accessibilityRole="button">
                <Text style={styles.cancel}>취소</Text>
              </Pressable>
            </View>
          </View>

          {params.suggested === "1" ? (
            <Text style={styles.notice}>추천으로 채웠어요. 내용을 확인 후 보내 주세요.</Text>
          ) : null}

          <FormField label="내용" hint="필수">
            <TextBox value={title} onChangeText={setTitle} />
          </FormField>

          <FormField label="받는 사람" hint="지정하지 않으면 모두에게 가요">
            <View style={styles.chips}>
              {RECEIVERS.map((m) => (
                <FilterChip key={m.id} label={m.name} selected={toIds.includes(m.id)} onPress={() => setToIds(toggle(toIds, m.id))} />
              ))}
              <FilterChip label="+ 누구" muted />
            </View>
            <Text style={styles.help}>여러 명에게 보내면 각자 수락할 수 있어요</Text>
          </FormField>

          {/* 서버는 "누구"를 저장하지 않는다(수락한 사람 일정의 누구는 보낸 사람으로 정해진다). 서버 모드에서는 숨긴다. */}
          {!isApiConfigured() && (
            <FormField label="누구" hint="관련된 사람">
              <View style={styles.chips}>
                {OTHERS.map((m) => (
                  <FilterChip key={m.id} label={m.name} selected={whoIds.includes(m.id)} onPress={() => setWhoIds(toggle(whoIds, m.id))} />
                ))}
                <FilterChip label="+ 누구" muted />
              </View>
            </FormField>
          )}

          <View style={styles.group}>
            <FormField label="날짜" hint="필수">
              <PressBox value={date ? formatDateWithYear(date) : ""} placeholder="날짜를 선택해 주세요" onPress={() => setDateOpen(true)} />
            </FormField>
            <FormField label="시간" action="시간 없음" onAction={() => setTime({ allDay: false, startTime: null, endTime: null })}>
              <PressBox value={formatTimeConfirmed(time)} placeholder="시간 없음" onPress={() => setTimeOpen(true)} />
            </FormField>
            <FormField label="장소">
              <TextBox value={place} onChangeText={setPlace} />
            </FormField>
          </View>

          <FormField label="메모">
            <TextBox value={memo} onChangeText={setMemo} placeholder="메모를 남겨 보세요" multiline />
          </FormField>

          {triedSend && !valid ? <Text style={styles.error}>내용과 날짜를 입력해 주세요</Text> : null}
          <Pressable onPress={send} style={[styles.send, !valid && styles.sendOff]} accessibilityRole="button">
            <Text style={styles.sendText}>보내기</Text>
          </Pressable>
        </View>
      </ScrollView>

      {timeOpen ? (
        <TimeSheet
          visible
          value={time}
          onClose={() => setTimeOpen(false)}
          onSelect={(picked) => {
            setTime(picked);
            setTimeOpen(false);
          }}
        />
      ) : null}
      {dateOpen ? (
        <DateSheet
          visible
          value={date}
          onClose={() => setDateOpen(false)}
          onSelect={(picked) => {
            setDate(picked);
            setDateOpen(false);
          }}
        />
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingBottom: spacing.xxl },
  body: { paddingHorizontal: spacing.xxl, paddingTop: spacing.xl, gap: 18 },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  topActions: { flexDirection: "row", alignItems: "center", gap: spacing.lg },
  titleBox: { flexDirection: "row", alignItems: "center", marginLeft: -spacing.sm },
  title: { ...font.page, color: colors.text },
  cancel: { fontSize: 14, fontWeight: "500", color: colors.textMuted },
  notice: {
    ...font.caption,
    textAlign: "center",
    color: colors.text,
    backgroundColor: colors.surfaceStrong,
    borderRadius: radius.button,
    paddingVertical: 10,
    paddingHorizontal: 14,
  },
  group: { gap: 4 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  help: { ...font.caption, color: colors.textMuted, marginTop: 6 },
  error: { ...font.caption, color: colors.danger, textAlign: "center" },
  send: { minHeight: 56, alignItems: "center", justifyContent: "center", borderRadius: radius.button, backgroundColor: colors.peach },
  sendOff: { opacity: 0.55 },
  sendText: { fontSize: 16, fontWeight: "700", color: colors.text },
});
