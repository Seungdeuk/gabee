import { Redirect } from "expo-router";

// 설정 버튼과 예전 주소(/more)는 마이 페이지 탭으로 보낸다.
export default function More() {
  return <Redirect href="/my" />;
}
