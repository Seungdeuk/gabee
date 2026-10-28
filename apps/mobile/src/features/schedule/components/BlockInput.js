import { useEffect, useRef, useState } from "react";
import { Keyboard, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { colors } from "@/theme";

/**
 * 블록으로 나뉜 숫자 입력 칸(날짜 YYYY-MM-DD, 시간 HH:MM). 칸은 하나이고 구분 글자(-, :)는 자동이다.
 * - 영역(연·월·일, 시·분)을 터치하면 그 영역이 통째로 선택되고, 이어서 치는 숫자가 그 영역을 처음부터 새로 채운다.
 * - 두 자리 영역은 첫 숫자가 크면 앞에 0을 붙여 바로 확정한다(월에서 9 → 09). 확정되면 다음 영역이 자동으로 선택된다.
 * - 범위를 벗어나는 숫자는 무시한다(월 13, 일 32, 시 24, 분 60). 한 자리만 치고 다른 영역으로 가면 앞에 0을 붙인다.
 * - 키보드의 좌우 화살표로 영역을 옮기고, Backspace 로 지운다(폰 숫자 키보드에는 화살표가 없어 터치로 옮긴다).
 * @param {{ blocks: { key: string, length: number, hint: string, min: number, max: number, padAbove?: number }[], separators: string[], values: string[], onChange: (values: string[]) => void, active?: boolean, onFocus?: () => void, autoFocus?: boolean, large?: boolean, compact?: boolean }} props
 *   values 는 영역마다 지금까지 친 숫자(비어 있으면 빈 글자)이고, 빈 자리는 hint 글자가 옅게 보인다. padAbove 는 이 숫자보다 큰 첫 숫자를 치면 0을 붙인다.
 */
export default function BlockInput({ blocks, separators, values, onChange, active = false, onFocus, autoFocus = false, large = false, compact = false }) {
  const inputRef = useRef(null);
  const [sel, setSel] = useState(autoFocus ? 0 : null);
  const [fresh, setFresh] = useState(true);
  const [focused, setFocused] = useState(false);

  // 안드로이드는 키보드만 내려가고 입력 칸은 포커스를 유지해서, 다시 영역을 눌러도 focus() 가 키보드를 못 띄운다.
  // 키보드가 내려가면 포커스도 풀어 두어 다음 터치에서 키보드가 다시 뜨게 한다.
  useEffect(() => {
    const hide = Keyboard.addListener("keyboardDidHide", () => inputRef.current?.blur());
    return () => hide.remove();
  }, []);

  // 한 자리만 친 영역은 앞에 0을 붙여 확정하고, 범위 밖이면 비운다.
  const normalize = (vals, i) => {
    const b = blocks[i];
    const v = vals[i];
    if (v.length === 0 || v.length === b.length) return vals;
    const padded = v.padStart(b.length, "0");
    const ok = Number(padded) >= b.min && Number(padded) <= b.max;
    const next = [...vals];
    next[i] = ok ? padded : "";
    return next;
  };
  const select = (i) => {
    if (sel !== null && sel !== i) {
      const cleaned = normalize(values, sel);
      if (cleaned !== values) onChange(cleaned);
    }
    setSel(i);
    setFresh(true);
    inputRef.current?.focus();
  };
  const typeDigit = (digit) => {
    if (sel === null) return;
    const b = blocks[sel];
    const current = fresh ? "" : values[sel];
    let next = current + digit;
    if (b.padAbove !== undefined && current === "" && Number(digit) > b.padAbove) next = `0${digit}`;
    if (next.length === b.length && (Number(next) < b.min || Number(next) > b.max)) return;
    const vals = [...values];
    vals[sel] = next;
    onChange(vals);
    if (next.length === b.length) {
      setSel(sel < blocks.length - 1 ? sel + 1 : sel);
      setFresh(true);
    } else {
      setFresh(false);
    }
  };
  const onKeyPress = (event) => {
    const key = event.nativeEvent.key;
    if (sel === null) return;
    if (key === "ArrowLeft" && sel > 0) select(sel - 1);
    else if (key === "ArrowRight" && sel < blocks.length - 1) select(sel + 1);
    else if (key === "Backspace") {
      const vals = [...values];
      if (values[sel] !== "") {
        vals[sel] = fresh ? "" : values[sel].slice(0, -1);
        setFresh(false);
        onChange(vals);
      } else if (sel > 0) {
        vals[sel - 1] = "";
        setSel(sel - 1);
        setFresh(false);
        onChange(vals);
      }
    }
  };

  return (
    <View style={[styles.box, large && styles.boxLarge, compact && styles.boxCompact, (active || focused) && styles.boxOn]}>
      <View style={styles.row}>
        {blocks.map((b, i) => (
          <View key={b.key} style={styles.row}>
            <Pressable
              onPress={() => select(i)}
              accessibilityRole="button"
              accessibilityLabel={`${b.hint} 영역`}
              style={[styles.block, focused && sel === i && styles.blockOn]}
            >
              <Text style={[styles.text, large && styles.textLarge, compact && styles.textCompact]}>
                {values[i]}
                <Text style={styles.hint}>{b.hint.slice(values[i].length)}</Text>
              </Text>
            </Pressable>
            {i < separators.length ? <Text style={[styles.text, large && styles.textLarge, compact && styles.textCompact]}>{separators[i]}</Text> : null}
          </View>
        ))}
      </View>
      <TextInput
        ref={inputRef}
        value=""
        autoFocus={autoFocus}
        keyboardType="number-pad"
        caretHidden
        onChangeText={(text) => {
          const digits = text.replace(/\D/g, "");
          if (digits !== "") typeDigit(digits[digits.length - 1]);
        }}
        onKeyPress={onKeyPress}
        onFocus={() => {
          setFocused(true);
          onFocus?.();
        }}
        onBlur={() => {
          setFocused(false);
          if (sel !== null) {
            const cleaned = normalize(values, sel);
            if (cleaned !== values) onChange(cleaned);
          }
        }}
        style={styles.hidden}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    alignItems: "center",
    justifyContent: "center",
    minHeight: 44,
    paddingHorizontal: 10,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 14,
  },
  boxLarge: { minHeight: 48 },
  boxCompact: { minHeight: 40, paddingHorizontal: 4 },
  boxOn: { borderColor: colors.peach },
  row: { flexDirection: "row", alignItems: "center" },
  block: { paddingHorizontal: 4, paddingVertical: 3, borderRadius: 8 },
  blockOn: { backgroundColor: colors.surfaceStrong },
  text: { fontSize: 20, fontWeight: "500", color: colors.text },
  textLarge: { fontSize: 22 },
  textCompact: { fontSize: 17 },
  hint: { color: colors.disabled, fontWeight: "400" },
  hidden: { position: "absolute", width: 1, height: 1, opacity: 0 },
});
