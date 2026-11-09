import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import { useState } from "react";
import { Linking, Pressable, Share, StyleSheet, Text, View } from "react-native";

import { colors } from "@/theme";

import useOriginal from "../hooks/useOriginal";
import { canOpenWebSource, webSourceHost } from "../webSources";
import OriginalViewer from "./OriginalViewer";

/** 한 줄 안의 **굵게** 와 [1] 출처 번호를 글자 조각으로 나눈다. */
function inline(text, keyBase) {
  return text.split(/(\*\*[^*]+\*\*|\[\d+\])/).filter(Boolean).map((part, i) => {
    const key = `${keyBase}-${i}`;
    if (part.startsWith("**")) {
      return (
        <Text key={key} style={styles.strong}>
          {part.slice(2, -2)}
        </Text>
      );
    }
    if (/^\[\d+\]$/.test(part)) {
      return (
        <Text key={key} style={styles.cite}>
          {` ${part.slice(1, -1)} `}
        </Text>
      );
    }
    return <Text key={key}>{part}</Text>;
  });
}

/** 간단한 마크다운(## 제목, - 목록, 빈 줄로 나뉜 문단)을 블록 목록으로 바꾼다. */
export function parseBlocks(text) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      if (line.startsWith("## ")) return { type: "h", text: line.slice(3) };
      if (/^[-*] /.test(line)) return { type: "li", text: line.slice(2) };
      return { type: "p", text: line };
    });
}

/**
 * 가비의 답변. 문단·제목·목록을 보여 주고, 아래에 출처 칩과 저장·복사 버튼을 둔다.
 * @param {{ text: string, sources?: { n: number, title: string, itemId?: string, sourcePath?: string | null }[], webSources?: { title: string, url: string }[], showActions?: boolean, children?: import("react").ReactNode }} props
 * children: 본문 아래, 출처 칩 위에 놓을 것(메시지 초안 카드 등). webSources: 답이 인용한 웹 페이지(눌러서 브라우저로 연다)
 */
export default function AnswerView({ text, sources = [], webSources = [], showActions = false, children }) {
  const [openSources, setOpenSources] = useState(false);
  const links = webSources.filter((s) => canOpenWebSource(s.url));
  const [copied, setCopied] = useState(false);
  const original = useOriginal();
  const blocks = parseBlocks(text);

  const copy = async () => {
    await Clipboard.setStringAsync(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  // TODO: .md 파일로 저장하려면 파일 시스템 모듈이 필요하다. 지금은 공유 시트로 내보낸다.
  const saveMd = () => Share.share({ message: text, title: "가비 보고서" });

  return (
    <View style={styles.wrap}>
      {blocks.map((b, i) =>
        b.type === "h" ? (
          <Text key={i} style={styles.h}>
            {b.text}
          </Text>
        ) : b.type === "li" ? (
          <View key={i} style={styles.li}>
            <Text style={styles.bullet}>•</Text>
            <Text style={styles.p}>{inline(b.text, i)}</Text>
          </View>
        ) : (
          <Text key={i} style={styles.p}>
            {inline(b.text, i)}
          </Text>
        ),
      )}

      {children}

      {sources.length > 0 ? (
        <>
          <Pressable onPress={() => setOpenSources((v) => !v)} style={styles.chip} accessibilityRole="button">
            <Ionicons name="document-text-outline" size={15} color={colors.text} />
            <Text style={styles.chipText}>
              출처 {sources.length}
              {sources.length === 1 ? ` · ${sources[0].title}` : ""}
            </Text>
          </Pressable>
          {openSources || sources.length === 1 ? (
            <View style={styles.sourceList}>
              {sources.map((s) => {
                return (
                  <View key={s.n} style={styles.sourceRow}>
                    {sources.length > 1 ? (
                      <Text style={styles.source}>
                        {s.n}. {s.title}
                      </Text>
                    ) : null}
                    {s.itemId ? (
                      <Pressable
                        onPress={() => original.open(s.itemId, s.sourcePath, s.title)}
                        style={styles.action}
                        accessibilityRole="button"
                      >
                        <Ionicons name="image-outline" size={15} color={colors.textSub} />
                        <Text style={styles.actionText}>원본 보기</Text>
                      </Pressable>
                    ) : null}
                  </View>
                );
              })}
            </View>
          ) : null}
        </>
      ) : null}

      {links.length > 0 ? (
        <View style={styles.webCard}>
          <View style={styles.webHeader}>
            <Ionicons name="globe-outline" size={18} color={colors.accent} />
            <Text style={styles.webHeading}>웹에서 찾았어요 · {links.length}곳</Text>
          </View>
          {links.map((s) => (
            <Pressable
              key={s.url}
              onPress={() => Linking.openURL(s.url).catch(() => {})}
              style={styles.webRow}
              accessibilityRole="link"
              accessibilityLabel={`${s.title} 페이지 열기`}
            >
              <View style={styles.webText}>
                <Text style={styles.webTitle} numberOfLines={2}>
                  {s.title}
                </Text>
                <Text style={styles.webHost} numberOfLines={1}>
                  {webSourceHost(s.url)}
                </Text>
              </View>
              <Ionicons name="open-outline" size={18} color={colors.accent} />
            </Pressable>
          ))}
        </View>
      ) : null}

      {showActions ? (
        <View style={styles.actions}>
          <Pressable onPress={saveMd} style={styles.action} accessibilityRole="button">
            <Ionicons name="download-outline" size={15} color={colors.textSub} />
            <Text style={styles.actionText}>보고서 .md 저장</Text>
          </Pressable>
          <Pressable onPress={copy} style={styles.action} accessibilityRole="button">
            <Ionicons name={copied ? "checkmark" : "copy-outline"} size={15} color={colors.textSub} />
            <Text style={styles.actionText}>{copied ? "복사했어요" : "복사"}</Text>
          </Pressable>
        </View>
      ) : null}

      <OriginalViewer state={original.state} onClose={original.close} />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 10 },
  p: { flexShrink: 1, fontSize: 15, lineHeight: 24, color: colors.text },
  strong: { fontWeight: "700" },
  h: { marginTop: 4, fontSize: 18, fontWeight: "700", color: colors.text },
  li: { flexDirection: "row", gap: 8, paddingLeft: 4 },
  bullet: { fontSize: 15, lineHeight: 24, color: colors.textSub },
  cite: {
    fontSize: 10,
    lineHeight: 16,
    color: colors.textMuted,
    backgroundColor: colors.surface,
  },
  chip: {
    alignSelf: "flex-start",
    minHeight: 36,
    paddingHorizontal: 12,
    borderRadius: 18,
    backgroundColor: colors.surface,
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
  },
  chipText: { fontSize: 13, fontWeight: "500", color: colors.text },
  sourceList: { gap: 6, paddingLeft: 4 },
  sourceRow: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 8 },
  source: { fontSize: 13, color: colors.textSub },
  webCard: {
    padding: 12,
    gap: 4,
    borderWidth: 1,
    borderColor: colors.accent,
    borderRadius: 14,
    backgroundColor: colors.honeySoft,
  },
  webHeader: { flexDirection: "row", alignItems: "center", gap: 6, paddingBottom: 4 },
  webHeading: { fontSize: 14, fontWeight: "700", color: colors.text },
  webRow: {
    minHeight: 52,
    paddingVertical: 8,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  webText: { flex: 1, gap: 2 },
  webTitle: { fontSize: 14, fontWeight: "600", color: colors.text },
  webHost: { fontSize: 12, color: colors.textSub },
  actions: { flexDirection: "row", gap: 8 },
  action: {
    minHeight: 36,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 18,
    backgroundColor: colors.card,
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
  },
  actionText: { fontSize: 13, color: colors.textSub },
});
