import * as Device from "expo-device";
import { useRouter } from "expo-router";
import * as SecureStore from "expo-secure-store";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Platform } from "react-native";

import {
  ApiError,
  clearSession,
  configureAuth,
  getRefreshToken,
  isApiConfigured,
  setSession,
} from "@/shared/api/client";

import { getMe, login, logoutOnServer } from "./sessionApi";
import { createTokenStore } from "./tokenStore";

// Refresh Token 만 기기의 보안 저장소(iOS Keychain / Android Keystore)에 둔다. 웹에는 없어서 메모리만 쓴다.
const store = createTokenStore(Platform.OS === "web" ? null : SecureStore);

const AuthContext = createContext(null);

/**
 * 로그인 상태.
 * - loading: 앱을 켠 직후 저장된 세션을 확인하는 중
 * - authenticated: 정식 회원으로 로그인됨 (user 에 사용자 정보)
 * - anonymous: 로그인 세션 없음 (기존 익명 계정/개발용 토큰 방식은 이 상태에서 그대로 동작)
 * - unreachable: 저장된 세션은 있지만 서버에 연결하지 못함 (세션은 지우지 않는다)
 */
export function AuthProvider({ children }) {
  const router = useRouter();
  const [state, setState] = useState({ status: "loading", user: null });
  const lastRedirect = useRef(0);

  // 클라이언트(shared/api/client.js)가 세션 이벤트를 앱에 알린다
  useEffect(() => {
    configureAuth({
      onRefreshTokenChanged: (token) => store.save(token),
      onSessionLost: () => {
        store.clear();
        setState({ status: "anonymous", user: null });
      },
      onEmailNotVerified: () => {
        // 동시에 여러 요청이 403 이어도 안내 화면은 한 번만 연다
        if (Date.now() - lastRedirect.current < 3000) return;
        lastRedirect.current = Date.now();
        router.navigate("/verify-email");
      },
    });
  }, [router]);

  const restore = useCallback(async () => {
    setState({ status: "loading", user: null });
    if (!isApiConfigured()) {
      setState({ status: "anonymous", user: null });
      return;
    }
    const refreshToken = await store.load();
    if (!refreshToken) {
      setState({ status: "anonymous", user: null });
      return;
    }
    setSession({ refreshToken }); // Access Token 은 첫 요청에서 자동으로 받는다
    try {
      setState({ status: "authenticated", user: await getMe() });
    } catch (e) {
      if (e instanceof ApiError && e.code === "network_error") {
        setState({ status: "unreachable", user: null });
      } else if (!(e instanceof ApiError && e.code === "session_expired")) {
        clearSession();
        await store.clear();
        setState({ status: "anonymous", user: null });
      } // session_expired 는 onSessionLost 가 이미 처리했다
    }
  }, []);

  useEffect(() => {
    restore();
  }, [restore]);

  const signIn = useCallback(async (loginId, password) => {
    const label = (Device.deviceName ?? Device.modelName ?? Platform.OS).slice(0, 60);
    const res = await login(loginId, password, label);
    setSession({ accessToken: res.access_token, refreshToken: res.refresh_token });
    await store.save(res.refresh_token);
    setState({ status: "authenticated", user: res.user });
    return res.user;
  }, []);

  const signOut = useCallback(async () => {
    const refreshToken = getRefreshToken();
    if (refreshToken) {
      try {
        await logoutOnServer(refreshToken); // 서버 세션 종료. 실패해도 이 기기의 로그아웃은 계속한다
      } catch {
        // 오프라인이면 서버 세션은 만료 때까지 남지만, 이 기기에서는 토큰을 지운다
      }
    }
    clearSession();
    await store.clear();
    setState({ status: "anonymous", user: null });
  }, []);

  const refreshUser = useCallback(async () => {
    const user = await getMe();
    setState({ status: "authenticated", user });
    return user;
  }, []);

  const value = useMemo(
    () => ({ ...state, signIn, signOut, refreshUser, restore }),
    [state, signIn, signOut, refreshUser, restore],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** @returns {{ status: "loading" | "authenticated" | "anonymous" | "unreachable", user: object | null, signIn: (loginId: string, password: string) => Promise<object>, signOut: () => Promise<void>, refreshUser: () => Promise<object>, restore: () => Promise<void> }} */
export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth 는 AuthProvider 안에서만 쓸 수 있어요");
  return value;
}
