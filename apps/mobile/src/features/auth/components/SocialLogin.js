import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { colors } from "@/theme";

import { socialLogin } from "../api";
import { errorMessage } from "../messages";
import { PROVIDER_LABEL, enabledProviders, isCandidate } from "../social";
import Notice from "./Notice";
import SocialButtons from "./SocialButtons";

/**
 * 로그인 화면의 소셜 로그인(설정된 제공자가 없으면 아무것도 그리지 않는다).
 * 성공하면 onSession(로그인 응답)을 부르고, 같은 이메일의 기존 계정이 있으면 합치지 않고 연동 방법을 안내한다.
 * @param {{ onSession: (res: object) => Promise<void> | void }} props
 */
export default function SocialLogin({ onSession }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [candidate, setCandidate] = useState("");

  if (enabledProviders().length === 0) return null;

  const onToken = async (provider, token) => {
    setBusy(true);
    setError("");
    setCandidate("");
    try {
      const res = await socialLogin(provider, token);
      if (isCandidate(res)) setCandidate(res.masked_email);
      else await onSession(res);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.box}>
      <Text style={styles.or}>또는</Text>
      <SocialButtons onToken={onToken} onFail={(p) => setError(`${PROVIDER_LABEL[p]} 로그인을 마치지 못했어요`)} disabled={busy} />
      <Notice tone="error" text={error} />
      <Notice text={candidate ? `이미 ${candidate} 이메일로 가입한 계정이 있어요. 아이디·비밀번호로 로그인한 뒤 설정(우측 상단 ⋮)의 "소셜 계정 연동"에서 연결해 주세요.` : ""} />
    </View>
  );
}

const styles = StyleSheet.create({
  box: { gap: 12 },
  or: { fontSize: 13, color: colors.textMuted, textAlign: "center" },
});
