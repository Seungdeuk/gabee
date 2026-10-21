import { StyleSheet, Text, View } from "react-native";

import Avatar from "@/shared/components/Avatar";
import { colors } from "@/theme";

/**
 * 채팅방 한 줄: 아바타, 이름과 마지막 말, 시각과 읽지 않은 개수.
 * @param {{ room: { name: string, last: string, time: string, unread: number, tone: string }, last?: boolean }} props
 */
export default function RoomRow({ room, last = false }) {
  return (
    <View style={[styles.row, !last && styles.divider]}>
      <Avatar name={room.name} tone={room.tone} />
      <View style={styles.main}>
        <Text style={styles.name}>{room.name}</Text>
        <Text style={styles.last} numberOfLines={1}>
          {room.last}
        </Text>
      </View>
      <View style={styles.side}>
        <Text style={styles.time}>{room.time}</Text>
        {room.unread > 0 ? (
          <View style={styles.badge}>
            <Text style={styles.badgeText}>{room.unread}</Text>
          </View>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 14, paddingVertical: 12 },
  divider: { borderBottomWidth: 1, borderBottomColor: colors.divider },
  main: { flex: 1, minWidth: 0, gap: 3 },
  name: { fontSize: 15, fontWeight: "700", color: colors.text },
  last: { fontSize: 13, color: colors.textSub },
  side: { alignItems: "flex-end", gap: 6 },
  time: { fontSize: 12, color: colors.textMuted },
  badge: {
    minWidth: 20,
    height: 20,
    paddingHorizontal: 6,
    borderRadius: 10,
    backgroundColor: colors.peach,
    alignItems: "center",
    justifyContent: "center",
  },
  badgeText: { fontSize: 11, fontWeight: "700", color: colors.text },
});
