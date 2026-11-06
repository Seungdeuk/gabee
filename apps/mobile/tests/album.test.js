// 채팅 앨범 묶음: 같은 batch_id 로 올린 사진을 한 덩어리로 묶고, 칸 배치·묶음 번호·보내기 모양을 시험한다: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { albumCells, albumIndexOf, makeBatchId, MAX_ALBUM_PHOTOS, ALBUM_VISIBLE } from "../src/features/family-chat/album.js";
import { buildItems, itemHasMessage } from "../src/features/family-chat/chatUtils.js";

const photo = (id, userId, batch, at = "2026-11-06T10:00:00Z") => ({
  id,
  user_id: userId,
  user_name: userId,
  text: "",
  created_at: at,
  attachment: { id: `att${id}`, kind: "image", url: `/p/${id}`, thumb_url: `/p/${id}?size=thumb`, width: 40, height: 30, batch_id: batch },
});
const text = (id, userId, at = "2026-11-06T10:00:00Z") => ({ id, user_id: userId, user_name: userId, text: "hi", created_at: at });

test("buildItems: 같은 사람이 같은 batch_id 로 연달아 올린 사진은 한 줄(앨범)이 된다", () => {
  const items = buildItems([photo(1, "a", "batch0001"), photo(2, "a", "batch0001"), photo(3, "a", "batch0001")]);
  const rows = items.filter((i) => i.type === "message");
  assert.equal(rows.length, 1);
  assert.deepEqual(rows[0].album.map((m) => m.id), [1, 2, 3]);
  assert.equal(rows[0].message.id, 3); // 시간·읽음·반응은 마지막 사진 기준
  assert.equal(rows[0].key, "m-1"); // 목록 key 는 첫 사진(새 사진이 붙어도 줄이 새로 만들어지지 않는다)
});

test("buildItems: 묶음 번호가 없거나 한 장뿐이면 album 이 없다", () => {
  const rows = buildItems([photo(1, "a", null), photo(2, "a", null), photo(3, "a", "batch0001")]).filter((i) => i.type === "message");
  assert.equal(rows.length, 3);
  assert.ok(rows.every((r) => r.album === undefined));
});

test("buildItems: 사이에 다른 글이 끼면 같은 번호여도 따로 묶는다(연속일 때만)", () => {
  const rows = buildItems([photo(1, "a", "batch0001"), photo(2, "a", "batch0001"), text(3, "b"), photo(4, "a", "batch0001"), photo(5, "a", "batch0001")]).filter((i) => i.type === "message");
  assert.deepEqual(rows.map((r) => r.album?.map((m) => m.id) ?? [r.message.id]), [[1, 2], [3], [4, 5]]);
});

test("buildItems: 다른 사람의 같은 번호는 섞지 않는다", () => {
  const rows = buildItems([photo(1, "a", "batch0001"), photo(2, "b", "batch0001")]).filter((i) => i.type === "message");
  assert.equal(rows.length, 2);
});

test("buildItems: 이름은 앨범 앞 메시지 기준, 시각은 앨범 뒤 메시지 기준으로 정한다", () => {
  const rows = buildItems([text(1, "a"), photo(2, "a", "batch0001"), photo(3, "a", "batch0001"), text(4, "b")]).filter((i) => i.type === "message");
  assert.equal(rows[1].showName, false); // 앞이 같은 사람
  assert.equal(rows[1].showTime, true); // 뒤가 다른 사람
});

test("buildItems: 지운 사진은 앨범에서 빠지고, 날짜가 바뀌면 나뉜다", () => {
  const deleted = { ...photo(2, "a", "batch0001"), deleted: true, attachment: null };
  const rows = buildItems([photo(1, "a", "batch0001"), deleted, photo(3, "a", "batch0001")]).filter((i) => i.type === "message");
  assert.equal(rows.length, 3);
  const days = buildItems([photo(1, "a", "batch0001", "2026-11-05T10:00:00Z"), photo(2, "a", "batch0001", "2026-11-07T10:00:00Z")]).filter((i) => i.type === "message");
  assert.equal(days.length, 2);
});

test("itemHasMessage: 앨범 안에 숨은 메시지도 찾는다(검색·고정 이동용)", () => {
  const rows = buildItems([photo(1, "a", "batch0001"), photo(2, "a", "batch0001")]).filter((i) => i.type === "message");
  assert.equal(itemHasMessage(rows[0], 1), true);
  assert.equal(itemHasMessage(rows[0], 2), true);
  assert.equal(itemHasMessage(rows[0], 3), false);
});

test("albumCells: 2장은 나란히, 3장은 위 한 장 + 아래 두 장, 4장 이상은 2×2 에 남는 수(+N)", () => {
  const w = 200;
  const two = albumCells(2, w);
  assert.equal(two.cells.length, 2);
  assert.equal(two.more, 0);
  const three = albumCells(3, w);
  assert.equal(three.cells.length, 3);
  assert.equal(three.cells[0].width, w); // 첫 칸이 한 줄 전체
  const six = albumCells(6, w);
  assert.equal(six.cells.length, ALBUM_VISIBLE);
  assert.equal(six.more, 6 - ALBUM_VISIBLE);
  assert.equal(albumCells(ALBUM_VISIBLE, w).more, 0);
});

test("albumIndexOf: 누른 사진의 순서(없으면 0)", () => {
  const album = [photo(1, "a", "batch0001"), photo(2, "a", "batch0001")];
  assert.equal(albumIndexOf(album, 2), 1);
  assert.equal(albumIndexOf(album, 99), 0);
});

test("makeBatchId: 서버 규칙(영문·숫자·_- 8~32자)에 맞고 호출마다 다르다", () => {
  const a = makeBatchId();
  const b = makeBatchId();
  assert.match(a, /^[A-Za-z0-9_-]{8,32}$/);
  assert.notEqual(a, b);
  assert.match(makeBatchId(0, () => 0), /^[A-Za-z0-9_-]{8,32}$/); // 난수가 0 이어도 길이가 모자라지 않는다
});

test("MAX_ALBUM_PHOTOS 는 한 번에 올리는 한도(10장)", () => {
  assert.equal(MAX_ALBUM_PHOTOS, 10);
});


const src = (rel) => readFileSync(new URL(`../src/features/family-chat/${rel}`, import.meta.url), "utf8");

test("보내기 연결: sendPhoto 는 묶음 번호가 있을 때만 batch_id 를 form 에 넣는다", () => {
  const api = src("api.js");
  assert.match(api, /export async function sendPhoto\(asset, roomId, batchId\)/);
  assert.match(api, /if \(batchId\) form\.append\("batch_id", batchId\)/);
});

test("보내기 연결: 방 화면은 여러 장을 같은 묶음 번호로 보내고 한 장이면 번호를 쓰지 않는다", () => {
  const room = src("screens/ChatRoomScreen.js");
  assert.match(room, /pickChatPhotos\(\)/);
  assert.match(room, /assets\.length > 1 \? makeBatchId\(\) : undefined/);
  assert.match(room, /chat\.sendImage\(asset, batchId\)/);
  assert.match(room, /album=\{item\.album\}/);
  assert.match(src("useChatMessages.js"), /sendPhoto\(asset, roomRef\.current, batchId\)/);
});

test("선택기: 여러 장 선택은 순서를 지키고 한도를 MAX_ALBUM_PHOTOS 로 둔다", () => {
  const pick = src("pickPhoto.js");
  assert.match(pick, /allowsMultipleSelection: true/);
  assert.match(pick, /selectionLimit: MAX_ALBUM_PHOTOS/);
  assert.match(pick, /orderedSelection: true/);
});
