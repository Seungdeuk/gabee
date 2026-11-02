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

/** 아이디·비밀번호 로그인. 성공하면 홈으로 간다(이메일 인증은 선택이라 로그인을 막거나 인증 화면으로 보내지 않는다). */
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
      await signIn(loginId, password);
      router.replace("/chat");
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
      <View style={styles.finds}>
        <Text style={styles.link} onPress={() => router.push("/find-id")} accessibilityRole="link">
          아이디 찾기
        </Text>
        <Text style={styles.dot}>·</Text>
        <Text style={styles.link} onPress={() => router.push("/forgot-password")} accessibilityRole="link">
          비밀번호 찾기
        </Text>
      </View>
      <SocialLogin
        onSession={async (res) => {
          const user = await signInWithSession(res);
          router.replace(user.email && !user.email_verified ? "/verify-email" : "/chat");
        }}
      />
      <View style={styles.signup}>
        <Text style={styles.signupText}>계정이 없으신가요?</Text>
        <Text style={styles.link} onPress={() => router.replace("/signup")} accessibilityRole="link">
          회원가입
        </Text>
      </View>
    </AuthLayout>
  );
}

const styles = StyleSheet.create({
  finds: { flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 10, paddingVertical: 4 },
  dot: { fontSize: 14, color: colors.textMuted },
  signup: { flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 8, paddingTop: 8 },
  signupText: { fontSize: 14, color: colors.textMuted },
  link: { fontSize: 14, fontWeight: "600", color: colors.accent },
});
