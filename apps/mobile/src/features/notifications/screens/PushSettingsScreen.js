import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, AppState, Linking, Platform, StyleSheet, Switch, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Dropdown from "@/shared/components/Dropdown";
import IconButton from "@/shared/components/IconButton";
import Screen from "@/shared/components/Screen";
import { colors, font, spacing } from "@/theme";

import { getPushSettings, savePushSettings } from "../api";
import { KIND_META } from "../kinds";
import { prepareThisDevice, readPermissionState } from "../PushBootstrap";
import {
  QUIET_HOUR_OPTIONS,
  QUIET_MINUTE_OPTIONS,
  formatQuietSummary,
  isQuietClash,
  isQuietOn,
  parseTime,
  permissionNotice,
  setQuietPart,
  toggleKind,
  withQuiet,
} from "../push";

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
  const [clash, setClash] = useState(false); // 시작과 끝이 같아지는 선택을 했을 때 안내
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

  /** 방해금지 시·분 드롭다운에서 고른 값을 저장한다. 시작과 끝이 같아지면 저장하지 않고 안내만 보인다. */
  const pickQuiet = (field, part, value) => {
    if (isQuietClash(settings, field, part, value)) {
      setClash(true);
      return;
    }
    setClash(false);
    change(setQuietPart(settings, field, part, value));
  };

  const quietStart = parseTime(settings?.quiet_start); // 서버는 "22:00:00" 으로도 돌려준다
  const quietEnd = parseTime(settings?.quiet_end);

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
                  <View style={styles.timeLine}>
                    <Dropdown label="시작 시" value={quietStart?.hour} display={two(quietStart?.hour)} options={QUIET_HOUR_OPTIONS} onChange={(v) => pickQuiet("quiet_start", "hour", v)} />
                    <Text style={styles.sep}>:</Text>
                    <Dropdown label="시작 분" value={quietStart?.minute} display={two(quietStart?.minute)} options={QUIET_MINUTE_OPTIONS} onChange={(v) => pickQuiet("quiet_start", "minute", v)} />
                    <Text style={styles.sep}>~</Text>
                    <Dropdown label="끝 시" value={quietEnd?.hour} display={two(quietEnd?.hour)} options={QUIET_HOUR_OPTIONS} onChange={(v) => pickQuiet("quiet_end", "hour", v)} />
                    <Text style={styles.sep}>:</Text>
                    <Dropdown label="끝 분" value={quietEnd?.minute} display={two(quietEnd?.minute)} options={QUIET_MINUTE_OPTIONS} onChange={(v) => pickQuiet("quiet_end", "minute", v)} />
                  </View>
                ) : null}
              </Card>
              {isQuietOn(settings) && clash ? (
                <Text style={styles.error} accessibilityLiveRegion="polite">
                  시작과 끝 시간이 같을 수 없어요
                </Text>
              ) : null}
              {isQuietOn(settings) ? <Text style={styles.hint}>{formatQuietSummary(settings)}</Text> : null}
              <Text style={styles.hint}>알림함에는 그대로 쌓여요.</Text>
            </>
          ) : null}
        </View>
      ) : null}
    </Screen>
  );
}

/** 칸에 보일 24시간 두 자리 표기("00"). */
function two(n) {
  return String(n ?? 0).padStart(2, "0");
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
  timeLine: { flexDirection: "row", flexWrap: "nowrap", alignItems: "center", justifyContent: "center", gap: spacing.xs, paddingVertical: spacing.sm },
  sep: { ...font.bodyStrong, color: colors.textMuted },
  rowLabel: { ...font.body, color: colors.text, flex: 1, paddingRight: spacing.md },
});
