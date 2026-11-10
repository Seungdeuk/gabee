import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { KeyboardAvoidingView, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, font, fonts } from "@/theme";

import { Bubble, PlayerStrip, TimeBar } from "../components/bomb/BombParts";
import PlayHeader from "../components/PlayHeader";
import { bombTurnOrder } from "../mock";
import { playLive } from "../hooks";
import { LiveBombSpectate } from "./BombLiveScreens";

const SEC = 10;
const CHEERS = ["힘내요", "아슬아슬", "끝내지 마!"];
const WORDS = ["누가", "어제", "학교에서", "강아지와", "춤을", "신나게", "열심히", "함께", "웃으면서", "그리고", "조용히", "천천히"];
const START = ["누가", "어제", "학교에서", "강아지와", "춤을"];
const ROUNDS_TO_END = 8; // 구경하다 보면 이만큼 더 이어진 뒤 판이 끝나 결과로 간다(시안)

const LIVES = { mom: 1, dad: 2, me: 0 }; // 시안: 남은 생명

/** 진행 순서(방장 → 나 → 입장순) 중 아직 살아 있는 상대만 추린 차례 */
const opponentsOf = (host) => bombTurnOrder(host).filter((p) => p.id !== "me");

const seed = (host) => {
  const opp = opponentsOf(host);
  return START.map((text, i) => ({ id: `s${i}`, uid: opp[i % opp.length].id, name: opp[i % opp.length].name, text }));
};

/** 탈락 뒤 관전: 판이 계속 이어지고, 응원 칩은 채팅에 올라간다. 몇 개 더 이어지면 결과 화면으로 간다. */
function MockBombSpectateScreen() {
  const router = useRouter();
  const host = useLocalSearchParams().host === "mom" ? "mom" : "me";
  const order = useMemo(() => bombTurnOrder(host), [host]);
  const opp = opponentsOf(host);
  const [msgs, setMsgs] = useState(() => seed(host));
  const [turn, setTurn] = useState(opp[0].id);
  const [left, setLeft] = useState(SEC);
  const scroll = useRef(null);
  const added = useRef(0);

  const players = order.map((p) => ({ ...p, lives: LIVES[p.id] ?? 0, total: 3, out: p.id === "me" }));

  // 차례 시간을 센다
  useEffect(() => {
    setLeft(SEC);
    const t = setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, [turn]);

  // 상대 두 명이 번갈아 말을 잇는다
  useEffect(() => {
    const wait = setTimeout(() => {
      const idx = added.current;
      if (idx >= ROUNDS_TO_END) {
        router.replace("/play/bomb-result");
        return;
      }
      added.current += 1;
      const cur = opp.find((p) => p.id === turn) ?? opp[0];
      const who = { uid: cur.id, name: cur.name };
      setMsgs((m) => [...m, { id: `n${m.length}`, ...who, text: WORDS[(m.length + idx) % WORDS.length] }]);
      setTurn(opp[(opp.findIndex((p) => p.id === turn) + 1) % opp.length].id);
    }, 2200);
    return () => clearTimeout(wait);
  }, [turn, router, opp]);

  const cheer = (text) => setMsgs((m) => [...m, { id: `c${m.length}`, uid: "me", name: "나", text: `${text}!`.replace("!!", "!"), mine: true, cheer: true }]);
  const chain = msgs.filter((m) => !m.cheer).length;
  const who = (opp.find((p) => p.id === turn) ?? opp[0]).name;

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <PlayHeader
        title="문장 폭탄"
        close
        right={
          __DEV__ ? (
            <Pressable onPress={() => router.replace("/play/bomb-result")} accessibilityRole="button" accessibilityLabel="결과 화면 보기(테스트)" hitSlop={8}>
              <Text style={styles.dev}>결과</Text>
            </Pressable>
          ) : null
        }
      />
      <View style={styles.top}>
        <PlayerStrip players={players} activeId={turn} />
        <View style={styles.timeRow}>
          <Text style={styles.timeText}>
            {who} 차례 {left}초
          </Text>
          <Text style={styles.chain}>이어가는 중 · {chain}개</Text>
        </View>
        <TimeBar left={left} total={SEC} danger={left <= 3} />
      </View>
      <KeyboardAvoidingView style={styles.flex} behavior="padding">
        <ScrollView ref={scroll} onContentSizeChange={() => scroll.current?.scrollToEnd({ animated: true })} contentContainerStyle={styles.chat}>
          <Text style={styles.sys}>탈락했어요 · 구경 중</Text>
          {msgs.map((m) => (
            <Bubble key={m.id} msg={{ id: m.uid, name: m.name, text: m.text }} mine={m.mine} />
          ))}
        </ScrollView>
        <View style={styles.bar}>
          <Text style={styles.rule}>구경 중이에요 · 탈락해도 끝까지 볼 수 있어요</Text>
          <View style={styles.chips}>
            {CHEERS.map((c) => (
              <Pressable key={c} onPress={() => cheer(c)} accessibilityRole="button" accessibilityLabel={`${c} 응원 보내기`} style={styles.chip}>
                <Text style={styles.chipText}>{c}</Text>
              </Pressable>
            ))}
          </View>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  top: { paddingHorizontal: 20, gap: 8 },
  timeRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline" },
  timeText: { fontSize: 16, fontFamily: fonts.bold, color: colors.text },
  chain: { ...font.caption, color: colors.textSub },
  chat: { paddingHorizontal: 20, paddingVertical: 12, gap: 6 },
  sys: { ...font.caption, color: colors.textSub, textAlign: "center" },
  dev: { fontSize: 12, fontFamily: fonts.bold, color: colors.textSub },
  bar: { paddingHorizontal: 20, paddingTop: 8, paddingBottom: 8, borderTopWidth: 1, borderTopColor: colors.border, gap: 6 },
  rule: { ...font.caption, color: colors.textSub, textAlign: "center" },
  chips: { flexDirection: "row", gap: 8, justifyContent: "center" },
  chip: { height: 40, paddingHorizontal: 16, borderRadius: 20, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  chipText: { fontSize: 14, fontFamily: fonts.regular, color: colors.text },
});

export default function BombSpectateScreen() {
  const { id } = useLocalSearchParams();
  return playLive() && id ? <LiveBombSpectate id={id} /> : <MockBombSpectateScreen />;
}
