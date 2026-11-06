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

test("안내 문구: 가족방 문서가 문서함에 자동 저장되고, 민감 문서·1:1 파일은 저장하지 않으며, 메시지를 지우면 함께 지워진다고 알린다", () => {
  assert.match(LIBRARY_NOTICE_TITLE, /문서함/);
  assert.match(LIBRARY_NOTICE_BODY, /자동/);
  assert.match(LIBRARY_NOTICE_BODY, /민감/);
  assert.match(LIBRARY_NOTICE_BODY, /1:1/);
  assert.match(LIBRARY_NOTICE_BODY, /지우면/);
});

test("채팅방 화면: 가족 전체방에서 문서를 고르기 전에만(1:1 방 제외) 안내를 한 번 보인다", () => {
  const room = readFileSync(new URL("../src/features/family-chat/screens/ChatRoomScreen.js", import.meta.url), "utf8");
  assert.match(room, /!direct && \(await shouldShowLibraryNotice\(AsyncStorage\)\)/);
  assert.match(room, /markLibraryNoticeSeen\(AsyncStorage\)/);
  assert.ok(room.indexOf("shouldShowLibraryNotice(AsyncStorage)") < room.indexOf("await pickChatDocument()"), "문서를 고르기 전에 안내한다");
});
