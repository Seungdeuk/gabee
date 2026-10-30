import { useState } from "react";
import { StyleSheet, View } from "react-native";

import Segmented from "@/shared/components/Segmented";

import AllowanceTab from "./AllowanceTab";
import ExpenseTab from "./ExpenseTab";
import SettlementTab from "./SettlementTab";

const PARTS = [
  { key: "settle", label: "정산" },
  { key: "expense", label: "지출" },
  { key: "allowance", label: "용돈" },
];

/**
 * 정산·용돈 구역: 엔빵(N분의 1)할 지출을 넣고(지출), 정산하고(정산), 아이 용돈을 챙긴다(용돈).
 * @param {{ month: string, notify: (text: string, isError?: boolean) => void, refreshKey?: number, initial?: string }} props initial: 처음 열 하위 구역
 */
export default function MoneySection({ month, notify, refreshKey, initial = "settle" }) {
  const [part, setPart] = useState(initial);
  return (
    <View style={styles.wrap}>
      <Segmented options={PARTS} value={part} onChange={setPart} />
      {part === "settle" ? <SettlementTab month={month} notify={notify} refreshKey={refreshKey} /> : null}
      {part === "expense" ? <ExpenseTab month={month} notify={notify} /> : null}
      {part === "allowance" ? <AllowanceTab notify={notify} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
});
