import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import DateSheet from "../components/DateSheet";
import FilterChip from "../components/FilterChip";
import { FormField, PressBox, TextBox } from "../components/FormControls";
import SegmentedControl from "../components/SegmentedControl";
import TimeSheet from "../components/TimeSheet";
import { KIND, KIND_LABEL } from "../constants";
import { ME_ID, members, topics } from "../mock";
import { addItem } from "../store";
import { formatDateWithYear, formatTimeConfirmed } from "../utils/date";

const KIND_OPTIONS = [KIND.appointment, KIND.todo].map((key) => ({ key, label: KIND_LABEL[key] }));
const OTHERS = members.filter((m) => m.id !== ME_ID);
const SHAREABLE = OTHERS.filter((m) => m.hasAccount);

const toggle = (list, id) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

/**
 * 약속·할 일 등록 화면. 약속과 할 일의 입력 항목은 같고 형태만 고른다. 필수는 제목과 날짜, 나머지는 선택. 저장하면 진입했던 화면으로 돌아가고,
 * 취소하면 아무것도 만들어지지 않는다. 제안으로 열리면(suggested) 안내 문구와 함께 미리 채워진다.
 */
export default function RegisterScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const [kind, setKind] = useState(params.kind === KIND.todo ? KIND.todo : KIND.appointment);
  const [title, setTitle] = useState(typeof params.title === "string" ? params.title : "");
  const [whoIds, setWhoIds] = useState([]);
  const [topicId, setTopicId] = useState(null);
  const [sharedWith, setSharedWith] = useState([]);
  const [date, setDate] = useState(/^\d{4}-\d{2}-\d{2}$/.test(params.date ?? "") ? params.date : "");
  const [place, setPlace] = useState("");
  const [memo, setMemo] = useState("");
  const [time, setTime] = useState({ allDay: false, startTime: null, endTime: null });
  const [dateOpen, setDateOpen] = useState(false);
  const [timeOpen, setTimeOpen] = useState(false);
  const [triedSave, setTriedSave] = useState(false);

  const valid = title.trim() !== "" && date !== "";
  const allShared = SHAREABLE.length > 0 && SHAREABLE.every((m) => sharedWith.includes(m.id));

  // 진입했던 화면으로 돌아간다. 이전 화면이 없으면(주소로 직접 열기) 일정 메인으로 간다.
  const leave = () => (router.canGoBack() ? router.back() : router.replace("/(tabs)/schedule"));
  const save = () => {
    if (!valid) {
      setTriedSave(true);
      return;
    }
    addItem({
      kind,
      title: title.trim(),
      date,
      ...time,
      place: place.trim(),
      memo: memo.trim(),
      whoIds,
      topicId,
      sharedWith,
      createdBy: ME_ID,
    });
    leave();
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
        <View style={styles.body}>
          <View style={styles.top}>
            <View style={styles.titleBox}>
              <IconButton name="chevron-back" label="뒤로" onPress={leave} />
              <Text style={styles.title} accessibilityRole="header">
                소중한 하루의 준비
              </Text>
            </View>
            <Pressable onPress={leave} hitSlop={10} accessibilityRole="button">
              <Text style={styles.cancel}>취소</Text>
            </Pressable>
          </View>

          {params.suggested === "1" ? (
            <Text style={styles.notice}>제안으로 채웠어요. 내용을 확인 후 저장해 주세요.</Text>
          ) : null}

          <SegmentedControl options={KIND_OPTIONS} value={kind} onChange={setKind} full />

          <FormField label="제목" hint="필수">
            <TextBox value={title} onChangeText={setTitle} />
          </FormField>

          <View style={styles.group}>
            <FormField label="누구" hint="관련된 사람">
              <View style={styles.chips}>
                {OTHERS.map((m) => (
                  <FilterChip key={m.id} label={m.name} selected={whoIds.includes(m.id)} onPress={() => setWhoIds(toggle(whoIds, m.id))} />
                ))}
                <FilterChip label="+ 누구" muted />
              </View>
            </FormField>
            <FormField label="주제">
              <View style={styles.chips}>
                {topics.map((t) => (
                  <FilterChip key={t.id} label={t.name} selected={topicId === t.id} onPress={() => setTopicId(topicId === t.id ? null : t.id)} />
                ))}
                <FilterChip label="+ 주제" muted />
              </View>
            </FormField>
            <FormField label="공유" hint="선택 안 하면 나만 봐요">
              <View style={styles.chips}>
                <FilterChip label="모두" selected={allShared} onPress={() => setSharedWith(allShared ? [] : SHAREABLE.map((m) => m.id))} />
                {SHAREABLE.map((m) => (
                  <FilterChip key={m.id} label={m.name} selected={sharedWith.includes(m.id)} onPress={() => setSharedWith(toggle(sharedWith, m.id))} />
                ))}
              </View>
            </FormField>
          </View>

          <View style={styles.group}>
            <FormField label="날짜" hint="필수">
              <PressBox value={date ? formatDateWithYear(date) : ""} placeholder="날짜를 선택해 주세요" onPress={() => setDateOpen(true)} />
            </FormField>
            <FormField
              label="시간"
              action="시간 없음"
              onAction={() => setTime({ allDay: false, startTime: null, endTime: null })}
            >
              <PressBox
                value={formatTimeConfirmed(time)}
                placeholder="시간 없음"
                onPress={() => setTimeOpen(true)}
              />
            </FormField>
            <FormField label="장소">
              <TextBox value={place} onChangeText={setPlace} />
            </FormField>
          </View>

          <FormField label="메모">
            <TextBox value={memo} onChangeText={setMemo} placeholder="메모를 남겨 보세요" multiline />
          </FormField>

          {triedSave && !valid ? <Text style={styles.error}>제목과 날짜를 입력해 주세요</Text> : null}
          <Pressable onPress={save} style={[styles.save, !valid && styles.saveOff]} accessibilityRole="button">
            <Text style={styles.saveText}>저장</Text>
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
  group: { gap: spacing.sm },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  error: { ...font.caption, color: colors.danger, textAlign: "center" },
  save: {
    minHeight: 56,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.button,
    backgroundColor: colors.peach,
  },
  saveOff: { opacity: 0.55 },
  saveText: { fontSize: 16, fontWeight: "700", color: colors.text },
});
