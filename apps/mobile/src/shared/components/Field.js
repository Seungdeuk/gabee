import { StyleSheet, Text, TextInput, View } from "react-native";

import { colors } from "@/theme";

/**
 * 이름표가 붙은 입력창.
 * @param {{ label?: string, value: string, onChangeText: (text: string) => void, placeholder?: string, keyboardType?: string, style?: object, testID?: string }} props
 */
export default function Field({ label, value, onChangeText, placeholder, keyboardType, style, testID }) {
  return (
    <View style={[styles.field, style]}>
      {label ? <Text style={styles.label}>{label}</Text> : null}
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.placeholder}
        keyboardType={keyboardType}
        accessibilityLabel={label ?? placeholder}
        testID={testID}
        style={styles.input}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  field: { gap: 6 },
  label: { fontSize: 14, fontWeight: "500", color: colors.text },
  input: {
    height: 46,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 14,
    paddingHorizontal: 12,
    fontSize: 15,
    color: colors.text,
    backgroundColor: colors.card,
  },
});
