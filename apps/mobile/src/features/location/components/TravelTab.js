import { useState } from "react";
import { StyleSheet, Text } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import Segmented from "@/shared/components/Segmented";
import { colors, font } from "@/theme";

import { setLocationPause } from "../api";
import { PAUSE_OPTIONS, pauseDays } from "../pause";
import { describePause, previewPause } from "../travel";
import { todayKst } from "../timelineView";

/**
 * '여행 모드' 하위 탭. 날짜(1·3·7일, 기타 1~14일)만 정하면 마지막 날이 끝나는 자정(한국 시간)에 자동으로 다시 공유한다.
 * 진행 중에는 D-day 와 재개 시각을 보이고, 원하면 지금 바로 다시 공유할 수 있다.
 * @param {{ me: import("../api").MyLocation, busy: boolean, run: (job: () => Promise<unknown>, okText?: string) => void, notify: (text: string, isError?: boolean) => void }} props
 */
export default function TravelTab({ me, busy, run, notify }) {
  const [pauseKey, setPauseKey] = useState("3");
  const [customDays, setCustomDays] = useState("");
  const pause = pauseDays(pauseKey, customDays);

  if (me.paused && me.paused_until) {
    const p = describePause(me.paused_until);
    return (
      <Card tone="white">
        <Text style={styles.title}>여행 모드 중 · {p.ddayText}</Text>
        <Text style={styles.big}>{p.untilText}</Text>
        <Text style={styles.caption}>{p.resumeText}. 그때 부모님께 다시 공유한다고 알려요.</Text>
        <Text style={styles.caption}>멈춰 있는 동안은 위치를 보내지 않고, 구역을 벗어나도 알리지 않아요.</Text>
        <Button label="지금 바로 다시 공유하기" variant="secondary" onPress={() => run(() => setLocationPause(null), "위치 공유를 다시 시작했어요")} disabled={busy} />
      </Card>
    );
  }

  const preview = pause.days != null ? previewPause(todayKst(), pause.days) : null;
  const start = () => {
    if (pause.days == null) {
      notify(pause.error, true);
      return;
    }
    run(() => setLocationPause(pause.days), `위치 공유를 ${pause.days}일 동안 멈췄어요`);
  };

  return (
    <Card tone="white">
      <Text style={styles.title}>여행 모드</Text>
      <Text style={styles.caption}>
        여행처럼 평소와 다른 곳에 갈 때 잠시 멈춰요. 멈췄다는 사실만 부모님께 알리고, 끝나는 날 자정에 자동으로 다시 공유해요.
      </Text>
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
      {preview ? (
        <Text style={styles.preview}>
          오늘부터 {preview.untilText} 멈추고, {preview.resumeText}
        </Text>
      ) : null}
      <Button
        label={pause.days != null ? `${pause.days}일 동안 멈추기` : "기간을 정해 주세요"}
        onPress={start}
        disabled={busy || pause.days == null}
        testID="pause-start"
      />
    </Card>
  );
}

const styles = StyleSheet.create({
  title: { ...font.bodyStrong, color: colors.text },
  big: { ...font.title, color: colors.text },
  caption: { ...font.caption, color: colors.textSub },
  preview: { ...font.caption, color: colors.text, fontWeight: "600" },
});
