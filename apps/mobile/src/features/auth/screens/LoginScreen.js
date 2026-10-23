import { useRouter } from "expo-router";
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Field from "@/shared/components/Field";
import { colors } from "@/theme";

import AuthLayout from "../components/AuthLayout";
import Notice from "../components/Notice";
import SocialLogin from "../components/SocialLogin";
import { errorMessage } from "../messages";
import { useAuth } from "@/shared/auth/AuthProvider";

/** 아이디·비밀번호 로그인. 성공하면 홈으로 가고, 이메일 인증이 안 된 회원은 홈에서 안내를 받는다. */
export default function LoginScreen() {
  const router = useRouter();
  const { signIn, signInWithSession } = useAuth();
  const [loginId, setLoginId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!loginId.trim() || !password) {
      setError("아이디와 비밀번호를 입력해 주세요");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const user = await signIn(loginId, password);
      router.replace(user.email && !user.email_verified ? "/verify-email" : "/chat");
    } catch (e) {
      setError(errorMessage(e));
      setPassword(""); // 실패한 비밀번호는 화면에 남기지 않는다
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title="로그인" subtitle="가입한 아이디와 비밀번호로 들어와요">
      <Field
        label="아이디"
        value={loginId}
        onChangeText={setLoginId}
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete="username"
        textContentType="username"
        returnKeyType="next"
        testID="login-id"
      />
      <Field
        label="비밀번호"
        value={password}
        onChangeText={setPassword}
        secureTextEntry
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete="current-password"
        textContentType="password"
        returnKeyType="go"
        onSubmitEditing={submit}
        testID="login-password"
      />
      <Notice tone="error" text={error} />
      <Button label={busy ? "로그인 중..." : "로그인"} onPress={submit} disabled={busy} testID="login-submit" />
      <SocialLogin
        onSession={async (res) => {
          const user = await signInWithSession(res);
          router.replace(user.email && !user.email_verified ? "/verify-email" : "/chat");
        }}
      />
      <View style={styles.links}>
        <Text style={styles.link} onPress={() => router.push("/forgot-password")} accessibilityRole="link">
          비밀번호를 잊으셨나요?
        </Text>
        <Text style={styles.link} onPress={() => router.replace("/signup")} accessibilityRole="link">
          회원가입
        </Text>
      </View>
    </AuthLayout>
  );
}

const styles = StyleSheet.create({
  links: { flexDirection: "row", justifyContent: "space-between", paddingTop: 4 },
  link: { fontSize: 14, fontWeight: "600", color: colors.accent },
});
