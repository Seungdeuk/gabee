import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Application from "expo-application";
import { useEffect } from "react";
import { Platform } from "react-native";

import { useAuth } from "@/shared/auth/AuthProvider";

import { sendInstallSource } from "./api";
import { parseReferrer } from "./referrer";

/**
 * 이 기기에서 이 사용자의 설치 경로를 이미 보냈는지 기억하는 저장 키.
 * @param {string} userId 로그인한 사용자 id
 * @returns {string}
 */
const sentKey = (userId) => `install_source_sent:${userId}`;

/**
 * 안드로이드에서 로그인된 사용자의 설치 경로(플레이 스토어 꼬리표의 utm 값)를 한 번만 서버에 보낸다.
 * 화면은 없고, 실패해도 앱 사용에는 영향이 없다(다음 실행 때 다시 시도한다).
 * 꼬리표는 플레이 스토어로 설치했을 때만 있다(APK 직접 설치·Expo Go·에뮬레이터는 값이 없거나 오류).
 * @returns {null}
 */
export default function AcquisitionBootstrap() {
  const { status, user } = useAuth();
  const userId = user?.id;

  useEffect(() => {
    if (Platform.OS !== "android" || status !== "authenticated" || !userId) return;
    let cancelled = false;
    (async () => {
      try {
        if (await AsyncStorage.getItem(sentKey(userId))) return; // 이미 보냄
        const raw = await Application.getInstallReferrerAsync();
        const tags = parseReferrer(raw);
        if (!tags || cancelled) return; // 꼬리표 없음(검색 설치 등에서 utm 값이 없을 때)
        await sendInstallSource(tags);
        await AsyncStorage.setItem(sentKey(userId), "1");
      } catch {
        // 플레이 스토어 연결 실패, 서버 준비 전(404·503) 등: 조용히 넘기고 다음 실행 때 다시 시도한다
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [status, userId]);

  return null;
}
