import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import UserAvatar from "@/shared/components/UserAvatar";
import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import SectionTitle from "@/shared/components/SectionTitle";
import Tag from "@/shared/components/Tag";
import { colors, font } from "@/theme";

import { setMemberRole, setNickname } from "../api";
import FamilyFrame from "../components/FamilyFrame";
import Notice from "../components/Notice";
import { familyErrorMessage, roleLabel } from "../messages";
import { relationText, shownName } from "../relations";
import useFamilyState from "../useFamilyState";

/**
 * 가족 구성원 한 명: 이름·관계·권한, 내가 붙이는 별명과 메모(나에게만 보임),
 * 그리고 가족 소유자에게만 보이는 관리자 지정·해제.
 */
export default function FamilyMemberScreen() {
  const router = useRouter();
  const { userId } = useLocalSearchParams();
  const family = useFamilyState();
  const [nick, setNick] = useState("");
  const [memo, setMemo] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const member = family.group?.members.find((m) => m.id === userId);

  useEffect(() => {
    if (family.status !== "member" || loaded) return;
    const saved = family.nicknames[userId];
    setNick(saved?.nickname ?? "");
    setMemo(saved?.memo ?? "");
    setLoaded(true);
  }, [family.status, family.nicknames, userId, loaded]);

  const run = async (job, done) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await job();
      setNotice(done);
      await family.reload();
    } catch (e) {
      setError(familyErrorMessage(e));
    }
    setBusy(false);
  };

  if (family.status === "loading") {
    return (
      <FamilyFrame title="가족 구성원">
        <Notice text="불러오고 있어요..." />
      </FamilyFrame>
    );
  }
  if (family.status !== "member" || !member) {
    return (
      <FamilyFrame title="가족 구성원">
        <Notice tone={family.status === "error" ? "error" : "info"} text={family.status === "error" ? family.error : "이 구성원을 찾을 수 없어요"} />
        <Button label="가족 그룹으로" onPress={() => router.replace("/family")} />
      </FamilyFrame>
    );
  }

  const isMe = member.id === family.group.my_id;
  const isOwner = family.group.my_role === "owner";
  const relation = relationText(member);
  return (
    <FamilyFrame title={shownName(member, family.nicknames[member.id])} subtitle={[relation, roleLabel(member.group_role)].filter(Boolean).join(" · ")}>
      <Notice tone="error" text={error} />
      <Notice tone="success" text={notice} />
      <Card tone="white">
        <View style={styles.who}>
          <UserAvatar name={shownName(member, family.nicknames[member.id])} userId={member.id} photoUrl={member.photo_url} size={52} />
          <View style={styles.text}>
            <Text style={styles.name}>{member.display_name || member.name}</Text>
            {member.display_name ? <Text style={styles.sub}>계정 이름 {member.name}</Text> : null}
          </View>
          <Tag label={roleLabel(member.group_role)} tone={member.group_role === "member" ? "gray" : "blue"} />
        </View>
        {relation ? <Text style={styles.sub}>가족 관계 · {relation}</Text> : null}
      </Card>

      {isMe ? (
        <Button label="내 프로필 수정" onPress={() => router.push("/family-profile")} testID="member-edit-profile" />
      ) : (
        <>
          <SectionTitle title="나만 보는 별명" />
          <Card tone="white">
            <Text style={styles.sub}>내가 이 사람을 부르는 이름이에요. 다른 가족에게는 보이지 않아요.</Text>
            <Field label="별명" value={nick} onChangeText={setNick} maxLength={40} placeholder="예: 우리 엄마" testID="nickname" />
            <Field label="메모" value={memo} onChangeText={setMemo} maxLength={1000} placeholder="나만 보는 메모" testID="memo" />
            <Button label={busy ? "저장 중..." : "별명 저장"} onPress={() => run(() => setNickname(member.id, { nickname: nick.trim(), memo: memo.trim() }), nick.trim() || memo.trim() ? "저장했어요" : "별명을 지웠어요")} disabled={busy} testID="nickname-save" />
          </Card>
        </>
      )}

      {isOwner && !isMe && member.group_role !== "owner" ? (
        <>
          <SectionTitle title="가족 관리자" />
          <Card tone="white">
            <Text style={styles.sub}>관리자는 초대 코드를 만들고 가입 요청을 승인하거나 거절할 수 있어요. 소유자만 지정할 수 있어요.</Text>
            {member.group_role === "admin" ? (
              <Button label="관리자에서 해제" variant="secondary" onPress={() => run(() => setMemberRole(member.id, "member"), "관리자에서 해제했어요")} disabled={busy} testID="role-member" />
            ) : (
              <Button label="관리자로 지정" onPress={() => run(() => setMemberRole(member.id, "admin"), "관리자로 지정했어요")} disabled={busy} testID="role-admin" />
            )}
          </Card>
        </>
      ) : null}
    </FamilyFrame>
  );
}

const styles = StyleSheet.create({
  who: { flexDirection: "row", alignItems: "center", gap: 12 },
  text: { flex: 1, gap: 2 },
  name: { ...font.cardTitle, color: colors.text },
  sub: { ...font.caption, color: colors.textMuted },
});
