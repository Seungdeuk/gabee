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
import { PUSH_CHANNEL_ID, createTokenTracker, isUsableToken, permissionState, routeForPush, shouldRegister } from "./push";

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

/** 이 기기의 푸시 토큰(서버에 보내기 전에 기억해 두어, 등록이 실패해도 로그아웃 때 해제를 시도한다). */
const tracker = createTokenTracker();

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
 * 서버에서 토큰을 지운다. 실패해도 던지지 않는다(서버에 닿지 않으면 Expo 가 만료 응답을 줄 때 정리된다).
 * @param {string} token
 * @returns {Promise<void>}
 */
async function unregisterQuietly(token) {
  try {
    await unregisterPushToken(token);
  } catch {
    // 로그아웃·정리를 막지 않는다
  }
}

/**
 * 기기 알림 권한 상태를 읽는다(웹이거나 읽지 못하면 "unknown").
 * @returns {Promise<"granted" | "ask" | "blocked" | "unknown">}
 */
export async function readPermissionState() {
  if (Platform.OS === "web") return "unknown";
  try {
    return permissionState(await Notifications.getPermissionsAsync());
  } catch {
    return "unknown";
  }
}

/**
 * 이 기기를 푸시 받을 준비를 한다: 알림 채널 → 권한 확인(처음이면 안내 후 요청) → 토큰 받기 → 서버 등록.
 * 거절·오류·에뮬레이터 실패는 던지지 않고 결과로 알린다(알림함은 그대로 쓴다). 등록하는 도중에 로그아웃이 지나갔으면 방금 받은 토큰을 서버에서 다시 지운다.
 * @returns {Promise<"granted" | "ask" | "blocked" | "failed">} granted 등록됨 · ask 안내를 닫았거나 아직 허용 안 함 · blocked 기기 설정에서만 켤 수 있음 · failed 토큰을 못 받음
 */
export async function prepareThisDevice() {
  const startedAt = tracker.begin();
  try {
    if (Platform.OS === "android") {
      await Notifications.setNotificationChannelAsync(PUSH_CHANNEL_ID, {
        name: PUSH_CHANNEL_NAME,
        importance: Notifications.AndroidImportance.HIGH,
      });
    }
    if (!(await ensurePermission())) {
      const state = await readPermissionState();
      return state === "granted" || state === "unknown" ? "ask" : state;
    }
    const token = await fetchToken();
    if (!isUsableToken(token)) return "failed";
    tracker.remember(token); // 서버에 보내기 전에 기억해 둔다
    if (tracker.isStale(startedAt)) {
      await unregisterQuietly(tracker.take()); // 토큰을 받는 동안 로그아웃이 지나갔다
      return "failed";
    }
    await registerPushToken({
      token,
      platform: Platform.OS === "ios" ? "ios" : "android",
      deviceLabel: Device.deviceName ?? Device.modelName ?? null,
    });
    if (tracker.isStale(startedAt)) await unregisterQuietly(token); // 등록하는 동안 로그아웃이 지나갔다
    return "granted";
  } catch {
    // 토큰을 못 받아도(Expo Go·에뮬레이터·오프라인) 앱 사용에는 영향이 없다
    return "failed";
  }
}

/**
 * 이 기기의 Expo 푸시 토큰을 받는다(권한이 없거나 못 받으면 null).
 * @returns {Promise<string | null>}
 */
async function fetchToken() {
  const projectId = Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
  const { data } = await Notifications.getExpoPushTokenAsync({ projectId });
  return data ?? null;
}

/**
 * 이 기기의 푸시 토큰을 서버에서 해제한다(로그아웃 직전). 기억한 토큰이 없으면(이번 실행에서 등록에 실패했지만
 * 서버에는 이전 실행의 토큰이 남아 있을 수 있다) 토큰을 다시 받아 지운다. 실패해도 던지지 않는다.
 * @returns {Promise<void>}
 */
export async function releasePushToken() {
  let token = tracker.take();
  if (!token) {
    try {
      const { status } = await Notifications.getPermissionsAsync();
      if (status === "granted") token = await fetchToken();
    } catch {
      token = null;
    }
  }
  if (isUsableToken(token)) await unregisterQuietly(token);
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
    prepareThisDevice();
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
