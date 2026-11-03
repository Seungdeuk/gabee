import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, font, radius, spacing } from "@/theme";

import { RECOMMEND_POOL } from "../mock";
import { deleteItem, listItems, replaceItems, resetAll, seedExamples } from "../api";
import ArrowPair from "../components/ArrowPair";
import ConfirmSheet, { ConfirmBody } from "../components/ConfirmSheet";
import DailyHeader from "../components/DailyHeader";
import PencilIcon from "../components/PencilIcon";
import SortableList from "../components/SortableList";
import {
  itemArrowDisabled,
  itemDescription,
  moveIndex,
  moveItemOne,
  recommendAvailable,
  recommendChipLabel,
  recommendToForm,
} from "../logic";
import { useDailyScope } from "../scope";
import { todayKey } from "../../utils/date";

// 편집 줄 높이(고정). 이름·보조글자, ∧∨, 연필, 휴지통이 한 줄에 든다.
const EDIT_ROW_HEIGHT = 64;

/**
 * 내 항목 편집: 매일 챙기는 일 목록(∧∨ 한 칸 옮기기, 줄을 꾹 누른 채 끌어서 순서 바꾸기, 고치기·지우기), 직접 만들기, 추천 항목을 눌러 바로 추가.
 * 순서를 바꾸면 바로 저장하고, 데일리 체크 메인도 같은 목록 순서를 읽는다.
 * 추가·수정 화면에서 돌아오면 다시 읽는다.
 */
export default function DailyEditScreen() {
  const router = useRouter();
  const scope = useDailyScope();
  const [items, setItems] = useState([]);
  const [sheet, setSheet] = useState(null); // 확인 팝업(ConfirmSheet) 내용. null 이면 닫힘
  const [dragging, setDragging] = useState(false); // 줄을 끄는 중이면 바깥 스크롤을 잠근다

  useFocusEffect(
    useCallback(() => {
      let alive = true;
      listItems(scope).then((list) => alive && setItems(list));
      return () => {
        alive = false;
      };
    }, [scope]),
  );

  // 바뀐 목록을 화면에 바로 보이고 이 폰에 저장한다.
  const applyItems = (next) => {
    setItems(next);
    replaceItems(scope, next);
  };

  const leave = () => (router.canGoBack() ? router.back() : router.replace("/schedule/daily-check"));

  const confirmDelete = (item) => {
    setSheet({
      title: "이 습관을 지울까요?",
      body: <ConfirmBody name={item.name} note="지우면 되돌릴 수 없어요" />,
      cancelLabel: "취소",
      confirmLabel: "지우기",
      tone: "danger",
      onConfirm: async () => {
        setSheet(null);
        await deleteItem(scope, item.id);
        setItems((prev) => prev.filter((x) => x.id !== item.id));
      },
    });
  };

  // 추천 칩은 바로 추가하지 않는다. 칩 내용이 채워진 항목 추가 화면으로 간다(사용자가 고쳐서 저장한다).
  // 이미 있는 이름은 추천에서 빠진다(목록은 화면에 올 때마다 다시 읽는다).
  const recommended = recommendAvailable(
    RECOMMEND_POOL,
    items.map((x) => x.name),
    6,
  );
  const openRecommended = (p) => router.push({ pathname: "/schedule/daily-item", params: recommendToForm(p) });

  // 개발용: 시안 예시 데이터(내 항목·오늘 기록·받은 응원)로 덮어쓴다. __DEV__ 에서만 보인다.
  const devSeed = async () => {
    await seedExamples(scope, todayKey());
    setItems(await listItems(scope));
  };

  // 개발용: 이 사용자의 데일리 체크 저장값을 모두 지우고(가상 가족 플래그 포함) 메인으로 돌아간다. 메인이 온보딩으로 보낸다.
  const devReset = () => {
    setSheet({
      title: "데일리 체크를 처음 상태로 지울까요?",
      body: "습관·기록·응원·온보딩 표시가 모두 지워져요 (개발용)",
      cancelLabel: "취소",
      confirmLabel: "지우기",
      tone: "danger",
      onConfirm: async () => {
        setSheet(null);
        await resetAll(scope);
        router.replace("/schedule/daily-check");
      },
    });
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <DailyHeader
        title="내 습관 편집"
        backLabel="뒤로"
        onBack={leave}
        right={
          <Pressable onPress={leave} style={styles.doneButton} accessibilityRole="button" accessibilityLabel="편집 끝내기">
            <Text style={styles.doneText}>완료</Text>
          </Pressable>
        }
      />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false} scrollEnabled={!dragging}>
        <Text style={styles.sectionLabel}>{`매일 습관 ${items.length}개`}</Text>

        {/* 줄을 꾹 누른 채 끌면 순서가 바뀐다(SortableList). ∧∨ 는 한 칸씩 옮긴다. 바꿀 때마다 바로 저장한다. */}
        <SortableList
          data={items}
          rowHeight={EDIT_ROW_HEIGHT}
          gap={10}
          onReorder={(from, to) => applyItems(moveIndex(items, from, to))}
          onDragActive={setDragging}
          renderRow={(item) => (
            <View style={styles.row}>
              {/* 화살표는 줄 맨 앞(왼쪽 끝)에 둔다. 가족 순서 바꾸기 화면과 같은 배치 */}
              <ArrowPair
                label={item.name}
                disabledUp={itemArrowDisabled(items, item.id, -1)}
                disabledDown={itemArrowDisabled(items, item.id, 1)}
                onUp={() => applyItems(moveItemOne(items, item.id, -1))}
                onDown={() => applyItems(moveItemOne(items, item.id, 1))}
              />
              <View style={styles.text}>
                <Text style={styles.name}>{item.name}</Text>
                <Text style={styles.sub}>{itemDescription(item)}</Text>
              </View>
              <Pressable
                onPress={() => router.push({ pathname: "/schedule/daily-item", params: { id: item.id } })}
                style={styles.iconButton}
                accessibilityRole="button"
                accessibilityLabel={`${item.name} 수정`}
              >
                <PencilIcon size={20} />
              </Pressable>
              <Pressable
                onPress={() => confirmDelete(item)}
                style={styles.iconButton}
                accessibilityRole="button"
                accessibilityLabel={`${item.name} 삭제`}
              >
                <Ionicons name="trash-outline" size={20} color={colors.danger} />
              </Pressable>
            </View>
          )}
        />

        <Pressable
          onPress={() => router.push("/schedule/daily-item")}
          style={styles.addButton}
          accessibilityRole="button"
          accessibilityLabel="직접 만들기"
        >
          <Text style={styles.addText}>+ 직접 만들기</Text>
        </Pressable>

        <Text style={[styles.sectionLabel, styles.recommendLabel]}>추천 습관</Text>
        <View style={styles.chips}>
          {recommended.map((p) => (
            <Pressable
              key={p.name}
              onPress={() => openRecommended(p)}
              style={styles.chip}
              accessibilityRole="button"
              accessibilityLabel={`${p.name} 추천 습관 열기`}
            >
              <Text style={styles.chipText}>{recommendChipLabel(p)}</Text>
            </Pressable>
          ))}
        </View>

        {__DEV__ ? (
          <Pressable
            onPress={devSeed}
            style={styles.devLink}
            accessibilityRole="button"
            accessibilityLabel="개발용 예시 데이터 채우기"
          >
            <Text style={styles.devText}>개발용 · 예시 데이터 채우기</Text>
          </Pressable>
        ) : null}
        {__DEV__ ? (
          <Pressable
            onPress={devReset}
            style={styles.devLink}
            accessibilityRole="button"
            accessibilityLabel="개발용 데일리 체크 초기화"
          >
            <Text style={styles.devText}>개발용 · 데일리 체크 초기화</Text>
          </Pressable>
        ) : null}
      </ScrollView>
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
  content: { padding: spacing.xl, gap: 10, paddingBottom: spacing.xxl },
  sectionLabel: { ...font.caption, fontSize: 14, fontWeight: "700", color: colors.textSub, marginBottom: 4 },
  recommendLabel: { marginTop: 12 },
  row: {
    height: EDIT_ROW_HEIGHT,
    paddingLeft: 6,
    paddingRight: 4,
    borderRadius: radius.button,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  text: { flex: 1, gap: 0 },
  name: { ...font.cardTitle, color: colors.text },
  sub: { ...font.caption, color: colors.textSub },
  iconButton: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: 22 },
  addButton: {
    height: 56,
    borderRadius: radius.button,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 4,
  },
  addText: { fontSize: 16, fontWeight: "500", color: colors.textSub },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    minHeight: 44,
    paddingHorizontal: 16,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    justifyContent: "center",
  },
  chipText: { fontSize: 15, color: colors.text },
  doneButton: { minHeight: 44, justifyContent: "center", paddingHorizontal: 12 },
  doneText: { fontSize: 16, fontWeight: "700", color: colors.text },
  devLink: { minHeight: 44, alignItems: "center", justifyContent: "center", marginTop: spacing.lg },
  devText: { fontSize: 13, color: colors.textMuted, textDecorationLine: "underline" },
});
