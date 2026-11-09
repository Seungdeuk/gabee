import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, AppState, Linking, Platform, Pressable, StyleSheet, Switch, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import IconButton from "@/shared/components/IconButton";
import Screen from "@/shared/components/Screen";
import { colors, font, radius, spacing } from "@/theme";

import { getPushSettings, savePushSettings } from "../api";
import { KIND_META } from "../kinds";
import { prepareThisDevice, readPermissionState } from "../PushBootstrap";
import { formatQuietSummary, formatTimeKorean, isQuietOn, permissionNotice, stepQuietTime, toggleKind, withQuiet } from "../push";

const KIND_KEYS = ["chat", "schedule", "billing", "care", "family_group", "ai_record", "support"];

/**
 * 마이 > 알림 설정: 푸시 켜기·끄기, 분류별 켜기·끄기, 방해금지 시간. 바꾸는 즉시 저장한다.
 * "푸시 알림 받기"를 켜면 이 기기의 알림 권한을 확인·요청하고 푸시 토큰을 등록한다. 기기 권한이 꺼져 있으면 안내와 "기기 설정 열기"를 보여 주고,
 * 화면에 돌아오거나 앱이 다시 활성화될 때마다 권한을 다시 확인해 허용돼 있으면 토큰을 등록한다(웹에는 기기 푸시가 없어 이 안내가 없다).
 */
export default function PushSettingsScreen() {
  const router = useRouter();
  const [settings, setSettings] = useState(null);
  const [status, setStatus] = useState("loading"); // loading | ready | error
  const [saveError, setSaveError] = useState(false);
  const [device, setDevice] = useState("unknown"); // 이 기기의 푸시 준비 상태: granted | ask | blocked | failed | unknown
  const busy = useRef(false); // 권한 창·토큰 등록이 도는 동안 겹쳐 부르지 않는다

  /** 이 기기의 권한을 확인하고, 이미 허용돼 있으면 토큰을 (다시) 등록해 둔다. 아직 묻지 않았으면 묻지 않고 상태만 알린다. */
  const syncDevice = useCallback(async () => {
    if (Platform.OS === "web" || busy.current) return;
    busy.current = true;
    try {
      const state = await readPermissionState();
      setDevice(state === "granted" ? await prepareThisDevice() : state);
    } finally {
      busy.current = false;
    }
  }, []);

  /** 사용자가 직접 허용하려 할 때: 필요하면 권한 안내·시스템 창을 띄우고 토큰을 등록한다. */
  const allowOnDevice = useCallback(async () => {
    if (Platform.OS === "web" || busy.current) return;
    busy.current = true;
    try {
      setDevice(await prepareThisDevice());
    } finally {
      busy.current = false;
    }
  }, []);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      setSettings(await getPushSettings());
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useFocusEffect(
    useCallback(() => {
      syncDevice();
    }, [syncDevice]),
  );

  useEffect(() => {
    // 기기 설정에서 권한을 바꾸고 돌아오면 다시 확인한다
    const sub = AppState.addEventListener("change", (state) => {
      if (state === "active") syncDevice();
    });
    return () => sub.remove();
  }, [syncDevice]);

  const change = async (next) => {
    const previous = settings;
    setSettings(next); // 바로 보여 주고, 저장에 실패하면 되돌린다
    setSaveError(false);
    try {
      setSettings(await savePushSettings(next));
      if (next.enabled && !previous?.enabled) allowOnDevice(); // 방금 켰다면 이 기기도 푸시를 받을 준비를 한다
    } catch {
      setSettings(previous);
      setSaveError(true);
    }
  };

  const notice = settings ? permissionNotice(device, settings.enabled) : null;
  const onNoticeAction = () => (notice?.action === "settings" ? Linking.openSettings() : allowOnDevice());

  return (
    <Screen
      title="알림 설정"
      subtitle="푸시로 받을 알림을 골라요"
      centered
      left={<IconButton name="chevron-back" label="뒤로" onPress={() => router.back()} />}
    >
      {status === "loading" ? <ActivityIndicator color={colors.primary} style={styles.center} /> : null}
      {status === "error" ? (
        <View style={styles.center}>
          <Text style={styles.empty}>설정을 불러오지 못했어요</Text>
          <Button label="다시 시도" variant="secondary" small onPress={load} testID="retry" />
        </View>
      ) : null}
      {status === "ready" && settings ? (
        <View style={styles.list}>
          {saveError ? <Text style={styles.error}>저장하지 못했어요. 다시 시도해 주세요</Text> : null}
          <Card tone="white">
            <Row label="푸시 알림 받기" value={settings.enabled} onChange={(enabled) => change({ ...settings, enabled })} />
          </Card>
          {notice ? (
            <Card tone="white">
              <Text style={styles.notice} accessibilityLiveRegion="polite">
                {notice.text}
              </Text>
              {notice.action ? <Button label={notice.actionLabel} variant="secondary" small onPress={onNoticeAction} testID="push-device-action" /> : null}
            </Card>
          ) : null}
          {settings.enabled ? (
            <>
              <Text style={styles.section}>받을 알림</Text>
              <Card tone="white">
                {KIND_KEYS.map((kind) => (
                  <Row
                    key={kind}
                    label={KIND_META[kind].label}
                    value={!settings.muted_kinds.includes(kind)}
                    onChange={() => change({ ...settings, muted_kinds: toggleKind(settings.muted_kinds, kind) })}
                  />
                ))}
              </Card>
              <Text style={styles.hint}>{"소통 푸시는 '새 메시지가 도착했어요'로만 와요. 내용은 앱에서 확인해요."}</Text>
              <Text style={styles.section}>방해금지</Text>
              <Card tone="white">
                <Row label="방해금지 켜기" value={isQuietOn(settings)} onChange={(on) => change(withQuiet(settings, on))} />
                {isQuietOn(settings) ? (
                  <>
                    <TimeRow label="시작 시간" time={settings.quiet_start} onStep={(unit, dir) => change(stepQuietTime(settings, "quiet_start", unit, dir))} />
                    <TimeRow label="끝 시간" time={settings.quiet_end} onStep={(unit, dir) => change(stepQuietTime(settings, "quiet_end", unit, dir))} />
                  </>
                ) : null}
              </Card>
              {isQuietOn(settings) ? <Text style={styles.hint}>{formatQuietSummary(settings)}</Text> : null}
              <Text style={styles.hint}>알림함에는 그대로 쌓여요.</Text>
            </>
          ) : null}
        </View>
      ) : null}
    </Screen>
  );
}

/** 시간 한 줄: 현재 시각을 크게 보이고, 시·분을 각각 줄이고 늘리는 버튼을 둔다. */
function TimeRow({ label, time, onStep }) {
  return (
    <View style={styles.timeRow}>
      <View style={styles.timeHead}>
        <Text style={styles.rowLabel}>{label}</Text>
        <Text style={styles.timeValue} accessibilityLabel={`${label} ${formatTimeKorean(time)}`}>
          {formatTimeKorean(time)}
        </Text>
      </View>
      <View style={styles.stepRow}>
        <Stepper name="시" label={`${label} 시`} onStep={(dir) => onStep("hour", dir)} />
        <Stepper name="분" label={`${label} 분`} onStep={(dir) => onStep("minute", dir)} />
      </View>
    </View>
  );
}

function Stepper({ name, label, onStep }) {
  return (
    <View style={styles.stepper}>
      <Text style={styles.stepName}>{name}</Text>
      <Pressable accessibilityRole="button" accessibilityLabel={`${label} 줄이기`} onPress={() => onStep(-1)} style={styles.stepButton}>
        <Text style={styles.stepText}>−</Text>
      </Pressable>
      <Pressable accessibilityRole="button" accessibilityLabel={`${label} 늘리기`} onPress={() => onStep(1)} style={styles.stepButton}>
        <Text style={styles.stepText}>+</Text>
      </Pressable>
    </View>
  );
}

function Row({ label, value, onChange }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Switch
        value={value}
        onValueChange={onChange}
        trackColor={{ false: colors.disabled, true: colors.peach }}
        thumbColor={colors.card}
        accessibilityLabel={label}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  list: { gap: spacing.md, paddingBottom: spacing.xxl },
  center: { alignItems: "center", gap: spacing.md, marginTop: spacing.xxl },
  empty: { ...font.body, color: colors.textMuted, textAlign: "center" },
  error: { ...font.body, color: colors.danger, textAlign: "center" },
  section: { ...font.bodyStrong, color: colors.text, marginTop: spacing.sm },
  hint: { ...font.caption, color: colors.textMuted },
  notice: { ...font.body, color: colors.text, marginBottom: spacing.sm },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: spacing.sm },
  timeRow: { paddingVertical: spacing.sm, gap: spacing.sm },
  timeHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  timeValue: { ...font.bodyStrong, color: colors.text },
  stepRow: { flexDirection: "row", justifyContent: "space-around" },
  stepper: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  stepName: { ...font.body, color: colors.textMuted },
  stepButton: { minWidth: 44, minHeight: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: colors.surfaceStrong },
  stepText: { ...font.bodyStrong, color: colors.text },
  rowLabel: { ...font.body, color: colors.text, flex: 1, paddingRight: spacing.md },
});
