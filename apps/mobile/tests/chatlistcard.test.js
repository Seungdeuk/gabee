// 소통 탭 채팅방 목록: 한 장의 둥근 흰 카드 안에 줄과 구분선, 새 대화는 + 아이콘, 가족 전체방은 육각형 아바타(제목·배경은 그대로): npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = (rel) => readFileSync(new URL(`../src/${rel}`, import.meta.url), "utf8");

test("헤더: 새 대화 버튼은 + 아이콘이고 제목은 그대로 '우리 도란도란'이다", () => {
  const header = read("features/family-chat/components/ChatListHeader.js");
  assert.match(header, /<IconButton name="add" label="새 대화"/);
  assert.doesNotMatch(header, /create-outline/);
  assert.match(header, /우리 도란도란/);
});

test("목록 화면: 채팅방 줄은 한 장의 흰 카드 안에 모이고 줄 사이에만 구분선이 있으며 배경은 그대로다", () => {
  const screen = read("features/family-chat/screens/FamilyChatScreen.js");
  assert.match(screen, /<Card tone="white" style=\{styles\.roomCard\}>/);
  assert.match(screen, /divider=\{i < shown\.length - 1\}/); // 마지막 줄에는 구분선이 없다
  assert.match(screen, /roomCard: \{[^}]*overflow: "hidden"/); // 눌린 줄의 배경이 카드 모서리 밖으로 나가지 않는다
  assert.match(screen, /safe: \{ flex: 1, backgroundColor: colors\.background \}/); // 배경은 바꾸지 않는다
});

test("채팅방 줄: 가족 전체방은 육각형 아바타, 1:1 방은 옅은 테두리 원형 프로필", () => {
  const row = read("features/family-chat/components/RoomRow.js");
  assert.match(row, /import HexAvatar from "@\/shared\/components\/HexAvatar"/);
  assert.match(row, /<HexAvatar name=\{room\.name\}/);
  assert.match(row, /styles\.ring/); // 1:1 방 프로필의 옅은 테두리
  assert.match(row, /<UserAvatar name=\{room\.name\} userId=\{room\.peerId\}/);
});

test("hexPoints: 꼭짓점이 위로 향한 정육각형의 여섯 점이 정사각형 안에 대칭으로 놓인다", async () => {
  const { hexPoints } = await import("../src/shared/hexagon.js");
  const size = 56;
  const pts = hexPoints(size, 2).split(" ").map((p) => p.split(",").map(Number));
  assert.equal(pts.length, 6);
  for (const [x, y] of pts) {
    assert.ok(x >= 0 && x <= size && y >= 0 && y <= size, `${x},${y} 가 범위 밖`);
  }
  const [top, bottom] = [pts[0], pts[3]];
  assert.ok(Math.abs(top[0] - size / 2) < 0.01 && Math.abs(bottom[0] - size / 2) < 0.01); // 위·아래 꼭짓점은 가운데 열
  assert.ok(top[1] < bottom[1]);
  const xs = pts.map(([x]) => x);
  assert.ok(Math.abs(Math.min(...xs) + Math.max(...xs) - size) < 0.01); // 좌우 대칭
});

test("스와이프 행: 앞면 배경은 카드와 같은 흰색이다(앱에서 흰 카드 안에 크림색 칸이 깔리지 않게)", () => {
  const swipe = read("features/family-chat/components/SwipeableRoomRow.js");
  assert.match(swipe, /front: \{[^}]*backgroundColor: colors\.card/);
  assert.doesNotMatch(swipe, /front: \{[^}]*colors\.background/);
});

test("1:1 프로필 테두리: 바깥 크기가 아바타 크기(56)와 정확히 같다(테두리 두 겹이 차지하는 폭 = 테두리 두께 × 4)", () => {
  const row = read("features/family-chat/components/RoomRow.js");
  assert.match(row, /const RING_SPACE = RING_BORDER \* 4;/);
  assert.match(row, /ring: \{ width: AVATAR_SIZE, height: AVATAR_SIZE, padding: RING_BORDER, borderWidth: RING_BORDER/);
});
