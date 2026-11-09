import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { ScrollView, StyleSheet, Text } from "react-native";

import Button from "@/shared/components/Button";
import ConfirmDialog from "@/shared/components/ConfirmDialog";
import { colors, font, fonts } from "@/theme";

import { BOMB_RED } from "../components/bomb/BombParts";
import PlayerRow from "../components/bomb/PlayerRow";
import RuleCard, { LIFE, SEC } from "../components/bomb/RuleCard";
import { useInvite } from "../components/InviteSheet";
import PlayIcon from "../components/PlayIcon";
import PlayScreen from "../components/PlayScreen";
import { GAMES } from "../games";
import { bombRoom, closeRoom } from "../mock";
import { playLive } from "../hooks";
import { LiveBombEntry, LiveBombLobby } from "./BombLiveScreens";


// 방에 들어온 가족(시안). joined 가 false 면 "초대하기" 버튼
const ROW_H = 52; // 선수 한 줄 높이
const VISIBLE_PLAYERS = 4; // 나 포함 4명까지 보이고 나머지는 이 영역 안에서 스크롤

/** 문장 폭탄 로비: 생명·시간 설정, 선수 대기 목록, 초대하기(공유 링크), 게임 시작. */
function MockBombLobbyScreen() {
  const router = useRouter();
  const { host: hostParam, life: lifeParam, sec: secParam } = useLocalSearchParams();
  const host = hostParam !== "0"; // 내가 연 방이면 방장, 초대받아 들어왔으면 손님
  const ROOM = bombRoom(host ? "me" : "mom"); // 방장 → 나 → 입장한 순서
  const [askClose, setAskClose] = useState(false);
  const [life, setLife] = useState(Number(lifeParam) || LIFE.def);
  const [sec, setSec] = useState(Number(secParam) || SEC.def);
  const joined = ROOM.filter((r) => r.joined).length;
  const { ask: askInvite, sheet: inviteSheet } = useInvite();

  return (
    <PlayScreen
      title="끝내는 순간 터진다!"
      fixed // 화면은 고정하고 선수 목록만 스크롤한다
      titleIcon={<PlayIcon icon={GAMES.bomb.icon} size={24} color={BOMB_RED} />}
      close
      footer={
        host ? (
          <>
            <Text style={styles.note}>2명부터 시작할 수 있어요 · 초대하기로 링크를 보내요</Text>
            <Button label={`게임 시작 (${joined}명)`} disabled={joined < 2} onPress={() => router.push({ pathname: "/play/bomb-play", params: { life: String(life), sec: String(sec), host: host ? "me" : "mom" } })} />
            <Button label="방 닫기" variant="secondary" onPress={() => setAskClose(true)} />
          </>
        ) : (
          <>
            <Text style={styles.note}>방장이 시작하면 바로 게임이 시작돼요</Text>
            <Button label="기다리는 중" disabled onPress={() => {}} />
          </>
        )
      }
    >
      <Text style={styles.intro}>{"차례대로 이어 말해요. 문장을 끝내면 탈락!\n마지막까지 살아남은 사람이 이겨요."}</Text>
      <RuleCard life={life} sec={sec} onLife={host ? setLife : undefined} onSec={host ? setSec : undefined} />
      <Text style={styles.section}>
        선수 대기 <Text style={styles.sectionSub}>({joined}명)</Text>
      </Text>
      <ScrollView style={styles.playerList} nestedScrollEnabled showsVerticalScrollIndicator={ROOM.length > VISIBLE_PLAYERS}>
        {ROOM.map((r) => (
          <PlayerRow key={r.id} {...r} onInvite={() => askInvite({ name: r.name, kind: "bomb" })} />
        ))}
      </ScrollView>
      {inviteSheet}
      <ConfirmDialog
        visible={askClose}
        title="방을 닫을까요?"
        message="들어온 가족은 나가게 돼요."
        confirmLabel="닫기"
        onCancel={() => setAskClose(false)}
        onConfirm={() => {
          closeRoom("s4");
          setAskClose(false);
          router.replace("/play/board?tab=sent");
        }}
      />
    </PlayScreen>
  );
}

const styles = StyleSheet.create({
  intro: { ...font.body, color: colors.text },
  playerList: { flexGrow: 0, flexShrink: 1, maxHeight: ROW_H * VISIBLE_PLAYERS },
  section: { ...font.cardTitle, color: colors.text },
  sectionSub: { fontSize: 13, fontFamily: fonts.regular, color: colors.textSub },
  note: { ...font.caption, color: colors.textSub, textAlign: "center" },
});

/** 서버에 연결되면 id 가 있는 방으로, id 가 없으면(홈의 카드) 열린 방을 찾거나 새로 연다. 아니면 시안. */
export default function BombLobbyScreen() {
  const { id } = useLocalSearchParams();
  if (!playLive()) return <MockBombLobbyScreen />;
  return id ? <LiveBombLobby id={id} /> : <LiveBombEntry />;
}
