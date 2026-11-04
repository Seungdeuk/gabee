import { useRouter } from "expo-router";
import { useState } from "react";
import { StyleSheet, Text } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Tag from "@/shared/components/Tag";
import { colors, font } from "@/theme";

import { leaveFamily } from "../api";
import FamilyFrame from "../components/FamilyFrame";
import FamilyHeader from "../components/FamilyHeader";
import FamilyNameEditor from "../components/FamilyNameEditor";
import LeaveFamilySection from "../components/LeaveFamilySection";
import Notice from "../components/Notice";
import { familyErrorMessage, roleLabel } from "../messages";
import useFamilyState from "../useFamilyState";

const POLL_MS = 8000;

/**
 * 우리 가족. 그룹이 없으면 만들기/참여, 승인 대기 중이면 대기 화면으로 안내한다.
 * 구성원이면 위쪽에 가족 이름·구성원 프로필·내 역할을, 아래쪽에 가족 나가기를 보여 준다. 가족 이름은 관리자에게만 바꾸는 칸이 보인다. 초대 코드·가입 요청은 "가족 초대" 화면(/family-invite)에 있고, 관리자에게는 거기로 가는 버튼이 보인다.
 * @returns {import("react").ReactElement}
 */
export default function FamilyScreen() {
  const router = useRouter();
  const family = useFamilyState({ pollMs: POLL_MS }); // 가입 요청이 들어오거나 승인되는 것을 바로 보여 주려고 몇 초마다 확인한다
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const run = async (job, done) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await job();
      setNotice(done);
    } catch (e) {
      setError(familyErrorMessage(e));
    }
    await family.reload();
    setBusy(false);
  };

  if (family.status === "loading") {
    return (
      <FamilyFrame title="가족 그룹">
        <Notice text="가족 그룹을 불러오고 있어요..." />
      </FamilyFrame>
    );
  }
  if (family.status === "error") {
    return (
      <FamilyFrame title="가족 그룹">
        <Notice tone="error" text={family.error} />
        <Button label="다시 시도" onPress={family.reload} />
      </FamilyFrame>
    );
  }
  if (family.status === "pending") {
    return (
      <FamilyFrame title="가족 그룹">
        <Card tone="blue">
          <Tag label="승인 대기 중" tone="orange" />
          <Text style={styles.title}>{family.request.group_name}</Text>
          <Text style={styles.sub}>가족 관리자의 승인을 기다리고 있어요.</Text>
        </Card>
        <Button label="승인 상태 보기" onPress={() => router.push("/family-pending")} />
      </FamilyFrame>
    );
  }
  if (family.status === "none") {
    return (
      <FamilyFrame title="가족 그룹" subtitle="가족을 만들거나 초대 코드로 참여해요">
        <Notice tone="success" text={notice} />
        {family.request?.status === "rejected" ? (
          <Notice tone="error" text={`${family.request.group_name} 가입 요청이 거절됐어요. 새 초대 코드로 다시 요청할 수 있어요`} />
        ) : null}
        <Button label="가족 만들기" icon="add-circle-outline" onPress={() => router.push("/family-create")} testID="family-new" />
        <Button label="초대 코드로 참여" variant="secondary" icon="people-outline" onPress={() => router.push("/family-join")} testID="family-join" />
      </FamilyFrame>
    );
  }

  const { group } = family;
  /**
   * 가족을 나간다. 성공하면 가족 정보를 다시 읽어 "가족 없음" 화면으로 바뀌고, 안내 문구가 거기서 보인다.
   * @returns {Promise<void>}
   */
  const leave = () => run(leaveFamily, "가족을 나갔어요. 다시 들어오려면 초대 코드가 필요해요");
  return (
    <FamilyFrame title="우리 가족">
      <Notice tone="error" text={error} />
      <Notice tone="success" text={notice} />
      <FamilyHeader
        name={group.name}
        memberCount={group.members.length}
        roleText={roleLabel(group.my_role)}
        members={group.members}
        nicknames={family.nicknames}
        isOwner={group.my_role === "owner"}
        onPressMember={(m) => router.push({ pathname: "/family-member", params: { userId: m.id } })}
      />
      {family.isManager ? <FamilyNameEditor name={group.name} onRenamed={family.reload} /> : null}
      <Button label="내 프로필 (이름·가족 관계)" variant="secondary" onPress={() => router.push("/family-profile")} testID="open-profile" />

      {family.isManager ? (
        <Button
          label={family.pendingCount > 0 ? `가족 초대 · 가입 요청 ${family.pendingCount}건` : "가족 초대 · 가입 요청"}
          variant="secondary"
          icon="person-add-outline"
          onPress={() => router.push("/family-invite")}
          testID="open-invite"
        />
      ) : null}

      <LeaveFamilySection isOwner={group.my_role === "owner"} onLeave={leave} busy={busy} />
    </FamilyFrame>
  );
}

const styles = StyleSheet.create({
  title: { ...font.title, color: colors.text },
  sub: { ...font.body, color: colors.textSub },
});
