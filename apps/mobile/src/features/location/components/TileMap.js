import { useState } from "react";
import { Image, Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

import { MAX_ZOOM, MIN_ZOOM, TILE, clampZoom, metersPerPixel, project, tileUrl, tilesFor } from "../mapMath";

const HEADERS = { "User-Agent": "GabeeBeta/1.0 (family location beta)" };

/**
 * 실제 지도 위에 사람(핀)과 평소 활동 구역(원)을 그린다. OpenStreetMap 타일을 이미지로 받아 이어 붙이는 방식이라 별도 지도 키가 필요 없다.
 * 확대·축소 버튼만 있고 끌어서 옮기지는 못한다. 지도 조각을 받을 때 보는 지역의 타일 주소가 OpenStreetMap 에 전달된다(내 정확한 좌표는 보내지 않는다).
 * @param {{ center: { lat: number, lng: number }, markers: { id: string, label: string, lat: number, lng: number, tone?: "me" | "member" | "alert" }[], zone?: { lat: number, lng: number, radius_m: number, alert?: boolean } | null, height?: number, initialZoom?: number }} props
 */
export default function TileMap({ center, markers, zone = null, height = 260, initialZoom = 16 }) {
  const [width, setWidth] = useState(0);
  const [zoom, setZoom] = useState(clampZoom(initialZoom));
  const size = { width, height };
  const tiles = width ? tilesFor(center, zoom, size) : [];
  const zoneR = zone ? zone.radius_m / metersPerPixel(zone.lat, zoom) : 0;
  const zoneAt = zone ? project(zone, center, zoom, size) : null;

  return (
    <View style={[styles.map, { height }]} onLayout={(e) => setWidth(e.nativeEvent.layout.width)} testID="tile-map" accessibilityLabel="지도">
      {tiles.map((t) => (
        <Image key={t.key} source={{ uri: tileUrl(t), headers: HEADERS }} style={[styles.tile, { left: t.left, top: t.top }]} />
      ))}
      {zoneAt && zoneR > 2 ? (
        <View
          pointerEvents="none"
          style={[
            styles.zone,
            zone.alert && styles.zoneAlert,
            { left: zoneAt.x - zoneR, top: zoneAt.y - zoneR, width: zoneR * 2, height: zoneR * 2, borderRadius: zoneR },
          ]}
        />
      ) : null}
      {width
        ? markers.map((m) => {
            const at = project(m, center, zoom, size);
            return (
              <View key={m.id} pointerEvents="none" style={[styles.pinWrap, { left: at.x - 16, top: at.y - 32 }]}>
                <View style={[styles.pin, m.tone === "me" && styles.pinMe, m.tone === "alert" && styles.pinAlert]}>
                  <Text style={styles.pinText}>{m.label.slice(0, 1)}</Text>
                </View>
                <View style={[styles.pinTip, m.tone === "me" && styles.pinTipMe, m.tone === "alert" && styles.pinTipAlert]} />
              </View>
            );
          })
        : null}
      <View style={styles.zoomBox}>
        <Pressable onPress={() => setZoom((z) => clampZoom(z + 1))} disabled={zoom >= MAX_ZOOM} accessibilityRole="button" accessibilityLabel="확대" style={styles.zoomBtn}>
          <Text style={styles.zoomText}>＋</Text>
        </Pressable>
        <Pressable onPress={() => setZoom((z) => clampZoom(z - 1))} disabled={zoom <= MIN_ZOOM} accessibilityRole="button" accessibilityLabel="축소" style={styles.zoomBtn}>
          <Text style={styles.zoomText}>－</Text>
        </Pressable>
      </View>
      <Text style={styles.credit}>© OpenStreetMap 기여자</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  map: { borderRadius: 18, overflow: "hidden", backgroundColor: colors.honeySoft, borderWidth: 1, borderColor: colors.border },
  tile: { position: "absolute", width: TILE, height: TILE },
  zone: { position: "absolute", borderWidth: 2, borderColor: colors.success, backgroundColor: colors.successSoft, opacity: 0.5 },
  zoneAlert: { borderColor: colors.danger, backgroundColor: colors.dangerSoft },
  pinWrap: { position: "absolute", width: 32, alignItems: "center" },
  pin: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.dark, alignItems: "center", justifyContent: "center", borderWidth: 2, borderColor: colors.card },
  pinMe: { backgroundColor: colors.primary },
  pinAlert: { backgroundColor: colors.danger },
  pinTip: { width: 0, height: 0, borderLeftWidth: 5, borderRightWidth: 5, borderTopWidth: 8, borderLeftColor: "transparent", borderRightColor: "transparent", borderTopColor: colors.dark },
  pinTipMe: { borderTopColor: colors.primary },
  pinTipAlert: { borderTopColor: colors.danger },
  pinText: { color: colors.onDark, fontWeight: "700", fontSize: 14 },
  zoomBox: { position: "absolute", right: 8, top: 8, borderRadius: 12, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
  zoomBtn: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  zoomText: { fontSize: 20, color: colors.text },
  credit: { position: "absolute", left: 6, bottom: 4, ...font.caption, fontSize: 10, color: colors.textSub, backgroundColor: colors.card, paddingHorizontal: 4, opacity: 0.85 },
});
