import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { colors, fonts, radius } from "@/theme";

import { BOMB_RED } from "./BombParts";

export const LIFE = { min: 1, max: 5, def: 3 };
export const SEC = { min: 1, max: 60, def: 10 };
export const clampTo = (n, r) => Math.max(r.min, Math.min(r.max, n));

/**
 * 폭탄 방 규칙 카드: 한 줄을 반으로 나눠 왼쪽 생명(하트), 오른쪽 시간(시계)을 각각 가운데 정렬로 둔다.
 * onLife / onSec 가 있으면(방장) − 숫자 + 로 고치고, 없으면(손님) 숫자만 보여 준다.
 */
export default function RuleCard({ life, sec, onLife, onSec }) {
  return (
    <View style={styles.card}>
      <Cell icon="heart" iconColor={BOMB_RED} label="생명" value={life} onChange={onLife ? (v) => onLife(clampTo(v, LIFE)) : undefined} />
      <Cell icon="timer-outline" iconColor={colors.text} label="시간" unit="초" value={sec} onChange={onSec ? (v) => onSec(clampTo(v, SEC)) : undefined} />
    </View>
  );
}

function Cell({ icon, iconColor, label, unit, value, onChange }) {
  const [text, setText] = useState(null);
  return (
    <View style={styles.cell} accessible accessibilityLabel={`${label} ${value}${unit ?? ""}`}>
      <Ionicons name={icon} size={20} color={iconColor} />
      {onChange ? (
        <Pressable onPress={() => onChange(value - 1)} accessibilityRole="button" accessibilityLabel={`${label} 줄이기`} style={styles.btn}>
          <Text style={styles.btnText}>−</Text>
        </Pressable>
      ) : null}
      <View style={styles.valueWrap}>
        {onChange ? (
          <TextInput
            value={text ?? String(value)}
            onChangeText={(v) => setText(v.replace(/[^0-9]/g, ""))}
            onBlur={() => {
              onChange(parseInt(text ?? value, 10) || value);
              setText(null);
            }}
            keyboardType="number-pad"
            inputMode="numeric"
            accessibilityLabel={label}
            style={styles.input}
          />
        ) : (
          <Text style={styles.value}>{value}</Text>
        )}
        {unit ? <Text style={styles.unit}>{unit}</Text> : null}
      </View>
      {onChange ? (
        <Pressable onPress={() => onChange(value + 1)} accessibilityRole="button" accessibilityLabel={`${label} 늘리기`} style={styles.btn}>
          <Text style={styles.btnText}>+</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { flexDirection: "row", paddingHorizontal: 6, borderRadius: radius.card, backgroundColor: colors.surface },
  cell: { flex: 1, minHeight: 52, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6 },
  btn: { width: 30, height: 30, borderRadius: 15, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  btnText: { fontSize: 20, lineHeight: 24, fontFamily: fonts.bold, color: colors.text },
  valueWrap: { minWidth: 40, flexDirection: "row", alignItems: "baseline", justifyContent: "center", gap: 2 },
  input: { minWidth: 26, paddingVertical: 0, paddingHorizontal: 0, textAlign: "center", includeFontPadding: false, fontSize: 20, lineHeight: 26, fontFamily: fonts.bold, color: colors.text },
  value: { fontSize: 20, lineHeight: 26, fontFamily: fonts.bold, color: colors.text },
  unit: { fontSize: 13, fontFamily: fonts.bold, color: colors.textSub },
});
