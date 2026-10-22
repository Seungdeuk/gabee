import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { StyleSheet, Text } from "react-native";

import Button from "@/shared/components/Button";
import Field from "@/shared/components/Field";
import { colors } from "@/theme";

import { useAuth } from "@/shared/auth/AuthProvider";
import { confirmEmailVerification, requestEmailVerification } from "../api";
import AuthLayout from "../components/AuthLayout";
import Notice from "../components/Notice";
import { errorMessage } from "../messages";
import { extractToken } from "../tokenLink";

const RESEND_COOLDOWN = 60; // 서버의 재발송 간격과 같다. 서버가 429 를 주면 그 안내를 따른다

/**
 * 이메일 인증. 두 가지로 들어온다.
 * - 메일의 링크(gabee://verify-email?token=...): 토큰을 받자마자 인증하고, 주소창/기록에서 토큰을 지운다.
 * - 가입 직후, 또는 이메일 미인증(403 email_not_verified)일 때: 인증 대기 안내, 메일 재발송, 코드 직접 입력.
 * 토큰은 화면 상태에만 두고 로그로 남기지 않는다.
 */
export default function VerifyEmailScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const { status, user, refreshUser } = useAuth();
  const [linkToken] = useState(() => extractToken(typeof params.token === "string" ? params.token : ""));
  const [phase, setPhase] = useState(linkToken ? "confirming" : "waiting"); // waiting | confirming | done | failed
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState(
    params.sent === "1" ? "인증 메일을 보냈어요. 메일함을 확인해 주세요" : params.sent === "unavailable" ? "지금은 인증 메일을 보낼 수 없어요. 서버의 메일 설정이 끝나면 다시 받을 수 있어요" : "",
  );
  const [cooldown, setCooldown] = useState(params.sent === "1" ? RESEND_COOLDOWN : 0);
  const [busy, setBusy] = useState(false);
  const started = useRef(false);

  const confirm = async (token) => {
    setBusy(true);
    setError("");
    try {
      await confirmEmailVerification(token);
      setPhase("done");
      if (status === "authenticated") await refreshUser().catch(() => {}); // 상태 표시 갱신. 실패해도 인증은 끝났다
    } catch (e) {
      setPhase("failed");
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  // 메일 링크로 들어왔으면 한 번만 자동 인증하고, 토큰을 주소(라우트 파라미터)에서 지운다
  useEffect(() => {
    if (!linkToken || started.current) return;
    started.current = true;
    router.setParams({ token: undefined });
    confirm(linkToken);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (cooldown <= 0) return undefined;
    const timer = setTimeout(() => setCooldown((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  const resend = async () => {
    setBusy(true);
    setError("");
    setInfo("");
    try {
      await requestEmailVerification();
      setInfo("인증 메일을 다시 보냈어요. 이전 메일의 링크는 쓸 수 없어요");
      setCooldown(RESEND_COOLDOWN);
    } catch (e) {
      if (e.code === "email_already_verified") {
        await refreshUser().catch(() => {});
        setPhase("done");
      } else {
        setError(errorMessage(e));
        if (e.code === "too_many_requests" && e.retryAfter) setCooldown(e.retryAfter);
      }
    } finally {
      setBusy(false);
    }
  };

  const submitCode = () => {
    const token = extractToken(code);
    if (!token) {
      setError("메일에 있는 인증 코드나 링크를 그대로 붙여 넣어 주세요");
      return;
    }
    confirm(token);
  };

  const verified = phase === "done" || (status === "authenticated" && user?.email_verified);
  if (verified) {
    return (
      <AuthLayout title="이메일 인증 완료" subtitle="이제 가족 그룹을 만들거나 참여할 수 있어요" back={false}>
        <Notice tone="success" text="이메일 인증이 끝났어요" />
        <Button label="시작하기" onPress={() => router.replace(status === "authenticated" ? "/chat" : "/login")} testID="verify-done" />
      </AuthLayout>
    );
  }
  if (phase === "confirming") {
    return (
      <AuthLayout title="이메일 인증 중" back={false}>
        <Notice text="인증을 확인하고 있어요..." />
      </AuthLayout>
    );
  }

  const loggedIn = status === "authenticated";
  return (
    <AuthLayout title="이메일 인증" subtitle={user?.email ? `${user.email} 로 보낸 메일에서 인증해 주세요` : "메일로 받은 링크로 인증해 주세요"}>
      <Notice tone="info" text={info} />
      <Notice tone="error" text={error} />
      {phase === "failed" && !loggedIn ? (
        <Button label="로그인하고 인증 메일 다시 받기" onPress={() => router.replace("/login")} />
      ) : null}
      {loggedIn ? (
        <Button
          label={cooldown > 0 ? `인증 메일 다시 보내기 (${cooldown}초)` : "인증 메일 다시 보내기"}
          onPress={resend}
          disabled={busy || cooldown > 0}
          testID="verify-resend"
        />
      ) : phase !== "failed" ? (
        <Button label="로그인" onPress={() => router.replace("/login")} />
      ) : null}
      <Field
        label="인증 코드 직접 입력"
        value={code}
        onChangeText={setCode}
        autoCapitalize="none"
        autoCorrect={false}
        placeholder="메일에 적힌 코드 또는 링크"
        onSubmitEditing={submitCode}
        testID="verify-code"
      />
      <Button label="코드로 인증하기" variant="secondary" onPress={submitCode} disabled={busy || !code.trim()} testID="verify-code-submit" />
      <Text style={styles.skip} onPress={() => router.replace("/chat")} accessibilityRole="link">
        나중에 할게요
      </Text>
    </AuthLayout>
  );
}

const styles = StyleSheet.create({
  skip: { fontSize: 14, color: colors.textMuted, textAlign: "center", fontWeight: "600" },
});
