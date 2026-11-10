import { useRouter } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import SectionTitle from "@/shared/components/SectionTitle";
import UserAvatar from "@/shared/components/UserAvatar";
import { colors, font } from "@/theme";

import { approveJoinRequest, rejectJoinRequest } from "../api";

export const ROLE_TEXT = { parent: "부모", child: "자녀", other: "기타" };

/**
 * 가족 관리자에게만 보이는 '가입 요청' 구역. 대기 중인 요청을 승인·거절하고 가입 요청 화면으로 이동할 수 있다.
 * busy/error/notice 처리는 부모의 run 이 맡는다.
 * @param {{
 *   pendingRequests: Array<object>,
 *   pendingCount: number,
 *   busy: boolean,
 *   run: (job: () => Promise<unknown>, doneMessage: string) => Promise<void>,
 * }} props pendingRequests: 대기 중인 요청 목록, pendingCount: 대기 건수, busy: 요청 중 여부, run: 부모의 작업 실행 도우미
 * @returns {JSX.Element} 가입 요청 구역
 */
export default function JoinRequestsSection({ pendingRequests, pendingCount, busy, run }) {
  const router = useRouter();
  return (
    <>
      <SectionTitle title="가입 요청" />
      <Card tone={pendingCount > 0 ? "orange" : "white"}>
        {pendingCount === 0 ? (
          <Text style={styles.sub}>기다리는 가입 요청이 없어요. 요청이 들어오면 여기에 바로 나타나요.</Text>
        ) : (
          <>
            <Text style={styles.sub}>승인을 기다리는 요청이 {pendingCount}건 있어요</Text>
            {pendingRequests.map((row) => (
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
  );
}

const styles = StyleSheet.create({
  sub: { ...font.body, color: colors.textSub },
  text: { flex: 1 },
  name: { ...font.bodyStrong, color: colors.text },
  relation: { ...font.caption, color: colors.textMuted },
  buttons: { flexDirection: "row", gap: 8 },
  request: { gap: 8, paddingVertical: 8 },
  requestWho: { flexDirection: "row", alignItems: "center", gap: 12 },
  grow: { flex: 1 },
});
