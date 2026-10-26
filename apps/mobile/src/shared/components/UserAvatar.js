import { Image } from "expo-image";
import { View } from "react-native";

import Avatar from "@/shared/components/Avatar";
import useProfilePhoto from "@/shared/hooks/useProfilePhoto";

const RING = 2;

/**
 * 사람의 아바타. 프로필 사진(photoUrl)이 있으면 사진을, 없거나 받지 못하면 이니셜+구성원 색 Avatar 를 보여 준다.
 * 사진은 로그인이 필요해서 로그인 헤더로 받는다(photoUrl 은 서버가 준 상대 경로 그대로).
 * @param {{ name: string, userId?: string, photoUrl?: string | null, tone?: string, size?: number, ring?: boolean }} props
 */
export default function UserAvatar({ photoUrl, ...avatarProps }) {
  const { source, markFailed } = useProfilePhoto(photoUrl);
  if (!source) return <Avatar {...avatarProps} />;
  const size = avatarProps.size ?? 44;
  const inset = avatarProps.ring ? RING : 0;
  return (
    <View style={{ width: size, height: size, borderRadius: size / 2, overflow: "hidden" }}>
      <Avatar {...avatarProps} />
      <Image
        source={source}
        style={{ position: "absolute", top: inset, left: inset, width: size - inset * 2, height: size - inset * 2, borderRadius: (size - inset * 2) / 2 }}
        contentFit="cover"
        cachePolicy="memory-disk"
        transition={150}
        onError={markFailed}
        accessibilityIgnoresInvertColors
      />
    </View>
  );
}
