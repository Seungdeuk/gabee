import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

import { projectItems } from "../geo";

const HEIGHT = 240;

/**
 * 지도 타일 없이 가족의 마지막 위치와 평소 활동 구역을 상대 위치로 그린다(베타). 북쪽이 위쪽이다.
 * @param {{ members: import("../api").MemberLocation[] }} props 위치가 있는 구성원만 그린다
 */
export default function FamilyMap({ members }) {
  const [width, setWidth] = useState(0);
  const shown = members.filter((m) => m.lat != null && m.lng != null);
  const placed = width ? projectItems(shown.map((m) => ({ id: m.user_id, lat: m.lat, lng: m.lng, zone: m.zone })), { width, height: HEIGHT }) : [];
  const byId = Object.fromEntries(placed.map((p) => [p.id, p]));
  return (
    <View style={styles.map} onLayout={(e) => setWidth(e.nativeEvent.layout.width)} testID="family-map" accessibilityLabel="가족 위치 지도">
      <Text style={styles.north}>북 ↑</Text>
      {shown.map((m) => {
        const p = byId[m.user_id];
        if (!p) return null;
        return (
          <View key={m.user_id}>
            {p.zone ? (
              <View
                style={[
                  styles.zone,
                  m.outside && styles.zoneOut,
                  { left: p.zone.x - p.zone.r, top: p.zone.y - p.zone.r, width: p.zone.r * 2, height: p.zone.r * 2, borderRadius: p.zone.r },
                ]}
              />
            ) : null}
            <View style={[styles.pin, m.outside && styles.pinOut, { left: p.x - 16, top: p.y - 16 }]}>
              <Text style={styles.pinText}>{m.name.slice(0, 1)}</Text>
            </View>
          </View>
        );
      })}
      {!shown.length ? <Text style={styles.empty}>아직 보이는 위치가 없어요</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  map: { height: HEIGHT, borderRadius: 18, backgroundColor: colors.honeySoft, borderWidth: 1, borderColor: colors.border, overflow: "hidden", justifyContent: "center" },
  north: { position: "absolute", top: 8, right: 12, ...font.caption, color: colors.textMuted },
  empty: { ...font.caption, color: colors.textMuted, textAlign: "center" },
  zone: { position: "absolute", borderWidth: 2, borderColor: colors.success, backgroundColor: colors.successSoft, opacity: 0.55 },
  zoneOut: { borderColor: colors.danger, backgroundColor: colors.dangerSoft },
  pin: { position: "absolute", width: 32, height: 32, borderRadius: 16, backgroundColor: colors.dark, alignItems: "center", justifyContent: "center", borderWidth: 2, borderColor: colors.card },
  pinOut: { backgroundColor: colors.danger },
  pinText: { color: colors.onDark, fontWeight: "700", fontSize: 14 },
});
