import MoreScreen from "@/features/more/screens/MoreScreen";
import useFamilyState from "@/features/family-group/useFamilyState";
import { relationText } from "@/features/family-group/relations";
import { roleLabel } from "@/features/family-group/messages";

/**
 * 마이 탭 라우트: 가족 정보(기능이 달라 여기서 읽는다)를 마이 페이지 화면에 넘겨 조립한다.
 * 프로필에는 가족 안에서 쓰는 내 이름·사진과 "가족 이름 · 역할"(관계가 있으면 관계, 없으면 권한)을 보인다.
 * 승인 대기 중·불러오는 중·오류일 때는 그 상태를 알려 주고, "내 정보 수정"은 가족 구성원일 때만 보인다.
 * @returns {import("react").ReactElement}
 */
export default function MyRoute() {
  const family = useFamilyState({ pollMs: 10000 }); // 가입 요청 수·승인 결과를 몇 초마다 새로 확인한다
  const group = family.status === "member" ? family.group : null;
  const me = group?.members?.find((m) => m.id === group.my_id);
  let groupName = group?.name ?? null;
  let roleText = null;
  if (group) roleText = relationText(me) || roleLabel(group.my_role);
  else if (family.status === "pending") {
    groupName = family.request?.group_name ?? null;
    roleText = "승인 대기 중";
  } else if (family.status === "loading") roleText = "불러오는 중…";
  else if (family.status === "error") roleText = "가족 정보를 불러오지 못했어요";
  return (
    <MoreScreen
      displayName={me?.display_name || me?.name || null}
      photoUrl={me?.photo_url ?? null}
      groupName={groupName}
      roleText={roleText}
      canEdit={Boolean(group)}
      pendingCount={family.pendingCount ?? 0}
    />
  );
}
