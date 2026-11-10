import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Keyboard, KeyboardAvoidingView, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import Avatar from "@/shared/components/Avatar";
import Button from "@/shared/components/Button";
import ConfirmDialog from "@/shared/components/ConfirmDialog";
import { colors, font, fonts, radius } from "@/theme";

import { bombChat, bombPath, lobbyPlayers, nextTurnPlayerId, recordNote, unfairMessageId } from "../adapt";
import { chatBomb, cheerBomb, closeBomb, createBomb, joinBomb, leaveBomb, sayBomb, startBomb, startBombVote, voteBomb } from "../api";
import { Bubble, BOMB_RED, PlayerStrip, TimeBar } from "../components/bomb/BombParts";
import PlayerRow from "../components/bomb/PlayerRow";
import RuleCard, { LIFE, SEC } from "../components/bomb/RuleCard";
import VoteBanner from "../components/bomb/VoteBanner";
import { useInvite } from "../components/InviteSheet";
import LoadNote from "../components/LoadNote";
import PlayHeader from "../components/PlayHeader";
import PlayIcon from "../components/PlayIcon";
import PlayScreen from "../components/PlayScreen";
import { GAMES, SCORE } from "../games";
import { useBombRedirect, useBombRoom, useBombRooms, useMyId } from "../hooks";
import { leaveToPlayMain } from "../nav";

/*
 * 서버에 연결됐을 때 쓰는 문장 폭탄 화면들. 방 상태는 useBombRoom 이 1초마다 서버에서 받고(폴링),
 * 상태가 바뀌면(게임 시작·탈락·판 끝남) useBombRedirect 가 알맞은 화면으로 옮겨 준다.
 */

const MAX_LEN = 10; // 한 번에 한 단어나 짧은 구, 10자까지
const ROW_H = 52;
const VISIBLE_PLAYERS = 4;

const PHASE_LABEL = { lobby: "대기 중", playing: "게임 중", finished: "게임 끝" };

/** 열린 방 한 줄: 방장 이름, 상태 칩, 들어온 사람 얼굴, 규칙. dim 이면 눌리지 않는다(내가 다른 방에 있을 때). */
function RoomCard({ room, mine = false, dim = false, onPress }) {
  const action = mine ? "돌아가기" : room.phase === "playing" ? "구경하기" : "들어가기";
  return (
    <Pressable
      disabled={dim}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${room.host.name} 방. ${PHASE_LABEL[room.phase]}. ${room.players.length}명 입장. ${dim ? "지금 방에서 나가야 들어갈 수 있어요" : action}`}
      style={[styles.roomCard, mine && styles.roomMine, dim && styles.roomDim]}
    >
      <View style={styles.roomTop}>
        <Text style={styles.roomName}>{room.host.name} 방</Text>
        <Text style={[styles.roomChip, room.phase === "playing" && styles.roomChipPlay]}>{PHASE_LABEL[room.phase]}</Text>
      </View>
      <View style={styles.faces}>
        {room.players.slice(0, 6).map((p) => (
          <Avatar key={p.id} name={p.name} userId={p.id} size={24} />
        ))}
      </View>
      <Text style={styles.roomMeta}>
        {room.players.length}명 입장 · 생명 {room.life} · {room.sec}초
      </Text>
      {dim ? null : <Text style={styles.roomGo}>{action} ›</Text>}
    </Pressable>
  );
}

/** 홈의 "문장 폭탄" 카드: 열린 방 목록. 눌러서 들어가거나 새 방을 만든다. 한 사람은 한 방에만 있을 수 있어 내가 방에 있으면 다른 방·새 방은 막힌다. */
export function LiveBombEntry() {
  const router = useRouter();
  const { rooms, error, refresh } = useBombRooms();
  const [busy, setBusy] = useState(false);
  const [makeError, setMakeError] = useState("");
  const mine = rooms?.find((r) => r.mine) ?? null;
  const others = (rooms ?? []).filter((r) => !r.mine);
  const open = (room) => router.push(bombPath("lobby", room.id));
  const create = async () => {
    if (busy || mine) return;
    setBusy(true);
    setMakeError("");
    try {
      open(await createBomb());
    } catch (e) {
      setMakeError(e.message || "방을 열지 못했어요");
      refresh();
    } finally {
      setBusy(false);
    }
  };
  return (
    <PlayScreen title="문장 폭탄" titleIcon={<PlayIcon icon={GAMES.bomb.icon} size={24} color={BOMB_RED} />} close>
      <Text style={styles.noteLeft}>{mine ? "지금 방에서 나가야 다른 방에 들어갈 수 있어요" : "열린 방에 들어가거나 새 방을 만들어요"}</Text>
      <Button label="새 방 만들기" disabled={busy || !!mine || rooms == null} onPress={create} />
      {makeError ? <Text style={styles.error}>{makeError}</Text> : null}
      <LoadNote loading={rooms == null && !error} error={rooms == null ? error : ""} data={rooms} reload={refresh} what="방 목록" />
      {rooms != null && mine ? (
        <>
          <Text style={styles.section}>내가 있는 방</Text>
          <RoomCard room={mine} mine onPress={() => open(mine)} />
        </>
      ) : null}
      {rooms != null && others.length > 0 ? (
        <>
          <Text style={styles.section}>
            {mine ? "다른 방" : "열린 방"} <Text style={styles.sectionSub}>({others.length}개)</Text>
          </Text>
          {others.map((r) => (
            <RoomCard key={r.id} room={r} dim={!!mine} onPress={() => open(r)} />
          ))}
          {mine ? <Text style={styles.noteLeft}>다른 방에 들어가거나 새 방을 열려면 먼저 내 방에서 “방 나가기”를 눌러요</Text> : null}
        </>
      ) : null}
      {rooms != null && !mine && others.length === 0 ? <Text style={styles.emptyRooms}>{"열린 방이 없어요\n새 방을 만들면 가족이 들어올 수 있어요"}</Text> : null}
    </PlayScreen>
  );
}

// ---------- 로비 ----------
export function LiveBombLobby({ id }) {
  const router = useRouter();
  const { room, error, busy, act } = useBombRoom(id);
  useBombRedirect(room, "lobby");
  const [life, setLife] = useState(LIFE.def);
  const [sec, setSec] = useState(SEC.def);
  const [askClose, setAskClose] = useState(false);
  const { ask: askInvite, sheet: inviteSheet } = useInvite();
  const myId = useMyId();
  if (!room) {
    return (
      <PlayScreen title="끝내는 순간 터진다!" close>
        <LoadNote loading={!error} error={error} data={null} reload={() => {}} what="방" />
      </PlayScreen>
    );
  }
  const joined = room.players.filter((p) => p.joined).length;
  const entered = room.my_status !== "none"; // 방에 들어와 있나(들어오기 전이 대기방, 들어온 뒤가 로비)
  const shown = lobbyPlayers(room.players, myId, entered, room.is_host);
  const invitees = room.players.filter((p) => !p.joined); // 아직 안 들어온 가족(로비 목록에는 없고 아래 초대하기로만 부른다)
  const isClosed = room.phase === "closed";
  let footer;
  if (isClosed) {
    footer = (
      <>
        <Text style={styles.note}>방이 닫혔어요</Text>
        <Button label="나가기" onPress={() => leaveToPlayMain(router)} />
      </>
    );
  } else if (room.is_host) {
    footer = (
      <>
        {error ? <Text style={styles.error}>{error}</Text> : <Text style={styles.note}>2명부터 시작할 수 있어요 · 초대하기로 공유 링크를 보내요</Text>}
        <Button label={`게임 시작 (${joined}명)`} disabled={joined < 2 || busy} onPress={() => act(() => startBomb(id, { life, sec }))} />
        <Button label="방 닫기" variant="secondary" onPress={() => setAskClose(true)} />
      </>
    );
  } else if (room.my_status === "none") {
    footer = (
      <>
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <Button label="방에 들어가기" disabled={busy} onPress={() => act(() => joinBomb(id))} />
      </>
    );
  } else {
    footer = (
      <>
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <Button label="기다리는 중" disabled onPress={() => {}} />
        <Button
          label="방 나가기"
          variant="secondary"
          onPress={async () => {
            if (await act(() => leaveBomb(id))) leaveToPlayMain(router);
          }}
        />
      </>
    );
  }
  return (
    <PlayScreen
      title="끝내는 순간 터진다!"
      fixed // 화면은 고정하고 선수 목록만 스크롤한다
      titleIcon={<PlayIcon icon={GAMES.bomb.icon} size={24} color={BOMB_RED} />}
      close
      footer={footer}
    >
      <Text style={styles.intro}>{"차례대로 이어 말해요. 문장을 끝내면 생명이 줄어요!\n마지막까지 살아남은 사람이 이겨요."}</Text>
      <RuleCard life={room.is_host ? life : room.life} sec={room.is_host ? sec : room.sec} onLife={room.is_host ? setLife : undefined} onSec={room.is_host ? setSec : undefined} />
      {room.is_host ? null : <Text style={styles.noteLeft}>생명과 시간은 방장이 시작할 때 정해요</Text>}
      {room.is_host || isClosed ? null : entered ? (
        <View style={[styles.state, styles.stateAfter]} accessible accessibilityLabel="방에 들어왔어요. 방장이 시작하면 바로 게임이 시작돼요">
          <Text style={styles.stateTitleAfter}>방에 들어왔어요</Text>
          <Text style={styles.stateTextAfter}>방장이 시작하면 바로 게임이 시작돼요</Text>
        </View>
      ) : (
        <View style={[styles.state, styles.stateBefore]} accessible accessibilityLabel="아직 들어가지 않았어요">
          <Text style={styles.stateTitleBefore}>아직 들어가지 않았어요</Text>
          <Text style={styles.stateTextBefore}>{room.phase === "playing" ? "게임 중이에요. 들어가면 구경할 수 있어요" : "들어가면 방장이 시작할 때 함께해요"}</Text>
        </View>
      )}
      <Text style={styles.section}>
        {entered && !room.is_host ? "선수 대기" : "방에 부른 가족"} <Text style={styles.sectionSub}>({entered && !room.is_host ? `${joined}명` : `${joined}/${room.players.length}명 입장`})</Text>
      </Text>
      <ScrollView style={styles.playerList} nestedScrollEnabled showsVerticalScrollIndicator={shown.length > VISIBLE_PLAYERS}>
        {shown.map((p) => (
          <PlayerRow
            key={p.id}
            id={p.id}
            name={p.name}
            note={p.host && p.id === myId ? "방장 · 나" : p.host ? "방장" : p.id === myId ? "나" : ""}
            joined={p.joined}
            mine={entered && p.id === myId && !p.host}
            onInvite={() => askInvite({ name: p.name, kind: "bomb" })}
          />
        ))}
      </ScrollView>
      {entered && !room.is_host && !isClosed && invitees.length > 0 ? (
        <Pressable
          onPress={() => askInvite({ name: invitees.length === 1 ? invitees[0].name : "가족", kind: "bomb" })}
          accessibilityRole="button"
          accessibilityLabel={`가족 초대하기. 아직 안 들어온 가족 ${invitees.length}명`}
          style={styles.inviteMore}
        >
          <Text style={styles.inviteMoreText}>+ 가족 초대하기 · 아직 {invitees.length}명이 안 들어왔어요</Text>
        </Pressable>
      ) : null}
      {inviteSheet}
      <ConfirmDialog
        visible={askClose}
        title="방을 닫을까요?"
        message="들어온 가족은 나가게 돼요."
        confirmLabel="닫기"
        onCancel={() => setAskClose(false)}
        onConfirm={async () => {
          setAskClose(false);
          if (await act(() => closeBomb(id))) leaveToPlayMain(router);
        }}
      />
    </PlayScreen>
  );
}

// ---------- 게임 화면(공통 윗부분) ----------
function GameTop({ room, left, compact = false, activeId }) {
  const players = room.players.filter((p) => p.lives != null).map((p) => ({ id: p.id, name: p.name, lives: p.lives, total: p.total, out: p.out }));
  const who = room.turn?.player;
  return (
    <View style={styles.top}>
      <PlayerStrip players={players} activeId={activeId ?? who?.id} compact={compact} />
      <View style={styles.timeRow}>
        <Text style={[styles.timeText, compact && styles.timeTextSm]} accessibilityLiveRegion="polite">
          {who ? `${who.name} 차례 ${Math.ceil(left ?? 0)}초` : room.phase === "finished" ? "게임이 끝났어요" : "잠시만요"}
        </Text>
        {compact ? null : <Text style={styles.chain}>이어가는 중 · {room.chain}개</Text>}
      </View>
      <TimeBar left={left ?? 0} total={room.turn?.limit ?? room.sec} danger={(left ?? 0) <= 3} />
    </View>
  );
}

function Chat({ chat, header, onCall, onUnfair, footer }) {
  const scroll = useRef(null);
  return (
    <ScrollView ref={scroll} onContentSizeChange={() => scroll.current?.scrollToEnd({ animated: true })} contentContainerStyle={styles.chat}>
      {header ? <Text style={styles.sys}>{header}</Text> : null}
      {chat.map((m) =>
        m.kind === "system" ? (
          <Text key={m.id} style={styles.sys}>
            {m.text}
          </Text>
        ) : (
          <View key={m.id} style={styles.msgWrap}>
            <Bubble msg={{ id: m.uid, name: m.name, text: m.text, chat: m.chat }} mine={m.mine} />
            {m.call && onCall ? (
              <Pressable onPress={onCall} accessibilityRole="button" accessibilityLabel="어라? 끝난 말인데 통과됐어요" style={styles.callChip}>
                <Text style={styles.callChipText}>어라?</Text>
              </Pressable>
            ) : null}
            {m.unfair && onUnfair ? (
              <Pressable onPress={onUnfair} accessibilityRole="button" accessibilityLabel="억울해요 끝난 말이 아닌데 탈락했어요" style={[styles.callChip, styles.unfairChip]}>
                <Text style={styles.callChipText}>억울해요</Text>
              </Pressable>
            ) : null}
          </View>
        ),
      )}
      {footer}
    </ScrollView>
  );
}

/** 판이 끝난 뒤 게임 채팅창 아래: 대화를 더 보다가 결과를 보거나 나간다(끝나자마자 결과로 튕기지 않는다). */
function EndBar({ onResult, onLeave }) {
  return (
    <View style={styles.bar}>
      <Text style={styles.rule}>게임이 끝났어요</Text>
      <View style={styles.footerRow}>
        <View style={styles.footerCell}>
          <Button label="나가기" variant="secondary" onPress={onLeave} />
        </View>
        <View style={styles.footerCell}>
          <Button label="결과 보기" onPress={onResult} />
        </View>
      </View>
    </View>
  );
}

// ---------- 게임 ----------
export function LiveBombPlay({ id }) {
  const router = useRouter();
  const { room, error, busy, act, left, voteLeft } = useBombRoom(id);
  const myId = useMyId();
  useBombRedirect(room, "play");
  const [text, setText] = useState("");
  const [kb, setKb] = useState(false); // 키보드가 올라오면 위쪽을 낮춘다
  useEffect(() => {
    const show = Keyboard.addListener("keyboardDidShow", () => setKb(true));
    const hide = Keyboard.addListener("keyboardDidHide", () => setKb(false));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);
  if (!room) {
    return (
      <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
        <PlayHeader title="문장 폭탄" close fallback="/play" />
        <View style={styles.pad}>
          <LoadNote loading={!error} error={error} data={null} reload={() => {}} what="게임" />
        </View>
      </SafeAreaView>
    );
  }
  const myTurn = room.turn?.player.id === myId && !room.vote; // 투표 중에는 이어 말할 수 없다
  const nextIsMe = !myTurn && !room.vote && room.phase === "playing" && nextTurnPlayerId(room) === myId; // 내 바로 앞사람이 말하는 중
  const send = async () => {
    const word = text.trim();
    if (!word || !myTurn || busy) return;
    setText("");
    await act(() => sayBomb(id, word));
  };
  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <PlayHeader title="문장 폭탄" close fallback="/play" onBack={() => leaveToPlayMain(router)} compact={kb} />
      <GameTop room={room} left={left} compact={kb} />
      {room.vote ? <VoteBanner vote={room.vote} left={voteLeft} busy={busy} onVote={(yes) => act(() => voteBomb(id, yes))} /> : null}
      <KeyboardAvoidingView style={styles.flex} behavior="padding">
        <Chat
          chat={bombChat(room.messages, myId, room.can_call ? room.call_msg_id : null, room.can_unfair ? unfairMessageId(room.messages, myId) : null)}
          onCall={() => act(() => startBombVote(id, "call"))}
          onUnfair={busy ? undefined : () => act(() => startBombVote(id, "unfair"))}
        />
        {room.phase === "finished" ? (
          <EndBar onResult={() => router.push(bombPath("result", id))} onLeave={() => router.replace(bombPath("lobby", id))} />
        ) : (
        <View style={styles.bar}>
          {nextIsMe ? <Text style={styles.nextBadge} accessibilityLiveRegion="polite">다음은 내 차례예요</Text> : null}
          {error ? <Text style={styles.error}>{error}</Text> : kb ? null : <Text style={styles.rule}>한 단어나 짧은 구, {MAX_LEN}자까지 · 끝내는 말을 하면 생명이 줄어요</Text>}
          <View style={styles.inputRow}>
            <TextInput
              value={text}
              onChangeText={(v) => setText(v.slice(0, MAX_LEN))}
              editable={myTurn || nextIsMe} // 내 바로 앞사람 차례에도 미리 칠 수 있다(보내기는 내 차례가 돼야 눌림, 쳐 둔 글자는 그대로 둔다)
              placeholder={myTurn ? "이어 말하기" : room.vote ? "투표 중이에요" : nextIsMe ? "곧 내 차례예요" : "차례를 기다려요"}
              placeholderTextColor={colors.placeholder}
              accessibilityLabel="이어 말하기"
              onSubmitEditing={send}
              style={[styles.input, !(myTurn || nextIsMe) && styles.inputOff]}
            />
            <Pressable onPress={send} disabled={!myTurn || !text.trim() || busy} accessibilityRole="button" accessibilityLabel="보내기" style={[styles.send, (!myTurn || !text.trim() || busy) && styles.sendOff]}>
              <Text style={styles.sendText}>보내기</Text>
            </Pressable>
          </View>
        </View>
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

// ---------- 관전 ----------
export function LiveBombSpectate({ id }) {
  const router = useRouter();
  const { room, error, busy, act, left, voteLeft, cheerLeft, chatLeft } = useBombRoom(id);
  const myId = useMyId();
  useBombRedirect(room, "spectate");
  const [mode, setMode] = useState("chat"); // 채팅(탈락한 사람끼리) / 응원(모두에게)
  const [askLeave, setAskLeave] = useState(false);
  const [kb, setKb] = useState(false); // 키보드가 올라오면 위쪽을 줄이고 입력 칸만 남겨서 채팅이 보이게 한다
  useEffect(() => {
    const show = Keyboard.addListener("keyboardDidShow", () => setKb(true));
    const hide = Keyboard.addListener("keyboardDidHide", () => setKb(false));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);
  const [text, setText] = useState("");
  if (!room) {
    return (
      <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
        <PlayHeader title="문장 폭탄" close fallback="/play" />
        <View style={styles.pad}>
          <LoadNote loading={!error} error={error} data={null} reload={() => {}} what="게임" />
        </View>
      </SafeAreaView>
    );
  }
  const chatMode = mode === "chat";
  const waiting = (chatMode ? chatLeft : cheerLeft) > 0; // 난타 방지: 보낸 뒤 2초는 쉰다
  const cheerWaiting = cheerLeft > 0;
  const send = async () => {
    const t = text.trim();
    if (!t || waiting || busy) return;
    setText("");
    await act(() => (chatMode ? chatBomb(id, t) : cheerBomb(id, t)));
  };
  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <PlayHeader
        title="문장 폭탄"
        close
        fallback="/play"
        onBack={() => leaveToPlayMain(router)}
        compact={kb}
        right={
          room.is_host ? null : (
            <Pressable onPress={() => setAskLeave(true)} accessibilityRole="button" accessibilityLabel="방 나가기" hitSlop={8}>
              <Ionicons name="exit-outline" size={22} color={colors.text} />
            </Pressable>
          )
        }
      />
      <GameTop room={room} left={left} compact={kb} />
      {room.vote ? <VoteBanner vote={room.vote} left={voteLeft} busy={busy} onVote={(yes) => act(() => voteBomb(id, yes))} /> : null}
      <KeyboardAvoidingView style={styles.flex} behavior="padding">
        <Chat
          chat={bombChat(room.messages, myId, null, room.can_unfair ? unfairMessageId(room.messages, myId) : null)}
          header={room.my_status === "out" ? "탈락했어요" : "구경 중이에요"}
          onUnfair={busy ? undefined : () => act(() => startBombVote(id, "unfair"))}
        />
        {room.phase === "finished" ? (
          <EndBar onResult={() => router.push(bombPath("result", id))} onLeave={() => router.replace(bombPath("lobby", id))} />
        ) : (
          <View style={styles.bar}>
            <View style={[styles.seg, kb && styles.hide]}>
              {[["chat", "채팅"], ["cheer", "응원"]].map(([key, label]) => (
                <Pressable key={key} onPress={() => setMode(key)} accessibilityRole="button" accessibilityState={{ selected: mode === key }} style={[styles.segBtn, mode === key && styles.segOn]}>
                  <Text style={[styles.segText, mode === key && styles.segTextOn]}>{label}</Text>
                </Pressable>
              ))}
            </View>
            {chatMode ? null : (
              <View style={styles.chips}>
                {room.cheers.map((c) => (
                  <Pressable key={c} onPress={() => act(() => cheerBomb(id, c))} disabled={cheerWaiting} accessibilityRole="button" accessibilityState={{ disabled: cheerWaiting }} accessibilityLabel={`${c} 응원 보내기`} style={[styles.chip, cheerWaiting && styles.chipOff]}>
                    <Text style={[styles.chipText, cheerWaiting && styles.chipTextOff]}>{c}</Text>
                  </Pressable>
                ))}
              </View>
            )}
            <View style={styles.inputRow}>
              {kb ? (
                <Pressable onPress={() => setMode(chatMode ? "cheer" : "chat")} accessibilityRole="button" accessibilityLabel={`${chatMode ? "채팅" : "응원"} 중, 누르면 ${chatMode ? "응원" : "채팅"}으로 바꿔요`} style={styles.modeBtn}>
                  <Text style={styles.modeBtnText}>{chatMode ? "채팅" : "응원"}</Text>
                </Pressable>
              ) : null}
              <TextInput
                value={text}
                onChangeText={(v) => setText(v.slice(0, chatMode ? 50 : 20))}
                placeholder={chatMode ? "메시지 보내기" : "직접 응원 쓰기"}
                placeholderTextColor={colors.placeholder}
                accessibilityLabel={chatMode ? "채팅 메시지" : "직접 쓰는 응원"}
                onSubmitEditing={send}
                style={styles.input}
              />
              <Pressable onPress={send} disabled={!text.trim() || waiting || busy} accessibilityRole="button" accessibilityLabel={chatMode ? "채팅 보내기" : "응원 보내기"} style={[styles.send, (!text.trim() || waiting || busy) && styles.sendOff]}>
                <Text style={styles.sendText}>{chatMode ? "보내기" : "응원"}</Text>
              </Pressable>
            </View>
            {error ? (
              <Text style={styles.error}>{error}</Text>
            ) : (
              <Text style={[styles.rule, kb && styles.hide]}>
                {waiting ? `${Math.ceil(chatMode ? chatLeft : cheerLeft)}초 뒤에 다시 보낼 수 있어요` : chatMode ? "탈락한 사람끼리만 보여요, 50자까지" : "살아있는 사람에게도 보여요, 20자까지"}
              </Text>
            )}
          </View>
        )}
      </KeyboardAvoidingView>
      <ConfirmDialog
        visible={askLeave}
        title="방에서 나갈까요?"
        message="나가면 이 판은 더 볼 수 없어요. 다른 방에 들어갈 수 있어요."
        confirmLabel="나가기"
        onCancel={() => setAskLeave(false)}
        onConfirm={async () => {
          setAskLeave(false);
          if (await act(() => leaveBomb(id))) leaveToPlayMain(router);
        }}
      />
    </SafeAreaView>
  );
}

// ---------- 결과 ----------
export function LiveBombResult({ id }) {
  const router = useRouter();
  const { room, error, busy, act } = useBombRoom(id);
  const myId = useMyId();
  useBombRedirect(room, "result");
  const result = room?.result;
  if (!room || !result) {
    return (
      <PlayScreen title="결과" close>
        <LoadNote loading={!error} error={error} data={null} reload={() => {}} what="결과" />
      </PlayScreen>
    );
  }
  const canAgain = room.is_host && room.phase === "finished";
  return (
    <PlayScreen
      title="결과"
      close
      onBack={() => (router.canGoBack() ? router.back() : router.replace(bombPath("lobby", id)))} // 게임 채팅창에서 왔으면 채팅창으로, 아니면 로비로
      fixed
      footer={
        <>
          {error ? <Text style={styles.error}>{error}</Text> : null}
          {!room.is_host && room.phase === "finished" ? <Text style={styles.note}>방장이 한 판 더를 시작하면 이어서 해요</Text> : null}
          <View style={styles.footerRow}>
            <View style={styles.footerCell}>
              <Button label="닫기" variant="secondary" onPress={() => router.replace(bombPath("lobby", id))} />
            </View>
            {canAgain ? (
              <View style={styles.footerCell}>
                <Button label="한 판 더" disabled={busy} onPress={() => act(() => startBomb(id, { life: room.life, sec: room.sec }))} />
              </View>
            ) : null}
          </View>
        </>
      }
    >
      <View style={styles.topBoxes}>
        <View style={[styles.box, styles.winner]}>
          <Text style={[styles.tag, { color: colors.accent }]}>최후의 1인</Text>
          <Text style={styles.big}>{result.winner?.name ?? "없음"}</Text>
        </View>
        <View style={[styles.box, styles.record]}>
          <Text style={[styles.tag, { color: "#2F4A3B" }]}>이번 판 기록</Text>
          <Text style={[styles.big, { color: "#2F4A3B" }]}>{result.longest_len}개</Text>
          {recordNote(result) ? <Text style={styles.recordNote}>{recordNote(result)}</Text> : null}
        </View>
      </View>
      <Text style={styles.section}>순위</Text>
      <ScrollView style={styles.list} contentContainerStyle={styles.listContent} showsVerticalScrollIndicator={false}>
        {result.ranking.map((r) => (
          <View key={r.player.id} style={[styles.row, r.player.id === myId && styles.rowMine, r.rank === 1 && styles.rowFirst]}>
            <Text style={styles.no}>{r.rank}</Text>
            <Avatar name={r.player.name} userId={r.player.id} size={40} />
            <View style={styles.rowText}>
              <Text style={styles.rowName}>{r.player.name}</Text>
              <Text style={styles.rowSub}>{r.sub}</Text>
            </View>
            <Text style={styles.points}>+{r.points}점</Text>
          </View>
        ))}
      </ScrollView>
      {result.my_points != null ? (
        <View style={styles.mine}>
          <Text style={styles.mineBig}>내가 받은 점수 {result.my_points}점</Text>
          <Text style={styles.mineSub}>
            {result.maker_paid_before ? `이 방에서는 이미 문제 내기 +${SCORE.make}을 받았어요` : `참여 +${SCORE.join} 우승하면 +${SCORE.bombWin}`}
          </Text>
        </View>
      ) : null}
    </PlayScreen>
  );
}

const ROW = 64;
const VISIBLE = 3; // 순위는 3줄만 보이고 나머지는 목록 안에서 스크롤

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  pad: { padding: 20 },
  intro: { ...font.body, color: colors.text },
  playerList: { flexGrow: 0, flexShrink: 1, maxHeight: ROW_H * VISIBLE_PLAYERS },
  section: { ...font.cardTitle, color: colors.text },
  sectionSub: { fontSize: 13, fontFamily: fonts.regular, color: colors.textSub },
  note: { ...font.caption, color: colors.textSub, textAlign: "center" },
  noteLeft: { ...font.caption, color: colors.textSub },
  error: { ...font.caption, color: colors.danger, fontFamily: fonts.bold, textAlign: "center" },
  top: { paddingHorizontal: 20, gap: 8 },
  timeRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline" },
  timeText: { fontSize: 16, fontFamily: fonts.bold, color: colors.text },
  timeTextSm: { fontSize: 13 },
  chain: { ...font.caption, color: colors.textSub },
  chat: { paddingHorizontal: 20, paddingVertical: 12, gap: 6 },
  sys: { ...font.caption, color: colors.textSub, textAlign: "center" },
  bar: { paddingHorizontal: 20, paddingTop: 8, paddingBottom: 8, borderTopWidth: 1, borderTopColor: colors.border, gap: 8 },
  rule: { ...font.caption, color: colors.textSub, textAlign: "center" },
  inputRow: { flexDirection: "row", gap: 8 },
  input: { flex: 1, height: 40, paddingVertical: 0, paddingHorizontal: 14, borderRadius: 20, borderWidth: 1, borderColor: "#E3CFB0", backgroundColor: colors.card, color: colors.text, fontSize: 15, lineHeight: 18, includeFontPadding: false, textAlignVertical: "center", fontFamily: fonts.regular },
  inputOff: { borderColor: colors.border, backgroundColor: colors.surface },
  send: { minWidth: 68, height: 40, borderRadius: 20, backgroundColor: colors.peach, alignItems: "center", justifyContent: "center" },
  sendOff: { backgroundColor: colors.honeySoft },
  sendText: { fontSize: 15, fontFamily: fonts.bold, color: colors.text },
  msgWrap: { gap: 3 },
  inviteMore: { alignSelf: "center", paddingVertical: 8, paddingHorizontal: 12 },
  inviteMoreText: { fontSize: 13, fontFamily: fonts.bold, color: "#8A5A2B" },
  roomCard: { padding: 14, gap: 8, borderRadius: radius.card, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card },
  roomMine: { borderWidth: 2, borderColor: "#E3CFB0", padding: 13 },
  roomDim: { opacity: 0.55 },
  roomTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  roomName: { ...font.bodyStrong, color: colors.text, flexShrink: 1 },
  roomChip: { paddingVertical: 3, paddingHorizontal: 10, borderRadius: 12, overflow: "hidden", backgroundColor: colors.successSoft, color: "#2F4A3B", fontSize: 12, fontFamily: fonts.bold },
  roomChipPlay: { backgroundColor: "#FBEAE3", color: BOMB_RED },
  faces: { flexDirection: "row", gap: 4 },
  roomMeta: { ...font.caption, color: colors.textSub },
  roomGo: { alignSelf: "flex-end", fontSize: 13, fontFamily: fonts.bold, color: "#8A5A2B" },
  emptyRooms: { ...font.body, color: colors.textSub, textAlign: "center", paddingVertical: 32 },
  state: { paddingVertical: 10, paddingHorizontal: 14, borderRadius: radius.lg, gap: 2 },
  stateBefore: { borderWidth: 1, borderStyle: "dashed", borderColor: "#8A5A2B", backgroundColor: colors.surface },
  stateAfter: { backgroundColor: colors.successSoft },
  stateTitleBefore: { fontSize: 14, fontFamily: fonts.bold, color: colors.text },
  stateTextBefore: { ...font.caption, color: colors.textSub },
  stateTitleAfter: { fontSize: 14, fontFamily: fonts.bold, color: "#2F4A3B" },
  stateTextAfter: { ...font.caption, color: "#2F4A3B" },
  nextBadge: { alignSelf: "center", paddingVertical: 4, paddingHorizontal: 14, borderRadius: 14, overflow: "hidden", backgroundColor: colors.peach, color: colors.text, fontSize: 13, fontFamily: fonts.bold },
  callChip: { alignSelf: "flex-start", marginLeft: 32, height: 24, paddingHorizontal: 10, borderRadius: 12, borderWidth: 1, borderColor: BOMB_RED, backgroundColor: "#FBEAE3", alignItems: "center", justifyContent: "center" },
  callChipText: { fontSize: 12, lineHeight: 16, fontFamily: fonts.bold, color: BOMB_RED },
  unfairChip: { alignSelf: "flex-end", marginLeft: 0 }, // 내 말풍선은 오른쪽이라 칩도 오른쪽 아래
  hide: { display: "none" },
  modeBtn: { height: 40, paddingHorizontal: 12, borderRadius: 20, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  modeBtnText: { fontSize: 13, fontFamily: fonts.bold, color: colors.text },
  seg: { flexDirection: "row", alignSelf: "center", borderWidth: 1, borderColor: colors.border, borderRadius: 999, overflow: "hidden" },
  segBtn: { paddingVertical: 4, paddingHorizontal: 20, backgroundColor: colors.card },
  segOn: { backgroundColor: colors.text },
  segText: { fontSize: 13, lineHeight: 18, fontFamily: fonts.regular, color: colors.text },
  segTextOn: { fontFamily: fonts.bold, color: colors.card },
  chips: { flexDirection: "row", gap: 8, justifyContent: "center" },
  chip: { height: 40, paddingHorizontal: 16, borderRadius: 20, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  chipOff: { backgroundColor: colors.surface },
  chipText: { fontSize: 14, fontFamily: fonts.regular, color: colors.text },
  chipTextOff: { color: colors.disabled },
  footerRow: { flexDirection: "row", gap: 10 },
  footerCell: { flex: 1 },
  topBoxes: { flexDirection: "row", gap: 12 },
  box: { flex: 1, padding: 16, borderRadius: radius.card, alignItems: "center", justifyContent: "flex-start", gap: 4 },
  winner: { backgroundColor: colors.surfaceStrong },
  record: { backgroundColor: colors.successSoft },
  tag: { fontSize: 13, lineHeight: 18, fontFamily: fonts.bold, textAlign: "center" },
  big: { fontSize: 28, lineHeight: 36, fontFamily: fonts.bold, color: colors.text, textAlign: "center" },
  recordNote: { ...font.caption, color: "#2F4A3B", textAlign: "center" },
  list: { flexGrow: 0, flexShrink: 1, maxHeight: ROW * VISIBLE + 8 * (VISIBLE - 1) },
  listContent: { gap: 8 },
  row: { minHeight: ROW, flexDirection: "row", alignItems: "center", gap: 14, paddingHorizontal: 16, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card },
  rowFirst: { borderColor: colors.surfaceStrong, backgroundColor: colors.surfaceStrong },
  rowMine: { borderWidth: 2, borderColor: "#E3CFB0", paddingHorizontal: 15 },
  no: { width: 24, fontSize: 18, fontFamily: fonts.bold, color: colors.textSub },
  rowText: { flex: 1 },
  rowName: { ...font.bodyStrong, color: colors.text },
  rowSub: { ...font.caption, color: colors.textSub },
  points: { ...font.bodyStrong, color: colors.text },
  mine: { padding: 14, borderRadius: radius.lg, backgroundColor: colors.surface, alignItems: "center", gap: 2 },
  mineBig: { ...font.bodyStrong, color: colors.text },
  mineSub: { ...font.caption, color: colors.textSub },
});
