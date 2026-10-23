import { useCallback, useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { useAuth } from "@/shared/auth/AuthProvider";
import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import Tag from "@/shared/components/Tag";
import { colors, font } from "@/theme";

import { linkSocialAccount, listSocialAccounts, unlinkSocialAccount } from "../api";
import AuthLayout from "../components/AuthLayout";
import Notice from "../components/Notice";
import SocialButtons from "../components/SocialButtons";
import { errorMessage } from "../messages";
import { PROVIDER_LABEL, enabledProviders } from "../social";

/**
 * 소셜 계정 연동: 내 계정에 Google·카카오 계정을 연결하거나 해제한다.
 * 연결할 때 비밀번호가 있는 계정은 비밀번호를 한 번 더 확인한다. 마지막 로그인 수단은 해제할 수 없다(서버가 거부).
 */
export default function SocialAccountsScreen() {
  const { status } = useAuth();
  const [linked, setLinked] = useState(null); // null: 불러오는 중
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setLinked((await listSocialAccounts()).map((a) => a.provider));
    } catch (e) {
      setLinked([]);
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    if (status === "authenticated") load();
  }, [status, load]);

  if (status !== "authenticated") {
    return (
      <AuthLayout title="소셜 계정 연동">
        <Notice text="소셜 계정을 연동하려면 먼저 아이디로 로그인해 주세요" />
      </AuthLayout>
    );
  }

  const link = async (provider, token) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await linkSocialAccount(provider, token, password);
      setNotice(`${PROVIDER_LABEL[provider]} 계정을 연결했어요`);
      setPassword("");
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
    setBusy(false);
  };

  const unlink = async (provider) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await unlinkSocialAccount(provider);
      setNotice(`${PROVIDER_LABEL[provider]} 연결을 해제했어요`);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
    setBusy(false);
  };

  const providers = enabledProviders();
  const unlinked = providers.filter((p) => !linked?.includes(p));
  return (
    <AuthLayout title="소셜 계정 연동" subtitle="연결하면 Google·카카오로도 같은 계정에 로그인할 수 있어요">
      <Notice tone="error" text={error} />
      <Notice tone="success" text={notice} />
      {linked === null ? <Notice text="불러오고 있어요..." /> : null}
      {(linked ?? []).map((provider) => (
        <Card key={provider} tone="white">
          <View style={styles.row}>
            <Text style={styles.name}>{PROVIDER_LABEL[provider] ?? provider}</Text>
            <Tag label="연결됨" tone="green" />
          </View>
          <Button label="연결 해제" small variant="secondary" onPress={() => unlink(provider)} disabled={busy} testID={`unlink-${provider}`} />
        </Card>
      ))}
      {providers.length === 0 ? <Notice text="이 앱에는 아직 소셜 로그인 설정이 없어요" /> : null}
      {unlinked.length > 0 && linked !== null ? (
        <Card tone="white">
          <Text style={styles.sub}>연결할 계정을 고르면 브라우저가 열려요. 비밀번호가 있는 계정은 보안을 위해 비밀번호를 먼저 입력해 주세요.</Text>
          <Field label="내 비밀번호" value={password} onChangeText={setPassword} secureTextEntry autoCapitalize="none" autoCorrect={false} hint="소셜 전용 계정이면 비워 두세요" testID="link-password" />
          <SocialButtons only={unlinked} onToken={link} onFail={(p) => setError(`${PROVIDER_LABEL[p]} 로그인을 마치지 못했어요`)} disabled={busy} />
        </Card>
      ) : null}
    </AuthLayout>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  name: { ...font.cardTitle, color: colors.text },
  sub: { ...font.body, color: colors.textSub },
});
