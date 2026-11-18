import { Pressable, StyleSheet, Text, View } from "react-native";

import AuthImage from "@/shared/components/AuthImage";
import { colors, font, radius } from "@/theme";

import { bundleCells, photoCaption } from "../timeline";

/**
 * 타임라인의 묶음 카드: 같은 batch_id 로 올린 사진을 한 카드로 보인다(채팅 앨범과 같은 규칙). 1장은 큰 카드(4:3), 2장은 나란히, 3장은 위 한 장 + 아래 두 장, 4장 이상은 2×2 에 마지막 칸 "+N".
 * 칸을 누르면 그 사진부터 뷰어가 열린다("+N" 칸은 보이는 마지막 사진부터). 썸네일만 쓴다(원본은 뷰어에서만 받는다).
 * @param {{ photos: { attachment_id: string, thumb_url: string, display_at?: string, taken_at?: string | null }[], width: number, onOpen: (index: number) => void }} props photos 는 올린 순서
 */
export default function BundleCard({ photos, width, onOpen }) {
  const { cells, more } = bundleCells(photos.length, width);
  const label = (i) => (photos.length === 1 ? `${photoCaption(photos[0])} 사진, 누르면 크게 봐요` : `사진 ${photos.length}장 중 ${i + 1}번째, 누르면 크게 봐요`);
  return (
    <View style={[styles.card, { width }]} accessible={false}>
      {cells.map((cell, i) => (
        <Pressable
          key={photos[i].attachment_id}
          onPress={() => onOpen(i)}
          accessibilityRole="imagebutton"
          accessibilityLabel={label(i)}
          style={{ width: cell.width, height: cell.height }}
        >
          <AuthImage path={photos[i].thumb_url} style={{ width: cell.width, height: cell.height, borderRadius: radius.sm }} />
          {more > 0 && i === cells.length - 1 ? (
            <View style={[styles.more, { borderRadius: radius.sm }]}>
              <Text style={styles.moreText}>{`+${more}`}</Text>
            </View>
          ) : null}
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { flexDirection: "row", flexWrap: "wrap", gap: 2 },
  more: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(0,0,0,0.45)" },
  moreText: { ...font.cardTitle, color: colors.onDark },
});
