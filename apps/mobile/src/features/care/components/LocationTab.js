import { useCallback, useEffect, useState } from "react";
import { Linking, Pressable, StyleSheet, Switch, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import SectionTitle from "@/shared/components/SectionTitle";
import Tag from "@/shared/components/Tag";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { getLatestLocations, getLocationConsent, setLocationConsent } from "../api";
import { placeName } from "../location/geocode";
import { mapUrl, timeText } from "../location/place";
import { canTrackInBackground, isBackgroundRunning, requestForeground, sendNow, startBackground, stopBackground } from "../location/sharing";

const ago = (minutes) => (minutes === null ? "" : minutes < 1 ? "방금" : minutes < 60 ? `${minutes}분 전` : `${Math.floor(minutes / 60)}시간 전`);

/** 좌표를 "시·동" 이름으로 바꿔 보여 준다(보는 사람의 기기가 주소 변환 서비스에 좌표를 보낸다). 변환하지 못하면 아무것도 그리지 않는다. */
function Place({ lat, lng, style }) {
  const [name, setName] = useState(null);
  useEffect(() => {
    let alive = true;
    placeName(lat, lng).then((n) => alive && setName(n));
    return () => {
      alive = false;
    };
  }, [lat, lng]);
  return name ? (
    <Text style={style} testID="place-name">
      {name}
    </Text>
  ) : null;
}

/**
 * 위치 확인: 동의한 가족 구성원의 최신 위치를 보여 주고, 내 위치 공유에 동의하거나 철회한다.
 * 구성원 카드에는 이름 옆에 "시·동"을 적고, 카드를 누르면 좌표·정확도·받은 시각과 "지도에서 보기"가 있는 확인 화면이 펼쳐진다.
 * 위치는 개인정보라서 동의한 사람만 보낼 수 있고 같은 가족만 볼 수 있다. 철회하면 저장된 위치가 바로 지워진다.
 * @param {{ notify: (text: string, isError?: boolean) => void }} props
 */
export default function LocationTab({ notify }) {
  const consent = useResource(getLocationConsent);
  const [refresh, setRefresh] = useState(0);
  const load = useCallback(() => getLatestLocations(), []);
  const latest = useResource(load, refresh);
  const [busy, setBusy] = useState(false);
  const [background, setBackground] = useState({ possible: false, running: false });
  const [selected, setSelected] = useState(null); // 확인 화면을 펼친 구성원 id

  useEffect(() => {
    (async () => setBackground({ possible: await canTrackInBackground(), running: await isBackgroundRunning() }))();
  }, [consent.data?.consent]);

  const on = consent.data?.consent === true;
  const reloadAll = async () => {
    await consent.reload();
    setRefresh((r) => r + 1);
  };

  const toggle = async (next) => {
    setBusy(true);
    try {
      if (next) {
        await setLocationConsent(true);
        if (!(await requestForeground())) {
          await setLocationConsent(false); // 기기에서 위치 권한을 허용하지 않았으면 동의도 켜 두지 않는다
          notify("기기의 위치 권한을 허용해야 공유할 수 있어요", true);
        } else {
          const result = await startBackground();
          notify(
            result === "started"
              ? "위치 공유를 켰어요. 백그라운드에서도 주기적으로 보내요"
              : result === "no-background-permission"
                ? "위치 공유를 켰어요. '항상 허용'이 아니라서 앱을 열었을 때만 보낼 수 있어요"
                : "위치 공유를 켰어요. 이 기기에서는 앱을 열었을 때만 보낼 수 있어요",
          );
        }
      } else {
        await stopBackground();
        await setLocationConsent(false);
        notify("위치 공유를 껐어요. 저장된 내 위치는 지웠어요");
      }
      await reloadAll();
    } catch (e) {
      notify(e.message, true);
      await reloadAll();
    } finally {
      setBusy(false);
    }
  };

  const send = async () => {
    setBusy(true);
    try {
      await sendNow();
      notify("내 위치를 보냈어요");
      setRefresh((r) => r + 1);
    } catch (e) {
      notify(e.message, true);
    } finally {
      setBusy(false);
    }
  };

  if (consent.loading && !consent.data) return <Text style={styles.muted}>불러오는 중…</Text>;
  if (!consent.data) return <Text style={styles.error}>{consent.error || "위치 설정을 불러오지 못했어요"}</Text>;

  return (
    <View style={styles.wrap}>
      <Card tone="orange">
        <Text style={styles.notice}>위치는 개인정보예요. 동의한 사람의 위치만 같은 가족에게 보이고, 7일이 지나면 자동으로 지워져요.</Text>
        <Text style={styles.caption}>시·동 이름은 보는 사람의 기기가 주소 변환 서비스에 좌표를 보내 받아와요. 서버에는 저장하지 않아요.</Text>
      </Card>

      <Card tone="white">
        <View style={styles.head}>
          <View style={styles.grow}>
            <Text style={styles.title}>내 위치 공유</Text>
            <Text style={styles.caption}>{on ? "가족 구성원이 내 최신 위치를 볼 수 있어요" : "공유하지 않아요"}</Text>
          </View>
          <Switch
            value={on}
            onValueChange={toggle}
            disabled={busy}
            accessibilityLabel="위치 공유 동의"
            testID="consent-switch"
            trackColor={{ false: colors.disabled, true: colors.peach }}
            thumbColor={colors.card}
            activeThumbColor={colors.card}
          />
        </View>
        <Text style={styles.caption} testID="background-note">
          {background.possible
            ? background.running
              ? "백그라운드 수집 켜짐 · 약 15분마다 또는 200m 이동 시 보내요"
              : "백그라운드 수집 꺼짐"
            : "이 기기(웹·Expo Go)에서는 앱을 열었을 때만 보낼 수 있어요"}
        </Text>
        <Text style={styles.caption}>끄면 저장된 내 위치를 바로 지워요.</Text>
        <Button label="지금 내 위치 보내기" onPress={send} disabled={!on || busy} />
      </Card>

      <SectionTitle title="가족 위치" action="새로고침" onAction={() => setRefresh((r) => r + 1)} />
      {latest.loading && !latest.data ? <Text style={styles.muted}>불러오는 중…</Text> : null}
      {latest.data?.members.map((m) => {
        const located = m.sharing && m.lat !== null;
        const open = located && selected === m.user_id;
        return (
          <Card key={m.user_id} tone="white" testID={`loc-${m.name}`}>
            <Pressable
              disabled={!located}
              onPress={() => setSelected(open ? null : m.user_id)}
              accessibilityRole={located ? "button" : undefined}
              accessibilityLabel={located ? `${m.name} 위치 자세히 보기` : undefined}
              accessibilityState={located ? { expanded: open } : undefined}
              style={styles.head}
            >
              <View style={styles.grow}>
                <View style={styles.nameRow}>
                  <Text style={styles.title}>
                    {m.name}
                    {m.is_me ? " (나)" : ""}
                  </Text>
                  {located ? <Place lat={m.lat} lng={m.lng} style={styles.place} /> : null}
                </View>
                {located ? (
                  <Text style={styles.caption} testID={`coords-${m.name}`}>
                    {m.lat.toFixed(5)}, {m.lng.toFixed(5)}
                    {m.accuracy_m !== null ? ` · ±${Math.round(m.accuracy_m)}m` : ""} · {ago(m.minutes_ago)}
                  </Text>
                ) : (
                  <Text style={styles.caption}>{m.sharing ? "아직 받은 위치가 없어요" : "위치를 공유하지 않아요"}</Text>
                )}
              </View>
              <Tag label={m.sharing ? "공유 중" : "공유 안 함"} tone={m.sharing ? "green" : "gray"} />
            </Pressable>
            {open ? (
              <View style={styles.detail} testID={`detail-${m.name}`}>
                <Place lat={m.lat} lng={m.lng} style={styles.detailPlace} />
                <Text style={styles.caption}>
                  위도 {m.lat.toFixed(5)} · 경도 {m.lng.toFixed(5)}
                </Text>
                {m.accuracy_m !== null ? <Text style={styles.caption}>정확도 약 ±{Math.round(m.accuracy_m)}m</Text> : null}
                {timeText(m.recorded_at) ? <Text style={styles.caption}>받은 시각 {timeText(m.recorded_at)} ({ago(m.minutes_ago)})</Text> : null}
                <Button small variant="secondary" label="지도에서 보기" a11yLabel={`${m.name} 위치를 지도에서 보기`} onPress={() => Linking.openURL(mapUrl(m.lat, m.lng)).catch(() => notify("지도를 열지 못했어요", true))} />
                <Text style={styles.caption}>누르면 이 좌표가 지도 앱(또는 브라우저)에 전달돼요.</Text>
              </View>
            ) : null}
          </Card>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
  head: { flexDirection: "row", alignItems: "center", gap: 12 },
  grow: { flex: 1, gap: 2 },
  title: { ...font.cardTitle, color: colors.text },
  nameRow: { flexDirection: "row", alignItems: "baseline", flexWrap: "wrap", columnGap: 8 },
  place: { ...font.caption, color: colors.text, fontWeight: "600" },
  detail: { gap: 6, paddingTop: 12, marginTop: 4, borderTopWidth: 1, borderTopColor: colors.divider },
  detailPlace: { ...font.bodyStrong, color: colors.text },
  notice: { ...font.caption, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 16 },
  error: { ...font.body, color: colors.danger },
});
