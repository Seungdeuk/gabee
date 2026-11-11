import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect } from "react";
import { ActivityIndicator, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors } from "@/theme";

import { listRooms } from "../api";
import { chatRouteFor } from "../chatOpen";

/**
 * 소통 푸시를 눌렀을 때 거치는 화면. 푸시에는 방 id 만 있어서 방 목록으로 가족방인지 1:1 인지(상대는 누구인지) 찾아
 * 알맞은 채팅방으로 바꿔서(replace) 열고, 못 찾거나 불러오지 못하면 소통 탭 목록으로 보낸다. 잠깐 로딩만 보인다.
 */
export default function ChatOpenScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const roomId = typeof params.roomId === "string" ? params.roomId : undefined;

  useEffect(() => {
    let alive = true;
    listRooms().then(
      (rooms) => alive && router.replace(chatRouteFor(rooms, roomId)),
      () => alive && router.replace(chatRouteFor(null, roomId)), // 목록을 못 읽어도 막히지 않게 소통 탭으로
    );
    return () => {
      alive = false;
    };
  }, [roomId, router]);

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} accessibilityLabel="채팅방을 여는 중" />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
});
