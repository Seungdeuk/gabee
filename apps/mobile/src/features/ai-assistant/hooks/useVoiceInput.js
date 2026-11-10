import { Alert } from "react-native";
import { useCallback, useEffect, useRef, useState } from "react";

// 네이티브 모듈이 없는 환경(Expo Go 등)에서 import 만으로 화면이 죽지 않도록, 있을 때만 쓴다
let speech = null;
try {
  speech = require("expo-speech-recognition").ExpoSpeechRecognitionModule ?? null;
} catch {
  speech = null;
}

const MESSAGES = {
  permission: "마이크 사용을 허용해야 말로 물어볼 수 있어요. 폰 설정에서 허용해 주세요. 글자로 입력해도 돼요.",
  language: "이 폰에서는 한국어 음성 인식을 쓸 수 없어요. 글자로 입력해 주세요.",
  unavailable: "이 앱에서는 음성 입력을 쓸 수 없어요. 글자로 입력해 주세요.",
  generic: "음성을 인식하지 못했어요. 잠시 후 다시 시도하거나 글자로 입력해 주세요.",
};

/**
 * 폰의 기본 음성 인식으로 말을 글자로 바꾼다. 오디오는 저장·전송하지 않고, 서버에는 글자만 간다.
 * @param {{ onEnd: () => void }} options onEnd: 인식이 끝났을 때(정상 종료·취소·오류 모두) 한 번 불린다
 * @returns {{ transcript: string, start: () => Promise<boolean>, stop: () => void }}
 *   transcript: 지금까지 인식된 글자(말하는 도중에도 갱신), start: 시작(권한 없으면 안내 후 false), stop: 끝내고 마지막 결과를 받는다
 */
export default function useVoiceInput({ onEnd }) {
  const [transcript, setTranscript] = useState("");
  const onEndRef = useRef(onEnd);
  onEndRef.current = onEnd;

  useEffect(() => {
    if (!speech) return undefined;
    const subs = [
      speech.addListener("result", (e) => setTranscript(e?.results?.[0]?.transcript ?? "")),
      speech.addListener("end", () => onEndRef.current?.()),
      speech.addListener("error", (e) => {
        const code = e?.error;
        // 말이 없어서 끝났거나 사용자가 직접 멈춘 경우는 조용히 넘어간다
        if (code === "aborted" || code === "no-speech") return;
        if (code === "not-allowed" || code === "service-not-allowed") Alert.alert("마이크 권한이 필요해요", MESSAGES.permission);
        else if (code === "language-not-supported") Alert.alert("음성 입력을 쓸 수 없어요", MESSAGES.language);
        else Alert.alert("음성 입력이 끊겼어요", MESSAGES.generic);
      }),
    ];
    return () => subs.forEach((s) => s?.remove?.());
  }, []);

  const start = useCallback(async () => {
    if (!speech) {
      Alert.alert("음성 입력을 쓸 수 없어요", MESSAGES.unavailable);
      return false;
    }
    try {
      const perm = await speech.requestPermissionsAsync();
      if (!perm?.granted) {
        Alert.alert("마이크 권한이 필요해요", MESSAGES.permission);
        return false;
      }
      setTranscript("");
      speech.start({ lang: "ko-KR", interimResults: true, continuous: false });
      return true;
    } catch {
      Alert.alert("음성 입력을 시작하지 못했어요", MESSAGES.generic);
      return false;
    }
  }, []);

  const stop = useCallback(() => {
    try {
      speech?.stop();
    } catch {
      // 이미 끝났으면 무시한다
    }
  }, []);

  return { transcript, start, stop };
}
