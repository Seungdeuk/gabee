import { StyleSheet, Text, View } from "react-native";

export default function BillingScreen() {
  return (
    <View style={styles.container}>
      <Text>가계</Text>
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
