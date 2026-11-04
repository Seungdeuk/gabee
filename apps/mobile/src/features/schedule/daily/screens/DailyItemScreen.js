import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import { FormField, TextBox } from "../../components/FormControls";
import ConfirmSheet, { ConfirmBody } from "../components/ConfirmSheet";
import { deleteItem, listItems, saveItem } from "../api";
import { RECOMMEND_POOL } from "../mock";
import { failureNotice } from "../serverMap";
import {
  ALL_DAYS,
  DAY_PRESETS,
  SELECT_BG,
  WEEK_DAYS,
  buildItem,
  formatGoal,
  matchDayPreset,
  parseGoal,
  presetDays,
  recommendChipLabel,
  draftFromParams,
  recommendAvailable,
  recommendToForm,
  stepGoalText,
  NAME_MAX,
  validateItem,
} from "../logic";

/** 안내 팝업 내용(확인 한 개). */
const infoSheet = (notice) => ({ title: notice.title, body: notice.body, confirmLabel: "확인" });

const TYPE_OPTIONS = [
  { key: "check", label: "한 번 체크" },
  { key: "count", label: "횟수 세기" },
];

/**
 * 항목 추가·수정. 헤더는 뒤로 + 제목("추가" 또는 "수정") + 오른쪽 "저장"(텍스트, 강조색). 구분선은 없다.
 * 추가 화면에는 "이런 건 어때요?" 추천 세 개가 있다: 칩을 고르면 이름·체크 방식·목표가 채워진다(이미 있는 항목은 뺀다).
 * 수정 화면(params.id)에는 추천이 없다.
 */
export default function DailyItemScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const editingId = typeof params.id === "string" ? params.id : "";
  // 추천 칩에서 넘어온 값은 문자열로 꺼내 둔다(객체 참조가 바뀌어도 값이 같으면 다시 채우지 않게)
  const pName = typeof params.name === "string" ? params.name : "";
  const pType = typeof params.type === "string" ? params.type : "";
  const pGoal = typeof params.goalText === "string" ? params.goalText : "";
  const editing = Boolean(editingId);

  const [name, setName] = useState("");
  const [type, setType] = useState("check");
  const [goalText, setGoalText] = useState("8");
  const [days, setDays] = useState(ALL_DAYS);
  const [alarm] = useState(false); // 알림은 아직 준비 중이라 바꿀 수 없다
  const [share, setShare] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [sheet, setSheet] = useState(null); // 확인 팝업(ConfirmSheet) 내용. null 이면 닫힘
  const [existing, setExisting] = useState([]); // 이미 있는 항목 이름(추천에서 뺀다)
  const [pickedRec, setPickedRec] = useState("");

  // 화면에 올 때마다 이미 있는 이름을 다시 읽는다(등록한 추천 칩이 추천에서 빠지도록).
  // 수정이면 저장된 항목을 채워 넣는다.
  useFocusEffect(
    useCallback(() => {
      let alive = true;
      listItems()
        .then((list) => {
          if (!alive) return;
          setExisting(list.map((x) => x.name));
          const item = editingId ? list.find((x) => x.id === editingId) : null;
          if (!item) return;
          setName(item.name);
          setType(item.type);
          setGoalText(formatGoal(item.goal, item.unit));
          setDays(item.days);
          setShare(Boolean(item.shareWithFamily));
        })
        .catch((error) => alive && setSheet(infoSheet(failureNotice(error, "불러오지 못했어요"))));
      return () => {
        alive = false;
      };
    }, [editingId]),
  );

  // 추천 칩에서 넘어온 값(이름·체크 방식·목표)으로 새 항목 폼을 채운다. 저장은 사용자가 한다.
  useEffect(() => {
    if (editingId) return;
    const draft = draftFromParams({ name: pName, type: pType, goalText: pGoal });
    if (!draft) return;
    setName(draft.name);
    setType(draft.type);
    setGoalText(draft.goalText);
    setPickedRec(draft.name);
  }, [editingId, pName, pType, pGoal]);

  // 추천은 이미 있는 이름을 뺀 앞의 세 개만 보여 준다(다른 추천으로 넘기지 않는다).
  // 새로 만들기 화면에서는 항상 세 개를 기본으로 보인다. 추천 칩으로 열렸으면 그 이름은 뺀다.
  const recommendations = useMemo(
    () => (editing ? [] : recommendAvailable(RECOMMEND_POOL, pName ? [...existing, pName] : existing, 3)),
    [editing, existing, pName],
  );

  // 온보딩의 "직접 만들기"에서 왔으면 뒤로 가도 온보딩이 아니라 데일리 체크 메인으로 간다
  const fromOnboarding = params.fromOnboarding === "1";
  const leave = () =>
    fromOnboarding || !router.canGoBack() ? router.replace("/schedule/daily-check") : router.back();
  const toggleDay = (key) => setDays((prev) => (prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key]));
  const pickPreset = (key) => setDays(presetDays(key));
  const activePreset = matchDayPreset(days);

  // 추천 칩을 고르면 폼을 채운다(이름, 체크 방식, 목표).
  const pickRecommendation = (p) => {
    const form = recommendToForm(p);
    setName(form.name);
    setType(form.type);
    setGoalText(form.goalText);
    setPickedRec(p.name);
    setError("");
  };

  const save = async () => {
    if (busy) return;
    const draft = { id: editingId || undefined, name, type, goalText, days, alarm, shareWithFamily: share };
    const check = validateItem(draft);
    if (!check.ok) {
      setError(check.error);
      return;
    }
    setBusy(true);
    try {
      await saveItem(buildItem(draft));
      leave();
    } catch (saveError) {
      setBusy(false);
      setSheet(infoSheet(failureNotice(saveError)));
    }
  };

  const remove = () => {
    setSheet({
      title: "이 습관을 지울까요?",
      body: <ConfirmBody name={name} note="지우면 되돌릴 수 없어요" />,
      cancelLabel: "취소",
      confirmLabel: "지우기",
      tone: "danger",
      onConfirm: async () => {
        setSheet(null);
        try {
          await deleteItem(editingId);
          leave();
        } catch (deleteError) {
          setSheet(infoSheet(failureNotice(deleteError, "지우지 못했어요")));
        }
      },
    });
  };

  const goal = parseGoal(goalText);
  const isCountType = type === "count";

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
                  {editing ? "수정" : "추가"}
                </Text>
              </View>
              {/* 수정 모드: 오른쪽 위에 휴지통. 추가 모드: 헤더는 비우고 저장은 하단 "추가하기"로 한다. 저장은 하단 버튼으로만 한다. */}
              {editing ? (
                <Pressable onPress={remove} style={styles.trash} accessibilityRole="button" accessibilityLabel="습관 삭제">
                  <Ionicons name="trash-outline" size={22} color={colors.danger} />
                </Pressable>
              ) : null}
            </View>

            <FormField label="이름">
              <TextBox
                value={name}
                onChangeText={(text) => {
                  // 최대 글자 수(앱 한도 20자)를 넘기지 못하게 자른다(maxLength 와 같은 동작)
                  setName(text.slice(0, NAME_MAX));
                  setPickedRec("");
                  setError("");
                }}
                placeholder="예: 물 마시기"
              />
            </FormField>

            <View style={styles.choiceRow}>
              {TYPE_OPTIONS.map((o) => {
                const on = type === o.key;
                return (
                  <Pressable
                    key={o.key}
                    onPress={() => setType(o.key)}
                    style={[styles.choice, on ? styles.onFill : styles.offFill]}
                    accessibilityRole="button"
                    accessibilityLabel={o.label}
                    accessibilityState={{ selected: on }}
                  >
                    <Text style={[styles.choiceText, on && styles.choiceTextOn]}>{o.label}</Text>
                  </Pressable>
                );
              })}
            </View>

            {isCountType ? (
              <View style={styles.goalRow}>
                <Text style={styles.goalLabel}>하루 목표</Text>
                <Pressable
                  onPress={() => setGoalText((t) => stepGoalText(t, -1))}
                  style={styles.stepBtn}
                  accessibilityRole="button"
                  accessibilityLabel="목표 줄이기"
                >
                  <Text style={styles.stepText}>−</Text>
                </Pressable>
                <TextInput
                  value={goalText}
                  onChangeText={(text) => {
                    setGoalText(text);
                    setError("");
                  }}
                  style={styles.goalInput}
                  accessibilityLabel="하루 목표 (숫자와 단위)"
                  maxLength={12}
                />
                <Pressable
                  onPress={() => setGoalText((t) => stepGoalText(t, 1))}
                  style={styles.stepBtn}
                  accessibilityRole="button"
                  accessibilityLabel="목표 늘리기"
                >
                  <Text style={styles.stepText}>+</Text>
                </Pressable>
              </View>
            ) : null}
            {isCountType && !goal ? <Text style={styles.hint}>예: 8잔, 10쪽, 30분 처럼 숫자와 단위를 적어 주세요</Text> : null}

            <View style={styles.repeatHead}>
              <Text style={styles.label}>반복</Text>
              <View style={styles.presetRow}>
                {DAY_PRESETS.map((p) => {
                  const on = activePreset === p.key;
                  return (
                    <Pressable
                      key={p.key}
                      onPress={() => pickPreset(p.key)}
                      style={[styles.preset, on ? styles.onFill : styles.offFill]}
                      accessibilityRole="button"
                      accessibilityLabel={p.label}
                      accessibilityState={{ selected: on }}
                    >
                      <Text style={[styles.presetText, on && styles.choiceTextOn]}>{p.label}</Text>
                    </Pressable>
                  );
                })}
              </View>
            </View>
            <View style={styles.dayRow}>
              {WEEK_DAYS.map((d) => {
                const on = days.includes(d.key);
                return (
                  <Pressable
                    key={d.key}
                    onPress={() => toggleDay(d.key)}
                    style={[styles.day, on ? styles.onFill : styles.offFill]}
                    accessibilityRole="button"
                    accessibilityLabel={`${d.label}요일`}
                    accessibilityState={{ selected: on }}
                  >
                    <Text style={[styles.dayText, on && styles.choiceTextOn]}>{d.label}</Text>
                  </Pressable>
                );
              })}
            </View>

            <View style={styles.switchBox}>
              <View style={styles.switchRow}>
                <View style={styles.switchText}>
                  <Text style={styles.switchTitle}>가족에게 보이기</Text>
                  <Text style={styles.switchSub}>끄면 내 탭에서만 보여요</Text>
                </View>
                <Switch
                  value={share}
                  onValueChange={setShare}
                  trackColor={{ false: colors.border, true: colors.success }}
                  thumbColor={colors.card}
                  accessibilityLabel="가족에게 보이기"
                />
              </View>
            </View>

            {!editing ? (
              <View style={styles.recBox}>
                <Text style={styles.label}>이런 건 어때요?</Text>
                <View style={styles.chips}>
                  {recommendations.map((p) => {
                    const on = pickedRec === p.name;
                    return (
                      <Pressable
                        key={p.name}
                        onPress={() => pickRecommendation(p)}
                        style={[styles.chip, on ? styles.onFill : styles.chipOff]}
                        accessibilityRole="button"
                        accessibilityLabel={`${recommendChipLabel(p)} 추천`}
                        accessibilityState={{ selected: on }}
                      >
                        <Text style={[styles.chipText, on && styles.choiceTextOn]}>{recommendChipLabel(p)}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </View>
            ) : null}

            {error ? <Text style={styles.error}>{error}</Text> : null}
            <Pressable
              onPress={save}
              style={[styles.save, busy && styles.saveOff]}
              accessibilityRole="button"
              accessibilityLabel={editing ? "저장하기" : "추가하기"}
              accessibilityState={{ disabled: busy }}
            >
              <Text style={styles.saveText}>{editing ? "저장" : "추가하기"}</Text>
            </Pressable>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
      <ConfirmSheet
        visible={sheet !== null}
        title={sheet?.title ?? ""}
        body={sheet?.body}
        cancelLabel={sheet?.cancelLabel}
        confirmLabel={sheet?.confirmLabel ?? "확인"}
        tone={sheet?.tone}
        onCancel={() => setSheet(null)}
        onConfirm={() => (sheet?.onConfirm ? sheet.onConfirm() : setSheet(null))}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingBottom: spacing.xxl * 3 }, // 키보드가 올라와도 맨 아래 칸까지 스크롤해 볼 수 있게 넉넉히
  body: { paddingHorizontal: 20, paddingTop: 18, gap: 18 },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: -7 },
  titleBox: { flexDirection: "row", alignItems: "center", marginLeft: -spacing.sm },
  title: { ...font.page, color: colors.text },
  trash: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  label: { fontSize: 15, fontWeight: "700", color: colors.text },
  hint: { fontSize: 13, color: colors.textSub },
  // 선택 = 노랑(바탕 SELECT_BG + 1px SELECT_BORDER), 미선택 = 흰 바탕 + 1px 옅은 테두리
  // 선택 칩은 외곽선 없이 노란 채움만(테두리는 바탕색과 같은 색으로 크기만 맞춘다)
  onFill: { backgroundColor: SELECT_BG, borderWidth: 1, borderColor: SELECT_BG },
  offFill: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  choiceRow: { flexDirection: "row", gap: 8 },
  choice: { flex: 1, height: 46, borderRadius: 14, alignItems: "center", justifyContent: "center" },
  choiceText: { fontSize: 15, color: colors.text },
  choiceTextOn: { fontWeight: "700", color: colors.text },
  goalRow: {
    height: 52,
    paddingLeft: 16,
    paddingRight: 6,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  goalLabel: { flex: 1, fontSize: 15, color: colors.text },
  // − 와 + 는 배경색 없이 글자만, 값은 탭하면 바로 고친다
  stepBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center", backgroundColor: "transparent" },
  stepText: { fontSize: 20, fontWeight: "700", color: colors.text },
  goalInput: {
    minWidth: 64,
    height: 44,
    paddingVertical: 0,
    paddingHorizontal: 4,
    backgroundColor: "transparent",
    color: colors.text,
    fontSize: 16,
    fontWeight: "700",
    textAlign: "center",
    textAlignVertical: "center",
    includeFontPadding: false,
  },
  // "반복" 글자와 같은 한 줄: 왼쪽 글자, 오른쪽 끝에 칩 4개(한 줄, 줄바꿈 없음)
  repeatHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  presetRow: { flexDirection: "row", alignItems: "center", flexShrink: 0, gap: 4 },
  preset: { height: 32, paddingHorizontal: 10, borderRadius: 16, alignItems: "center", justifyContent: "center" },
  presetText: { fontSize: 13, color: colors.text },
  // 요일 7개는 그 아래 줄에 전체 폭을 7등분
  dayRow: { flexDirection: "row", gap: 6 },
  day: { flex: 1, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  dayText: { fontSize: 14, color: colors.text },
  switchBox: { borderRadius: radius.button, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card },
  switchRow: { minHeight: 64, paddingHorizontal: 16, flexDirection: "row", alignItems: "center", gap: 12 },
  disabledRow: { opacity: 0.5 }, // 항목 사이에 구분선을 두지 않는다
  switchText: { flex: 1, gap: 2 },
  switchTitle: { fontSize: 15, fontWeight: "500", color: colors.text },
  switchSub: { fontSize: 13, color: colors.textSub },
  recBox: { gap: 10 },
  recHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  recMore: { fontSize: 13, fontWeight: "500", color: colors.accent },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { height: 38, paddingHorizontal: 12, borderRadius: 19, alignItems: "center", justifyContent: "center" },
  chipOff: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  chipText: { fontSize: 14, color: colors.text },
  error: { fontSize: 14, color: colors.danger, textAlign: "center" },
  save: { height: 56, borderRadius: radius.button, backgroundColor: colors.peach, alignItems: "center", justifyContent: "center" },
  saveOff: { opacity: 0.55 },
  saveText: { fontSize: 16, fontWeight: "700", color: colors.text },
});
