import { StyleSheet, Text, View } from "react-native";

import Card from "@/shared/components/Card";
import { colors, font } from "@/theme";

import { agoText } from "../geo";
import MapCard from "./MapCard";

const ZONE_MIN_POINTS = 5; // 서버가 활동 구역을 만드는 최소 위치 수(서버 location/service.py 와 같다)

/**
 * '내 위치' 하위 탭: 지도와 가족 공유 상태, 활동 구역 요약.
 * @param {{ me: import("../api").MyLocation, members: import("../api").MemberLocation[], canSeeFamily: boolean }} props
 */
export default function MyLocationTab({ me, members, canSeeFamily }) {
  return (
    <View style={styles.wrap}>
      <MapCard members={members} zone={me.zone} canSeeFamily={canSeeFamily} />
      <Card tone="white">
        <Text style={styles.title}>공유 상태</Text>
        {members.map((m) => (
          <Text key={m.user_id} style={styles.row}>
            {m.name}
            {m.is_me ? "(나)" : ""} · {memberState(m)}
          </Text>
        ))}
        <Text style={styles.caption}>
          {me.zone
            ? `내 활동 구역: 반지름 약 ${Math.round(me.zone.radius_m)}m (위치 ${me.zone.sample_count}개로 계산)`
            : `활동 구역은 위치가 ${ZONE_MIN_POINTS}개 모이면 만들어요 (지금 ${me.point_count}개)`}
        </Text>
      </Card>
    </View>
  );
}

/** @param {import("../api").MemberLocation} m @returns {string} */
function memberState(m) {
  if (m.paused) return "여행 모드";
  if (!m.sharing) return "공유 안 함";
  if (m.lat == null) return "위치 기다리는 중";
  return `${agoText(m.recorded_at)} · ${m.outside ? "평소 구역 밖" : "평소 구역 안"}`;
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
  title: { ...font.bodyStrong, color: colors.text },
  caption: { ...font.caption, color: colors.textSub },
  row: { ...font.caption, color: colors.text },
});
