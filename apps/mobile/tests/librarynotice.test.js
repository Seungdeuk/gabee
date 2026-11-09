// 가족방에 올린 문서가 가족 공유 문서함에 자동 등록된다는 처음 한 번 안내: 한 번만 보이고, 기억을 못 읽어도 안내가 사라지지는 않는다: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  LIBRARY_NOTICE_BODY,
  LIBRARY_NOTICE_KEY,
  LIBRARY_NOTICE_TITLE,
  markLibraryNoticeSeen,
  shouldShowLibraryNotice,
} from "../src/features/family-chat/libraryNotice.js";

const memory = () => {
  const data = new Map();
  return {
    getItem: async (k) => data.get(k) ?? null,
    setItem: async (k, v) => void data.set(k, v),
    data,
  };
};

test("처음에는 안내를 보이고, 확인한 뒤에는 다시 보이지 않는다", async () => {
  const storage = memory();
  assert.equal(await shouldShowLibraryNotice(storage), true);
  await markLibraryNoticeSeen(storage);
  assert.equal(storage.data.get(LIBRARY_NOTICE_KEY), "1");
  assert.equal(LIBRARY_NOTICE_KEY, "gabee.library.notice.v2"); // 사진도 자동 등록되도록 범위가 넓어졌으니, 이전 안내를 본 사람에게도 다시 보인다
  assert.equal(await shouldShowLibraryNotice(storage), false);
});

test("기억을 읽지 못하면 안내를 보인다(안내가 조용히 사라지지 않는다), 저장을 못 해도 던지지 않는다", async () => {
  const broken = {
    getItem: async () => {
      throw new Error("storage down");
    },
    setItem: async () => {
      throw new Error("storage down");
    },
  };
  assert.equal(await shouldShowLibraryNotice(broken), true);
  await assert.doesNotReject(() => markLibraryNoticeSeen(broken));
});

test("안내 문구: 가족방 문서가 문서함에 자동 저장되고, 민감한 문서도 가족 모두가 본다고 알리며, 1:1 파일은 해당하지 않고, 메시지를 지우면 함께 지워진다", () => {
  assert.match(LIBRARY_NOTICE_TITLE, /문서함/);
  assert.match(LIBRARY_NOTICE_BODY, /자동/);
  assert.match(LIBRARY_NOTICE_BODY, /민감/);
  assert.match(LIBRARY_NOTICE_BODY, /가족 모두/); // 민감한 문서도 가족이 함께 본다
  assert.doesNotMatch(LIBRARY_NOTICE_BODY, /저장하지 않고/); // 민감 문서를 저장하지 않는다는 옛 안내가 없다
  assert.match(LIBRARY_NOTICE_BODY, /1:1/);
  assert.match(LIBRARY_NOTICE_BODY, /지우면/);
  assert.match(LIBRARY_NOTICE_BODY, /사진/); // 문서를 찍은 사진도 자동 등록된다
  assert.match(LIBRARY_NOTICE_BODY, /문서로 저장/); // 자동으로 안 된 사진은 직접 넣을 수 있다
});

test("채팅방 화면: 가족 전체방에서 문서나 사진을 고르기 전에만(1:1 방 제외) 같은 안내를 한 번 보인다", () => {
  const room = readFileSync(new URL("../src/features/family-chat/screens/ChatRoomScreen.js", import.meta.url), "utf8");
  assert.match(room, /!direct && \(await shouldShowLibraryNotice\(AsyncStorage\)\)/);
  assert.equal(room.split("shouldShowLibraryNotice(AsyncStorage)").length - 1, 1, "안내 판단은 한 곳(같은 저장 키)에서만 한다");
  assert.match(room, /markLibraryNoticeSeen\(AsyncStorage\)/);
  const notice = room.indexOf("await noticeLibraryOnce()");
  assert.ok(notice > 0);
  assert.ok(room.indexOf("await noticeLibraryOnce()") < room.indexOf("await pickChatDocument()"), "문서를 고르기 전에 안내한다");
  assert.ok(room.indexOf("await noticeLibraryOnce()", notice + 1) > 0, "사진 쪽에서도 안내를 부른다");
  const photoFlow = room.slice(room.indexOf("const onPickPhoto"), room.indexOf("const onPickFile"));
  assert.ok(photoFlow.indexOf("await noticeLibraryOnce()") > 0 && photoFlow.indexOf("await noticeLibraryOnce()") < photoFlow.indexOf("await pickChatPhotos()"), "사진을 고르기 전에 안내한다");
});

test("채팅방 화면: 웹에서는 Alert 대신 브라우저 알림으로 안내하고(웹 Alert 는 동작하지 않아 버튼이 잠긴다), 안드로이드 뒤로 가기로도 닫힌다", () => {
  const room = readFileSync(new URL("../src/features/family-chat/screens/ChatRoomScreen.js", import.meta.url), "utf8");
  assert.match(room, /function showLibraryNotice\(\)[\s\S]*Platform\.OS === "web"[\s\S]*globalThis\.alert/);
  assert.match(room, /cancelable: true/);
  assert.match(room, /await showLibraryNotice\(\)/); // 안내를 보이는 곳은 noticeLibraryOnce 한 곳
});
