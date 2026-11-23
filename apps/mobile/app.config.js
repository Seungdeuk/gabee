// 메타(페이스북·인스타그램) 광고 측정 SDK 설정. 나머지 앱 설정은 app.json 에 그대로 있고, 여기서는 메타 설정만 덧붙인다.
// 클라이언트 토큰은 코드에 쓰지 않는다. EAS 환경변수 META_CLIENT_TOKEN 을 빌드할 때 읽는다(docs/features/meta-sdk.md).
// 토큰이 없는 빌드(로컬 빌드 등)는 extra.metaEnabled 가 false 라서 앱이 메타를 켜지 않는다.

/** 메타 개발자 앱 "Gabee" 의 앱 ID(공개 값). */
const META_APP_ID = "1523729119817097";

/**
 * app.json 설정에 메타 SDK 설정을 더한다.
 * @param {{ config: Record<string, any> }} ctx app.json 에서 읽은 설정
 * @returns {Record<string, any>} 최종 앱 설정
 */
module.exports = ({ config }) => {
  const clientToken = process.env.META_CLIENT_TOKEN ?? "";
  return {
    ...config,
    plugins: [
      ...(config.plugins ?? []),
      [
        "react-native-fbsdk-next",
        {
          appID: META_APP_ID,
          clientToken,
          displayName: config.name,
          // 앱 코드(src/shared/meta)가 Expo Go 가 아닌지 확인한 뒤에 직접 켠다
          isAutoInitEnabled: false,
          // 켠 뒤에는 설치·실행 이벤트를 SDK 가 자동으로 기록한다
          autoLogAppEventsEnabled: true,
          // 안드로이드 광고 ID(사용자가 휴대폰 설정에서 지우거나 끌 수 있다). 개인정보처리방침 4·5항 참고
          advertiserIDCollectionEnabled: true,
          // 아이폰 추적 허용 팝업(ATT)은 아직 쓰지 않는다(다음 작업)
          iosUserTrackingPermission: false,
        },
      ],
    ],
    extra: { ...config.extra, metaEnabled: clientToken.length > 0 },
  };
};
