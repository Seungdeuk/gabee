import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Field from "@/shared/components/Field";
import Tag from "@/shared/components/Tag";
import { colors, font } from "@/theme";

import { approveAllowanceRequest, cancelAllowanceRequest, rejectAllowanceRequest, requestAllowance } from "../api";
import { formatMoneyInput, parseWon, won } from "../format";

const STATUS = {
  pending: { label: "기다리는 중", tone: "orange" },
  approved: { label: "✓ 승인", tone: "green" },
  rejected: { label: "거절", tone: "red" },
  cancelled: { label: "취소됨", tone: "gray" },
};

/**
 * 용돈 요청: 자녀 본인이 금액과 사유를 적어 요청하고(대기 5건까지), 부모(또는 그룹을 만든 사람)가 승인·거절한다.
 * 승인하면 장부에 입금이 기록되고 금액을 바꿔 승인할 수도 있다. 자녀는 대기 중인 자기 요청을 취소할 수 있다.
 * @param {{ item: import("../api").Allowance, notify: (text: string, isError?: boolean) => void, onChanged: () => Promise<void> | void }} props
 */
export default function AllowanceRequests({ item, notify, onChanged }) {
  const [amount, setAmount] = useState("");
  const [memo, setMemo] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async (fn, done, after) => {
    setBusy(true);
    try {
      await fn();
      notify(done);
      after?.();
      await onChanged();
    } catch (e) {
      notify(e.message, true);
    } finally {
      setBusy(false);
    }
  };

  const send = () => {
    const value = parseWon(amount);
    if (!(value > 0)) return notify("요청 금액은 1원 이상의 정수로 입력해 주세요", true);
    run(() => requestAllowance(item.child_id, { amount: value, memo: memo.trim() }), "용돈을 요청했어요", () => {
      setAmount("");
      setMemo("");
    });
  };

  if (!item.can_request && item.requests.length === 0) return null;

  return (
    <View style={styles.box} testID={`requests-${item.name}`}>
      <Text style={styles.label}>용돈 요청</Text>
      {item.can_request ? (
        <View style={styles.line}>
          <Field style={styles.amountField} value={amount} onChangeText={(text) => setAmount(formatMoneyInput(text))} placeholder={`${item.name} 요청 금액`} keyboardType="numeric" />
          <Field style={styles.grow} value={memo} onChangeText={setMemo} placeholder="무엇에 쓸까요" />
          <Button small label="용돈 요청" a11yLabel={`${item.name} 용돈 요청`} onPress={send} disabled={busy} />
        </View>
      ) : null}
      {item.requests.map((r) => (
        <RequestRow key={r.id} item={item} request={r} busy={busy} run={run} notify={notify} />
      ))}
    </View>
  );
}

function RequestRow({ item, request: r, busy, run, notify }) {
  const [approve, setApprove] = useState("");
  const status = STATUS[r.status];
  const ask = `${item.name} ${won(r.amount)} 요청`;

  const onApprove = () => {
    const changed = approve.trim() ? parseWon(approve) : null;
    if (changed !== null && !(changed > 0)) return notify("승인 금액은 1원 이상의 정수로 입력해 주세요", true);
    return run(() => approveAllowanceRequest(item.child_id, r.id, { amount: changed ?? undefined }), "요청을 승인했어요 · 장부에 기록됐어요");
  };

  return (
    <View style={styles.row} testID={`request-${item.name}-${r.id}`}>
      <View style={styles.head}>
        <View style={styles.grow}>
          <Text style={styles.body}>
            {won(r.amount)} · {r.memo || "사유 없음"}
          </Text>
          <Text style={styles.caption}>
            {r.created_at.slice(0, 10)}
            {r.status === "approved" ? ` · ${r.decided_by_name}이(가) ${won(r.approved_amount)} 승인` : ""}
            {r.status === "rejected" ? ` · ${r.decided_by_name}이(가) 거절` : ""}
            {r.decision_note ? ` · ${r.decision_note}` : ""}
          </Text>
        </View>
        <Tag label={status.label} tone={status.tone} />
      </View>
      {r.status === "pending" && item.can_manage ? (
        <View style={styles.line}>
          <Field style={styles.grow} value={approve} onChangeText={(text) => setApprove(formatMoneyInput(text))} placeholder="승인 금액 (비우면 요청 금액)" keyboardType="numeric" />
          <Button small label="승인" a11yLabel={`${ask} 승인`} onPress={onApprove} disabled={busy} />
          <Button small variant="secondary" label="거절" a11yLabel={`${ask} 거절`} onPress={() => run(() => rejectAllowanceRequest(item.child_id, r.id, {}), "요청을 거절했어요")} disabled={busy} />
        </View>
      ) : null}
      {r.status === "pending" && item.can_request ? (
        <View style={styles.line}>
          <Button small variant="ghost" label="요청 취소" a11yLabel={`${ask} 취소`} onPress={() => run(() => cancelAllowanceRequest(item.child_id, r.id), "요청을 취소했어요")} disabled={busy} />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { gap: 8 },
  label: { fontSize: 14, fontWeight: "500", color: colors.text },
  line: { flexDirection: "row", alignItems: "center", gap: 8 },
  grow: { flex: 1, gap: 2 },
  amountField: { width: 120 },
  row: { gap: 8 },
  head: { flexDirection: "row", alignItems: "center", gap: 8 },
  body: { ...font.body, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
});
