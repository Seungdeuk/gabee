// 가족 전체방에 올린 문서가 가족 공유 문서함에 자동 등록된다는 처음 한 번 안내(순수 함수 + 문구). 저장소는 주입해서 시험한다(앱은 AsyncStorage 를 넘긴다).

/** 안내를 이미 봤다고 이 폰에 기억하는 키. */
export const LIBRARY_NOTICE_KEY = "gabee.library.notice.v1";

export const LIBRARY_NOTICE_TITLE = "가족 문서함에 자동으로 모여요";
export const LIBRARY_NOTICE_BODY =
  "가족 채팅방에 올린 문서는 가족 공유 문서함에도 자동으로 저장돼서 가비가 찾아 줄 수 있어요. 처방전·신분증 같은 민감한 문서는 저장하지 않고, 1:1 대화방의 파일도 저장하지 않아요. 채팅에서 메시지를 지우면 문서함에서도 함께 지워져요.";

/**
 * 안내를 보여야 하는지(처음 한 번). 기억을 읽지 못하면 안내를 보인다(안내가 조용히 사라지지 않게).
 * @param {{ getItem: (key: string) => Promise<string | null> }} storage
 * @returns {Promise<boolean>}
 */
export async function shouldShowLibraryNotice(storage) {
  try {
    return (await storage.getItem(LIBRARY_NOTICE_KEY)) == null;
  } catch {
    return true;
  }
}

/**
 * 안내를 봤다고 기억한다. 저장하지 못해도 던지지 않는다(다음에 한 번 더 보일 뿐이다).
 * @param {{ setItem: (key: string, value: string) => Promise<void> }} storage
 * @returns {Promise<void>}
 */
export async function markLibraryNoticeSeen(storage) {
  try {
    await storage.setItem(LIBRARY_NOTICE_KEY, "1");
  } catch {
    // 저장이 안 돼도 이번에는 안내를 보았다
  }
}
