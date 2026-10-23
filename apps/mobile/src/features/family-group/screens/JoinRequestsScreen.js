import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Avatar from "@/shared/components/Avatar";
import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import { colors, font } from "@/theme";

import { approveJoinRequest, listJoinRequests, rejectJoinRequest } from "../api";
import FamilyFrame from "../components/FamilyFrame";
import Notice from "../components/Notice";
import { familyErrorMessage } from "../messages";

const ROLE_TEXT = { parent: "부모", child: "자녀", other: "기타" };

/**
 * 가족 관리자(소유자·관리자)의 가입 요청 목록. 승인하면 구성원이 되고, 거절하면 요청이 닫힌다.
 * 구성원은 이 화면의 내용을 볼 수 없고(서버가 403), 이미 다른 관리자가 처리한 요청은 목록을 새로 불러와 보여 준다.
 */
export default function JoinRequestsScreen() {
  const router = useRouter();
  const [rows, setRows] = useState(null); // null: 불러오는 중
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busyId, setBusyId] = useState("");

  const load = useCallback(async () => {
    try {
      setRows(await listJoinRequests());
      setError("");
    } catch (e) {
      setRows([]);
      setError(familyErrorMessage(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const decide = async (row, approve) => {
    setBusyId(row.id);
    setError("");
    setNotice("");
    try {
      await (approve ? approveJoinRequest(row.id) : rejectJoinRequest(row.id));
      setNotice(approve ? `${row.user_name}님을 가족으로 받았어요` : `${row.user_name}님의 요청을 거절했어요`);
    } catch (e) {
      setError(familyErrorMessage(e));
    }
    await load();
    setBusyId("");
  };

  return (
    <FamilyFrame title="가입 요청" subtitle="초대 코드로 참여를 요청한 사람이에요">
      <Notice tone="error" text={error} />
      <Notice tone="success" text={notice} />
      {rows === null ? (
        <Notice text="가입 요청을 불러오고 있어요..." />
      ) : rows.length === 0 ? (
        <Card tone="white">
          <Text style={styles.empty}>기다리는 가입 요청이 없어요</Text>
        </Card>
      ) : (
        rows.map((row) => (
          <Card key={row.id} tone="white">
            <View style={styles.who}>
              <Avatar name={row.user_name} />
              <View style={styles.text}>
                <Text style={styles.name}>{row.user_name}</Text>
                <Text style={styles.sub}>{ROLE_TEXT[row.user_role] ?? "구성원"} · 참여 요청</Text>
              </View>
            </View>
            <View style={styles.buttons}>
              <View style={styles.grow}>
                <Button label="승인" small onPress={() => decide(row, true)} disabled={busyId !== ""} testID={`approve-${row.id}`} />
              </View>
              <View style={styles.grow}>
                <Button label="거절" small variant="secondary" onPress={() => decide(row, false)} disabled={busyId !== ""} testID={`reject-${row.id}`} />
              </View>
            </View>
          </Card>
        ))
      )}
      <Button label="가족 그룹으로" variant="secondary" onPress={() => router.replace("/family")} />
    </FamilyFrame>
  );
}

const styles = StyleSheet.create({
  who: { flexDirection: "row", alignItems: "center", gap: 12 },
  text: { flex: 1, gap: 2 },
  name: { ...font.bodyStrong, color: colors.text },
  sub: { ...font.caption, color: colors.textMuted },
  empty: { ...font.body, color: colors.textSub },
  buttons: { flexDirection: "row", gap: 8, marginTop: 8 },
  grow: { flex: 1 },
});
