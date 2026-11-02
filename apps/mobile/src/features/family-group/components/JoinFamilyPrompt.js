import { useRouter } from "expo-router";
import { StyleSheet, View } from "react-native";

import Button from "@/shared/components/Button";
import { spacing } from "@/theme";

import { joinPromptVisible } from "../joinPrompt";
import useFamilyState from "../useFamilyState";

/** 홈 인사말 아래 버튼 둘: 가족 그룹이 없는 사람이 바로 가족을 만들거나 받은 코드로 참여하러 갈 수 있게 한다. 가족이 있으면 아무것도 그리지 않는다. */
export default function JoinFamilyPrompt() {
  const router = useRouter();
  const family = useFamilyState();
  if (!joinPromptVisible(family.status)) return null;
  return (
    <View style={styles.row}>
      <Button label="가족 만들기" small icon="add-circle-outline" onPress={() => router.push("/family-create")} testID="home-family-create" />
      <Button label="초대 코드로 참여" small variant="secondary" icon="people-outline" onPress={() => router.push("/family-join")} testID="home-family-join" />
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", gap: spacing.sm, justifyContent: "center" },
});
