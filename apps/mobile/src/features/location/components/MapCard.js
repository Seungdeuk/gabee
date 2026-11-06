import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import { colors, font } from "@/theme";

import { agoText } from "../geo";
import { DEFAULT_CENTER } from "../mapMath";
import useDevicePosition from "../useDevicePosition";
import TileMap from "./TileMap";

const STATUS_TEXT = {
  "needs-permission": "내 위치를 지도에 보려면 위치 권한이 필요해요. 이 위치는 서버로 보내지 않고 이 화면에서만 써요.",
  denied: "위치 권한이 꺼져 있어요. 휴대폰 설정에서 가비 베타의 위치 권한을 허용해 주세요.",
  loading: "내 위치를 찾는 중이에요…",
  error: "내 위치를 가져오지 못했어요. 잠시 뒤에 다시 눌러 주세요.",
};

/**
 * 지도 카드. 서버에 위치 기록이 없어도 이 기기의 현재 위치를 지도에 바로 보여 준다(서버로 보내지 않음).
 * 가족의 마지막 위치(서버가 알려 준 것)와 내 평소 활동 구역도 함께 그린다.
 * @param {{ members: import("../api").MemberLocation[], zone: import("../api").Zone | null, canSeeFamily: boolean }} props
 */
export default function MapCard({ members, zone, canSeeFamily }) {
  const device = useDevicePosition();
  const mine = members.find((m) => m.is_me);
  const mineOnMap = mine && mine.lat != null ? { lat: mine.lat, lng: mine.lng } : null;
  const center = device.position ?? mineOnMap ?? members.find((m) => m.lat != null) ?? DEFAULT_CENTER;

  const markers = members
    .filter((m) => m.lat != null && m.lng != null && !(m.is_me && device.position))
    .map((m) => ({ id: m.user_id, label: m.name, lat: m.lat, lng: m.lng, tone: m.outside ? "alert" : m.is_me ? "me" : "member" }));
  if (device.position) markers.push({ id: "device", label: "나", lat: device.position.lat, lng: device.position.lng, tone: "me" });

  const zoneOnMap = zone ? { lat: zone.center_lat, lng: zone.center_lng, radius_m: zone.radius_m } : null;
  const known = device.position || mineOnMap || markers.length > 0;

  return (
    <Card tone="white">
      <Text style={styles.title}>{canSeeFamily ? "가족 위치 지도" : "내 위치 지도"}</Text>
      <TileMap center={center} markers={markers} zone={zoneOnMap} initialZoom={device.position || mineOnMap ? 16 : 12} />
      <View style={styles.row}>
        <Button
          label={device.position ? "내 위치로 새로고침" : "내 위치 보기"}
          variant="secondary"
          small
          onPress={device.refresh}
          disabled={device.status === "loading"}
          testID="map-my-location"
        />
      </View>
      {!known ? <Text style={styles.caption}>아직 위치를 모르는 상태라 서울시청을 보여 주고 있어요.</Text> : null}
      {STATUS_TEXT[device.status] ? <Text style={styles.caption}>{STATUS_TEXT[device.status]}</Text> : null}
      {device.position ? <Text style={styles.caption}>내 현재 위치예요{device.position.accuracy_m ? ` (오차 약 ${Math.round(device.position.accuracy_m)}m)` : ""}.</Text> : null}
      {members
        .filter((m) => !m.is_me && m.lat != null)
        .map((m) => (
          <Text key={m.user_id} style={styles.caption}>
            {m.name}: {agoText(m.recorded_at)}{m.outside ? " · 평소 구역 밖" : ""}
          </Text>
        ))}
      <Text style={styles.credit}>지도는 OpenStreetMap에서 받아 와요. 내 정확한 좌표는 보내지 않지만 보고 있는 지역의 지도 조각을 요청하므로 대략적인 지역이 전달돼요.</Text>
    </Card>
  );
}

const styles = StyleSheet.create({
  title: { ...font.bodyStrong, color: colors.text },
  caption: { ...font.caption, color: colors.textSub },
  credit: { ...font.caption, fontSize: 11, color: colors.textMuted },
  row: { flexDirection: "row" },
});
