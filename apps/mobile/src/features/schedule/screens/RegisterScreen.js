import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import ConfirmDialog from "../components/ConfirmDialog";
import DateSheet from "../components/DateSheet";
import FilterChip from "../components/FilterChip";
import { FormField, PressBox, TextBox } from "../components/FormControls";
import SegmentedControl from "../components/SegmentedControl";
import TimeSheet from "../components/TimeSheet";
import TopicChips from "../components/TopicChips";
import WhoChips from "../components/WhoChips";
import { KIND, KIND_LABEL } from "../constants";
import { useHiddenWho } from "../favorites_hook";
import { ME_ID } from "../mock";
import { addItem, addTopic, loadSharing, removeTopic, updateItem, useMembers, useScheduleItem, useTopics } from "../store";
import { markUsed } from "../suggestions_store";
import { formatDateWithYear, formatTimeConfirmed } from "../utils/date";

const KIND_OPTIONS = [KIND.appointment, KIND.todo].map((key) => ({ key, label: KIND_LABEL[key] }));
const toggle = (list, id) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

/**
 * 약속·할 일 등록 화면. 약속과 할 일의 입력 항목은 같고 형태만 고른다. 필수는 제목과 날짜, 나머지는 선택. 저장하면 진입했던 화면으로 돌아가고,
 * 취소하면 아무것도 만들어지지 않는다. 제안으로 열리면(suggested) 안내 문구와 함께 미리 채워진다.
 * id 를 받으면 수정 화면이다: 같은 화면에 현재 값이 채워지고 제목줄은 "수정", 저장하면 그 항목이 고쳐진다(형태도 바꿀 수 있다).
 */
export default function RegisterScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const editing = useScheduleItem(typeof params.id === "string" ? params.id : "");
  const [kind, setKind] = useState(editing?.kind ?? (params.kind === KIND.todo ? KIND.todo : KIND.appointment));
  const [title, setTitle] = useState(editing?.title ?? (typeof params.title === "string" ? params.title : ""));
  const [topicId, setTopicId] = useState(editing?.topicId ?? null);
  const [sharedWith, setSharedWith] = useState(editing?.sharedWith ?? []);
  // 수정할 때 지금의 공유 상태(undefined 는 아직 읽는 중). 공유 대상은 원본 주인(sharedBy 가 없는 사람)만 보고 바꾼다.
  const [shareInfo, setShareInfo] = useState(undefined);
  const [removeShareOpen, setRemoveShareOpen] = useState(false);
  const [date, setDate] = useState(editing?.date ?? (/^\d{4}-\d{2}-\d{2}$/.test(params.date ?? "") ? params.date : ""));
  const [place, setPlace] = useState(editing?.place ?? (typeof params.place === "string" ? params.place : ""));
  const [memo, setMemo] = useState(editing?.memo ?? "");
  const [time, setTime] = useState(
    editing
      ? { allDay: editing.allDay, startTime: editing.startTime, endTime: editing.endTime }
      : { allDay: false, startTime: null, endTime: null },
  );
  const [dateOpen, setDateOpen] = useState(false);
  const [timeOpen, setTimeOpen] = useState(false);
  const [triedSave, setTriedSave] = useState(false);
  const topics = useTopics();
  const family = useMembers();

  // 서버에서 가족을 읽은 뒤에 바뀌므로 화면을 그릴 때마다 계산한다.
  const OTHERS = family.filter((m) => m.id !== ME_ID);
  const SHAREABLE = OTHERS.filter((m) => m.hasAccount);
  // "공유" 칩 줄에서 뺀 사람(이 폰에만 저장).
  const share = useHiddenWho("share", SHAREABLE);
  const valid = title.trim() !== "" && date !== "";
  const editingId = editing?.id;
  useEffect(() => {
    if (!editingId) return undefined;
    let alive = true;
    loadSharing(editingId).then((value) => {
      if (!alive) return;
      // 서버가 없거나 못 읽으면 항목에 든 값으로 본다(내가 만든 일정이면 원본 주인).
      const info = value ?? { sharedBy: editing.createdBy === ME_ID ? null : editing.createdBy, sharedWith: editing.sharedWith ?? [] };
      setShareInfo(info);
      setSharedWith(info.sharedWith);
    });
    return () => {
      alive = false;
    };
    // editing 은 id 가 같으면 값을 다시 읽을 필요가 없어 id 만 본다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editingId]);
  const canShare = !editing || (shareInfo !== undefined && shareInfo.sharedBy === null);
  const removedShare = editing && canShare ? shareInfo.sharedWith.filter((x) => !sharedWith.includes(x)) : [];
  const shareChanged = editing && canShare && (removedShare.length > 0 || sharedWith.some((x) => !shareInfo.sharedWith.includes(x)));
  const hideShare = (id) => {
    share.hide(id);
    setSharedWith(sharedWith.filter((x) => x !== id));
  };
  const deleteTopic = (id) => {
    removeTopic(id);
    if (topicId === id) setTopicId(null);
  };
  const allShared = SHAREABLE.length > 0 && SHAREABLE.every((m) => sharedWith.includes(m.id));

  // 진입했던 화면으로 돌아간다. 이전 화면이 없으면(주소로 직접 열기) 일정 메인으로 간다.
  const leave = () => (router.canGoBack() ? router.back() : router.replace("/(tabs)/schedule"));
  const save = (confirmedRemove = false) => {
    if (!valid) {
      setTriedSave(true);
      return;
    }
    // 공유에서 사람을 빼면 그 사람이 받은 일정도 지워지므로 한 번 확인한다.
    if (removedShare.length > 0 && confirmedRemove !== true) {
      setRemoveShareOpen(true);
      return;
    }
    const fields = {
      kind,
      title: title.trim(),
      date,
      ...time,
      place: place.trim(),
      memo: memo.trim(),
      topicId,
    };
    // 수정에서는 원본 주인이 공유를 바꿨을 때만 공유 대상을 함께 보낸다.
    if (editing) updateItem(editing.id, shareChanged ? { ...fields, sharedWith } : fields);
    else {
      // 서버 추천에서 열린 등록이면 제안 id 를 같이 보내 서버가 제안을 확정하게 하고, 홈의 추천 목록에서도 뺀다.
      const suggestionId = typeof params.suggestionId === "string" && params.suggestionId ? params.suggestionId : undefined;
      addItem({ ...fields, sharedWith, createdBy: ME_ID, ...(suggestionId ? { suggestionId } : {}) });
      if (suggestionId) markUsed(suggestionId);
    }
    leave();
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView style={styles.safe} behavior="padding">
      <ScrollView
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode={Platform.OS === "ios" ? "interactive" : "on-drag"}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.body}>
          <View style={styles.top}>
            <View style={styles.titleBox}>
              <IconButton name="chevron-back" label="뒤로" onPress={leave} />
              <Text style={styles.title} accessibilityRole="header">
                {editing ? "수정" : "소중한 하루의 준비"}
              </Text>
            </View>
            <View style={styles.topActions}>
              <Pressable onPress={save} hitSlop={10} accessibilityRole="button">
                <Text style={styles.cancel}>{editing ? "저장" : "등록"}</Text>
              </Pressable>
              <Pressable onPress={leave} hitSlop={10} accessibilityRole="button">
                <Text style={styles.cancel}>취소</Text>
              </Pressable>
            </View>
          </View>

          {params.suggested === "1" ? (
            <Text style={styles.notice}>제안으로 채웠어요. 내용을 확인 후 저장해 주세요.</Text>
          ) : null}

          <SegmentedControl options={KIND_OPTIONS} value={kind} onChange={setKind} full />

          <FormField label="제목" hint="필수">
            <TextBox value={title} onChangeText={setTitle} />
          </FormField>

          <View style={styles.group}>
            <FormField label="주제">
              <TopicChips
                topics={topics}
                selectedIds={topicId ? [topicId] : []}
                onToggle={(id) => setTopicId(topicId === id ? null : id)}
                onCreate={addTopic}
                onCreated={(topic) => setTopicId(topic.id)}
                onDelete={deleteTopic}
              />
            </FormField>
            {canShare ? (
              <FormField label="공유" hint="선택 안 하면 나만 봐요">
                <WhoChips
                  members={SHAREABLE}
                  hiddenIds={share.hidden}
                  selectedIds={sharedWith}
                  onToggle={(id) => setSharedWith(toggle(sharedWith, id))}
                  onHide={hideShare}
                  onShow={share.show}
                  lead={
                    <FilterChip label="모두" selected={allShared} onPress={() => setSharedWith(allShared ? [] : SHAREABLE.map((m) => m.id))} />
                  }
                />
              </FormField>
            ) : null}
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
      </KeyboardAvoidingView>

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
      <ConfirmDialog
        visible={removeShareOpen}
        title="공유에서 뺄까요?"
        message="받은 분 일정도 같이 사라져요."
        confirmLabel="저장"
        onCancel={() => setRemoveShareOpen(false)}
        onConfirm={() => {
          setRemoveShareOpen(false);
          save(true);
        }}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingBottom: spacing.xxl * 3 }, // 키보드가 올라와도 맨 아래 칸까지 스크롤해 볼 수 있게 넉넉히
  body: { paddingHorizontal: spacing.xxl, paddingTop: spacing.xl, gap: 14 },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: -7 }, // 제목과 형태 선택 사이를 반으로
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
  group: { gap: 6 },
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
