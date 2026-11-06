import { useCallback, useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import Segmented from "@/shared/components/Segmented";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import {
  deleteMyLocation,
  getFamilyLocations,
  getMyLocation,
  setLocationConsent,
  setLocationPause,
  simulateExit,
} from "../api";
import { wantsBackground } from "../background";
import { agoText } from "../geo";
import { PAUSE_OPTIONS, pauseDays } from "../pause";
import { isBackgroundRunning, requestForeground, seedZoneNearHere, sendNow, startBackground, stopBackground } from "../sharing";
import BackgroundCard from "./BackgroundCard";
import MapCard from "./MapCard";
import TimelineCard from "./TimelineCard";

const SEND_EVERY_MS = 60 * 1000; // 베타: 화면이 열려 있는 동안 1분마다 한 번
const ZONE_MIN_POINTS = 5; // 서버가 활동 구역을 만드는 최소 위치 수(서버 location/service.py 와 같다)

/**
 * 위치 탭(베타). 지도·동의·앱을 꺼도 공유·여행 모드·이동 기록·이탈 알림 시연을 한 화면에 둔다.
 * 위치는 이 화면이 열려 있는 동안 보내고, "앱을 꺼도 계속 공유"에 동의하면 앱이 꺼져 있어도 기기에서 모아 보낸다.
 * @param {{ notify: (text: string, isError?: boolean) => void }} props
 */
export default function LocationSection({ notify }) {
  const [tick, setTick] = useState(0);
  const [pauseKey, setPauseKey] = useState("3");
  const [customDays, setCustomDays] = useState("");
  const [busy, setBusy] = useState(false);
  const loadMe = useCallback(() => getMyLocation(), []);
  const { data: me, error: meError, reload: reloadMe } = useResource(loadMe, tick);
  const active = Boolean(me?.enabled && me?.consent);
  const loadFamily = useCallback(() => (active ? getFamilyLocations() : Promise.resolve(null)), [active]);
  const { data: family, reload: reloadFamily } = useResource(loadFamily, tick);

  const sharing = active && !me?.paused;
  const background = Boolean(me?.background);
  const refresh = useCallback(() => setTick((t) => t + 1), []);
  const pause = pauseDays(pauseKey, customDays);

  // 서버 상태에 맞춰 이 기기의 백그라운드 수집을 켜고 끈다: 동의했고 일시정지가 아닐 때만 돌고, 철회·일시정지·스위치 꺼짐이면 멈춘다.
  useEffect(() => {
    if (!me) return;
    (async () => {
      if (wantsBackground(me)) {
        if (!(await isBackgroundRunning())) await startBackground();
      } else {
        await stopBackground();
      }
    })().catch(() => {});
  }, [me]);

  // 화면이 열려 있고 공유 중이면 1분마다 위치를 한 번 보낸다. 백그라운드 수집이 켜져 있으면 그쪽이 보내므로 겹쳐 보내지 않는다.
  useEffect(() => {
    if (!sharing || background) return undefined;
    let cancelled = false;
    const send = async () => {
      try {
        if (!(await requestForeground())) return;
        const res = await sendNow();
        if (cancelled) return;
        if (res.alerted) notify("평소 활동 구역을 벗어나 부모님께 알렸어요");
        reloadMe();
        reloadFamily();
      } catch {
        /* 한 번 못 보내도 다음 주기에 다시 보낸다 */
      }
    };
    send();
    const id = setInterval(send, SEND_EVERY_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [sharing, background, notify, reloadMe, reloadFamily]);

  const run = async (job, okText) => {
    if (busy) return;
    setBusy(true);
    try {
      await job();
      if (okText) notify(okText);
      refresh();
    } catch (e) {
      notify(e.message || "처리하지 못했어요", true);
    } finally {
      setBusy(false);
    }
  };

  const agree = () =>
    run(async () => {
      if (!(await requestForeground())) throw new Error("위치 권한을 허용해야 위치를 공유할 수 있어요");
      await setLocationConsent(true);
    }, "위치 공유를 시작했어요");
  const withdraw = () =>
    run(async () => {
      await stopBackground(); // 철회하면 서버 응답을 기다리지 않고 먼저 이 기기의 수집을 멈춘다
      await setLocationConsent(false);
    }, "위치 공유를 끄고 기록을 지웠어요");
  const seedZone = () =>
    run(async () => {
      if (!(await requestForeground())) throw new Error("위치 권한이 필요해요");
      await seedZoneNearHere(ZONE_MIN_POINTS);
    }, "활동 구역을 만들었어요");
  const simulate = () =>
    run(async () => {
      const r = await simulateExit();
      notify(r.alerted ? "부모님께 알림을 보냈어요" : "방금 보낸 알림이 있어 다시 보내지 않았어요");
    });
  const startPause = () => {
    if (pause.days == null) {
      notify(pause.error, true);
      return;
    }
    run(() => setLocationPause(pause.days), `위치 공유를 ${pause.days}일 동안 멈췄어요`);
  };

  if (meError && !me) return <Text style={styles.error}>{meError}</Text>;
  if (!me) return null;

  if (!me.enabled) {
    return (
      <Card tone="white">
        <Text style={styles.title}>위치 공유(베타)</Text>
        <Text style={styles.caption}>이 서버에서는 위치 공유가 꺼져 있어요. 베타 버전에서만 켤 수 있어요.</Text>
        {me.consent ? <Button label="내 위치 공유 끄고 기록 지우기" variant="secondary" small onPress={withdraw} /> : null}
      </Card>
    );
  }

  const members = family?.members ?? [];
  const mine = members.find((m) => m.is_me);
  return (
    <View style={styles.wrap}>
      <MapCard members={members} zone={me.zone} canSeeFamily={Boolean(family?.can_see_family)} />

      <Card tone="white">
        <Text style={styles.title}>위치 공유(베타)</Text>
        <Text style={styles.caption}>
          시연용 베타예요. 동의한 사람의 위치만 모으고 평소 활동 구역을 벗어나면 부모님께 알려요. 알림에는 위치가 담기지 않아요. 언제든 끄고 기록을 지울 수 있어요. 급한 일은 112로 연락하세요.
        </Text>
        {!me.consent ? (
          <Button label="위치 공유에 동의하고 시작" onPress={agree} disabled={busy} testID="location-agree" />
        ) : (
          <Button label="공유 끄고 내 위치 기록 지우기" variant="secondary" small onPress={withdraw} disabled={busy} />
        )}
      </Card>

      {me.consent ? (
        <>
          <BackgroundCard me={me} notify={notify} onChanged={refresh} />

          <Card tone="white">
            <Text style={styles.title}>여행 모드(일시정지)</Text>
            {me.paused ? (
              <>
                <Text style={styles.caption}>위치를 보내지 않고 있어요. 이 동안은 구역을 벗어나도 알리지 않아요.</Text>
                <Button label="다시 공유하기" onPress={() => run(() => setLocationPause(null), "위치 공유를 다시 시작했어요")} disabled={busy} />
              </>
            ) : (
              <>
                <Text style={styles.caption}>여행처럼 평소와 다른 곳에 갈 때 잠시 멈춰요. 멈췄다는 사실만 부모님께 알려요.</Text>
                <Segmented options={PAUSE_OPTIONS} value={pauseKey} onChange={setPauseKey} />
                {pauseKey === "other" ? (
                  <Field
                    label="며칠 동안 멈출까요? (1~14일)"
                    value={customDays}
                    onChangeText={setCustomDays}
                    placeholder="예: 10"
                    keyboardType="number-pad"
                    maxLength={2}
                    error={customDays && pause.days == null ? pause.error : undefined}
                    testID="pause-custom-days"
                  />
                ) : null}
                <Button
                  label={pause.days != null ? `${pause.days}일 동안 멈추기` : "기간을 정해 주세요"}
                  variant="secondary"
                  onPress={startPause}
                  disabled={busy || pause.days == null}
                />
              </>
            )}
          </Card>

          <Card tone="white">
            <Text style={styles.title}>공유 상태</Text>
            {members.map((m) => (
              <Text key={m.user_id} style={styles.row}>
                {m.name}
                {m.is_me ? "(나)" : ""} · {memberState(m)}
              </Text>
            ))}
            <Text style={styles.caption}>
              {me.zone
                ? `내 활동 구역: 반지름 약 ${Math.round(me.zone.radius_m)}m (위치 ${me.zone.sample_count}개로 계산)`
                : `활동 구역은 위치가 ${ZONE_MIN_POINTS}개 모이면 만들어요 (지금 ${me.point_count}개)`}
            </Text>
          </Card>

          <TimelineCard members={members} canSeeFamily={Boolean(family?.can_see_family)} refreshKey={tick} notify={notify} />

          <Card tone="white">
            <Text style={styles.title}>시연 도구</Text>
            <Text style={styles.caption}>실제로 걸어 나가지 않아도 흐름을 보여 줄 수 있어요. 내 위치만 써요.</Text>
            <Button label="활동 구역 빨리 만들기" variant="secondary" small disabled={busy || me.paused} onPress={seedZone} />
            <Button label="구역 이탈 알림 시연" variant="secondary" small disabled={busy || !me.zone} onPress={simulate} />
            <Button label="내 저장된 위치만 지우기" variant="ghost" small disabled={busy || !mine} onPress={() => run(() => deleteMyLocation(), "저장된 내 위치를 지웠어요")} />
          </Card>
        </>
      ) : null}
    </View>
  );
}

/** @param {import("../api").MemberLocation} m @returns {string} */
function memberState(m) {
  if (m.paused) return "일시정지 중";
  if (!m.sharing) return "공유 안 함";
  if (m.lat == null) return "위치 기다리는 중";
  return `${agoText(m.recorded_at)} · ${m.outside ? "평소 구역 밖" : "평소 구역 안"}`;
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
  title: { ...font.bodyStrong, color: colors.text },
  caption: { ...font.caption, color: colors.textSub },
  row: { ...font.caption, color: colors.text },
  error: { ...font.caption, color: colors.danger },
});
