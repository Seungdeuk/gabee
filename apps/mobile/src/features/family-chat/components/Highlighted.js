import { StyleSheet, Text } from "react-native";

import { colors, font } from "@/theme";

import { splitHighlight } from "../searchUtils";

/**
 * 글을 강조 조각으로 나눠 Text 안에 넣을 노드 배열로 만든다. 일치하는 부분은 hitStyle 의 안쪽 Text 가 된다.
 * @param {string} text
 * @param {string[]} terms
 * @param {object} hitStyle
 * @returns {(string | import("react").ReactElement)[]}
 */
export function highlightNodes(text, terms, hitStyle) {
  return splitHighlight(text, terms).map((part, i) =>
    part.hit ? (
      <Text key={i} style={hitStyle}>
        {part.text}
      </Text>
    ) : (
      part.text
    ),
  );
}

/**
 * 글 안에서 검색어 낱말이 들어 있는 부분을 굵게(꿀색 바탕) 보여 준다. 대소문자는 구분하지 않는다.
 * @param {{ text: string, terms: string[], style?: object, numberOfLines?: number }} props
 */
export default function Highlighted({ text, terms, style, numberOfLines }) {
  return (
    <Text style={style} numberOfLines={numberOfLines}>
      {highlightNodes(text, terms, styles.hit)}
    </Text>
  );
}

export const hitStyles = StyleSheet.create({
  current: { fontFamily: font.bodyStrong.fontFamily, color: colors.onDark, backgroundColor: colors.accent },
});

const styles = StyleSheet.create({
  hit: { fontFamily: font.bodyStrong.fontFamily, color: colors.text, backgroundColor: colors.honeySoft },
});
