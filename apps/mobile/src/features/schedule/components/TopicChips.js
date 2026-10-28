import { useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { colors, font, radius } from "@/theme";

import { TOPIC_TEXT } from "../constants";
import { TOPIC_COLOR_KEYS, TOPIC_NAME_MAX, topicErrorMessage, validateTopicName } from "../favorites";
import AnchoredPopover from "./AnchoredPopover";
import FilterChip from "./FilterChip";

const DELETE_MS = 3000; // 삭제 버튼이 저절로 사라지는 시간

/**
 * 주제 칩 줄. 짧게 누르면 선택/해제, 길게 누르면 그 칩 위에 "삭제" 버튼이 떠서 눌러야 지운다(약 3초 뒤 사라짐).
 * "+ 주제" 를 누르면 그 칩 아래에 이름·색·[추가] 말풍선이 뜬다. 키보드가 올라오면 말풍선이 키보드 위로 올라간다.
 * 선택은 여러 개를 받을 수 있다(등록 화면은 하나만 고르도록 onToggle 에서 처리). 새로 만든 주제는 onCreated 로 알린다.
 * @param {{ topics: { id: string, name: string, color: string }[], selectedIds: string[], onToggle: (id: string) => void,
 *   onCreate: (name: string, color: string) => Promise<{ id: string }>, onCreated?: (topic: { id: string }) => void, onDelete: (id: string) => void }} props
 */
export default function TopicChips({ topics, selectedIds, onToggle, onCreate, onCreated, onDelete }) {
  const [pop, setPop] = useState(null); // { kind: "delete", id, rect } | { kind: "add", rect }
  const [name, setName] = useState("");
  const [color, setColor] = useState(TOPIC_COLOR_KEYS[0]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const close = () => setPop(null);
  // React Compiler 가 콜백 안의 pop.id 를 렌더 중에 미리 읽으므로, null 일 때를 막아 둔 값으로 꺼내 쓴다.
  const deleteId = pop?.kind === "delete" ? pop.id : null;
  const check = validateTopicName(name);
  const submit = async () => {
    if (!check.ok || busy) return;
    setBusy(true);
    setError("");
    try {
      const created = await onCreate(check.name, color);
      onCreated?.(created);
      close();
      setName("");
      setColor(TOPIC_COLOR_KEYS[0]);
    } catch (e) {
      setError(topicErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.chips}>
      {topics.map((t) => (
        <FilterChip
          key={t.id}
          label={t.name}
          selected={selectedIds.includes(t.id)}
          accent={TOPIC_TEXT[t.color]}
          ringed={pop?.kind === "delete" && pop.id === t.id}
          onPress={() => {
            close();
            onToggle(t.id);
          }}
          onLongPressRect={(rect) => setPop({ kind: "delete", id: t.id, rect })}
        />
      ))}
      <FilterChip
        label="+ 주제"
        muted
        onPressRect={(rect) => {
          setError("");
          setPop({ kind: "add", rect });
        }}
      />

      <AnchoredPopover
        visible={pop?.kind === "delete"}
        anchor={pop?.rect ?? null}
        onClose={close}
        width={56}
        placement="above"
        tone="dark"
        autoCloseMs={DELETE_MS}
      >
        <Pressable
          onPress={() => {
            if (deleteId !== null) onDelete(deleteId);
            close();
          }}
          accessibilityRole="button"
          style={styles.delete}
        >
          <Text style={styles.deleteText}>삭제</Text>
        </Pressable>
      </AnchoredPopover>

      <AnchoredPopover visible={pop?.kind === "add"} anchor={pop?.rect ?? null} onClose={close} width={240} placement="right">
        <View style={styles.bubble}>
          <Text style={styles.title}>새 주제</Text>
          <TextInput
            value={name}
            onChangeText={(text) => {
              setName(text);
              setError("");
            }}
            autoFocus
            maxLength={TOPIC_NAME_MAX}
            placeholder="주제 이름"
            placeholderTextColor={colors.textMuted}
            style={styles.input}
          />
          <View style={styles.dots}>
            {TOPIC_COLOR_KEYS.map((key) => (
              <Pressable
                key={key}
                onPress={() => setColor(key)}
                hitSlop={4}
                accessibilityRole="button"
                accessibilityLabel={`색 ${key}`}
                accessibilityState={{ selected: color === key }}
                style={[styles.ring, color === key && styles.ringOn]}
              >
                <View style={[styles.dot, { backgroundColor: TOPIC_TEXT[key] }, color === key && styles.dotOn]} />
              </Pressable>
            ))}
          </View>
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <Pressable
            onPress={submit}
            disabled={!check.ok || busy}
            accessibilityRole="button"
            style={[styles.add, (!check.ok || busy) && styles.addOff]}
          >
            <Text style={styles.addText}>추가</Text>
          </Pressable>
        </View>
      </AnchoredPopover>
    </View>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 5 },
  delete: { paddingVertical: 7, alignItems: "center" },
  deleteText: { fontSize: 13, fontWeight: "700", color: colors.onDark },
  bubble: { padding: 12, gap: 10 },
  title: { ...font.caption, color: colors.textMuted },
  input: {
    minHeight: 38,
    paddingHorizontal: 12,
    borderRadius: radius.button,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    fontSize: 14,
    color: colors.text,
  },
  dots: { flexDirection: "row", justifyContent: "space-between" },
  ring: { width: 32, height: 32, borderRadius: 16, borderWidth: 2, borderColor: "transparent", alignItems: "center", justifyContent: "center" },
  ringOn: { borderColor: colors.text },
  dot: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: "transparent" },
  dotOn: { borderColor: colors.onDark },
  error: { ...font.caption, color: colors.danger },
  add: { minHeight: 36, alignItems: "center", justifyContent: "center", borderRadius: 12, backgroundColor: colors.text },
  addOff: { opacity: 0.55 },
  addText: { fontSize: 13, fontWeight: "700", color: colors.onDark },
});
