import { useCallback, useEffect, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { LocationSection } from "@/features/location/public";
import Screen from "@/shared/components/Screen";
import { colors, font } from "@/theme";

/**
 * 위치 탭(위치 베타 브랜치): 위치 기능만 보인다(지도, 위치 공유 동의, 앱을 꺼도 공유, 여행 모드, 이동 기록).
 * 지갑(정산·지출·용돈) 화면 코드는 features/billing 에 그대로 있고 이 탭에서만 뺐다. 라우트 이름(care)과 폴더 이름은 그대로 둔다.
 * feature/hojenn-location-beta 에만 있고 release/1.2 에 병합하지 않는다.
 */
export default function CareScreen() {
  const [message, setMessage] = useState(null);
  const timer = useRef(null);

  const notify = useCallback((text, isError = false) => {
    setMessage({ text, isError });
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setMessage(null), 3500);
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <Screen title="위치">
      {message ? (
        <View style={[styles.message, message.isError && styles.messageError]} accessibilityLiveRegion="polite" testID="message">
          <Text style={[styles.messageText, message.isError && styles.messageTextError]}>{message.text}</Text>
        </View>
      ) : null}
      <LocationSection notify={notify} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  message: { backgroundColor: colors.successSoft, borderRadius: 14, paddingHorizontal: 14, paddingVertical: 10 },
  messageError: { backgroundColor: colors.dangerSoft },
  messageText: { ...font.caption, color: colors.success, fontWeight: "600" },
  messageTextError: { color: colors.danger },
});
