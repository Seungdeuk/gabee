import { useRouter } from "expo-router";
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Field from "@/shared/components/Field";
import Segmented from "@/shared/components/Segmented";
import { colors } from "@/theme";

import { useAuth } from "@/shared/auth/AuthProvider";
import { logMetaSignup } from "@/shared/meta/metaEvents";
import { checkLoginIdAvailable, requestEmailVerification, signupAccount } from "../api";
import AuthLayout from "../components/AuthLayout";
import Notice from "../components/Notice";
import { errorMessage } from "../messages";
import { checkLoginId, checkName, checkOptionalEmail, checkPassword, normalizeLoginId } from "../validation";

const ROLES = [
  { key: "parent", label: "부모" },
  { key: "child", label: "자녀" },
  { key: "other", label: "기타" },
];

/**
 * 회원가입. 이메일은 선택이다. 가입이 끝나면 바로 로그인하고, 이메일을 적었다면 인증 메일을 보낸 뒤 인증 화면으로("나중에 할게요"로 건너뛸 수 있다), 없으면 바로 홈으로 간다.
 * 메일 설정이 없는 서버에서는 인증 메일을 못 보내도 가입·로그인은 완료된다.
 */
export default function SignupScreen() {
  const router = useRouter();
  const { signIn } = useAuth();
  const [form, setForm] = useState({ loginId: "", name: "", email: "", password: "", password2: "", role: "child", roleDetail: "" });
  const [errors, setErrors] = useState({});
  const [idState, setIdState] = useState({ checked: "", available: null, busy: false, message: "" });
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key) => (value) => setForm((prev) => ({ ...prev, [key]: value }));

  const validate = () => {
    const next = {
      loginId: checkLoginId(form.loginId),
      name: checkName(form.name),
      email: checkOptionalEmail(form.email),
      password: checkPassword(form.password, form.loginId, form.email),
      password2: form.password === form.password2 ? "" : "비밀번호가 서로 달라요",
    };
    setErrors(next);
    return Object.values(next).every((v) => !v);
  };

  const checkId = async () => {
    const problem = checkLoginId(form.loginId);
    if (problem) {
      setErrors((prev) => ({ ...prev, loginId: problem }));
      return false;
    }
    setIdState((prev) => ({ ...prev, busy: true, message: "" }));
    try {
      const res = await checkLoginIdAvailable(form.loginId);
      setIdState({ checked: res.login_id, available: res.available, busy: false, message: "" });
      setErrors((prev) => ({ ...prev, loginId: res.available ? "" : "이미 사용 중인 아이디예요" }));
      return res.available;
    } catch (e) {
      setIdState((prev) => ({ ...prev, busy: false, message: errorMessage(e) }));
      return false;
    }
  };

  const submit = async () => {
    setFormError("");
    if (!validate()) return;
    setBusy(true);
    try {
      await signupAccount(form);
    } catch (e) {
      if (e.code === "login_id_taken") setErrors((prev) => ({ ...prev, loginId: errorMessage(e) }));
      else if (e.code === "email_taken") setErrors((prev) => ({ ...prev, email: errorMessage(e) }));
      else setFormError(errorMessage(e));
      setBusy(false);
      return;
    }
    logMetaSignup(); // 메타 광고 측정: 가입 완료(이름·아이디·이메일은 보내지 않음)
    try {
      await signIn(form.loginId, form.password);
    } catch {
      setBusy(false);
      router.replace("/login"); // 가입은 됐지만 자동 로그인에 실패: 로그인 화면에서 직접 들어간다
      return;
    }
    if (!form.email.trim()) {
      setBusy(false);
      router.replace("/chat"); // 이메일은 선택이라 없으면 인증 단계 없이 바로 시작한다
      return;
    }
    let sent = "0";
    try {
      await requestEmailVerification();
      sent = "1";
    } catch (e) {
      sent = e.code === "mail_not_configured" ? "unavailable" : "0";
    }
    setBusy(false);
    router.replace({ pathname: "/verify-email", params: { sent } });
  };

  const idOk = idState.available && idState.checked === normalizeLoginId(form.loginId);
  return (
    <AuthLayout title="회원가입" subtitle="가족과 함께 쓰려면 계정이 필요해요">
      <View style={styles.row}>
        <Field
          style={styles.grow}
          label="아이디"
          value={form.loginId}
          onChangeText={set("loginId")}
          autoCapitalize="none"
          autoCorrect={false}
          autoComplete="username"
          maxLength={32}
          error={errors.loginId}
          hint={idOk ? "사용할 수 있는 아이디예요" : "영문 소문자로 시작, 소문자·숫자·밑줄 4~32자"}
          testID="signup-login-id"
        />
        <View style={styles.checkButton}>
          <Button label={idState.busy ? "확인 중" : "중복 확인"} small variant="secondary" onPress={checkId} disabled={idState.busy} />
        </View>
      </View>
      <Notice tone="error" text={idState.message} />
      <Field label="이름" value={form.name} onChangeText={set("name")} maxLength={40} error={errors.name} testID="signup-name" />
      <View style={styles.roles}>
        <Text style={styles.roleLabel}>가족 안에서의 역할</Text>
        <Segmented options={ROLES} value={form.role} onChange={set("role")} />
      </View>
      {form.role === "other" ? (
        <Field
          label="가족과의 관계"
          value={form.roleDetail}
          onChangeText={set("roleDetail")}
          maxLength={40}
          placeholder="예: 이모, 할머니, 삼촌"
          hint="적어 두면 가족에게 이 관계로 보여요 (선택)"
          testID="signup-role-detail"
        />
      ) : null}
      <Field
        label="이메일 (선택)"
        value={form.email}
        onChangeText={set("email")}
        keyboardType="email-address"
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete="email"
        error={errors.email}
        hint="비밀번호를 잊었을 때 찾는 데 써요. 없어도 가입하고 가족에 참여할 수 있어요"
        testID="signup-email"
      />
      <Field
        label="비밀번호"
        value={form.password}
        onChangeText={set("password")}
        secureTextEntry
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete="new-password"
        textContentType="newPassword"
        error={errors.password}
        hint="8자 이상, 문자와 숫자를 모두 넣어 주세요"
        testID="signup-password"
      />
      <Field
        label="비밀번호 확인"
        value={form.password2}
        onChangeText={set("password2")}
        secureTextEntry
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete="new-password"
        error={errors.password2}
        onSubmitEditing={submit}
        testID="signup-password2"
      />
      <Notice tone="error" text={formError} />
      <Button label={busy ? "가입 중..." : "가입하기"} onPress={submit} disabled={busy} testID="signup-submit" />
      <Text style={styles.footer}>
        이미 계정이 있나요?{" "}
        <Text style={styles.link} onPress={() => router.replace("/login")} accessibilityRole="link">
          로그인
        </Text>
      </Text>
    </AuthLayout>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "flex-start", gap: 8 },
  grow: { flex: 1 },
  checkButton: { paddingTop: 26 },
  roles: { gap: 6 },
  roleLabel: { fontSize: 14, fontWeight: "500", color: colors.text },
  footer: { fontSize: 14, color: colors.textMuted, textAlign: "center" },
  link: { fontWeight: "700", color: colors.text },
});
