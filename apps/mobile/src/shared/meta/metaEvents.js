// 메타(페이스북·인스타그램) 광고 측정. 광고를 보고 설치한 사람이 실행·가입했는지만 메타에 알린다.
// 이름·이메일·가족·대화 같은 이용 내용은 보내지 않는다(개인정보처리방침 4항).
// Expo Go·웹·토큰 없는 빌드에서는 아무것도 하지 않는다(metaGate.js).
import Constants from "expo-constants";
import { Platform } from "react-native";

import { canUseMeta } from "./metaGate";

/** 불러온 SDK(react-native-fbsdk-next). 켤 수 없는 환경이면 null 로 남는다. */
let sdk = null;

/**
 * 앱이 켜질 때 한 번 메타 SDK 를 켠다. 켠 뒤에는 설치·실행 이벤트가 자동으로 기록된다.
 * 실패해도 앱 사용에는 영향이 없게 조용히 넘어간다.
 * @returns {void}
 */
export function startMeta() {
  if (sdk) return;
  const ok = canUseMeta({
    os: Platform.OS,
    executionEnvironment: Constants.executionEnvironment,
    metaEnabled: Constants.expoConfig?.extra?.metaEnabled,
  });
  if (!ok) return;
  try {
    // Expo Go 에서는 이 줄에 오지 않는다. 맨 위에서 import 하면 Expo Go 에서도 불러와지므로 여기서 불러온다
    const loaded = require("react-native-fbsdk-next");
    loaded.Settings.initializeSDK();
    sdk = loaded;
  } catch {
    sdk = null;
  }
}

/**
 * 아이디 회원가입을 마쳤다고 메타에 알린다(광고 관리자의 "가입 완료").
 * @returns {void}
 */
export function logMetaSignup() {
  if (!sdk) return;
  try {
    const { AppEventsLogger } = sdk;
    AppEventsLogger.logEvent(AppEventsLogger.AppEvents.CompletedRegistration, {
      [AppEventsLogger.AppEventParams.RegistrationMethod]: "id",
    });
  } catch {
    // 측정 실패는 가입 흐름에 영향을 주지 않는다
  }
}
