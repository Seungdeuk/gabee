import { useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { StyleSheet, Text } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Tag from "@/shared/components/Tag";
import { colors, font } from "@/theme";

import { cancelJoinRequest, getMyJoinRequest } from "../api";
import FamilyFrame from "../components/FamilyFrame";
import Notice from "../components/Notice";
import { familyErrorMessage } from "../messages";

const POLL_MS = 8000;

/**
 * 가입 승인 대기. 가족 관리자가 승인하면 가족 화면으로, 거절하면 안내를 보여 준다.
 * 화면이 열려 있는 동안 몇 초마다 상태를 확인하고, 직접 새로고침하거나 요청을 취소할 수도 있다.
 */
export default function JoinPendingScreen() {
  const router = useRouter();
  const [request, setRequest] = useState(undefined); // undefined: 불러오는 중, null: 요청 없음
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const next = await getMyJoinRequest();
      if (!alive.current) return;
      setRequest(next);
      setError("");
      if (next?.status === "approved") router.replace("/family");
    } catch (e) {
      if (alive.current) setError(familyErrorMessage(e));
    }
  }, [router]);

  useEffect(() => {
    alive.current = true;
    refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => {
      alive.current = false;
      clearInterval(timer);
    };
  }, [refresh]);

  const cancel = async () => {
    setBusy(true);
    try {
      await cancelJoinRequest(request.id);
    } catch (e) {
      setError(familyErrorMessage(e));
    }
    await refresh();
    if (alive.current) setBusy(false);
  };

  const status = request?.status;
  return (
    <FamilyFrame title="가입 승인 대기" subtitle="가족 관리자가 승인하면 가족 그룹에 들어가요">
      <Notice tone="error" text={error} />
      {request === undefined ? (
        <Notice text="요청 상태를 불러오고 있어요..." />
      ) : status === "pending" ? (
        <>
          <Card tone="blue">
            <Tag label="승인 대기 중" tone="orange" />
            <Text style={styles.title}>{request.group_name}</Text>
            <Text style={styles.sub}>참여 요청을 보냈어요. 가족 관리자에게 승인을 부탁해 주세요. 승인되면 이 화면이 자동으로 넘어가요.</Text>
          </Card>
          <Button label="지금 확인하기" variant="secondary" onPress={refresh} disabled={busy} testID="pending-refresh" />
          <Button label={busy ? "취소하는 중..." : "요청 취소"} variant="secondary" onPress={cancel} disabled={busy} testID="pending-cancel" />
        </>
      ) : status === "rejected" ? (
        <>
          <Card tone="orange">
            <Tag label="거절됨" tone="red" />
            <Text style={styles.title}>{request.group_name}</Text>
            <Text style={styles.sub}>가족 관리자가 이번 요청을 받아들이지 않았어요. 가족에게 확인한 뒤 새 초대 코드로 다시 요청할 수 있어요.</Text>
          </Card>
          <Button label="다른 초대 코드 입력" onPress={() => router.replace("/family-join")} />
        </>
      ) : (
        <>
          <Notice text={status === "cancelled" ? "가입 요청을 취소했어요" : "대기 중인 가입 요청이 없어요"} />
          <Button label="초대 코드로 참여" onPress={() => router.replace("/family-join")} />
        </>
      )}
    </FamilyFrame>
  );
}

const styles = StyleSheet.create({
  title: { ...font.title, color: colors.text },
  sub: { ...font.body, color: colors.textSub },
});
