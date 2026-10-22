import { useCallback, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import SectionTitle from "@/shared/components/SectionTitle";
import Tag from "@/shared/components/Tag";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import {
  createSubscription,
  deleteSubscription,
  generateMonthly,
  getMembers,
  getMonthlyPlan,
  getMyId,
  getSubscriptions,
  updateSubscription,
} from "../api";
import { won } from "../format";
import SubscriptionForm, { CARRIERS } from "./SubscriptionForm";

const STATUS = [
  { key: "check", label: "확인 필요", tone: "gray" },
  { key: "available", label: "적용 가능", tone: "orange" },
  { key: "active", label: "✓ 적용 중", tone: "green" },
];

const GROUPS = [
  { kind: "ott", title: "OTT" },
  { kind: "telecom", title: "통신비 가족 할인" },
];

const PLAN_STATE = {
  ready: { label: "만들 수 있어요", tone: "orange" },
  created: { label: "✓ 만들었어요", tone: "green" },
  no_payer: { label: "결제한 사람 없음", tone: "red" },
};

const carrierLabel = (key) => CARRIERS.find((c) => c.key === key)?.label;

/** @param {import("../api").Subscription} item @returns {string} 예: SKT · 월 55,000원 · 매월 25일 결제 · 엄마 결제 · 1명 분담 */
function summaryText(item) {
  const parts = [];
  if (item.carrier) parts.push(carrierLabel(item.carrier));
  parts.push(item.monthly_fee == null ? "금액 미입력" : `월 ${won(item.monthly_fee)}`);
  if (item.billing_day != null) parts.push(`매월 ${item.billing_day}일 결제`);
  parts.push(item.payer_name ? `${item.payer_name} 결제` : "결제한 사람 없음");
  parts.push(`${item.split_among.length}명 분담`);
  return parts.join(" · ");
}

/**
 * 구독·통신비 관리: 항목 추가·수정·삭제, 월 금액·결제일·통신사, 결제한 사람·나눌 사람, 가족 할인 상태,
 * 그리고 "이번 달 구독료 지출 만들기". 금액은 사용자가 입력한 값만 합산하고 할인 금액은 계산하지도 보장하지도 않는다.
 * 만든 지출은 미정산이라 정산 탭에서 정산하기를 눌러야 잔액에 들어간다.
 * @param {{ month: string, notify: (text: string, isError?: boolean) => void }} props
 */
export default function SubscriptionTab({ month, notify }) {
  const { data, error, loading, reload } = useResource(getSubscriptions);
  const loadPlan = useCallback(() => getMonthlyPlan(month), [month]);
  const plan = useResource(loadPlan);
  const members = useResource(getMembers);
  const me = useResource(getMyId);
  const [editing, setEditing] = useState(null); // { kind } 추가 | { id } 수정
  const [busy, setBusy] = useState(false);

  const refresh = () => Promise.all([reload(), plan.reload()]);
  const run = async (fn, done) => {
    setBusy(true);
    try {
      const result = await fn();
      if (done) notify(typeof done === "function" ? done(result) : done);
      await refresh();
      return true;
    } catch (e) {
      notify(e.message, true);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const save = async (values) => {
    const ok = await run(
      () => (editing.id ? updateSubscription(editing.id, values) : createSubscription({ kind: editing.kind, ...values })),
      editing.id ? "항목을 수정했어요" : "항목을 추가했어요",
    );
    if (ok) setEditing(null);
  };

  const generate = () =>
    run(
      () => generateMonthly(month),
      (r) => `구독료 지출 ${r.created.length}건을 만들었어요 · 정산 탭에서 정산하기를 눌러 주세요`,
    );

  if (loading && !data) return <Text style={styles.muted}>불러오는 중…</Text>;
  if (!data) return <Text style={styles.error}>{error || "목록을 불러오지 못했어요"}</Text>;

  const people = members.data ?? [];
  const planItems = (plan.data?.items ?? []).filter((i) => i.state !== "no_fee");
  const skipped = (plan.data?.items ?? []).length - planItems.length;
  const formProps = { people, meId: me.data ?? null, busy, onSubmit: save, onCancel: () => setEditing(null), notify };

  return (
    <View style={styles.wrap}>
      <Card tone="blue">
        <Text style={styles.notice} testID="subscription-notice">
          {data.notice}
        </Text>
        <Text style={styles.caption}>할인 금액은 계산하거나 보장하지 않아요.</Text>
      </Card>

      <Card tone="white">
        <View style={styles.head}>
          <Text style={styles.name}>월 합계</Text>
          <Text style={styles.total} testID="subscription-total">
            {won(data.monthly_total)}
          </Text>
        </View>
        <Text style={styles.caption}>입력한 월 금액의 합이에요. 할인은 반영하지 않아요.</Text>
      </Card>

      <SectionTitle title={`${month} 구독료 지출`} />
      <Card tone="white" testID="monthly-plan">
        {planItems.length === 0 ? <Text style={styles.muted}>금액을 입력한 항목이 없어요</Text> : null}
        {planItems.map((i) => (
          <View key={i.id} style={styles.head}>
            <View style={styles.grow}>
              <Text style={styles.name}>{i.name}</Text>
              <Text style={styles.caption}>
                {won(i.amount)} · {i.date.slice(8)}일 · {i.payer_name || "결제한 사람 없음"} · {i.split_count}명 분담
              </Text>
            </View>
            <Tag label={PLAN_STATE[i.state].label} tone={PLAN_STATE[i.state].tone} />
          </View>
        ))}
        {skipped > 0 ? <Text style={styles.caption}>금액이 없는 항목 {skipped}개는 건너뛰어요.</Text> : null}
        <Button
          label={plan.data?.ready_count ? `이번 달 구독료 지출 만들기 · ${plan.data.ready_count}건 ${won(plan.data.ready_total)}` : "이번 달 구독료 지출 만들기"}
          a11yLabel="구독료 지출 만들기"
          onPress={generate}
          disabled={busy || !plan.data?.ready_count}
        />
        <Text style={styles.caption}>{"만든 지출은 \"미정산\"이에요. 정산 탭에서 정산하기를 눌러야 잔액에 들어가요."}</Text>
      </Card>

      {GROUPS.map((g) => (
        <View key={g.kind} style={styles.wrap}>
          <SectionTitle title={g.title} action="+ 추가" onAction={() => setEditing({ kind: g.kind })} />
          {editing && !editing.id && editing.kind === g.kind ? <SubscriptionForm kind={g.kind} {...formProps} /> : null}
          {data.items
            .filter((i) => i.kind === g.kind)
            .map((item) =>
              editing?.id === item.id ? (
                <SubscriptionForm key={item.id} kind={g.kind} initial={item} {...formProps} />
              ) : (
                <Card key={item.id} tone="white">
                  <View style={styles.head}>
                    <View style={styles.grow}>
                      <Text style={styles.name}>{item.name}</Text>
                      <Text style={styles.caption}>{summaryText(item)}</Text>
                    </View>
                    <Tag label={STATUS.find((s) => s.key === item.status).label} tone={STATUS.find((s) => s.key === item.status).tone} />
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
                        onPress={() => run(() => updateSubscription(item.id, { status: s.key }), "상태를 바꿨어요")}
                      />
                    ))}
                  </View>
                  <View style={styles.actions}>
                    <Button small variant="secondary" label="수정" a11yLabel={`${item.name} 수정`} onPress={() => setEditing({ id: item.id })} />
                    <Button small variant="ghost" label="삭제" a11yLabel={`${item.name} 삭제`} onPress={() => run(() => deleteSubscription(item.id), "항목을 삭제했어요")} />
                  </View>
                </Card>
              ),
            )}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12 },
  grow: { flex: 1, gap: 2 },
  name: { ...font.cardTitle, color: colors.text },
  total: { ...font.title, color: colors.text },
  options: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  actions: { flexDirection: "row", justifyContent: "flex-end", gap: 8 },
  notice: { ...font.bodyStrong, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 8 },
  error: { ...font.body, color: colors.danger },
});
