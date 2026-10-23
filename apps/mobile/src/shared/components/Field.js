import { StyleSheet, Text, TextInput, View } from "react-native";

import { colors } from "@/theme";

/**
 * 이름표가 붙은 입력창. 비밀번호(secureTextEntry)·자동 대문자 끄기 같은 입력 옵션과 오류/도움말 문구를 지원한다.
 * @param {{ label?: string, value: string, onChangeText: (text: string) => void, placeholder?: string, keyboardType?: string, style?: object, testID?: string, error?: string, hint?: string, secureTextEntry?: boolean, autoCapitalize?: "none" | "sentences" | "words" | "characters", autoCorrect?: boolean, autoComplete?: string, textContentType?: string, maxLength?: number, editable?: boolean, onBlur?: () => void, onSubmitEditing?: () => void, returnKeyType?: string }} props
 */
export default function Field({
  label,
  value,
  onChangeText,
  placeholder,
  keyboardType,
  style,
  testID,
  error,
  hint,
  secureTextEntry,
  autoCapitalize,
  autoCorrect,
  autoComplete,
  textContentType,
  maxLength,
  editable,
  onBlur,
  onSubmitEditing,
  returnKeyType,
}) {
  return (
    <View style={[styles.field, style]}>
      {label ? <Text style={styles.label}>{label}</Text> : null}
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.placeholder}
        keyboardType={keyboardType}
        secureTextEntry={secureTextEntry}
        autoCapitalize={autoCapitalize}
        autoCorrect={autoCorrect}
        autoComplete={autoComplete}
        textContentType={textContentType}
        maxLength={maxLength}
        editable={editable}
        onBlur={onBlur}
        onSubmitEditing={onSubmitEditing}
        returnKeyType={returnKeyType}
        accessibilityLabel={label ?? placeholder}
        testID={testID}
        style={[styles.input, error ? styles.inputError : null]}
      />
      {error ? (
        <Text style={styles.error} accessibilityRole="alert">
          {error}
        </Text>
      ) : hint ? (
        <Text style={styles.hint}>{hint}</Text>
      ) : null}
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
  inputError: { borderColor: colors.danger },
  error: { fontSize: 13, color: colors.danger },
  hint: { fontSize: 13, color: colors.textMuted },
});
