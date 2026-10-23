import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font } from "@/theme";

import { useAuth } from "@/shared/auth/AuthProvider";
import { confirmEmailCode, confirmEmailVerification, requestEmailVerification } from "../api";
import { CODE_TTL_SECONDS, formatClock, parseCode } from "../code";
import AuthLayout from "../components/AuthLayout";
import CodeBoxes from "../components/CodeBoxes";
import Notice from "../components/Notice";
import { errorMessage } from "../messages";
import { extractToken, scrubTokenFromBrowserUrl } from "../tokenLink";
import useCountdown from "../useCountdown";

const RESEND_COOLDOWN = 60; // 서버의 재발송 간격과 같다. 서버가 429 를 주면 그 안내를 따른다

/**
 * 이메일 인증. 두 가지로 들어온다.
 * - 메일의 링크(gabee://verify-email?token=...): 토큰을 받자마자 자동으로 인증하고, 주소창/기록에서 토큰을 지운다.
 * - 가입 직후, 또는 이메일 미인증(403 email_not_verified)일 때: 메일의 6자리 인증번호를 입력한다(남은 시간, 다시 받기).
 * 토큰과 인증번호는 화면 상태에만 두고 로그로 남기지 않는다.
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
    params.sent === "unavailable" ? "지금은 인증 메일을 보낼 수 없어요. 서버의 메일 설정이 끝나면 다시 받을 수 있어요" : "",
  );
  const sentAtStart = params.sent === "1";
  const expiry = useCountdown(sentAtStart ? CODE_TTL_SECONDS : 0);
  const cooldown = useCountdown(sentAtStart ? RESEND_COOLDOWN : 0);
  const [mailSent, setMailSent] = useState(sentAtStart);
  const [busy, setBusy] = useState(false);
  const started = useRef(false);

  const finish = async () => {
    setPhase("done");
    if (status === "authenticated") await refreshUser().catch(() => {}); // 상태 표시 갱신. 실패해도 인증은 끝났다
  };

  const confirmLink = async (token) => {
    setBusy(true);
    setError("");
    try {
      await confirmEmailVerification(token);
      await finish();
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
    scrubTokenFromBrowserUrl();
    confirmLink(linkToken);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const resend = async () => {
    setBusy(true);
    setError("");
    setInfo("");
    try {
      await requestEmailVerification();
      setInfo("인증번호를 다시 보냈어요. 이전 번호는 쓸 수 없어요");
      setCode("");
      setMailSent(true);
      expiry.restart(CODE_TTL_SECONDS);
      cooldown.restart(RESEND_COOLDOWN);
    } catch (e) {
      if (e.code === "email_already_verified") {
        await refreshUser().catch(() => {});
        setPhase("done");
      } else {
        setError(errorMessage(e));
        if (e.code === "too_many_requests" && e.retryAfter) cooldown.restart(e.retryAfter);
      }
    } finally {
      setBusy(false);
    }
  };

  const submit = async (value = code) => {
    const digits = parseCode(value);
    if (!digits) {
      setError("인증번호 6자리를 모두 입력해 주세요");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await confirmEmailCode(digits);
      await finish();
    } catch (e) {
      setError(errorMessage(e));
      if (e.code === "verification_code_invalid" || e.code === "verification_code_locked") setCode("");
    } finally {
      setBusy(false);
    }
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
  const expired = mailSent && expiry.remaining === 0;
  const email = user?.email;
  return (
    <AuthLayout
      title={"인증번호를\n입력해 주세요"}
      subtitle={email ? `${email}로 보낸 6자리 숫자를 입력하면 인증이 끝나요.` : "메일로 받은 6자리 숫자를 입력하면 인증이 끝나요."}
    >
      {loggedIn ? (
        <>
          <CodeBoxes value={code} onChange={setCode} onComplete={submit} error={Boolean(error)} disabled={busy} testID="verify-code" />
          <View style={styles.timerRow}>
            <Text style={styles.timer} accessibilityLiveRegion="polite">
              {mailSent ? (expired ? "인증 시간이 지났어요" : `남은 시간 ${formatClock(expiry.remaining)}`) : "인증번호를 받아 주세요"}
            </Text>
            <Text
              style={[styles.resend, (busy || cooldown.remaining > 0) && styles.resendOff]}
              onPress={busy || cooldown.remaining > 0 ? undefined : resend}
              accessibilityRole="button"
              accessibilityState={{ disabled: busy || cooldown.remaining > 0 }}
              testID="verify-resend"
            >
              인증번호 다시 받기
            </Text>
          </View>
          <Notice tone="info" text={info} />
          <Notice tone="error" text={error} />
          <Notice text="메일이 오지 않나요? 스팸함을 확인하거나 인증번호를 다시 받아 주세요. 메일의 링크를 열어도 바로 인증돼요." />
        </>
      ) : (
        <>
          <Notice tone="info" text={info} />
          <Notice tone="error" text={error} />
          <Notice text="인증번호를 입력하려면 먼저 로그인해 주세요. 메일의 링크를 열면 로그인 없이도 인증돼요." />
          <Button label="로그인" onPress={() => router.replace("/login")} />
        </>
      )}
      {loggedIn ? (
        <Button label={busy ? "확인 중..." : "인증하기"} onPress={() => submit()} disabled={busy || code.length < 6} testID="verify-code-submit" />
      ) : null}
      <Text style={styles.skip} onPress={() => router.replace("/chat")} accessibilityRole="link">
        나중에 할게요
      </Text>
    </AuthLayout>
  );
}

const styles = StyleSheet.create({
  timerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  timer: { ...font.caption, color: colors.text, fontFamily: font.bodyStrong.fontFamily },
  resend: { ...font.caption, color: colors.text, fontFamily: font.bodyStrong.fontFamily, textDecorationLine: "underline" },
  resendOff: { color: colors.disabled },
  skip: { fontSize: 14, color: colors.textMuted, textAlign: "center", fontWeight: "600" },
});
