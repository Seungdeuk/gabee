import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, radius, spacing } from "@/theme";

import { ME_ID } from "../../mock";
import { loadTabOrder, saveTabOrder } from "../api";
import ArrowPair from "../components/ArrowPair";
import DailyHeader from "../components/DailyHeader";
import SortableList from "../components/SortableList";
import {
  TAB_ROW_GAP,
  TAB_ROW_HEIGHT,
  hideTab,
  moveTab,
  normalizeTabs,
  reorderTabs,
  showTab,
  tabArrowDisabled,
  visibleTabIds,
} from "../logic";
import { useDailyMembers, useDailyScope } from "../scope";

/**
 * 가족 순서 바꾸기: 나는 맨 앞에 고정(잠금 아이콘). 가족 탭은 ∧∨ 화살표로 한 칸씩 옮기거나, 줄을 꾹 누르고 끌어서 순서를 바꾼다.
 * 눈 버튼으로 숨기거나 다시 보인다. 바꿀 때마다 바로 저장하고, 데일리 체크 메인으로 돌아가면 그 순서가 보인다.
 */
export default function DailyTabOrderScreen() {
  const router = useRouter();
  const scope = useDailyScope();
  const members = useDailyMembers();
  const [saved, setSaved] = useState(null);
  const [dragging, setDragging] = useState(false); // 줄을 끄는 중이면 바깥 스크롤을 잠근다

  const familyIds = useMemo(() => members.filter((m) => m.id !== ME_ID).map((m) => m.id), [members]);

  useEffect(() => {
    let alive = true;
    loadTabOrder(scope).then((tb) => alive && setSaved(tb));
    return () => {
      alive = false;
    };
  }, [scope]);

  const tabs = normalizeTabs(saved, familyIds);
  const visible = visibleTabIds(tabs);
  const hidden = tabs.hidden;
  const nameOf = (id) => members.find((m) => m.id === id)?.name ?? "";

  // 바꾼 탭 상태를 화면에 바로 보이고 이 폰에 저장한다.
  const update = (next) => {
    setSaved(next);
    saveTabOrder(scope, next);
  };
  const leave = () => (router.canGoBack() ? router.back() : router.replace("/schedule/daily-check"));

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <DailyHeader
        title="가족 순서 바꾸기"
        backLabel="뒤로"
        onBack={leave}
        right={
          <Pressable onPress={leave} style={styles.doneButton} accessibilityRole="button" accessibilityLabel="가족 순서 편집 끝내기">
            <Text style={styles.doneText}>완료</Text>
          </Pressable>
        }
      />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false} scrollEnabled={!dragging}>
        <Text style={styles.intro}>나는 항상 맨 앞에 있어요</Text>

        <View style={[styles.row, styles.rowMe]}>
          <Ionicons name="lock-closed-outline" size={20} color={colors.accent} />
          <Text style={[styles.name, styles.grow]}>나</Text>
          <Text style={styles.fixed}>고정</Text>
        </View>

        <SortableList
          data={visible.map((id) => ({ id }))}
          rowHeight={TAB_ROW_HEIGHT}
          gap={TAB_ROW_GAP}
          onReorder={(from, to) => update(reorderTabs(tabs, from, to))}
          onDragActive={setDragging}
          renderRow={(item) => (
            <View style={[styles.row, styles.rowFill]}>
              {/* 위·아래 한 칸 이동(공용 ArrowPair). 줄을 꾹 누른 채 끌어서도 옮긴다(SortableList). */}
              <ArrowPair
                label={nameOf(item.id)}
                disabledUp={tabArrowDisabled(tabs, item.id, -1)}
                disabledDown={tabArrowDisabled(tabs, item.id, 1)}
                onUp={() => update(moveTab(tabs, item.id, -1))}
                onDown={() => update(moveTab(tabs, item.id, 1))}
              />
              <Text style={[styles.name, styles.grow]}>{nameOf(item.id)}</Text>
              <Pressable
                onPress={() => update(hideTab(tabs, item.id))}
                style={styles.round}
                accessibilityRole="button"
                accessibilityLabel={`${nameOf(item.id)} 탭 숨기기`}
              >
                <Ionicons name="eye-outline" size={22} color={colors.textMuted} />
              </Pressable>
            </View>
          )}
        />

        {hidden.length ? (
          <>
            <View style={styles.gap} />
            <Text style={styles.sectionLabel}>숨긴 탭</Text>
            {hidden.map((id) => (
              <View key={id} style={[styles.row, styles.rowHidden]}>
                <Text style={[styles.name, styles.grow, styles.nameMuted]}>{nameOf(id)}</Text>
                <Pressable
                  onPress={() => update(showTab(tabs, id))}
                  style={styles.showButton}
                  accessibilityRole="button"
                  accessibilityLabel={`${nameOf(id)} 탭 다시 보기`}
                >
                  <Text style={styles.showText}>다시 보기</Text>
                </Pressable>
              </View>
            ))}
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { padding: spacing.xl, gap: 12, paddingBottom: spacing.xxl },
  intro: { fontSize: 15, lineHeight: 22, color: colors.textSub },
  row: {
    height: TAB_ROW_HEIGHT,
    paddingRight: 8,
    paddingLeft: 4,
    borderRadius: radius.button,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  rowFill: { flex: 1 },
  rowMe: { paddingLeft: 16, backgroundColor: colors.surfaceStrong, borderWidth: 0, gap: 14 },
  rowHidden: { backgroundColor: colors.surface, borderWidth: 0, paddingLeft: 16, gap: 14 },
  round: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
  name: { fontSize: 17, fontWeight: "700", color: colors.text },
  nameMuted: { fontWeight: "500", color: colors.textSub },
  grow: { flex: 1 },
  fixed: { fontSize: 13, color: colors.textSub, paddingRight: 8 },
  sectionLabel: { fontSize: 14, fontWeight: "700", color: colors.textSub },
  gap: { height: 16 },
  showButton: {
    minHeight: 44,
    paddingHorizontal: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.background,
    justifyContent: "center",
  },
  showText: { fontSize: 14, fontWeight: "500", color: colors.text },
  doneButton: { minHeight: 44, justifyContent: "center", paddingHorizontal: 12 },
  doneText: { fontSize: 16, fontWeight: "700", color: colors.text },
});
