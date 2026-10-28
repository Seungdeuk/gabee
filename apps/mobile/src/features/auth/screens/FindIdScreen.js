import { useState } from "react";

import Button from "@/shared/components/Button";
import Field from "@/shared/components/Field";

import { recoverLoginId } from "../api";
import AuthLayout from "../components/AuthLayout";
import Notice from "../components/Notice";
import { errorMessage } from "../messages";
import { checkEmail } from "../validation";

/**
 * 아이디 찾기. 가입한 이메일을 입력하면 아이디를 메일로 보낸다. 계정이 있든 없든 같은 안내를 보여 준다(서버도 항상 같은 응답).
 */
export default function FindIdScreen() {
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
      await recoverLoginId(email);
      setSent(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title="아이디 찾기" subtitle="가입할 때 적은 이메일로 아이디를 보내 드려요">
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
        testID="find-id-email"
      />
      <Notice tone="error" text={error} />
      <Notice text="이메일을 등록하지 않았다면 가족 관리자에게 문의해 주세요" />
      {sent ? <Notice tone="success" text="가입한 메일로 아이디를 보냈어요. 메일이 없으면 스팸함을 확인해 주세요." /> : null}
      <Button label={busy ? "보내는 중..." : sent ? "다시 보내기" : "아이디 보내기"} onPress={submit} disabled={busy} testID="find-id-submit" />
    </AuthLayout>
  );
}
