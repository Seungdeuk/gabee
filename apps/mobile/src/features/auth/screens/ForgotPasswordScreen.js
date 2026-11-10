import { useRouter } from "expo-router";
import { useState } from "react";

import Button from "@/shared/components/Button";
import Field from "@/shared/components/Field";

import { requestPasswordReset } from "../api";
import AuthLayout from "../components/AuthLayout";
import Notice from "../components/Notice";
import { errorMessage } from "../messages";
import { checkEmail, checkLoginId, normalizeLoginId } from "../validation";

/**
 * 비밀번호 재설정 요청. 계정이 있는지와 상관없이 같은 안내를 보여 준다(서버도 항상 같은 응답을 준다).
 */
export default function ForgotPasswordScreen() {
  const router = useRouter();
  const [loginId, setLoginId] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const problem = checkLoginId(loginId) || checkEmail(email);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError("");
    try {
      await requestPasswordReset(loginId, email);
      setSent(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title="비밀번호 재설정" subtitle="가입할 때 적은 아이디와 이메일이 맞으면 재설정 코드를 보내 드려요">
      <Field
        label="아이디"
        value={loginId}
        onChangeText={(v) => {
          setLoginId(v);
          setSent(false);
        }}
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete="username"
        textContentType="username"
        returnKeyType="next"
        testID="forgot-login-id"
      />
      <Field
        label="이메일"
        value={email}
        onChangeText={(v) => {
          setEmail(v);
          setSent(false);
        }}
        keyboardType="email-address"
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete="email"
        onSubmitEditing={submit}
        testID="forgot-email"
      />
      <Notice tone="error" text={error} />
      <Notice text="이메일을 등록하지 않았다면 가족 관리자에게 문의해 주세요" />
      {sent ? (
        <Notice tone="success" text="재설정 코드를 메일로 보냈어요. 메일함(스팸함 포함)을 확인해 주세요" />
      ) : null}
      <Button label={busy ? "보내는 중..." : sent ? "다시 보내기" : "재설정 메일 보내기"} onPress={submit} disabled={busy} testID="forgot-submit" />
      <Button
        label="메일의 재설정 코드를 입력할게요"
        variant="secondary"
        onPress={() => router.push({ pathname: "/reset-password", params: loginId.trim() ? { loginId: normalizeLoginId(loginId) } : {} })}
      />
    </AuthLayout>
  );
}
