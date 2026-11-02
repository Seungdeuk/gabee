import { useState } from "react";
import { StyleSheet, View } from "react-native";

import Button from "@/shared/components/Button";

import { socialLogin } from "../api";
import { errorMessage } from "../messages";
import { PROVIDER_LABEL, enabledProviders, isCandidate } from "../social";
import Notice from "./Notice";
import SocialButtons from "./SocialButtons";

/** 소셜 로그인을 아직 쓸 수 없을 때 보이는 카카오·Google 버튼. 누르면 준비 중이라고만 알려 준다. */
function ComingSoon() {
  const [shown, setShown] = useState(false);
  return (
    <View style={styles.box}>
      <Button label="카카오로 계속하기 · 준비 중" icon="chatbubble" variant="ghost" onPress={() => setShown(true)} testID="social-kakao-soon" />
      <Button label="Google로 계속하기 · 준비 중" icon="logo-google" variant="ghost" onPress={() => setShown(true)} testID="social-google-soon" />
      <Notice text={shown ? "소셜 로그인은 준비 중이에요. 지금은 아이디와 비밀번호로 들어와 주세요" : ""} />
    </View>
  );
}

/**
 * 로그인 화면의 소셜 로그인(쓸 수 있는 제공자가 없으면 "준비 중" 버튼을 보여 준다).
 * 성공하면 onSession(로그인 응답)을 부르고, 같은 이메일의 기존 계정이 있으면 합치지 않고 연동 방법을 안내한다.
 * @param {{ onSession: (res: object) => Promise<void> | void }} props
 */
export default function SocialLogin({ onSession }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [candidate, setCandidate] = useState("");

  if (enabledProviders().length === 0) return <ComingSoon />;

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
      <SocialButtons onToken={onToken} onFail={(p) => setError(`${PROVIDER_LABEL[p]} 로그인을 마치지 못했어요`)} disabled={busy} />
      <Notice tone="error" text={error} />
      <Notice text={candidate ? `이미 ${candidate} 이메일로 가입한 계정이 있어요. 아이디·비밀번호로 로그인한 뒤 설정(우측 상단 ⋮)의 "소셜 계정 연동"에서 연결해 주세요.` : ""} />
    </View>
  );
}

const styles = StyleSheet.create({
  box: { gap: 12 },
});
