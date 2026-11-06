import { useCallback, useEffect, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Screen from "@/shared/components/Screen";
import useResource from "@/shared/hooks/useResource";
import { colors, font, spacing } from "@/theme";

import { getFamilyLocations, getMyLocation, setLocationConsent } from "../api";
import { trackingMode } from "../background";
import { startBackground, stopBackground } from "../backgroundControl";
import { savePausedUntil } from "../pauseState";
import { requestForeground, sendNow } from "../sharing";
import { statusLine } from "../status";
import HistoryTab from "./HistoryTab";
import ConsentGate from "./ConsentGate";
import MyLocationTab from "./MyLocationTab";
import SettingsTab from "./SettingsTab";
import SubTabs from "./SubTabs";
import TravelTab from "./TravelTab";

const SEND_EVERY_MS = 60 * 1000; // 베타: 화면이 열려 있는 동안 1분마다 한 번
const MAX_TIMER_MS = 2 ** 31 - 1;

const TABS = [
  { key: "me", label: "내 위치", icon: "location" },
  { key: "history", label: "이동 기록", icon: "time" },
  { key: "travel", label: "여행 모드", icon: "airplane" },
  { key: "settings", label: "설정", icon: "settings" },
];

/**
 * 위치 탭(베타) 전체. 이 컴포넌트(하위 탭의 공통 부모)가 서버 상태 불러오기, 앱을 꺼도 공유(백그라운드) 맞추기,
 * 화면이 열려 있을 때 1분마다 보내기를 맡는다. 하위 탭 화면은 처음 열 때 만들고 그 뒤로는 숨기기만 해서,
 * 탭을 옮겨도 지도 확대·고른 날짜·입력이 그대로 남고 수집은 멈추지 않는다.
 * 동의 전에는 동의 화면만 보인다.
 */
export default function LocationHome() {
  const [message, setMessage] = useState(null);
  const timer = useRef(null);
  const notify = useCallback((text, isError = false) => {
    setMessage({ text, isError });
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setMessage(null), 3500);
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);

  const [tab, setTab] = useState("me");
  const [visited, setVisited] = useState(() => new Set(["me"]));
  const [tick, setTick] = useState(0);
  const [busy, setBusy] = useState(false);
  const loadMe = useCallback(() => getMyLocation(), []);
  const { data: me, error: meError, reload: reloadMe } = useResource(loadMe, tick);
  const active = Boolean(me?.enabled && me?.consent);
  const loadFamily = useCallback(() => (active ? getFamilyLocations() : Promise.resolve(null)), [active]);
  const { data: family, reload: reloadFamily } = useResource(loadFamily, tick);

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  const mode = trackingMode(me);
  const sharing = active && !me?.paused;
  const background = Boolean(me?.background);
  const pausedUntil = me?.paused ? me.paused_until : null;

  const pick = (key) => {
    setTab(key);
    setVisited((prev) => (prev.has(key) ? prev : new Set(prev).add(key)));
  };

  // 서버 상태에 맞춰 이 기기의 수집을 정한다. off=멈춤, waiting=여행 모드 저전력 대기(보내지 않음), normal=정상 수집.
  // 여행 모드 종료 시각은 기기에도 적어 두어, 앱이 꺼진 채 깨어난 작업이 종료를 스스로 알아챈다.
  useEffect(() => {
    if (!me) return;
    (async () => {
      if (mode === "off") {
        await savePausedUntil(null);
        await stopBackground();
      } else {
        await savePausedUntil(mode === "waiting" ? pausedUntil : null);
        await startBackground(mode);
      }
    })().catch(() => {});
  }, [me, mode, pausedUntil]);

  // 앱이 켜진 채 여행 모드가 끝나는 시각이 되면 상태를 다시 불러와 정상 수집·1분 전송으로 돌아간다.
  useEffect(() => {
    if (!pausedUntil) return undefined;
    const delay = Date.parse(pausedUntil) - Date.now() + 1000;
    if (!(delay > 0)) return undefined;
    const id = setTimeout(refresh, Math.min(delay, MAX_TIMER_MS));
    return () => clearTimeout(id);
  }, [pausedUntil, refresh]);

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
      await savePausedUntil(null);
      await setLocationConsent(false);
      setTab("me");
    }, "위치 공유를 끄고 기록을 지웠어요");

  const status = statusLine(me);
  const pinned = (
    <View style={styles.pinned}>
      {message ? (
        <View style={[styles.message, message.isError && styles.messageError]} accessibilityLiveRegion="polite" testID="message">
          <Text style={[styles.messageText, message.isError && styles.messageTextError]}>{message.text}</Text>
        </View>
      ) : null}
      {me ? (
        <View style={[styles.status, status.tone === "ok" && styles.statusOk, status.tone === "pause" && styles.statusPause]} testID="location-status">
          <Text style={[styles.statusText, status.tone === "ok" && styles.statusTextOk]}>{status.text}</Text>
        </View>
      ) : null}
      {active ? <SubTabs tabs={TABS} value={tab} onChange={pick} /> : null}
    </View>
  );

  return (
    <Screen title="위치" pinned={pinned}>
      {meError && !me ? <Text style={styles.error}>{meError}</Text> : null}
      {me && !me.enabled ? (
        <Card tone="white">
          <Text style={styles.title}>위치 공유(베타)</Text>
          <Text style={styles.caption}>이 서버에서는 위치 공유가 꺼져 있어요. 베타 버전에서만 켤 수 있어요.</Text>
          {me.consent ? <Button label="내 위치 공유 끄고 기록 지우기" variant="secondary" small onPress={withdraw} /> : null}
        </Card>
      ) : null}
      {me?.enabled && !me.consent ? <ConsentGate onAgree={agree} busy={busy} /> : null}
      {active ? (
        <>
          <Panel on={tab === "me"} show>
            <MyLocationTab me={me} members={family?.members ?? []} canSeeFamily={Boolean(family?.can_see_family)} />
          </Panel>
          <Panel on={tab === "history"} show={visited.has("history")}>
            <HistoryTab members={family?.members ?? []} canSeeFamily={Boolean(family?.can_see_family)} refreshKey={tick} notify={notify} />
          </Panel>
          <Panel on={tab === "travel"} show={visited.has("travel")}>
            <TravelTab me={me} busy={busy} run={run} notify={notify} />
          </Panel>
          <Panel on={tab === "settings"} show={visited.has("settings")}>
            <SettingsTab
              me={me}
              members={family?.members ?? []}
              busy={busy}
              refreshKey={tick}
              run={run}
              notify={notify}
              onChanged={refresh}
              onWithdraw={withdraw}
            />
          </Panel>
        </>
      ) : null}
    </Screen>
  );
}

/**
 * 하위 탭 한 칸. 처음 열기 전에는 만들지 않고, 만든 뒤에는 숨기기만 한다(상태가 사라지지 않는다).
 * @param {{ on: boolean, show: boolean, children: import("react").ReactNode }} props
 */
function Panel({ on, show, children }) {
  if (!show) return null;
  return <View style={on ? undefined : styles.hidden}>{children}</View>;
}

const styles = StyleSheet.create({
  pinned: { paddingHorizontal: spacing.xl, paddingBottom: spacing.sm, gap: spacing.sm },
  hidden: { display: "none" },
  title: { ...font.bodyStrong, color: colors.text },
  caption: { ...font.caption, color: colors.textSub },
  error: { ...font.caption, color: colors.danger },
  message: { backgroundColor: colors.successSoft, borderRadius: 14, paddingHorizontal: 14, paddingVertical: 10 },
  messageError: { backgroundColor: colors.dangerSoft },
  messageText: { ...font.caption, color: colors.success, fontWeight: "600" },
  messageTextError: { color: colors.danger },
  status: { backgroundColor: colors.surface, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 8 },
  statusOk: { backgroundColor: colors.successSoft },
  statusPause: { backgroundColor: colors.warningSoft },
  statusText: { ...font.caption, color: colors.textSub, fontWeight: "600" },
  statusTextOk: { color: colors.success },
});
