import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import Button from "@/shared/components/Button";
import IconButton from "@/shared/components/IconButton";
import Tag from "@/shared/components/Tag";
import { colors, font, radius, spacing } from "@/theme";

import { briefWhen } from "../togetherUtils";
import useFamilyTogether from "../useFamilyTogether";

/**
 * 서랍 "가족 할 일": 일정 탭의 **할 일**과 **함께하기**를 날짜 순으로 간소화해서 보여 준다(보기만 한다). 줄을 누르면 일정 탭의 그 화면(할 일 상세·받은 함께하기·보낸 함께하기)으로 간다.
 * 채팅에서 "함께하기로 보내기"를 하면 여기와 일정 탭에 나타난다. 화면이 보일 때와 당겨서 새로고침할 때만 불러온다.
 */
export default function FamilyTogetherScreen() {
  const router = useRouter();
  const brief = useFamilyTogether();
  const back = () => (router.canGoBack() ? router.back() : router.replace("/family-chat"));

  let body;
  if (brief.status === "loading") {
    body = (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} accessibilityLabel="불러오는 중" />
      </View>
    );
  } else if (brief.status === "none") {
    body = (
      <View style={styles.center}>
        <Text style={styles.emptyTitle}>가족을 먼저 만들어 주세요</Text>
        <Button label="가족 만들기 · 참여하기" onPress={() => router.push("/family")} />
      </View>
    );
  } else if (brief.status === "error") {
    body = (
      <View style={styles.center}>
        <Text style={styles.emptyText}>{brief.error}</Text>
        <Button label="다시 시도" onPress={brief.reload} />
      </View>
    );
  } else {
    body = (
      <ScrollView contentContainerStyle={styles.content} refreshControl={<RefreshControl refreshing={brief.refreshing} onRefresh={brief.refresh} tintColor={colors.accent} />}>
        {brief.items.length === 0 ? (
          <View style={styles.empty}>
            <Text style={styles.emptyTitle}>지금 챙길 일이 없어요</Text>
            <Text style={styles.emptyText}>채팅에서 할 일을 함께하기로 보내거나, 일정 탭에서 추가해 보세요.</Text>
          </View>
        ) : (
          brief.items.map((row) => (
            <Pressable
              key={row.key}
              onPress={() => router.push(row.route)}
              accessibilityRole="button"
              accessibilityLabel={`${row.tag}: ${row.title}, ${briefWhen(row)}. 누르면 일정 탭에서 열어요`}
              style={({ pressed }) => [styles.row, pressed && styles.pressed]}
            >
              <View style={styles.rowBody}>
                <Text style={styles.title} numberOfLines={2}>
                  {row.title}
                </Text>
                <Text style={styles.meta}>{briefWhen(row)}</Text>
                <Tag label={row.tag} tone={row.type === "request" ? "orange" : "gray"} />
              </View>
              <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
            </Pressable>
          ))
        )}
        <Button label="일정 탭에서 모두 보기" variant="secondary" small onPress={() => router.push("/schedule")} />
      </ScrollView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.bar}>
        <IconButton name="chevron-back" label="뒤로" onPress={back} />
        <Text style={styles.barTitle} accessibilityRole="header">
          가족 할 일
        </Text>
      </View>
      {body}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  bar: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, borderBottomWidth: 1, borderBottomColor: colors.divider },
  barTitle: { ...font.cardTitle, color: colors.text, flex: 1 },
  content: { paddingHorizontal: spacing.lg, paddingVertical: spacing.md, gap: spacing.sm },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md, padding: spacing.xxl },
  empty: { alignItems: "center", gap: spacing.sm, paddingVertical: spacing.xxl },
  emptyTitle: { ...font.cardTitle, color: colors.text, textAlign: "center" },
  emptyText: { ...font.body, color: colors.textSub, textAlign: "center" },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.card, borderRadius: radius.card, borderWidth: 1, borderColor: colors.border, padding: spacing.lg },
  pressed: { backgroundColor: colors.surface },
  rowBody: { flex: 1, gap: spacing.xs },
  title: { ...font.bodyStrong, color: colors.text },
  meta: { ...font.caption, color: colors.textMuted },
});
