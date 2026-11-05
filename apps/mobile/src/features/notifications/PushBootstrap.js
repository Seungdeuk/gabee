import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { useRouter } from "expo-router";
import { useEffect } from "react";
import { Alert, Platform } from "react-native";

import { onBeforeSignOut } from "@/shared/auth/signOutHooks";
import { useAuth } from "@/shared/auth/AuthProvider";

import { registerPushToken, unregisterPushToken } from "./api";
import { PUSH_INTRO_BODY, PUSH_INTRO_TITLE, PUSH_CHANNEL_NAME } from "./messages";
import { PUSH_CHANNEL_ID, isUsableToken, routeForPush, shouldRegister } from "./push";

// 앱이 켜져 있을 때 푸시가 오면 상단 배너로 보여 준다(웹에는 푸시가 없다).
if (Platform.OS !== "web") {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: false,
      shouldSetBadge: false,
    }),
  });
}

/** 이 기기에서 서버에 등록한 푸시 토큰(로그아웃 때 해제하려고 기억한다). */
let registeredToken = null;

/**
 * 권한을 처음 묻기 전에 한 번 안내한다. 확인을 눌러야 시스템 권한 창으로 넘어간다.
 * @returns {Promise<void>}
 */
function showIntro() {
  return new Promise((resolve) => {
    Alert.alert(PUSH_INTRO_TITLE, PUSH_INTRO_BODY, [{ text: "확인", onPress: () => resolve() }], {
      onDismiss: () => resolve(),
    });
  });
}

/**
 * 푸시 권한을 확인하고(처음이면 안내 후 요청) 허용됐는지 돌려준다.
 * @returns {Promise<boolean>}
 */
async function ensurePermission() {
  const current = await Notifications.getPermissionsAsync();
  if (current.status === "granted") return true;
  if (!current.canAskAgain) return false;
  await showIntro();
  const asked = await Notifications.requestPermissionsAsync();
  return asked.status === "granted";
}

/**
 * 이 기기의 Expo 푸시 토큰을 받아 서버에 등록한다. 거절·오류·에뮬레이터 실패는 조용히 넘긴다(알림함은 그대로 쓴다).
 * @returns {Promise<void>}
 */
async function registerThisDevice() {
  try {
    if (Platform.OS === "android") {
      await Notifications.setNotificationChannelAsync(PUSH_CHANNEL_ID, {
        name: PUSH_CHANNEL_NAME,
        importance: Notifications.AndroidImportance.HIGH,
      });
    }
    if (!(await ensurePermission())) return;
    const projectId = Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
    const { data: token } = await Notifications.getExpoPushTokenAsync({ projectId });
    if (!isUsableToken(token)) return;
    await registerPushToken({
      token,
      platform: Platform.OS === "ios" ? "ios" : "android",
      deviceLabel: Device.deviceName ?? Device.modelName ?? null,
    });
    registeredToken = token;
  } catch {
    // 토큰을 못 받아도(Expo Go·에뮬레이터·오프라인) 앱 사용에는 영향이 없다
  }
}

/**
 * 이 기기의 푸시 토큰을 서버에서 해제한다(로그아웃 직전). 실패해도 던지지 않는다.
 * @returns {Promise<void>}
 */
export async function releasePushToken() {
  const token = registeredToken;
  registeredToken = null;
  if (!token) return;
  try {
    await unregisterPushToken(token);
  } catch {
    // 서버에 닿지 않으면 토큰은 서버가 만료 응답을 받을 때 정리된다
  }
}

/**
 * 로그인하면 푸시 토큰을 등록하고, 로그아웃 직전에 해제하며, 푸시를 누르면 알림함으로 이동한다(안드로이드·iOS).
 * @returns {null}
 */
function NativePush() {
  const { status } = useAuth();
  const router = useRouter();
  const lastResponse = Notifications.useLastNotificationResponse();

  useEffect(() => {
    if (!shouldRegister({ status, platform: Platform.OS })) return undefined;
    registerThisDevice();
    return onBeforeSignOut(releasePushToken);
  }, [status]);

  useEffect(() => {
    if (!lastResponse || status !== "authenticated") return;
    const data = lastResponse.notification.request.content.data;
    Notifications.clearLastNotificationResponse();
    router.push(routeForPush(data));
  }, [lastResponse, status, router]);

  return null;
}

/**
 * 앱 루트에서 AuthProvider 안에 한 번만 둔다. 화면은 그리지 않고, 웹에서는 아무것도 하지 않는다.
 * @returns {import("react").ReactElement | null}
 */
export default function PushBootstrap() {
  return Platform.OS === "web" ? null : <NativePush />;
}
