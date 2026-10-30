import { useRouter } from "expo-router";
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Tag from "@/shared/components/Tag";
import { colors, font } from "@/theme";

import { useAuth } from "./AuthProvider";

/** 기타 탭의 계정 카드: 로그인 상태, 이메일 인증 상태, 로그인/가입/로그아웃. 익명(로그인 안 한) 사용자는 기존처럼 계속 쓸 수 있다. */
export default function AccountCard() {
  const router = useRouter();
  const { status, user, signOut, restore } = useAuth();
  const [busy, setBusy] = useState(false);

  if (status === "loading") return null;
  if (status === "unreachable") {
    return (
      <Card tone="orange">
        <Text style={styles.title}>서버에 연결하지 못했어요</Text>
        <Text style={styles.sub}>로그인 정보는 이 기기에 그대로 있어요.</Text>
        <Button label="다시 시도" small variant="secondary" onPress={restore} />
      </Card>
    );
  }
  if (status !== "authenticated") {
    return (
      <Card tone="white">
        <Text style={styles.title}>로그인하지 않았어요</Text>
        <Text style={styles.sub}>계정을 만들면 다른 기기에서도 가족 그룹을 이어서 쓸 수 있어요.</Text>
        <View style={styles.row}>
          <Button label="로그인" small onPress={() => router.push("/login")} />
          <Button label="회원가입" small variant="secondary" onPress={() => router.push("/signup")} />
        </View>
      </Card>
    );
  }
  const verified = Boolean(user?.email_verified);
  return (
    <Card tone="white">
      <View style={styles.row}>
        <Text style={styles.title}>{user?.name}</Text>
        <Tag label={verified ? "이메일 인증됨" : "이메일 미인증"} tone={verified ? "green" : "orange"} />
      </View>
      <Text style={styles.sub}>{user?.email ?? user?.login_id}</Text>
      <View style={styles.row}>
        {verified ? null : <Button label="이메일 인증하기" small onPress={() => router.push("/verify-email")} />}
        <Button label="소셜 계정 연동" small variant="secondary" onPress={() => router.push("/social-accounts")} />
        <Button
          label={busy ? "로그아웃 중..." : "로그아웃"}
          small
          variant="secondary"
          disabled={busy}
          onPress={async () => {
            setBusy(true);
            await signOut();
            setBusy(false);
            router.replace("/"); // 처음(시작) 화면으로 돌아간다
          }}
        />
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  title: { ...font.cardTitle, color: colors.text },
  sub: { ...font.caption, color: colors.textMuted },
  row: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
});
