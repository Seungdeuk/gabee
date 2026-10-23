import { Image } from "expo-image";
import { useEffect, useState } from "react";
import { Modal, Pressable, StyleSheet, Text } from "react-native";

/**
 * 올린 원본 사진을 전체 화면으로 띄운다. 눌러서 닫는다.
 * 사진이 아니거나 원본을 못 찾으면 안내 문구를 보여 준다(PDF 등은 앱 안에서 열지 못한다).
 * @param {{ source: { uri: string, headers?: Record<string, string> } | null, title?: string, onClose: () => void }} props
 */
export default function OriginalViewer({ source, title = "", onClose }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [source]);

  return (
    <Modal visible={source !== null} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.viewer} onPress={onClose} accessibilityLabel="원본 닫기">
        {source && !failed ? (
          <Image
            source={source}
            style={styles.image}
            contentFit="contain"
            onError={() => setFailed(true)}
            accessibilityLabel={`${title} 원본`}
          />
        ) : (
          <Text style={styles.text}>이 파일은 앱 안에서 열 수 없어요. 사진이 아니거나 원본을 찾지 못했어요.</Text>
        )}
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  viewer: { flex: 1, backgroundColor: "rgba(0,0,0,0.9)", alignItems: "center", justifyContent: "center", padding: 16 },
  image: { width: "100%", height: "100%" },
  text: { color: "#fff", fontSize: 15, textAlign: "center", lineHeight: 24 },
});
