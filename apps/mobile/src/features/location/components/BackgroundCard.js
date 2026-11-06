import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import { colors, font } from "@/theme";

import { setLocationBackground } from "../api";
import { isScrolledToEnd } from "../background";
import { BACKGROUND_TERMS } from "../consentText";
import { canTrackInBackground, startBackground, stopBackground } from "../backgroundControl";
import { requestBackgroundPermission } from "../sharing";

/**
 * 앱을 꺼도 위치를 계속 모으는 것(백그라운드)에 따로 동의하거나 끄는 카드.
 * 안내는 작은 상자 안에서 스크롤해 맨 아래까지 읽어야 체크할 수 있고, 체크해야 시작 버튼이 켜진다.
 * 켜기 순서: 기기에서 쓸 수 있는지 → 휴대폰 위치 권한('항상 허용') → 서버에 동의 기록 → 수집 시작. 어느 단계든 실패하면 서버 동의를 켜지 않는다.
 * @param {{ me: import("../api").MyLocation, notify: (text: string, isError?: boolean) => void, onChanged: () => void }} props
 */
export default function BackgroundCard({ me, notify, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [readAll, setReadAll] = useState(false);
  const [agreed, setAgreed] = useState(false);

  const turnOn = async () => {
    if (busy || !agreed) return;
    setBusy(true);
    try {
      if (!(await canTrackInBackground())) {
        notify("이 기기에서는 앱을 꺼도 위치를 모을 수 없어요. 개발 빌드(전용 앱)에서만 쓸 수 있어요", true);
        return;
      }
      const permission = await requestBackgroundPermission();
      if (permission !== "granted") {
        notify("휴대폰 설정에서 위치를 '항상 허용'으로 바꿔야 앱을 꺼도 공유할 수 있어요", true);
        return;
      }
      await setLocationBackground(true);
      if ((await startBackground(me.paused ? "waiting" : "normal")) !== "started") {
        await setLocationBackground(false); // 시작하지 못했는데 동의만 켜진 채로 두지 않는다
        notify("앱을 꺼도 위치를 모으는 것을 시작하지 못했어요", true);
        return;
      }
      notify("앱을 꺼도 위치를 공유해요. 상단에 공유 중 표시가 보여요");
    } catch (e) {
      notify(e.message || "처리하지 못했어요", true);
    } finally {
      setBusy(false);
      setAgreed(false);
      onChanged();
    }
  };

  const turnOff = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await stopBackground(); // 서버 응답보다 먼저 기기의 수집을 멈춘다
      await setLocationBackground(false);
      setReadAll(false);
      notify("앱을 끄면 더는 위치를 모으지 않아요");
    } catch (e) {
      notify(e.message || "처리하지 못했어요", true);
    } finally {
      setBusy(false);
      onChanged();
    }
  };

  return (
    <Card tone="white">
      <Text style={styles.title}>앱을 꺼도 계속 공유</Text>
      {me.background ? (
        <>
          <Text style={styles.caption}>
            켜져 있어요. 앱이 꺼져 있어도 위치를 모아 보내요.{me.paused ? " 지금은 여행 모드라 멈춰 있어요." : ""}
          </Text>
          <Button label="앱을 꺼도 공유 끄기" variant="secondary" onPress={turnOff} disabled={busy} testID="background-off" />
        </>
      ) : (
        <>
          <Text style={styles.caption}>아래 안내를 맨 아래까지 읽으면 동의할 수 있어요.</Text>
          <View style={styles.box}>
            <ScrollView
              style={styles.scroll}
              nestedScrollEnabled
              scrollEventThrottle={64}
              onScroll={(e) => {
                if (isScrolledToEnd(e.nativeEvent)) setReadAll(true);
              }}
              onContentSizeChange={(_, h) => {
                if (h <= 188) setReadAll(true); // 안내가 짧아 스크롤할 게 없으면 바로 읽은 것으로 본다
              }}
              testID="background-terms"
            >
              {BACKGROUND_TERMS.map((t) => (
                <View key={t.title} style={styles.term}>
                  <Text style={styles.termTitle}>{t.title}</Text>
                  <Text style={styles.termBody}>{t.body}</Text>
                </View>
              ))}
            </ScrollView>
          </View>
          <Pressable
            onPress={() => readAll && setAgreed((a) => !a)}
            disabled={!readAll}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: agreed, disabled: !readAll }}
            style={[styles.check, !readAll && styles.checkOff]}
            testID="background-check"
          >
            <View style={[styles.boxMark, agreed && styles.boxMarkOn]}>
              {agreed ? <Ionicons name="checkmark" size={16} color={colors.onDark} /> : null}
            </View>
            <Text style={styles.checkText}>{readAll ? "끝까지 읽었고, 위 내용에 동의해요" : "맨 아래까지 내리면 체크할 수 있어요"}</Text>
          </Pressable>
          <Button label="앱을 꺼도 공유 시작" onPress={turnOn} disabled={busy || !agreed} testID="background-on" />
        </>
      )}
    </Card>
  );
}

const styles = StyleSheet.create({
  title: { ...font.bodyStrong, color: colors.text },
  caption: { ...font.caption, color: colors.textSub },
  box: { borderWidth: 1, borderColor: colors.border, borderRadius: 12, backgroundColor: colors.background },
  scroll: { height: 176, paddingHorizontal: 12 },
  term: { gap: 2, paddingVertical: 6 },
  termTitle: { ...font.caption, color: colors.text, fontWeight: "700" },
  termBody: { ...font.caption, color: colors.textSub },
  check: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 4 },
  checkOff: { opacity: 0.45 },
  boxMark: { width: 24, height: 24, borderRadius: 6, borderWidth: 2, borderColor: colors.textMuted, alignItems: "center", justifyContent: "center", backgroundColor: colors.card },
  boxMarkOn: { backgroundColor: colors.dark, borderColor: colors.dark },
  checkText: { ...font.caption, color: colors.text, flex: 1 },
});
