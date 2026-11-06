import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, StyleSheet, Switch, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import IconButton from "@/shared/components/IconButton";
import Screen from "@/shared/components/Screen";
import { colors, font, spacing } from "@/theme";

import { getPushSettings, savePushSettings } from "../api";
import { KIND_META } from "../kinds";
import { isQuietOn, toggleKind, withQuiet } from "../push";

const KIND_KEYS = ["chat", "schedule", "billing", "care", "family_group", "ai_record", "support"];

/** 마이 > 알림 설정: 푸시 켜기·끄기, 분류별 켜기·끄기, 메시지 내용 표시 방식, 방해금지 시간. 바꾸는 즉시 저장한다. */
export default function PushSettingsScreen() {
  const router = useRouter();
  const [settings, setSettings] = useState(null);
  const [status, setStatus] = useState("loading"); // loading | ready | error
  const [saveError, setSaveError] = useState(false);

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

  const change = async (next) => {
    const previous = settings;
    setSettings(next); // 바로 보여 주고, 저장에 실패하면 되돌린다
    setSaveError(false);
    try {
      setSettings(await savePushSettings(next));
    } catch {
      setSettings(previous);
      setSaveError(true);
    }
  };

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
                <Row
                  label="밤 10시 ~ 아침 7시에는 푸시 끄기"
                  value={isQuietOn(settings)}
                  onChange={(on) => change(withQuiet(settings, on))}
                />
              </Card>
              <Text style={styles.hint}>알림함에는 그대로 쌓여요.</Text>
            </>
          ) : null}
        </View>
      ) : null}
    </Screen>
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
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: spacing.sm },
  rowLabel: { ...font.body, color: colors.text, flex: 1, paddingRight: spacing.md },
});
