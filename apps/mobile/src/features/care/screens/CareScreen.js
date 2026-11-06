import { LocationHome } from "@/features/location/public";

/**
 * 위치 탭(위치 베타 브랜치): 위치 기능만 보인다(내 위치, 이동 기록, 여행 모드, 설정). 화면 조립은 features/location 이 맡는다.
 * 지갑(정산·지출·용돈) 화면 코드는 features/billing 에 그대로 있고 이 탭에서만 뺐다. 라우트 이름(care)과 폴더 이름은 그대로 둔다.
 * feature/hojenn-location-beta 에만 있고 release/1.2 에 병합하지 않는다.
 */
export default function CareScreen() {
  return <LocationHome />;
}
