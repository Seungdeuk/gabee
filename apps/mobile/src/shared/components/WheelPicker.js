import { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { indexToOffset, offsetToIndex } from "@/shared/wheel";
import { colors, font, radius } from "@/theme";

const ITEM_HEIGHT = 44;
const VISIBLE_ROWS = 3; // 가운데 줄이 선택값, 위아래 한 줄씩 흐리게
const PAD = ((VISIBLE_ROWS - 1) / 2) * ITEM_HEIGHT;
const SETTLE_MS = 120; // 웹은 momentum 이벤트가 없어 마지막 스크롤 뒤 이 시간이 지나면 멈춘 것으로 본다

/**
 * 아이폰 시간 휠처럼 세로로 스크롤해 가운데 줄에 멈춘 값을 고르는 선택기. 가운데 값을 누르면 숫자를 직접 입력할 수 있다.
 * 스크롤이 멈추면 onChange(값)을 부른다. onChange 가 false 를 돌려주면 거부로 보고 현재 value 위치로 되돌린다.
 * 값이 바깥에서 바뀌면 휠이 그 위치로 이동한다.
 * @param {{
 *   value: number | undefined,
 *   options: { value: number, label: string }[],
 *   onChange: (value: number) => boolean | void,
 *   parseInput: (text: string) => number | null,
 *   label: string,
 *   testID?: string,
 * }} props parseInput 은 직접 입력한 글자를 값으로 읽고, 맞지 않으면 null 을 돌려준다
 * @returns {JSX.Element}
 */
export default function WheelPicker({ value, options, onChange, parseInput, label, testID }) {
  const scroller = useRef(null);
  const timer = useRef(null);
  const valueRef = useRef(value);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const done = useRef(false); // 입력 마침(완료·포커스 아웃)을 한 번만 처리한다

  valueRef.current = value;
  const index = Math.max(options.findIndex((o) => o.value === value), 0);
  const shown = options[index]?.label ?? "";

  const moveTo = useCallback(
    (i) => {
      scroller.current?.scrollTo({ y: indexToOffset(i, ITEM_HEIGHT), animated: false });
    },
    [],
  );

  // 값이 바깥에서 바뀌면(저장 응답, 거부로 되돌림) 휠을 그 위치로 옮긴다
  useEffect(() => {
    moveTo(index);
  }, [index, moveTo]);

  useEffect(() => () => clearTimeout(timer.current), []);

  /** 스크롤이 멈춘 위치의 값으로 정렬하고, 값이 달라졌으면 알린다(거부되면 되돌린다). */
  const settle = (offset) => {
    clearTimeout(timer.current);
    const i = offsetToIndex(offset, ITEM_HEIGHT, options.length);
    moveTo(i);
    const picked = options[i]?.value;
    if (picked !== undefined && picked !== valueRef.current && onChange(picked) === false) moveTo(index);
  };

  const scheduleSettle = (event) => {
    const y = event.nativeEvent.contentOffset.y;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => settle(y), SETTLE_MS);
  };

  const step = (delta) => {
    const next = options[Math.min(Math.max(index + delta, 0), options.length - 1)];
    if (next && next.value !== value && onChange(next.value) === false) moveTo(index);
  };

  const startEditing = () => {
    done.current = false;
    setText(shown);
    setEditing(true);
  };

  const finishEditing = () => {
    if (done.current) return;
    done.current = true;
    setEditing(false);
    const parsed = parseInput(text);
    if (parsed === null || parsed === value) {
      moveTo(index); // 범위 밖·빈 값은 이전 값으로 되돌린다
      return;
    }
    if (onChange(parsed) === false) moveTo(index);
  };

  return (
    <View
      style={styles.box}
      testID={testID}
      accessible={!editing}
      accessibilityRole="adjustable"
      accessibilityLabel={`${label} ${shown}`}
      accessibilityValue={{ text: shown }}
      accessibilityActions={[{ name: "increment" }, { name: "decrement" }]}
      onAccessibilityAction={(event) => step(event.nativeEvent.actionName === "increment" ? 1 : -1)}
    >
      <View pointerEvents="none" style={styles.band} />
      <ScrollView
        ref={scroller}
        style={styles.scroll}
        contentContainerStyle={{ paddingVertical: PAD }}
        showsVerticalScrollIndicator={false}
        nestedScrollEnabled
        snapToInterval={ITEM_HEIGHT}
        decelerationRate="fast"
        scrollEventThrottle={16}
        scrollEnabled={!editing}
        onScroll={scheduleSettle}
        onScrollEndDrag={scheduleSettle}
        onMomentumScrollEnd={(event) => settle(event.nativeEvent.contentOffset.y)}
        onLayout={() => moveTo(index)}
      >
        {options.map((o, i) => (
          <Pressable
            key={o.value}
            style={styles.item}
            onPress={() => (i === index ? startEditing() : step(i - index))}
          >
            <Text style={i === index ? styles.itemSelected : styles.itemText}>{o.label}</Text>
          </Pressable>
        ))}
      </ScrollView>
      {editing ? (
        <View style={styles.editor}>
          <TextInput
            style={styles.input}
            value={text}
            onChangeText={setText}
            keyboardType="number-pad"
            maxLength={2}
            autoFocus
            selectTextOnFocus
            onBlur={finishEditing}
            onSubmitEditing={finishEditing}
            accessibilityLabel={`${label} 직접 입력`}
          />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { width: 48, height: ITEM_HEIGHT * VISIBLE_ROWS, backgroundColor: colors.card, overflow: "hidden" },
  band: { position: "absolute", left: 0, right: 0, top: PAD, height: ITEM_HEIGHT, borderRadius: radius.sm, backgroundColor: colors.surfaceStrong },
  scroll: { flex: 1 },
  item: { height: ITEM_HEIGHT, alignItems: "center", justifyContent: "center" },
  itemText: { ...font.body, color: colors.placeholder },
  itemSelected: { ...font.bodyStrong, color: colors.text },
  editor: { position: "absolute", left: 0, right: 0, top: PAD, height: ITEM_HEIGHT, borderRadius: radius.sm, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.primary },
  input: { flex: 1, textAlign: "center", ...font.bodyStrong, color: colors.text, padding: 0 },
});
