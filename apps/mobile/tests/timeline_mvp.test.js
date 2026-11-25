// 가족 타임라인 MVP(2026-11-26) 앱 쪽 규칙: 서버가 준 묶음 번호(s_…)로 비슷한 사진 카드를 만들고, 정리 중인 사진 수를 알리고, 제외 상태는 목록에서 한 번만 뺀다.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ANALYSIS_POLL_MAX,
  analysisNotice,
  buildTimelineRows,
  initialTimelineState,
  shouldPollAnalysis,
  timelineBodyKind,
  timelineReducer,
} from "../src/features/family-chat/timeline.js";

const photo = (id, extra = {}) => ({
  attachment_id: id,
  message_id: Number(id.replace(/\D/g, "")) || 1,
  display_at: "2026-11-20T03:00:00Z",
  batch_id: null,
  mine: true,
  group_kind: "single",
  confirmed: false,
  ...extra,
});

test("서버가 같은 묶음 번호(s_…)를 준 비슷한 사진은 한 카드가 되고 similar 로 표시된다", () => {
  const rows = buildTimelineRows([
    photo("p3", { batch_id: "s_abc", group_kind: "similar" }),
    photo("p2", { batch_id: "s_abc", group_kind: "similar" }),
    photo("p1", { batch_id: "s_abc", group_kind: "similar" }),
  ]);
  const bundles = rows.filter((r) => r.type === "bundle");
  assert.equal(bundles.length, 1);
  assert.equal(bundles[0].photos.length, 3);
  assert.equal(bundles[0].similar, true);
});

test("같이 올린 묶음(batch)은 similar 가 아니고, 묶음 번호가 없는 사진은 단독 카드다", () => {
  const rows = buildTimelineRows([
    photo("p5", { batch_id: "bbbb1111", group_kind: "batch" }),
    photo("p4", { batch_id: "bbbb1111", group_kind: "batch" }),
    photo("p9"),
  ]);
  const bundles = rows.filter((r) => r.type === "bundle");
  assert.equal(bundles.length, 2);
  const batch = bundles.find((b) => b.photos.length === 2);
  assert.equal(batch.similar, false);
  const single = bundles.find((b) => b.photos.length === 1);
  assert.equal(single.photos[0].attachment_id, "p9"); // 유사 사진이 없어도 보인다
});

test("같은 묶음 번호라도 날짜가 다르면 날짜마다 따로 카드가 된다(다른 날짜는 합치지 않는다)", () => {
  const rows = buildTimelineRows([
    photo("p2", { batch_id: "s_abc", group_kind: "similar", display_at: "2026-11-21T03:00:00Z" }),
    photo("p1", { batch_id: "s_abc", group_kind: "similar", display_at: "2026-11-20T03:00:00Z" }),
  ]);
  assert.equal(rows.filter((r) => r.type === "bundle").length, 2);
});

test("정리 중인 사진 수는 첫 쪽 응답에서 받아 상태에 둔다(없으면 0)", () => {
  let state = timelineReducer(initialTimelineState(), { type: "start", seq: 1 });
  state = timelineReducer(state, { type: "firstOk", seq: 1, page: { items: [], next_before: null, analyzing: 2, analysis_failed: 1 } });
  assert.equal(state.analyzing, 2);
  assert.equal(state.analysisFailed, 1);
  let old = timelineReducer(initialTimelineState(), { type: "start", seq: 2 });
  old = timelineReducer(old, { type: "firstOk", seq: 2, page: { items: [photo("p1")], next_before: null } });
  assert.equal(old.analyzing, 0);
  assert.equal(old.analysisFailed, 0);
});

test("보일 사진이 없어도 서버가 정리 중이면 '없어요'가 아니라 analyzing 이다", () => {
  const base = { ...initialTimelineState(), status: "ready", items: [], next: null };
  assert.equal(timelineBodyKind({ ...base, analyzing: 3 }), "analyzing");
  assert.equal(timelineBodyKind({ ...base, analysisFailed: 1 }), "analyzing");
  assert.equal(timelineBodyKind(base), "empty");
  assert.equal(timelineBodyKind({ ...base, analyzing: 3, items: [photo("p1")] }), "list");
});

test("정리 안내 문구: 정리 중·실패를 알리고, 알릴 것이 없으면 빈 문자열", () => {
  assert.equal(analysisNotice({ analyzing: 0, analysisFailed: 0 }), "");
  assert.equal(analysisNotice(null), "");
  assert.match(analysisNotice({ analyzing: 2 }), /2장을 정리하는 중/);
  assert.match(analysisNotice({ analysisFailed: 1 }), /1장은 정리하지 못해/);
});

test("정리 중이면 몇 번까지 자동으로 다시 조회하고, 끝나거나 횟수를 넘기면 멈춘다", () => {
  const ready = { ...initialTimelineState(), status: "ready", analyzing: 5 };
  assert.equal(shouldPollAnalysis(ready, 0), true);
  assert.equal(shouldPollAnalysis(ready, ANALYSIS_POLL_MAX - 1), true);
  assert.equal(shouldPollAnalysis(ready, ANALYSIS_POLL_MAX), false); // 횟수 상한: 무한히 두드리지 않는다
  assert.equal(shouldPollAnalysis({ ...ready, analyzing: 0 }, 0), false); // 다 끝났다
  assert.equal(shouldPollAnalysis({ ...ready, analyzing: 0, analysisFailed: 3 }, 0), false); // 실패는 자동 재시도하지 않는다(서버가 10분 뒤 다시 맡긴다, 새로고침은 사용자가)
  assert.equal(shouldPollAnalysis({ ...ready, status: "loading" }, 0), false);
  assert.equal(shouldPollAnalysis({ ...ready, status: "error" }, 0), false);
});

test("조용한 갱신(refreshOk)은 로딩 화면 없이 목록·정리 수만 바꾸고, 옛 응답은 버린다", () => {
  let state = timelineReducer(initialTimelineState(), { type: "start", seq: 3 });
  state = timelineReducer(state, { type: "firstOk", seq: 3, page: { items: [], next_before: null, analyzing: 4 } });
  const next = timelineReducer(state, {
    type: "refreshOk",
    seq: 3,
    page: { items: [photo("p1")], next_before: null, analyzing: 1, analysis_failed: 0 },
  });
  assert.equal(next.status, "ready"); // 다시 loading 으로 돌아가지 않는다
  assert.deepEqual(next.items.map((i) => i.attachment_id), ["p1"]);
  assert.equal(next.analyzing, 1);
  assert.equal(timelineReducer(state, { type: "refreshOk", seq: 2, page: { items: [photo("p9")] } }), state); // 번호가 다르면 버린다
});

test("뺀 사진 화면: excluded 라우트 값만 뺀 사진 모드이고, 상태 라벨과 다시 넣기 흐름이 있다", async () => {
  const pc = await import("../src/features/family-chat/photoChecks.js");
  assert.equal(pc.reviewKindOf("excluded"), "excluded");
  assert.equal(pc.reviewKindOf(undefined), "review");
  assert.equal(pc.reviewKindOf("anything"), "review");
  assert.equal(pc.statusLabel("excluded"), "뺀 사진");
  // 다시 넣기: 안내 확인 전에는 서버를 부르지 않고, 확인하면 한 번만 부른다
  let calls = 0;
  const confirm = async () => {
    calls += 1;
  };
  const working = new Set();
  assert.deepEqual(await pc.runConfirm({ id: "p1", acknowledged: false, busy: null, working, confirm }), { kind: "skipped" });
  assert.equal(calls, 0);
  const done = await pc.runConfirm({ id: "p1", acknowledged: true, busy: null, working, confirm });
  assert.equal(done.kind, "confirmed");
  assert.equal(calls, 1);
  // 내 사진이 아니거나 지워졌으면(404) 목록에서 뺀다
  const gone = await pc.runConfirm({ id: "p1", acknowledged: true, busy: null, working, confirm: async () => { throw Object.assign(new Error("x"), { status: 404 }); } });
  assert.equal(gone.kind, "gone");
});

test("뺀 사진은 목록에서 한 번만 빠지고 다시 반영하면 그대로다(제외 상태는 서버가 보존한다)", () => {
  let state = { ...initialTimelineState(), status: "ready", items: [photo("p1"), photo("p2")] };
  state = timelineReducer(state, { type: "removed", id: "p1" });
  assert.deepEqual(state.items.map((i) => i.attachment_id), ["p2"]);
  assert.equal(timelineReducer(state, { type: "removed", id: "p1" }), state);
});
