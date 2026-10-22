import { StyleSheet, Text } from "react-native";

import { colors } from "@/theme";

import { KIND_COLOR, KIND_LABEL } from "../constants";

/**
 * 형태 배지("약속" / "할 일").
 * @param {{ kind: "appointment" | "todo" }} props
 */
export default function FormTag({ kind }) {
  return <Text style={[styles.tag, { backgroundColor: KIND_COLOR[kind] }]}>{KIND_LABEL[kind]}</Text>;
}

const styles = StyleSheet.create({
  tag: {
    alignSelf: "flex-start",
    fontSize: 12,
    fontWeight: "700",
    color: colors.onDark,
    paddingHorizontal: 9,
    paddingVertical: 3,
    borderRadius: 6,
    overflow: "hidden",
  },
});
