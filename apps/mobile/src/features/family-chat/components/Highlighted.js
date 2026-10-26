import { StyleSheet, Text } from "react-native";

import { colors, font } from "@/theme";

import { splitHighlight } from "../searchUtils";

/**
 * 글 안에서 검색어 낱말이 들어 있는 부분을 굵게(꿀색 바탕) 보여 준다. 대소문자는 구분하지 않는다.
 * @param {{ text: string, terms: string[], style?: object, numberOfLines?: number }} props
 */
export default function Highlighted({ text, terms, style, numberOfLines }) {
  return (
    <Text style={style} numberOfLines={numberOfLines}>
      {splitHighlight(text, terms).map((part, i) =>
        part.hit ? (
          <Text key={i} style={styles.hit}>
            {part.text}
          </Text>
        ) : (
          part.text
        ),
      )}
    </Text>
  );
}

const styles = StyleSheet.create({
  hit: { fontFamily: font.bodyStrong.fontFamily, color: colors.text, backgroundColor: colors.honeySoft },
});
