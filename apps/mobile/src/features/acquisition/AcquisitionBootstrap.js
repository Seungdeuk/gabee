import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Application from "expo-application";
import { useEffect } from "react";
import { Platform } from "react-native";

import { useAuth } from "@/shared/auth/AuthProvider";

import { sendInstallSource } from "./api";
import { parseReferrer } from "./referrer";

// 플레이 스토어가 꼬리표 기능을 주지 않는 기기(플레이 스토어 없음 등). 다시 물어도 같은 답이라 끝난 것으로 본다.
const REFERRER_UNAVAILABLE = "ERR_APPLICATION_INSTALL_REFERRER_UNAVAILABLE";

/**
 * 이 기기에서 이 사용자의 설치 경로 확인을 끝냈는지(보냈거나, 보낼 꼬리표가 없었는지) 기억하는 저장 키.
 * @param {string} userId 로그인한 사용자 id
 * @returns {string}
 */
const doneKey = (userId) => `install_source_done:${userId}`;

/**
 * 확인을 끝냈다고 적는다. 적기에 실패해도 다음 실행 때 한 번 더 확인할 뿐이라 오류를 무시한다.
 * @param {string} userId 로그인한 사용자 id
 * @returns {Promise<void>}
 */
async function markDone(userId) {
  try {
    await AsyncStorage.setItem(doneKey(userId), "1");
  } catch {
    // 저장소 쓰기 실패: 다음 실행 때 다시 확인한다
  }
}

/**
 * 안드로이드에서 로그인된 사용자의 설치 경로(플레이 스토어 꼬리표의 utm 값)를 한 번만 서버에 보낸다.
 * 화면은 없고 타이머도 없다. 사용자마다 한 번 확인하고 나면(보냈거나 보낼 꼬리표가 없으면) 다시 묻지 않는다.
 * 플레이 스토어 연결 실패나 서버 실패처럼 잠깐의 문제일 때만 다음 실행 때 다시 시도한다.
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
        if (await AsyncStorage.getItem(doneKey(userId))) return; // 이미 확인함: 플레이 스토어에 다시 묻지 않는다
      } catch {
        return; // 저장소를 못 읽으면 이번에는 건너뛴다
      }

      let raw;
      try {
        raw = await Application.getInstallReferrerAsync();
      } catch (error) {
        if (error?.code === REFERRER_UNAVAILABLE) await markDone(userId); // 이 기기에서는 앞으로도 못 읽는다
        return; // 연결 실패 등은 다음 실행 때 다시 시도
      }

      const tags = parseReferrer(raw);
      if (!tags) {
        await markDone(userId); // 꼬리표가 없거나 쓸 수 없는 값: 다시 물어도 같다
        return;
      }
      if (cancelled) return;
      try {
        await sendInstallSource(tags);
        await markDone(userId);
      } catch {
        // 서버 준비 전(404·503)이나 네트워크 실패: 다음 실행 때 다시 보낸다
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [status, userId]);

  return null;
}
