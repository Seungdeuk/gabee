import { Ionicons } from "@expo/vector-icons";
import { StyleSheet, Text, View } from "react-native";

import { colors } from "@/theme";

const UNREAD_MARK = "[읽지 못한 부분]";
const FIELD = /^- ([^:]{1,12}):\s*(.+)$/; // "- 날짜: 2026-10-05" 같은 요약 줄
const BLOCK_NO = /^\(블록 \d+\)\s*/; // 읽은 순서를 나타내는 번호는 보여 줄 필요가 없다
const SLIDE_NO = /^\[\d+\]\s*/;

/**
 * 저장된 기록 글(마크다운)을 화면용으로 나눈다.
 * 맨 앞 "# 제목", "분류:" 줄은 화면 위쪽에 따로 보이므로 뺀다.
 * @param {string} md
 * @returns {{ fields: { label: string, value: string }[], tags: string[], lines: { type: "heading" | "text" | "row", text?: string, cells?: string[], head?: boolean }[], unread: boolean }}
 */
export function parseRecord(md) {
  const rows = (md ?? "").split("\n");
  let i = 0;
  if (rows[i]?.startsWith("# ")) i += 1;
  if (rows[i]?.startsWith("분류:")) i += 1;

  const fields = [];
  let tags = [];
  for (; i < rows.length; i += 1) {
    const m = FIELD.exec(rows[i].trim());
    if (!m) break;
    if (m[1] === "태그") tags = m[2].split(",").map((t) => t.trim()).filter(Boolean);
    else fields.push({ label: m[1], value: m[2] });
  }

  const lines = [];
  let unread = false;
  let seenTableHead = false;
  for (; i < rows.length; i += 1) {
    const raw = rows[i].trim();
    if (!raw) continue;
    if (raw.includes(UNREAD_MARK)) {
      unread = true;
      continue;
    }
    if (raw.startsWith("|")) {
      const cells = raw.split("|").slice(1, -1).map((c) => c.trim());
      if (cells.every((c) => /^:?-{2,}:?$/.test(c))) continue; // 표의 구분선
      lines.push({ type: "row", cells, head: !seenTableHead });
      seenTableHead = true;
      continue;
    }
    seenTableHead = false;
    const text = raw.replace(BLOCK_NO, "").replace(SLIDE_NO, "");
    if (!text) continue;
    if (text.startsWith("## ")) lines.push({ type: "heading", text: text.slice(3) });
    else lines.push({ type: "text", text: text.replace(/^#+\s*/, "") });
  }
  return { fields, tags, lines, unread };
}

/**
 * 읽어 낸 내용을 보기 좋게 보여 준다: 위에 요약(날짜·금액 등과 태그), 아래에 읽어 낸 글(표는 칸으로, 소제목은 굵게).
 * @param {{ markdown: string }} props
 */
export default function RecordContent({ markdown }) {
  const { fields, tags, lines, unread } = parseRecord(markdown);
  return (
    <View style={styles.wrap}>
      {fields.length > 0 || tags.length > 0 ? (
        <View style={styles.card}>
          {fields.map((f) => (
            <View key={f.label} style={styles.field}>
              <Text style={styles.label}>{f.label}</Text>
              <Text style={styles.value} selectable>
                {f.value}
              </Text>
            </View>
          ))}
          {tags.length > 0 ? (
            <View style={styles.tags}>
              {tags.map((t) => (
                <View key={t} style={styles.tag}>
                  <Text style={styles.tagText}>{t}</Text>
                </View>
              ))}
            </View>
          ) : null}
        </View>
      ) : null}

      {unread ? (
        <View style={styles.unread}>
          <Ionicons name="alert-circle-outline" size={16} color={colors.warning} />
          <Text style={styles.unreadText}>읽지 못한 부분이 있어요. 원본과 비교해 확인해 주세요.</Text>
        </View>
      ) : null}

      <Text style={styles.sectionTitle}>읽어 낸 글</Text>
      {lines.length === 0 ? (
        <Text style={styles.empty}>읽어 낸 글이 없어요.</Text>
      ) : (
        <View style={[styles.card, styles.body]}>
          {lines.map((l, idx) =>
            l.type === "heading" ? (
              <Text key={idx} style={styles.heading}>
                {l.text}
              </Text>
            ) : l.type === "row" ? (
              <View key={idx} style={[styles.tableRow, l.head && styles.tableHead]}>
                {l.cells.map((c, ci) => (
                  <Text key={ci} style={[styles.cell, l.head && styles.cellHead]} selectable>
                    {c}
                  </Text>
                ))}
              </View>
            ) : (
              <Text key={idx} style={styles.line} selectable>
                {l.text}
              </Text>
            ),
          )}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 12 },
  card: { padding: 14, borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, gap: 8 },
  field: { flexDirection: "row", gap: 12 },
  label: { width: 52, fontSize: 13, color: colors.textMuted },
  value: { flex: 1, fontSize: 14, fontWeight: "600", color: colors.text },
  tags: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 2 },
  tag: { paddingHorizontal: 10, height: 24, borderRadius: 12, backgroundColor: colors.surfaceStrong, justifyContent: "center" },
  tagText: { fontSize: 12, color: colors.text },
  unread: { flexDirection: "row", gap: 6, padding: 10, borderRadius: 12, backgroundColor: colors.honeySoft },
  unreadText: { flex: 1, fontSize: 13, lineHeight: 19, color: colors.text },
  sectionTitle: { marginTop: 4, fontSize: 13, fontWeight: "700", color: colors.textSub },
  empty: { fontSize: 14, color: colors.textMuted },
  body: { gap: 6 },
  heading: { marginTop: 4, fontSize: 15, fontWeight: "700", color: colors.text },
  line: { fontSize: 14, lineHeight: 21, color: colors.text },
  tableRow: { flexDirection: "row", gap: 8, paddingVertical: 4, borderBottomWidth: 1, borderBottomColor: colors.divider },
  tableHead: { borderBottomColor: colors.border },
  cell: { flex: 1, minWidth: 0, fontSize: 13, lineHeight: 19, color: colors.text },
  cellHead: { fontWeight: "700", color: colors.textSub },
});
