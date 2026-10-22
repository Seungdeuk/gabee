import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import SectionTitle from "@/shared/components/SectionTitle";
import Tag from "@/shared/components/Tag";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { getSubscriptions, setSubscriptionStatus } from "../api";

const STATUS = [
  { key: "check", label: "확인 필요", tone: "gray" },
  { key: "available", label: "적용 가능", tone: "orange" },
  { key: "active", label: "✓ 적용 중", tone: "green" },
];

const GROUPS = [
  { kind: "ott", title: "OTT" },
  { kind: "telecom", title: "통신비 가족 할인" },
];

/**
 * 구독·통신비 가족 할인 상태. 상태만 기록하고 할인 금액은 계산하지도 보장하지도 않는다.
 * @param {{ notify: (text: string, isError?: boolean) => void }} props
 */
export default function SubscriptionTab({ notify }) {
  const { data, error, loading, reload } = useResource(getSubscriptions);

  const change = async (item, status) => {
    try {
      await setSubscriptionStatus(item.id, status);
      notify("상태를 바꿨어요");
      await reload();
    } catch (e) {
      notify(e.message, true);
    }
  };

  if (loading && !data) return <Text style={styles.muted}>불러오는 중…</Text>;
  if (!data) return <Text style={styles.error}>{error || "목록을 불러오지 못했어요"}</Text>;

  return (
    <View style={styles.wrap}>
      <Card tone="blue">
        <Text style={styles.notice} testID="subscription-notice">
          {data.notice}
        </Text>
        <Text style={styles.caption}>할인 금액은 계산하거나 보장하지 않아요.</Text>
      </Card>
      {GROUPS.map((g) => (
        <View key={g.kind} style={styles.wrap}>
          <SectionTitle title={g.title} />
          {data.items
            .filter((i) => i.kind === g.kind)
            .map((item) => {
              const current = STATUS.find((s) => s.key === item.status);
              return (
                <Card key={item.id} tone="white">
                  <View style={styles.head}>
                    <Text style={styles.name}>{item.name}</Text>
                    <Tag label={current.label} tone={current.tone} />
                  </View>
                  <View style={styles.options}>
                    {STATUS.map((s) => (
                      <Button
                        key={s.key}
                        small
                        variant="secondary"
                        selected={item.status === s.key}
                        label={s.label}
                        a11yLabel={`${item.name} ${s.label}`}
                        onPress={() => change(item, s.key)}
                      />
                    ))}
                  </View>
                </Card>
              );
            })}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  name: { ...font.cardTitle, color: colors.text },
  options: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  notice: { ...font.bodyStrong, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 8 },
  error: { ...font.body, color: colors.danger },
});
