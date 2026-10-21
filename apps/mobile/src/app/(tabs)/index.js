import { StyleSheet, Text, View } from "react-native";

export default function AiAssistantScreen() {
  return (
    <View style={styles.container}>
      <Text>AI 비서</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
  },
});
