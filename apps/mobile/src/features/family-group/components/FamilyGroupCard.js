import { useRouter } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import Avatar from "@/shared/components/Avatar";
import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Tag from "@/shared/components/Tag";
import { colors, font } from "@/theme";

import { roleLabel } from "../messages";
import useFamilyState from "../useFamilyState";

/** 기타 탭의 가족 그룹 카드: 내 가족 요약과 가족 화면으로 가는 버튼. 가족 관리자에게는 기다리는 가입 요청 수도 보인다. */
export default function FamilyGroupCard() {
  const router = useRouter();
  const family = useFamilyState({ pollMs: 10000 }); // 가입 요청 수·승인 결과를 몇 초마다 새로 확인한다

  if (family.status === "loading") {
    return (
      <Card tone="white">
        <Text style={styles.sub}>가족 그룹을 불러오고 있어요...</Text>
      </Card>
    );
  }
  if (family.status === "error") {
    return (
      <Card tone="orange">
        <Text style={styles.title}>가족 그룹을 불러오지 못했어요</Text>
        <Text style={styles.sub}>{family.error}</Text>
        <Button label="다시 시도" small variant="secondary" onPress={family.reload} />
      </Card>
    );
  }
  if (family.status === "pending") {
    return (
      <Card tone="blue">
        <Tag label="승인 대기 중" tone="orange" />
        <Text style={styles.title}>{family.request.group_name}</Text>
        <Text style={styles.sub}>가족 관리자의 승인을 기다리고 있어요.</Text>
        <Button label="승인 상태 보기" small onPress={() => router.push("/family-pending")} />
      </Card>
    );
  }
  if (family.status === "none") {
    return (
      <Card tone="white">
        <Text style={styles.title}>아직 가족 그룹이 없어요</Text>
        <Text style={styles.sub}>가족을 만들거나, 받은 초대 코드로 참여해 보세요.</Text>
        <View style={styles.row}>
          <Button label="가족 만들기" small onPress={() => router.push("/family-create")} />
          <Button label="초대 코드로 참여" small variant="secondary" onPress={() => router.push("/family-join")} />
        </View>
      </Card>
    );
  }
  const { group } = family;
  return (
    <Card tone="white">
      <View style={styles.row}>
        <Text style={styles.title}>{group.name}</Text>
        <Tag label={roleLabel(group.my_role)} tone={family.isManager ? "blue" : "gray"} />
      </View>
      <View style={styles.row}>
        {group.members.slice(0, 5).map((m) => (
          <Avatar key={m.id} name={m.name} userId={m.id} size={36} />
        ))}
        <Text style={styles.sub}>구성원 {group.members.length}명</Text>
      </View>
      {family.pendingCount > 0 ? <Tag label={`가입 요청 ${family.pendingCount}건`} tone="orange" /> : null}
      <Button label="가족 그룹 열기" small onPress={() => router.push("/family")} testID="open-family" />
    </Card>
  );
}

const styles = StyleSheet.create({
  title: { ...font.cardTitle, color: colors.text },
  sub: { ...font.body, color: colors.textSub },
  row: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 8 },
});
