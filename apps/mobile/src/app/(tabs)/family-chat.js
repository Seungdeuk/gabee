import { StyleSheet, Text, View } from "react-native";

export default function FamilyChatScreen() {
  return (
    <View style={styles.container}>
      <Text>소통</Text>
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
