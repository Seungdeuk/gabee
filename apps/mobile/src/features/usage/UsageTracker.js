import { usePathname } from "expo-router";
import { useEffect, useRef } from "react";
import { AppState } from "react-native";

import { useAuth } from "@/shared/auth/AuthProvider";

import { sendUsage } from "./api";
import { createMeter } from "./meter";
import { tabFromPath } from "./tabs";

/**
 * 앱이 화면에 떠 있던 시간을 탭별로 모아, 백그라운드로 갈 때 한 번 서버에 보낸다(체류시간).
 * - 타이머를 쓰지 않는다: "앞에 온 시각"과 "뒤로 간 시각·탭을 옮긴 시각"의 차이로만 계산한다.
 * - 값은 측정기 객체에만 두고 화면을 다시 그리지 않는다. 휴대폰 저장소에도 쓰지 않는다.
 * - 정밀한 기록이 목적이 아니라서, 보내다 실패하거나 앱이 갑자기 꺼지면 그 사용분은 빠진다.
 * - 로그인한 사람만 잰다. 화면은 없다.
 * @returns {null}
 */
export default function UsageTracker() {
  const { status } = useAuth();
  const pathname = usePathname();
  const meter = useRef(null);
  if (meter.current === null) meter.current = createMeter(tabFromPath(pathname), sendUsage);

  // 로그인되면 재기 시작, 로그아웃되면 모은 값을 버린다
  useEffect(() => {
    meter.current.setAuthed(status === "authenticated", Date.now(), AppState.currentState === "active");
  }, [status]);

  // 탭을 옮기면 앞 탭 시간을 정리하고 새 탭으로 이어서 잰다
  useEffect(() => {
    meter.current.moveTo(tabFromPath(pathname), Date.now());
  }, [pathname]);

  // 앞으로 오고 뒤로 가는 순간만 듣는다(타이머 없음)
  useEffect(() => {
    const sub = AppState.addEventListener("change", (state) => {
      if (state === "active") meter.current.begin(Date.now());
      else if (state === "background") meter.current.finish(Date.now());
      // "inactive"(아이폰에서 알림 센터를 내린 순간 등)는 잠깐이라 무시한다
    });
    return () => sub.remove();
  }, []);

  return null;
}
