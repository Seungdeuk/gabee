import { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import { colors, font } from "@/theme";

import { deleteMyLocation, simulateExit } from "../api";
import { isBackgroundRunning } from "../backgroundControl";
import { describeLastSent, describePermission } from "../diagnostics";
import { readPermissions, requestForeground, seedZoneNearHere } from "../sharing";
import BackgroundCard from "./BackgroundCard";

const ZONE_MIN_POINTS = 5; // 서버가 활동 구역을 만드는 최소 위치 수(서버 location/service.py 와 같다)

/**
 * '설정' 하위 탭: 앱을 꺼도 공유(동의), 상태 점검, 시연 도구(접어 둠), 공유 끄기·기록 지우기.
 * @param {{ me: import("../api").MyLocation, members: import("../api").MemberLocation[], busy: boolean, refreshKey: number, run: (job: () => Promise<unknown>, okText?: string) => void, notify: (text: string, isError?: boolean) => void, onChanged: () => void, onWithdraw: () => void }} props
 */
export default function SettingsTab({ me, members, busy, refreshKey, run, notify, onChanged, onWithdraw }) {
  const [demoOpen, setDemoOpen] = useState(false);
  const mine = members.find((m) => m.is_me);
  return (
    <View style={styles.wrap}>
      <BackgroundCard me={me} notify={notify} onChanged={onChanged} />
      <HealthCard me={me} lastSeen={mine?.recorded_at} refreshKey={refreshKey} />

      <Card tone="white">
        <Text style={styles.title}>시연 도구</Text>
        {demoOpen ? (
          <>
            <Text style={styles.caption}>실제로 걸어 나가지 않아도 흐름을 보여 줄 수 있어요. 내 위치만 써요.</Text>
            <Button
              label="활동 구역 빨리 만들기"
              variant="secondary"
              small
              disabled={busy || me.paused}
              onPress={() =>
                run(async () => {
                  if (!(await requestForeground())) throw new Error("위치 권한이 필요해요");
                  await seedZoneNearHere(ZONE_MIN_POINTS);
                }, "활동 구역을 만들었어요")
              }
            />
            <Button
              label="구역 이탈 알림 시연"
              variant="secondary"
              small
              disabled={busy || !me.zone}
              onPress={() =>
                run(async () => {
                  const r = await simulateExit();
                  notify(r.alerted ? "부모님께 알림을 보냈어요" : "방금 보낸 알림이 있어 다시 보내지 않았어요");
                })
              }
            />
            <Button label="내 저장된 위치만 지우기" variant="ghost" small disabled={busy || !mine} onPress={() => run(() => deleteMyLocation(), "저장된 내 위치를 지웠어요")} />
          </>
        ) : null}
        <Button label={demoOpen ? "시연 도구 접기" : "시연 도구 펼치기"} variant="ghost" small onPress={() => setDemoOpen((v) => !v)} />
      </Card>

      <Card tone="white">
        <Text style={styles.title}>위치 공유 끄기</Text>
        <Text style={styles.caption}>끄면 서버에 저장된 내 위치와 기록이 모두 지워져요.</Text>
        <Button label="공유 끄고 내 위치 기록 지우기" variant="secondary" small onPress={onWithdraw} disabled={busy} />
      </Card>
    </View>
  );
}

/**
 * 상태 점검 카드: 위치가 왜 안 쌓이는지 바로 알 수 있게 권한·기기 수집 작업·마지막 전송 시각을 보인다.
 * @param {{ me: import("../api").MyLocation, lastSeen?: string | null, refreshKey: number }} props
 */
function HealthCard({ me, lastSeen, refreshKey }) {
  const [perm, setPerm] = useState(null);
  const [running, setRunning] = useState(null);
  useEffect(() => {
    let live = true;
    (async () => {
      const [p, r] = await Promise.all([readPermissions(), isBackgroundRunning()]);
      if (live) {
        setPerm(p);
        setRunning(r);
      }
    })().catch(() => {});
    return () => {
      live = false;
    };
  }, [refreshKey, me.background, me.paused]);

  const permission = perm ? describePermission(perm.foreground, perm.background) : null;
  const sent = describeLastSent(lastSeen);
  const rows = [
    permission && { label: "위치 권한", ok: permission.ok, text: permission.text },
    me.background && running != null && {
      label: "앱을 꺼도 수집",
      ok: running,
      text: running ? (me.paused ? "여행 모드 대기 중" : "이 기기에서 돌고 있어요") : "이 기기에서 멈춰 있어요. 앱을 다시 열면 켜져요",
    },
    { label: "마지막 전송", ok: me.paused || sent.ok, text: me.paused ? "여행 모드라 보내지 않아요" : sent.text },
  ].filter(Boolean);

  return (
    <Card tone="white">
      <Text style={styles.title}>상태 점검</Text>
      {rows.map((r) => (
        <Text key={r.label} style={styles.row}>
          <Text style={r.ok ? styles.ok : styles.bad}>{r.ok ? "● " : "▲ "}</Text>
          {r.label} · {r.text}
        </Text>
      ))}
    </Card>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
  title: { ...font.bodyStrong, color: colors.text },
  caption: { ...font.caption, color: colors.textSub },
  row: { ...font.caption, color: colors.text },
  ok: { color: colors.success },
  bad: { color: colors.danger },
});
