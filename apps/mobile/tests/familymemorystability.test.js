// 출시 전 안정화: 생성 버튼 중복 요청 방지, 철회·삭제 뒤 오래된 후보·사진 캐시 정리, 로그아웃 상태 진입 처리. npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { createSingleFlight } from "../src/features/family-memory/generation.js";
import { initialMemoriesState, memoriesReducer, needsLogin, removedPhotoPaths } from "../src/features/family-memory/memories.js";

const ph = (id) => ({ attachment_id: id, thumb_url: `/t/${id}`, photo_url: `/p/${id}`, taken_at: "2024-05-01T00:00:00+00:00", is_representative: false });
const cand = (ids) => ({ id: "c1", status: "private", representative: { ...ph(ids[0]), is_representative: true }, photos: ids.map(ph), photo_count: ids.length, dated_count: ids.length, undated_count: 0, starts_at: null, ends_at: null, bridged: false, score: 1, algorithm_version: "x", updated_at: "x" });
const loaded = (ids) => memoriesReducer(memoriesReducer(initialMemoriesState(), { type: "scope", scope: "u:g", seq: 1 }), { type: "ok", seq: 1, items: [cand(ids)] });

test("생성 버튼 연타: 진행 중에는 두 번째 요청을 시작하지 않는다", () => {
  const g = createSingleFlight();
  assert.equal(g.tryStart(), true);
  assert.equal(g.tryStart(), false);
  assert.equal(g.tryStart(), false);
  g.done();
  assert.equal(g.tryStart(), true); // 끝나면 다시 누를 수 있다
});

test("범위가 바뀌면(가족 전환·로그아웃) 진행 표시를 풀어 새 범위에서 다시 누를 수 있다", () => {
  const g = createSingleFlight();
  g.tryStart();
  g.reset();
  assert.equal(g.tryStart(), true);
});

test("철회·삭제 뒤 새 응답: 빠진 사진이 목록에서 사라지고 기기 캐시 정리 대상이 된다", () => {
  const before = loaded(["a", "b", "c", "d", "e", "f"]);
  const after = memoriesReducer(before, { type: "ok", seq: 1, items: [cand(["a", "b", "c", "d", "e"])] });
  assert.equal(after.items[0].photo_count, 5);
  assert.deepEqual(removedPhotoPaths(before.items, after.items).sort(), ["/p/f", "/t/f"]);
});

test("늦게 온 옛 응답(seq 불일치)은 최신 목록을 덮어쓰지 못한다", () => {
  const fresh = memoriesReducer(loaded(["a", "b", "c", "d", "e", "f"]), { type: "start", seq: 2 });
  const after = memoriesReducer(fresh, { type: "ok", seq: 1, items: [cand(["a", "b", "c", "d", "e", "f", "g"])] });
  assert.equal(after.items[0].photo_count, 6);
});

test("로그아웃(anonymous) 상태로 추억 화면에 직접 들어오면 로그인으로 보낸다", () => {
  assert.equal(needsLogin("anonymous"), true);
  assert.equal(needsLogin("authenticated"), false);
  assert.equal(needsLogin("loading"), false); // 세션 확인 중에는 기다린다
  assert.equal(needsLogin("unreachable"), false);
});