import * as Linking from "expo-linking";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Share, StyleSheet, Text } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Tag from "@/shared/components/Tag";
import { colors, font } from "@/theme";

import FamilyFrame from "../components/FamilyFrame";
import InviteSection from "../components/InviteSection";
import JoinRequestsSection from "../components/JoinRequestsSection";
import Notice from "../components/Notice";
import { inviteLink, inviteMessage } from "../inviteLink";
import { familyErrorMessage, managersOf } from "../messages";
import useFamilyState from "../useFamilyState";

const POLL_MS = 8000;

/**
 * 가족 초대: 새 구성원을 들이는 화면. 가족 관리자(소유자·관리자)는 초대 코드를 만들고 공유하고 가입 요청을 승인·거절한다.
 * 일반 구성원에게는 초대가 관리자만 할 수 있다는 안내와 관리자 이름을 보여 주고, 가족이 없으면 만들기·참여로, 승인 대기 중이면 대기 화면으로 안내한다.
 * 구성원 확인·내 프로필·가족 나가기는 "우리 가족" 화면(/family)에 있다.
 * @returns {import("react").ReactElement}
 */
export default function FamilyInviteScreen() {
  const router = useRouter();
  const family = useFamilyState({ pollMs: POLL_MS }); // 가입 요청이 들어오는 것을 바로 보여 주려고 몇 초마다 확인한다
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const linkFor = (code) => inviteLink(code, Linking.createURL("family-join", { queryParams: { code } }));

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

  const share = async (code) => {
    try {
      await Share.share({ message: inviteMessage(code, linkFor(code)) });
    } catch {
      setError("공유하지 못했어요. 코드를 길게 눌러 복사해 보세요");
    }
  };

  if (family.status === "loading") {
    return (
      <FamilyFrame title="가족 초대">
        <Notice text="가족 그룹을 불러오고 있어요..." />
      </FamilyFrame>
    );
  }
  if (family.status === "error") {
    return (
      <FamilyFrame title="가족 초대">
        <Notice tone="error" text={family.error} />
        <Button label="다시 시도" onPress={family.reload} />
      </FamilyFrame>
    );
  }
  if (family.status === "pending") {
    return (
      <FamilyFrame title="가족 초대">
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
      <FamilyFrame title="가족 초대" subtitle="가족을 초대하려면 먼저 가족이 필요해요">
        <Button label="가족 만들기" icon="add-circle-outline" onPress={() => router.push("/family-create")} testID="family-new" />
        <Button label="초대 코드로 참여" variant="secondary" icon="people-outline" onPress={() => router.push("/family-join")} testID="family-join" />
      </FamilyFrame>
    );
  }

  const { group } = family;
  if (!family.isManager) {
    const names = managersOf(group.members).map((m) => m.display_name || m.name);
    return (
      <FamilyFrame title="가족 초대" subtitle="새 구성원은 가족 관리자가 초대해요">
        <Card tone="white">
          <Text style={styles.title}>초대는 가족 관리자만 할 수 있어요</Text>
          <Text style={styles.sub}>
            {names.length > 0 ? `${names.join(", ")}님에게 초대 코드를 요청해 보세요.` : "가족 소유자나 관리자에게 초대 코드를 요청해 보세요."}
          </Text>
        </Card>
        <Button label="우리 가족 보기" variant="secondary" onPress={() => router.push("/family")} testID="open-family" />
      </FamilyFrame>
    );
  }
  return (
    <FamilyFrame title="가족 초대" subtitle="초대 코드를 공유하고 가입 요청을 확인해요">
      <Notice tone="error" text={error} />
      <Notice tone="success" text={notice} />
      <InviteSection group={group} busy={busy} run={run} onShare={share} linkFor={linkFor} />
      <JoinRequestsSection pendingRequests={family.pendingRequests} pendingCount={family.pendingCount} busy={busy} run={run} />
    </FamilyFrame>
  );
}

const styles = StyleSheet.create({
  title: { ...font.title, color: colors.text },
  sub: { ...font.body, color: colors.textSub },
});
