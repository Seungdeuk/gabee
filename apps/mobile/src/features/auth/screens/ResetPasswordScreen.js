import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Field from "@/shared/components/Field";
import { colors } from "@/theme";

import { confirmPasswordReset, confirmPasswordResetCode } from "../api";
import { parseCode } from "../code";
import AuthLayout from "../components/AuthLayout";
import CodeBoxes from "../components/CodeBoxes";
import Notice from "../components/Notice";
import { errorMessage } from "../messages";
import { extractToken, scrubTokenFromBrowserUrl } from "../tokenLink";
import { checkLoginId, checkPassword } from "../validation";

const EXPIRED_CODES = ["reset_token_expired", "reset_token_used", "reset_token_invalid"];

/**
 * 새 비밀번호 설정. 메일 링크(gabee://reset-password?token=...)로 열면 토큰이 이미 들어 있고(주소에서는 바로 지운다),
 * 아니면 메일의 6자리 재설정 코드와 아이디를 입력한다. 성공하면 모든 기기가 로그아웃되므로 로그인 화면으로 보낸다.
 */
export default function ResetPasswordScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const [linkToken] = useState(() => extractToken(typeof params.token === "string" ? params.token : ""));
  const [loginId, setLoginId] = useState(() => (typeof params.loginId === "string" ? params.loginId : ""));
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
    const digits = parseCode(code);
    const next = {
      loginId: linkToken ? "" : checkLoginId(loginId),
      code: linkToken || digits ? "" : "메일에 있는 재설정 코드 6자리를 입력해 주세요",
      password: checkPassword(password, loginId),
      password2: password === password2 ? "" : "비밀번호가 서로 달라요",
    };
    setErrors(next);
    setFormError("");
    if (Object.values(next).some(Boolean)) return;
    setBusy(true);
    try {
      if (linkToken) await confirmPasswordReset(linkToken, password);
      else await confirmPasswordResetCode(loginId, digits, password);
      setDone(true);
    } catch (e) {
      if (EXPIRED_CODES.includes(e.code) || e.code === "reset_code_invalid") setExpired(true);
      if (e.code === "reset_code_invalid") setCode("");
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
        <>
          <Field
            label="아이디"
            value={loginId}
            onChangeText={setLoginId}
            autoCapitalize="none"
            autoCorrect={false}
            autoComplete="username"
            textContentType="username"
            error={errors.loginId}
            testID="reset-login-id"
          />
          <View style={styles.codeBlock}>
            <Text style={styles.codeLabel}>재설정 코드 6자리</Text>
            <CodeBoxes value={code} onChange={setCode} error={Boolean(errors.code)} disabled={busy} testID="reset-code" />
            {errors.code ? (
              <Text style={styles.codeError} accessibilityRole="alert">
                {errors.code}
              </Text>
            ) : null}
          </View>
        </>
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

const styles = StyleSheet.create({
  codeBlock: { gap: 8 },
  codeLabel: { fontSize: 14, fontWeight: "500", color: colors.text },
  codeError: { fontSize: 13, color: colors.danger },
});
