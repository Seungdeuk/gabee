import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

import { ROW_HEIGHT, countChipText, isCount, isDone, itemSubText, memoPreview } from "../logic";

import MemoIcon from "./MemoIcon";

/**
 * 데일리 체크 항목 한 줄. 줄 높이는 ROW_HEIGHT 로 고정이다.
 * - 내 탭: 줄 왼쪽에 handle(길게 누른 줄의 점 세 개 표시, 평소에는 없음), 한 번 체크는 체크 버튼, 횟수 세기는 − 횟수 + 버튼.
 *   이름 옆 메모 아이콘(onMemoIcon 이 있을 때만, 보이는 크기 28·터치 44): 메모가 있으면 노란 원, 없으면 연한 윤곽선.
 * - 가족 탭(family): 손잡이 없이 보기만 한다(완료·기록 없음·횟수 표시). 메모 아이콘은 없다.
 * - 메모가 있으면 보조 글자 뒤에 " · 메모 앞 10자"를 붙인다. 그 글자를 누르면 onMemoText(전문 팝업)를 부른다.
 * @param {{ item: object, entry?: object, family?: boolean, handle?: import("react").ReactNode, memo?: string,
 *   onMemoIcon?: () => void, onMemoText?: () => void, onCheck?: () => void, onStep?: (delta: number) => void }} props
 */
export default function DailyRow({ item, entry, family = false, handle = null, memo = "", onMemoIcon, onMemoText, onCheck, onStep }) {
  const done = isDone(item, entry);
  const count = isCount(item);
  const sub = itemSubText(item, entry, { family });
  const preview = memoPreview(memo);

  return (
    <View style={[styles.row, handle ? styles.rowWithHandle : styles.rowPlain]} accessibilityLabel={`${item.name}, ${sub}${preview ? `, 메모 ${preview}` : ""}`}>
      {handle}
      <View style={styles.text}>
        <View style={styles.nameRow}>
          <Text style={styles.name} numberOfLines={1}>
            {item.name}
          </Text>
          {onMemoIcon ? (
            <Pressable
              onPress={onMemoIcon}
              style={styles.memoHit}
              accessibilityRole="button"
              accessibilityLabel={`${item.name} ${preview ? "메모 고치기" : "메모 쓰기"}`}
            >
              <View style={[styles.memoCircle, preview ? styles.memoOn : styles.memoOff]}>
                <MemoIcon size={16} color={preview ? colors.text : colors.textMuted} />
              </View>
            </Pressable>
          ) : null}
        </View>
        <Text style={styles.sub} numberOfLines={1}>
          {sub}
          {preview ? (
            <Text>
              {" · "}
              <Text style={styles.memoText} onPress={onMemoText} accessibilityRole="button" accessibilityLabel={`${item.name} 메모 전체 보기`}>
                {preview}
              </Text>
            </Text>
          ) : null}
        </Text>
      </View>

      {family ? (
        count ? (
          // 목표 달성이면 초록 칩 흰 글자, 아니면 노랑 칩(예: 5/8)
          <View style={[styles.chip56, done ? styles.pillDone : styles.pillSoft]}>
            <Text style={done ? styles.pillDoneText : styles.pillText}>{countChipText(entry, item.goal)}</Text>
          </View>
        ) : done ? (
          <View style={[styles.chip56, styles.pillDone]}>
            <Text style={styles.pillDoneText}>완료</Text>
          </View>
        ) : (
          // 안 한 체크는 "3/8"과 같은 너비(56)의 노랑 칩에 "-"
          <View style={[styles.chip56, styles.pillSoft]}>
            <Text style={styles.pillText}>-</Text>
          </View>
        )
      ) : count ? (
        <View style={styles.stepGroup}>
          <Pressable
            onPress={() => onStep?.(-1)}
            style={[styles.roundButton, styles.minusLine]}
            accessibilityRole="button"
            accessibilityLabel={`${item.name} 한 번 빼기`}
          >
            <Text style={styles.stepText}>−</Text>
          </Pressable>
          <Text style={[styles.countText, done && styles.countDone]}>{countChipText(entry, item.goal)}</Text>
          <Pressable
            onPress={() => onStep?.(1)}
            style={[styles.roundButton, styles.plusGreen]}
            accessibilityRole="button"
            accessibilityLabel={`${item.name} 한 번 더하기`}
          >
            <Text style={[styles.stepText, styles.plusText]}>+</Text>
          </Pressable>
        </View>
      ) : (
        <Pressable
          onPress={onCheck}
          style={[styles.roundButton, done ? styles.checkDone : styles.checkLine]}
          accessibilityRole="button"
          accessibilityLabel={done ? `${item.name} 완료 취소` : `${item.name} 완료로 표시`}
          accessibilityState={{ checked: done }}
        >
          {done ? <Ionicons name="checkmark" size={22} color={colors.onDark} /> : null}
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    height: ROW_HEIGHT,
    paddingVertical: 0,
    paddingRight: 14,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  rowWithHandle: { paddingLeft: 4 },
  rowPlain: { paddingLeft: 18 },
  text: { flex: 1, minWidth: 0, gap: 2 },
  nameRow: { flexDirection: "row", alignItems: "center", gap: 4, minWidth: 0 },
  name: { ...font.cardTitle, fontSize: 17, color: colors.text, flexShrink: 1 },
  // 메모 아이콘: 보이는 원 28, 터치 칸 44(위아래 -8 로 줄 높이를 넘기지 않게)
  memoHit: { width: 44, height: 44, marginVertical: -8, marginLeft: -4, alignItems: "center", justifyContent: "center", flex: 0 },
  memoCircle: { width: 28, height: 28, borderRadius: 14, alignItems: "center", justifyContent: "center" },
  memoOn: { backgroundColor: colors.surfaceStrong },
  memoOff: { borderWidth: 1, borderColor: colors.border },
  memoText: { fontWeight: "700", color: colors.text },
  sub: { ...font.caption, fontSize: 14, color: colors.textSub },
  roundButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: "center",
    justifyContent: "center",
  },
  // − 는 흰 바탕 1px 테두리(색 없음), + 는 초록 바탕에 초록 글자, 체크 원은 1.5px 테두리
  // − 는 배경도 테두리도 없이 글자만(터치 영역 44 유지)
  minusLine: { borderWidth: 0, backgroundColor: "transparent" },
  plusGreen: { backgroundColor: colors.successSoft },
  plusText: { color: colors.success, fontWeight: "700" },
  checkLine: { borderWidth: 1.5, borderColor: colors.textMuted, backgroundColor: colors.card },
  // 가족 탭의 읽기 전용 칩(완료 / 3/8 / -)은 모두 같은 폭 56, 같은 높이, 가운데 정렬(늘어나지 않게 좌우 패딩 0)
  chip56: { width: 56, paddingHorizontal: 0, paddingVertical: 6, alignItems: "center", justifyContent: "center", borderRadius: 999 },
  checkDone: { backgroundColor: colors.success },
  stepGroup: { flexDirection: "row", alignItems: "center", gap: 6 },
  stepText: { fontSize: 20, color: colors.text, fontWeight: "700" },
  countText: { minWidth: 40, textAlign: "center", fontSize: 16, fontWeight: "700", color: colors.text },
  countDone: { color: colors.success },
  pill: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999 },
  pillDone: { backgroundColor: colors.success },
  pillDoneText: { ...font.caption, fontSize: 14, fontWeight: "700", color: colors.onDark },
  pillEmpty: { backgroundColor: colors.surface },
  pillEmptyText: { ...font.caption, fontSize: 14, fontWeight: "500", color: colors.textSub },
  pillSoft: { backgroundColor: colors.surfaceStrong },
  pillText: { ...font.caption, fontSize: 14, fontWeight: "700", color: colors.text },
});
