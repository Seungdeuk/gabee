import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, Share, StyleSheet, Text, View } from "react-native";

import UserAvatar from "@/shared/components/UserAvatar";
import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import SectionTitle from "@/shared/components/SectionTitle";
import Tag from "@/shared/components/Tag";
import { colors, font } from "@/theme";

import { approveJoinRequest, reissueInvite, rejectJoinRequest, revokeInvite } from "../api";
import FamilyFrame from "../components/FamilyFrame";
import Notice from "../components/Notice";
import { expiryText, familyErrorMessage, roleLabel } from "../messages";
import { relationText, shownName } from "../relations";
import useFamilyState from "../useFamilyState";

const POLL_MS = 8000;
const ROLE_TEXT = { parent: "부모", child: "자녀", other: "기타" };

/**
 * 내 가족 그룹. 그룹이 없으면 만들기/참여, 승인 대기 중이면 대기 화면으로 안내하고,
 * 구성원이면 가족 목록을 보여 준다. 가족 관리자(소유자·관리자)에게는 초대 코드 발급·공유·폐기와, 들어온 가입 요청이 바로 보이고 여기서 승인·거절할 수 있다.
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

  const share = async (code) => {
    try {
      await Share.share({ message: `가비 가족 초대 코드: ${code}\n가비 앱에서 "초대 코드로 참여"에 입력해 주세요. 24시간 안에 한 번만 쓸 수 있어요.` });
    } catch {
      setError("공유하지 못했어요. 코드를 길게 눌러 복사해 보세요");
    }
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
        {family.request?.status === "rejected" ? (
          <Notice tone="error" text={`${family.request.group_name} 가입 요청이 거절됐어요. 새 초대 코드로 다시 요청할 수 있어요`} />
        ) : null}
        <Button label="가족 만들기" onPress={() => router.push("/family-create")} testID="family-new" />
        <Button label="초대 코드로 참여" variant="secondary" onPress={() => router.push("/family-join")} testID="family-join" />
      </FamilyFrame>
    );
  }

  const { group } = family;
  const expiry = expiryText(group.invite_expires_at);
  return (
    <FamilyFrame title={group.name} subtitle={`구성원 ${group.members.length}명 · 내 권한 ${roleLabel(group.my_role)}`}>
      <Notice tone="error" text={error} />
      <Notice tone="success" text={notice} />
      <SectionTitle title="가족" />
      <Card tone="white">
        {group.members.map((m) => (
          <Pressable key={m.id} style={styles.member} onPress={() => router.push({ pathname: "/family-member", params: { userId: m.id } })} accessibilityRole="button" accessibilityLabel={`${shownName(m, family.nicknames[m.id])} 보기`} testID={`member-${m.id}`}>
            <UserAvatar name={shownName(m, family.nicknames[m.id])} userId={m.id} photoUrl={m.photo_url} />
            <View style={styles.text}>
              <Text style={styles.name}>{shownName(m, family.nicknames[m.id])}</Text>
              {relationText(m) ? <Text style={styles.relation}>{relationText(m)}</Text> : null}
            </View>
            <Tag label={roleLabel(m.group_role)} tone={m.group_role === "member" ? "gray" : "blue"} />
          </Pressable>
        ))}
      </Card>
      <Button label="내 프로필 (이름·가족 관계)" variant="secondary" onPress={() => router.push("/family-profile")} testID="open-profile" />

      {family.isManager ? (
        <>
          <SectionTitle title="가족 초대" />
          <Card tone="white">
            {group.invite_code ? (
              <>
                <Text style={styles.code} selectable accessibilityLabel="초대 코드" testID="invite-code">
                  {group.invite_code}
                </Text>
                <Text style={styles.sub}>{expiry ? `${expiry} · ` : ""}한 번만 쓸 수 있어요. 코드를 받은 사람은 관리자의 승인을 거쳐 들어와요.</Text>
                <Button label="초대 코드 공유" onPress={() => share(group.invite_code)} disabled={busy} testID="invite-share" />
                <View style={styles.buttons}>
                  <View style={styles.grow}>
                    <Button label="새 코드 만들기" small variant="secondary" onPress={() => run(reissueInvite, "새 초대 코드를 만들었어요. 이전 코드는 쓸 수 없어요")} disabled={busy} testID="invite-reissue" />
                  </View>
                  <View style={styles.grow}>
                    <Button label="코드 폐기" small variant="secondary" onPress={() => run(revokeInvite, "초대 코드를 폐기했어요")} disabled={busy} testID="invite-revoke" />
                  </View>
                </View>
              </>
            ) : (
              <>
                <Text style={styles.sub}>지금 쓸 수 있는 초대 코드가 없어요. 새 코드를 만들어 가족에게 알려 주세요.</Text>
                <Button label="초대 코드 만들기" onPress={() => run(reissueInvite, "초대 코드를 만들었어요")} disabled={busy} testID="invite-reissue" />
              </>
            )}
          </Card>
          <SectionTitle title="가입 요청" />
          <Card tone={family.pendingCount > 0 ? "orange" : "white"}>
            {family.pendingCount === 0 ? (
              <Text style={styles.sub}>기다리는 가입 요청이 없어요. 요청이 들어오면 여기에 바로 나타나요.</Text>
            ) : (
              <>
                <Text style={styles.sub}>승인을 기다리는 요청이 {family.pendingCount}건 있어요</Text>
                {family.pendingRequests.map((row) => (
                  <View key={row.id} style={styles.request}>
                    <View style={styles.requestWho}>
                      <UserAvatar name={row.user_name} userId={row.user_id} size={36} />
                      <View style={styles.text}>
                        <Text style={styles.name}>{row.user_name}</Text>
                        <Text style={styles.relation}>{ROLE_TEXT[row.user_role] ?? "구성원"} · 참여 요청</Text>
                      </View>
                    </View>
                    <View style={styles.buttons}>
                      <View style={styles.grow}>
                        <Button label="승인" small onPress={() => run(() => approveJoinRequest(row.id), `${row.user_name}님을 가족으로 받았어요`)} disabled={busy} testID={`approve-${row.id}`} />
                      </View>
                      <View style={styles.grow}>
                        <Button label="거절" small variant="secondary" onPress={() => run(() => rejectJoinRequest(row.id), `${row.user_name}님의 요청을 거절했어요`)} disabled={busy} testID={`reject-${row.id}`} />
                      </View>
                    </View>
                  </View>
                ))}
              </>
            )}
            <Button label="가입 요청 화면 열기" variant="secondary" small onPress={() => router.push("/family-requests")} testID="open-requests" />
          </Card>
        </>
      ) : null}
    </FamilyFrame>
  );
}

const styles = StyleSheet.create({
  title: { ...font.title, color: colors.text },
  sub: { ...font.body, color: colors.textSub },
  member: { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 8 },
  text: { flex: 1 },
  name: { ...font.bodyStrong, color: colors.text },
  relation: { ...font.caption, color: colors.textMuted },
  code: { ...font.h1, color: colors.text, letterSpacing: 2, textAlign: "center", paddingVertical: 8 },
  buttons: { flexDirection: "row", gap: 8 },
  request: { gap: 8, paddingVertical: 8 },
  requestWho: { flexDirection: "row", alignItems: "center", gap: 12 },
  grow: { flex: 1 },
});
