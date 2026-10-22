import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";

import Button from "@/shared/components/Button";
import Field from "@/shared/components/Field";

import { confirmPasswordReset } from "../api";
import AuthLayout from "../components/AuthLayout";
import Notice from "../components/Notice";
import { errorMessage } from "../messages";
import { extractToken, scrubTokenFromBrowserUrl } from "../tokenLink";
import { checkPassword } from "../validation";

const EXPIRED_CODES = ["reset_token_expired", "reset_token_used", "reset_token_invalid"];

/**
 * 새 비밀번호 설정. 메일 링크(gabee://reset-password?token=...)로 열면 토큰이 이미 들어 있고(주소에서는 바로 지운다),
 * 아니면 메일의 코드나 링크를 붙여 넣는다. 성공하면 모든 기기가 로그아웃되므로 로그인 화면으로 보낸다.
 */
export default function ResetPasswordScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const [linkToken] = useState(() => extractToken(typeof params.token === "string" ? params.token : ""));
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState("");
  const [expired, setExpired] = useState(false);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const cleaned = useRef(false);

  useEffect(() => {
    if (linkToken && !cleaned.current) {
      cleaned.current = true;
      router.setParams({ token: undefined }); // 토큰이 라우트 파라미터와 주소/기록에 남지 않게 한다
      scrubTokenFromBrowserUrl();
    }
  }, [linkToken, router]);

  const submit = async () => {
    const token = linkToken || extractToken(code);
    const next = {
      code: token ? "" : "메일에 있는 코드나 링크를 그대로 붙여 넣어 주세요",
      password: checkPassword(password),
      password2: password === password2 ? "" : "비밀번호가 서로 달라요",
    };
    setErrors(next);
    setFormError("");
    if (Object.values(next).some(Boolean)) return;
    setBusy(true);
    try {
      await confirmPasswordReset(token, password);
      setDone(true);
    } catch (e) {
      if (EXPIRED_CODES.includes(e.code)) setExpired(true);
      if (e.code === "weak_password") setErrors((prev) => ({ ...prev, password: errorMessage(e) }));
      else setFormError(errorMessage(e));
    } finally {
      setBusy(false);
      setPassword("");
      setPassword2("");
    }
  };

  if (done) {
    return (
      <AuthLayout title="비밀번호를 바꿨어요" back={false}>
        <Notice tone="success" text="새 비밀번호로 다시 로그인해 주세요. 다른 기기에서는 로그아웃돼요" />
        <Button label="로그인하러 가기" onPress={() => router.replace("/login")} testID="reset-done" />
      </AuthLayout>
    );
  }
  return (
    <AuthLayout title="새 비밀번호" subtitle="새로 사용할 비밀번호를 입력해 주세요">
      {linkToken ? null : (
        <Field
          label="재설정 코드"
          value={code}
          onChangeText={setCode}
          autoCapitalize="none"
          autoCorrect={false}
          placeholder="메일에 적힌 코드 또는 링크"
          error={errors.code}
          testID="reset-code"
        />
      )}
      <Field
        label="새 비밀번호"
        value={password}
        onChangeText={setPassword}
        secureTextEntry
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete="new-password"
        textContentType="newPassword"
        error={errors.password}
        hint="8자 이상, 문자와 숫자를 모두 넣어 주세요"
        testID="reset-password"
      />
      <Field
        label="새 비밀번호 확인"
        value={password2}
        onChangeText={setPassword2}
        secureTextEntry
        autoCapitalize="none"
        autoCorrect={false}
        error={errors.password2}
        onSubmitEditing={submit}
        testID="reset-password2"
      />
      <Notice tone="error" text={formError} />
      <Button label={busy ? "바꾸는 중..." : "비밀번호 바꾸기"} onPress={submit} disabled={busy} testID="reset-submit" />
      {expired ? <Button label="재설정 메일 다시 받기" variant="secondary" onPress={() => router.replace("/forgot-password")} /> : null}
    </AuthLayout>
  );
}
