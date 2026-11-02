import { useRouter } from "expo-router";

import Button from "@/shared/components/Button";

import { joinPromptVisible } from "../joinPrompt";
import useFamilyState from "../useFamilyState";

/** 홈 인사말 아래 버튼: 가족 그룹이 없는 사람이 받은 초대 코드로 바로 참여하러 갈 수 있게 한다. 가족이 있으면 아무것도 그리지 않는다. */
export default function JoinFamilyPrompt() {
  const router = useRouter();
  const family = useFamilyState();
  if (!joinPromptVisible(family.status)) return null;
  return <Button label="가족 초대 코드로 참여하기" icon="people-outline" variant="secondary" onPress={() => router.push("/family-join")} testID="home-family-join" />;
}
