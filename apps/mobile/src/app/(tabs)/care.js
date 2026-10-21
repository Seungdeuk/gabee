import { StyleSheet, Text, View } from "react-native";

export default function CareScreen() {
  return (
    <View style={styles.container}>
      <Text>돌봄</Text>
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
