import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import Tag from "@/shared/components/Tag";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import {
  addAllowanceCredit,
  addAllowanceUse,
  deleteAllowancePlan,
  getAllowances,
  payAllowanceDue,
  setAllowancePlan,
  voidAllowanceEntry,
} from "../api";
import { formatMoneyInput, parseWon, won } from "../format";
import AllowancePlanForm, { planText } from "./AllowancePlanForm";
import AllowanceRequests from "./AllowanceRequests";

const SOURCE_LABEL = { manual: "직접", plan_auto: "자동 지급", plan_remind: "리마인드", request: "요청 승인" };

/**
 * 용돈 장부: 자녀별 잔액, 고정 주기(자동 지급 또는 리마인드), 입금·사용 내역. 은행·계좌와 연결하지 않고
 * 앱 안 장부로만 관리한다(보안상 실시간 연동을 하지 않는다). 잔액보다 큰 사용은 서버가 거절한다.
 * @param {{ notify: (text: string, isError?: boolean) => void }} props
 */
export default function AllowanceTab({ notify }) {
  const { data, error, loading, reload } = useResource(getAllowances);

  if (loading && !data) return <Text style={styles.muted}>불러오는 중…</Text>;
  if (!data) return <Text style={styles.error}>{error || "용돈을 불러오지 못했어요"}</Text>;
  if (data.length === 0) return <Text style={styles.muted}>자녀(부모 역할이 아닌 구성원)가 없어요</Text>;

  return (
    <View style={styles.wrap}>
      <Text style={styles.caption} testID="allowance-notice">
        용돈은 가비 앱 안 장부로만 관리해요. 은행 계좌와 연결하지 않아서 실제 송금은 직접 하고, 여기에는 기록만 남아요.
      </Text>
      {data.map((c) => (
        <ChildLedger key={c.child_id} item={c} notify={notify} onChanged={reload} />
      ))}
    </View>
  );
}

function ChildLedger({ item, notify, onChanged }) {
  const [editingPlan, setEditingPlan] = useState(false);
  const [credit, setCredit] = useState("");
  const [creditMemo, setCreditMemo] = useState("");
  const [use, setUse] = useState("");
  const [useMemo, setUseMemo] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async (fn, done, after) => {
    setBusy(true);
    try {
      await fn();
      notify(done);
      after?.();
      await onChanged();
      return true;
    } catch (e) {
      notify(e.message, true);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const savePlan = async (body) => {
    const ok = await run(() => setAllowancePlan(item.child_id, body), "용돈 주기를 저장했어요");
    if (ok) setEditingPlan(false);
  };

  const saveCredit = () => {
    const value = parseWon(credit);
    if (!(value > 0)) return notify("지급 금액은 1원 이상의 정수로 입력해 주세요", true);
    run(() => addAllowanceCredit(item.child_id, { amount: value, memo: creditMemo }), "지급을 기록했어요", () => {
      setCredit("");
      setCreditMemo("");
    });
  };

  const saveUse = () => {
    const value = parseWon(use);
    if (!(value > 0)) return notify("사용 금액은 1원 이상의 정수로 입력해 주세요", true);
    run(() => addAllowanceUse(item.child_id, { amount: value, memo: useMemo }), "사용 내역을 기록했어요", () => {
      setUse("");
      setUseMemo("");
    });
  };

  return (
    <Card tone="white" testID={`ledger-${item.name}`}>
      <View style={styles.head}>
        <View style={styles.grow}>
          <Text style={styles.name}>{item.name}</Text>
          <Text style={styles.caption}>
            받은 용돈 {won(item.total_credit)} · 쓴 돈 {won(item.total_use)}
          </Text>
        </View>
        <View style={styles.balanceBox}>
          <Text style={styles.caption}>잔액</Text>
          <Text style={[styles.balance, item.balance > 0 ? styles.ok : styles.none]} testID={`balance-${item.name}`}>
            {won(item.balance)}
          </Text>
        </View>
      </View>

      <View style={styles.planRow}>
        <View style={styles.grow}>
          <Text style={styles.label}>고정 용돈 주기</Text>
          <Text style={styles.caption} testID={`plan-${item.name}`}>
            {item.plan ? `${planText(item.plan)} · 다음 ${item.plan.next_due}` : "설정 안 함"}
          </Text>
        </View>
        {item.can_manage && !editingPlan ? (
          <View style={styles.actions}>
            <Button small variant="secondary" label={item.plan ? "주기 수정" : "주기 설정"} a11yLabel={`${item.name} 주기 ${item.plan ? "수정" : "설정"}`} onPress={() => setEditingPlan(true)} />
            {item.plan ? (
              <Button small variant="ghost" label="주기 끄기" a11yLabel={`${item.name} 주기 끄기`} onPress={() => run(() => deleteAllowancePlan(item.child_id), "용돈 주기를 껐어요")} />
            ) : null}
          </View>
        ) : null}
      </View>
      {editingPlan ? <AllowancePlanForm name={item.name} initial={item.plan} busy={busy} onSubmit={savePlan} onCancel={() => setEditingPlan(false)} notify={notify} /> : null}

      {item.pending.length > 0 ? (
        <View style={styles.pending} testID={`pending-${item.name}`}>
          <Text style={styles.label}>지급할 차례예요</Text>
          {item.pending.map((p) => (
            <View key={p.due_date} style={styles.planRow}>
              <Text style={[styles.caption, styles.grow]}>
                {p.due_date} · {won(p.amount)}
              </Text>
              <Button small label="지급했어요" a11yLabel={`${item.name} ${p.due_date} 지급했어요`} onPress={() => run(() => payAllowanceDue(item.child_id, p.due_date), "지급을 기록했어요")} disabled={busy} />
            </View>
          ))}
        </View>
      ) : null}

      {item.can_manage ? (
        <View style={styles.line}>
          <Field style={styles.amountField} value={credit} onChangeText={(text) => setCredit(formatMoneyInput(text))} placeholder={`${item.name} 지급 금액`} keyboardType="numeric" />
          <Field style={styles.grow} value={creditMemo} onChangeText={setCreditMemo} placeholder="메모" />
          <Button small label="지급 기록" a11yLabel={`${item.name} 지급 기록`} onPress={saveCredit} disabled={busy} />
        </View>
      ) : null}
      {item.can_record_use ? (
        <View style={styles.line}>
          <Field style={styles.amountField} value={use} onChangeText={(text) => setUse(formatMoneyInput(text))} placeholder={`${item.name} 사용 금액`} keyboardType="numeric" />
          <Field style={styles.grow} value={useMemo} onChangeText={setUseMemo} placeholder="어디에 썼나요" />
          <Button small variant="secondary" label="사용 기록" a11yLabel={`${item.name} 사용 기록`} onPress={saveUse} disabled={busy} />
        </View>
      ) : null}

      <AllowanceRequests item={item} notify={notify} onChanged={onChanged} />

      <Text style={styles.label}>월별 요약</Text>
      {item.months.map((m) => (
        <Text key={m.month} style={styles.caption} testID={`month-${item.name}-${m.month}`}>
          {m.month} · 받은 용돈 {won(m.credit)} · 쓴 돈 {won(m.use)}
        </Text>
      ))}

      <Text style={styles.label}>내역</Text>
      {item.entries.length === 0 ? <Text style={styles.caption}>아직 내역이 없어요</Text> : null}
      {item.entries.map((e) => (
        <View key={e.id} style={styles.entry} testID={`entry-${item.name}-${e.id}`}>
          <View style={styles.grow}>
            <Text style={[styles.entryTitle, e.voided && styles.voided]}>
              {e.kind === "credit" ? "+" : "−"}
              {won(e.amount)} · {e.memo || (e.kind === "credit" ? "용돈" : "사용")}
            </Text>
            <Text style={styles.caption}>
              {e.date} · {e.by_name} · {SOURCE_LABEL[e.source]}
              {e.balance_after === null ? "" : ` · 잔액 ${won(e.balance_after)}`}
            </Text>
          </View>
          {e.voided ? (
            <Tag label="취소됨" tone="gray" />
          ) : (
            <Button small variant="ghost" label="취소" a11yLabel={`${item.name} ${e.date} ${won(e.amount)} 취소`} onPress={() => run(() => voidAllowanceEntry(item.child_id, e.id), "내역을 취소했어요")} disabled={busy} />
          )}
        </View>
      ))}
    </Card>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
  head: { flexDirection: "row", alignItems: "center", gap: 12 },
  grow: { flex: 1 },
  name: { ...font.cardTitle, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
  label: { fontSize: 14, fontWeight: "500", color: colors.text },
  balanceBox: { alignItems: "flex-end" },
  balance: { ...font.cardTitle },
  ok: { color: colors.success },
  none: { color: colors.danger },
  planRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  actions: { flexDirection: "row", gap: 8 },
  pending: { gap: 8, padding: 12, borderRadius: 12, backgroundColor: colors.surface },
  line: { flexDirection: "row", alignItems: "center", gap: 8 },
  amountField: { width: 120 },
  entry: { flexDirection: "row", alignItems: "center", gap: 8 },
  entryTitle: { ...font.body, color: colors.text },
  voided: { textDecorationLine: "line-through", color: colors.textMuted },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 8 },
  error: { ...font.body, color: colors.danger },
});
