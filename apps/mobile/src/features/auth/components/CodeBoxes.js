import { useRef, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { colors, font, radius } from "@/theme";

import { CODE_LENGTH, digitsOnly } from "../code";

/**
 * 6칸 인증번호 입력. 보이는 칸은 그림일 뿐이고 실제 입력은 숨은 TextInput 하나가 받는다
 * (숫자 키패드, 붙여 넣기, iOS/Android 의 메시지·메일 자동 입력 제안이 그대로 동작한다).
 * @param {{ value: string, onChange: (digits: string) => void, error?: boolean, disabled?: boolean, testID?: string, onComplete?: (digits: string) => void }} props
 */
export default function CodeBoxes({ value, onChange, error = false, disabled = false, testID, onComplete }) {
  const input = useRef(null);
  const [focused, setFocused] = useState(false);
  const current = Math.min(value.length, CODE_LENGTH - 1);

  const change = (text) => {
    const digits = digitsOnly(text);
    onChange(digits);
    if (digits.length === CODE_LENGTH) onComplete?.(digits);
  };

  return (
    <Pressable onPress={() => input.current?.focus()} accessibilityLabel="인증번호 6자리 입력" accessibilityRole="none">
      <View style={styles.row}>
        {Array.from({ length: CODE_LENGTH }, (_, i) => {
          const filled = i < value.length;
          const active = focused && i === current && !disabled;
          return (
            <View key={i} style={[styles.box, filled ? styles.filled : styles.empty, active && styles.active, error && styles.error]}>
              <Text style={styles.digit}>{value[i] ?? ""}</Text>
            </View>
          );
        })}
      </View>
      <TextInput
        ref={input}
        value={value}
        onChangeText={change}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        keyboardType="number-pad"
        inputMode="numeric"
        maxLength={CODE_LENGTH}
        autoComplete="one-time-code"
        textContentType="oneTimeCode"
        editable={!disabled}
        caretHidden
        accessibilityLabel="인증번호"
        testID={testID}
        style={styles.hidden}
      />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", justifyContent: "space-between", gap: 8 },
  box: { flex: 1, aspectRatio: 0.9, maxWidth: 56, borderRadius: radius.md, alignItems: "center", justifyContent: "center", borderWidth: 1 },
  filled: { backgroundColor: colors.card, borderColor: colors.border },
  empty: { backgroundColor: colors.surface, borderColor: colors.surface },
  active: { backgroundColor: colors.card, borderColor: colors.text, borderWidth: 1.5 },
  error: { borderColor: colors.danger },
  digit: { ...font.title, color: colors.text },
  // 화면에는 보이지 않지만 포커스·접근성·자동 입력을 받는다
  hidden: { position: "absolute", opacity: 0, width: 1, height: 1 },
});
