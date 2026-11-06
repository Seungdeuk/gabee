import * as Location from "expo-location";
import { useCallback, useEffect, useState } from "react";

/**
 * 이 기기의 현재 위치를 지도에 보이기 위해 읽는다. 서버로 보내지 않고 이 화면에서만 쓴다(위치 공유 동의와 상관없이 본인 화면 확인용).
 * 권한이 이미 있으면 화면을 열 때 읽고, 없으면 refresh()(버튼)로 권한을 물은 뒤 읽는다.
 * @returns {{ status: "idle" | "needs-permission" | "denied" | "loading" | "ok" | "error", position: { lat: number, lng: number, accuracy_m: number | null } | null, refresh: () => Promise<void> }}
 */
export default function useDevicePosition() {
  const [state, setState] = useState({ status: "idle", position: null });

  const read = useCallback(async (askPermission) => {
    try {
      let permission = await Location.getForegroundPermissionsAsync();
      if (permission.status !== "granted") {
        if (!askPermission) {
          setState({ status: "needs-permission", position: null });
          return;
        }
        permission = await Location.requestForegroundPermissionsAsync();
        if (permission.status !== "granted") {
          setState({ status: "denied", position: null });
          return;
        }
      }
      setState((prev) => ({ ...prev, status: "loading" }));
      const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      setState({
        status: "ok",
        position: { lat: loc.coords.latitude, lng: loc.coords.longitude, accuracy_m: loc.coords.accuracy ?? null },
      });
    } catch {
      setState({ status: "error", position: null });
    }
  }, []);

  useEffect(() => {
    read(false);
  }, [read]);

  return { ...state, refresh: () => read(true) };
}
