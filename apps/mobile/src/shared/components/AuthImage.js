import { Image } from "expo-image";
import { StyleSheet, View } from "react-native";

import useProfilePhoto from "@/shared/hooks/useProfilePhoto";
import { colors } from "@/theme";

/**
 * 로그인이 필요한 서버 이미지(프로필 사진·채팅 사진). 서버가 준 상대 경로를 로그인 헤더로 받는다
 * (허용되는 경로 모양은 shared/photoCache.js 의 photoPath 가 정한다). 받는 동안·실패하면 옅은 바탕만 보인다.
 * onLoad 는 사진 크기를 알아야 할 때(그림 위에 네모를 겹칠 때 등) { source: { width, height } } 를 받는다.
 * @param {{ path: string | null | undefined, style?: object, contentFit?: "cover" | "contain", accessibilityLabel?: string, onLoad?: (event: { source: { width: number, height: number } }) => void }} props
 */
export default function AuthImage({ path, style, contentFit = "cover", accessibilityLabel, onLoad }) {
  const { source, markFailed } = useProfilePhoto(path);
  return (
    <View style={[styles.box, style]}>
      {source ? (
        <Image
          source={source}
          style={StyleSheet.absoluteFill}
          contentFit={contentFit}
          cachePolicy="memory-disk"
          transition={150}
          onError={markFailed}
          onLoad={onLoad}
          accessibilityLabel={accessibilityLabel}
          accessibilityIgnoresInvertColors
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { backgroundColor: colors.surface, overflow: "hidden" },
});
