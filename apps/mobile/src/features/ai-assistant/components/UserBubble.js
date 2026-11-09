import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/theme";

/**
 * 내가 보낸 말: 오른쪽 복숭아색 말풍선. 음성으로 보냈으면 아래에 작게 표시한다.
 * 사진을 올렸으면 말풍선 위에 썸네일을 함께 보여 주고, onPressImage 가 있으면 누르면 크게(확대해서) 볼 수 있다.
 * @param {{ text: string, voice?: boolean, imageUri?: string, onPressImage?: () => void }} props
 */
export default function UserBubble({ text, voice = false, imageUri, onPressImage }) {
  return (
    <View style={styles.wrap}>
      {imageUri ? (
        <Pressable onPress={onPressImage} disabled={!onPressImage} accessibilityRole="imagebutton" accessibilityLabel="올린 사진 크게 보기">
          <Image source={{ uri: imageUri }} style={styles.image} contentFit="cover" accessibilityLabel="올린 사진" />
        </Pressable>
      ) : null}
      <View style={styles.bubble}>
        <Text style={styles.text}>{text}</Text>
      </View>
      {voice ? (
        <View style={styles.meta}>
          <Ionicons name="mic-outline" size={13} color={colors.textMuted} />
          <Text style={styles.metaText}>음성으로 요청</Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: "flex-end", gap: 6 },
  image: { width: 160, height: 160, borderRadius: 14 },
  bubble: {
    maxWidth: 270,
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: 18,
    backgroundColor: colors.peach,
  },
  text: { fontSize: 15, lineHeight: 22, color: colors.text },
  meta: { flexDirection: "row", alignItems: "center", gap: 3 },
  metaText: { fontSize: 12, color: colors.textMuted },
});
