import { useRouter } from "expo-router";
import { useState } from "react";

import Button from "@/shared/components/Button";
import Field from "@/shared/components/Field";

import { requestPasswordReset } from "../api";
import AuthLayout from "../components/AuthLayout";
import Notice from "../components/Notice";
import { errorMessage } from "../messages";
import { checkEmail } from "../validation";

/**
 * 비밀번호 재설정 요청. 가입된 주소인지와 상관없이 같은 안내를 보여 준다(서버도 항상 같은 응답을 준다).
 */
export default function ForgotPasswordScreen() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const problem = checkEmail(email);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError("");
    try {
      await requestPasswordReset(email);
      setSent(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title="비밀번호 재설정" subtitle="가입할 때 쓴 이메일로 재설정 코드와 링크를 보내 드려요">
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
      <Notice text="가입할 때 이메일을 적지 않았다면 비밀번호를 찾을 수 없어요" />
      {sent ? (
        <Notice tone="success" text="가입된 이메일이라면 재설정 메일을 보냈어요. 메일함을 확인해 주세요 (30분 안에 한 번만 쓸 수 있어요)" />
      ) : null}
      <Button label={busy ? "보내는 중..." : sent ? "다시 보내기" : "재설정 메일 보내기"} onPress={submit} disabled={busy} testID="forgot-submit" />
      <Button
        label="메일의 재설정 코드를 입력할게요"
        variant="secondary"
        onPress={() => router.push({ pathname: "/reset-password", params: email.trim() ? { email: email.trim() } : {} })}
      />
    </AuthLayout>
  );
}
