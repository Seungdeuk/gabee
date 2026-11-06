import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Keyboard, KeyboardAvoidingView, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, font, fonts } from "@/theme";

import { Bubble, endsSentence, PlayerStrip, TimeBar } from "../components/bomb/BombParts";
import PlayHeader from "../components/PlayHeader";
import { bombTurnOrder } from "../mock";
import { playLive } from "../hooks";
import { LiveBombPlay } from "./BombLiveScreens";

const MAX_LEN = 10; // 한 번에 한 단어나 짧은 구, 10자까지
// 상대 차례를 흉내 내는 말들(서버 연결 전 시안). 문장을 끝내지 않는 말만 쓴다.
const SCRIPT = ["누가", "어제", "학교에서", "강아지와", "춤을", "열심히", "함께", "웃으면서", "그리고", "조용히"];

/** 문장 폭탄 플레이: 선수 줄, 시간 막대, 채팅. 내 차례에 문장을 끝내거나 시간이 다 되면 생명이 줄어든다. */
function MockBombPlayScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const total = Math.max(1, Math.min(5, parseInt(params.life, 10) || 3));
  const sec = Math.max(1, Math.min(60, parseInt(params.sec, 10) || 10));

  const host = params.host === "mom" ? "mom" : "me";
  // 진행 순서: 방장 → 나 → 입장한 순서(방장이 첫 차례)
  const [players, setPlayers] = useState(() => bombTurnOrder(host).map((p) => ({ ...p, lives: total, total, out: false })));
  const [turn, setTurn] = useState(0);
  const [left, setLeft] = useState(sec);
  const [msgs, setMsgs] = useState([]);
  const [text, setText] = useState("");
  const scroll = useRef(null);
  const live = useRef({ players, turn, msgs });
  live.current = { players, turn, msgs };
  const scriptAt = useRef(0);
  const [kb, setKb] = useState(false); // 키보드가 올라오면 위쪽을 낮추고 채팅을 맨 아래로

  useEffect(() => {
    const show = Keyboard.addListener("keyboardDidShow", () => {
      setKb(true);
      setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 60);
    });
    const hide = Keyboard.addListener("keyboardDidHide", () => setKb(false));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);

  const current = players[turn];
  const myTurn = current.id === "me" && !current.out;

  // 다음으로 살아 있는 사람에게 차례를 넘긴다
  const advance = useCallback((list, from) => {
    for (let k = 1; k <= list.length; k += 1) {
      const n = (from + k) % list.length;
      if (!list[n].out) return n;
    }
    return from;
  }, []);

  const loseLife = useCallback(
    (idx) => {
      const list = live.current.players.map((p, i) => (i === idx ? { ...p, lives: p.lives - 1, out: p.lives - 1 <= 0 } : p));
      setPlayers(list);
      if (list[idx].id === "me" && list[idx].out) return router.replace({ pathname: "/play/bomb-spectate", params: { host } });
      if (list.filter((p) => !p.out).length <= 1) return router.replace("/play/bomb-result");
      setTurn(advance(list, idx));
      return undefined;
    },
    [advance, host, router],
  );

  // 차례마다 시간을 다시 센다. 0이 되면 시간 초과로 생명이 줄어든다.
  useEffect(() => {
    setLeft(sec);
    const tick = setInterval(() => setLeft((s) => s - 1), 1000);
    return () => clearInterval(tick);
  }, [turn, sec]);
  useEffect(() => {
    if (left <= 0) {
      setMsgs((m) => [...m, { id: `t${m.length}`, name: current.name, uid: current.id, text: "(시간 초과)", system: true }]);
      loseLife(turn);
    }
  }, [left]); // eslint-disable-line react-hooks/exhaustive-deps

  // 상대 차례: 잠깐 뒤 한 단어를 보낸다
  useEffect(() => {
    if (current.id === "me" || current.out) return undefined;
    const wait = setTimeout(() => {
      const word = SCRIPT[scriptAt.current % SCRIPT.length];
      scriptAt.current += 1;
      setMsgs((m) => [...m, { id: `m${m.length}`, name: current.name, uid: current.id, text: word }]);
      setTurn((t) => advance(live.current.players, t));
    }, 1500 + (turn % 3) * 600);
    return () => clearTimeout(wait);
  }, [turn]); // eslint-disable-line react-hooks/exhaustive-deps

  const send = () => {
    const word = text.trim();
    if (!word || !myTurn) return;
    setText("");
    setMsgs((m) => [...m, { id: `m${m.length}`, name: "나", uid: "me", text: word, mine: true }]);
    if (endsSentence(word)) {
      loseLife(turn);
    } else {
      setTurn(advance(live.current.players, turn));
    }
  };

  const chain = msgs.filter((m) => !m.system).length;
  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <PlayHeader
        title="문장 폭탄"
        close
        fallback="/play/bomb-lobby"
        right={
          __DEV__ ? (
            <View style={styles.devRow}>
              <Pressable onPress={() => router.replace("/play/bomb-result")} accessibilityRole="button" accessibilityLabel="결과 화면 보기(테스트)" hitSlop={8}>
                <Text style={styles.dev}>결과</Text>
              </Pressable>
            </View>
          ) : null
        }
      />
      <View style={styles.top}>
        <PlayerStrip players={players} activeId={current.id} compact={kb} />
        <View style={styles.timeRow}>
          <Text style={styles.timeText} accessibilityLiveRegion="polite">
            {myTurn ? "내 차례" : `${current.name} 차례`} {Math.max(0, left)}초
          </Text>
          <Text style={styles.chain}>이어가는 중 · {chain}개</Text>
        </View>
        <TimeBar left={left} total={sec} danger={left <= 3} />
      </View>
      <KeyboardAvoidingView style={styles.flex} behavior="padding">
        <ScrollView ref={scroll} onContentSizeChange={() => scroll.current?.scrollToEnd({ animated: true })} contentContainerStyle={styles.chat}>
          <Text style={styles.sys}>
            {players.length}명 · 생명 {total}개 · {sec}초
          </Text>
          {msgs.map((m) => (m.system ? <Text key={m.id} style={styles.sys}>{m.name} {m.text}</Text> : <Bubble key={m.id} msg={{ id: m.uid, name: m.name, text: m.text }} mine={m.mine} />))}
        </ScrollView>
        <View style={styles.bar}>
          {kb ? null : <Text style={styles.rule}>한 단어나 짧은 구, {MAX_LEN}자까지 · 끝내는 말을 하면 생명이 줄어요</Text>}
          <View style={styles.inputRow}>
            <TextInput
              value={text}
              onChangeText={(v) => setText(v.slice(0, MAX_LEN))}
              editable={myTurn}
              placeholder={myTurn ? "이어 말하기" : "차례를 기다려요"}
              placeholderTextColor={colors.placeholder}
              accessibilityLabel="이어 말하기"
              onSubmitEditing={send}
              style={[styles.input, !myTurn && styles.inputOff]}
            />
            <Pressable onPress={send} disabled={!myTurn || !text.trim()} accessibilityRole="button" accessibilityLabel="보내기" style={[styles.send, (!myTurn || !text.trim()) && styles.sendOff]}>
              <Text style={styles.sendText}>보내기</Text>
            </Pressable>
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
  devRow: { flexDirection: "row", gap: 14 }, // 개발용 바로가기(테스트)
  dev: { fontSize: 12, fontFamily: fonts.bold, color: colors.textSub },
  sys: { ...font.caption, color: colors.textSub, textAlign: "center" },
  bar: { paddingHorizontal: 20, paddingTop: 8, paddingBottom: 8, borderTopWidth: 1, borderTopColor: colors.border, gap: 8 },
  rule: { ...font.caption, color: colors.textSub },
  inputRow: { flexDirection: "row", gap: 8 },
  input: { flex: 1, height: 40, paddingVertical: 0, paddingHorizontal: 14, borderRadius: 20, borderWidth: 1, borderColor: "#E3CFB0", backgroundColor: colors.card, color: colors.text, fontSize: 15, lineHeight: 18, includeFontPadding: false, textAlignVertical: "center", fontFamily: fonts.regular }, // 안드로이드 글꼴 여백을 빼서 커서가 칸 높이만큼 길어지지 않게
  inputOff: { borderColor: colors.border, backgroundColor: colors.surface },
  send: { minWidth: 68, height: 40, borderRadius: 20, backgroundColor: colors.peach, alignItems: "center", justifyContent: "center" },
  sendOff: { backgroundColor: colors.honeySoft },
  sendText: { fontSize: 15, fontFamily: fonts.bold, color: colors.text },
});

export default function BombPlayScreen() {
  const { id } = useLocalSearchParams();
  return playLive() && id ? <LiveBombPlay id={id} /> : <MockBombPlayScreen />;
}
