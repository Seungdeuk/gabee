import MoreScreen from "@/features/more/screens/MoreScreen";
import useFamilyState from "@/features/family-group/useFamilyState";
import { relationText } from "@/features/family-group/relations";
import { roleLabel } from "@/features/family-group/messages";
import { useAuth } from "@/shared/auth/AuthProvider";

/**
 * 마이 탭 라우트: 가족 정보(기능이 달라 여기서 읽는다)를 마이 페이지 화면에 넘겨 조립한다.
 * 프로필 둘째 줄에는 가족 이름과 내 가족 내 역할(관계가 있으면 관계, 없으면 권한)을 보인다.
 */
export default function MyRoute() {
  const { user } = useAuth();
  const family = useFamilyState({ pollMs: 10000 }); // 가입 요청 수를 몇 초마다 새로 확인한다
  const group = family.status === "member" ? family.group : null;
  const me = group?.members?.find((m) => m.id === user?.id);
  const roleText = group ? relationText(me) || roleLabel(group.my_role) : null;
  return <MoreScreen groupName={group?.name ?? null} roleText={roleText} pendingCount={family.pendingCount ?? 0} />;
}
