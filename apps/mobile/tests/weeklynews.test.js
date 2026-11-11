// 마이 > AI 리포트 > 가족 뉴스 카드의 화면 상태 계산(순수 함수) 시험: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { ApiError } from "../src/shared/api/client.js";
import {
  canCreateNews,
  describeNewsError,
  itemRoute,
  newsCardView,
  sentenceSources,
} from "../src/features/more/news/newsView.js";

const ready = {
  status: "ready",
  title: "축구가 있던 주",
  items: [
    { text: "하늘이가 15시에 축구를 했어요", source_ids: ["e1"] },
    { text: "서류를 올렸어요", source_ids: ["d1"] },
  ],
  sources: [
    { id: "e1", kind: "event", ref: "ev-1", label: "축구", date: "2026-11-03" },
    { id: "d1", kind: "document", ref: "doc-1", label: "가정통신문", date: null },
  ],
};
const news = (status, extra = {}) => ({ status, items: [], sources: [], ...extra });

test("뉴스를 새로 만들 수 있는 것은 이번 주와 지난 주뿐이다", () => {
  assert.equal(canCreateNews(0), true);
  assert.equal(canCreateNews(-1), true);
  assert.equal(canCreateNews(-2), false);
});

test("받는 중이면 로딩, 받지 못하면 다시 불러오기를 준다", () => {
  assert.equal(newsCardView({ phase: "loading", offset: 0 }).kind, "loading");
  const v = newsCardView({ phase: "error", offset: 0, error: new ApiError(0, "network_error", "x") });
  assert.equal(v.kind, "error");
  assert.equal(v.action, "reload");
});

test("뉴스가 있으면 제목·문장·안내를 보여 주고 만들기 버튼은 없다", () => {
  const v = newsCardView({ phase: "loaded", offset: -1, news: ready });
  assert.equal(v.kind, "ready");
  assert.equal(v.title, "축구가 있던 주");
  assert.equal(v.items.length, 2);
  assert.match(v.note, /일정을 지워도/);
  assert.equal(v.action, undefined);
});

test("제목이 비어 있으면 기본 제목을 쓴다", () => {
  const v = newsCardView({ phase: "loaded", offset: 0, news: { ...ready, title: null } });
  assert.equal(v.title, "가족 뉴스");
});

test("아직 안 만든 이번 주·지난 주는 만들기 버튼, 오래된 주는 안내만", () => {
  const a = newsCardView({ phase: "loaded", offset: 0, news: news("not_generated") });
  assert.equal(a.kind, "offer");
  assert.equal(a.action, "create");
  const b = newsCardView({ phase: "loaded", offset: -1, news: news("not_generated") });
  assert.equal(b.action, "create");
  const c = newsCardView({ phase: "loaded", offset: -3, news: news("not_generated") });
  assert.equal(c.kind, "missing");
  assert.equal(c.action, undefined);
});

test("만드는 중에는 버튼이 눌리지 않는다", () => {
  const v = newsCardView({ phase: "loaded", offset: 0, news: news("not_generated"), creating: true });
  assert.equal(v.kind, "offer");
  assert.equal(v.busy, true);
  assert.equal(newsCardView({ phase: "loaded", offset: 0, news: news("pending") }).kind, "pending");
});

test("너무 이른 주·재료 없음·만들지 못함 안내", () => {
  const early = newsCardView({ phase: "loaded", offset: 0, news: news("too_early") });
  assert.equal(early.kind, "too_early");
  assert.match(early.message, /일요일 저녁/);
  assert.equal(early.action, undefined);
  const empty = newsCardView({ phase: "loaded", offset: 0, news: news("empty") });
  assert.equal(empty.kind, "empty");
  assert.doesNotMatch(empty.message, /다음 주/);
  assert.equal(empty.action, "create"); // 서버는 empty 를 다시 보내면 새로 확인한다
  assert.equal(newsCardView({ phase: "loaded", offset: -2, news: news("empty") }).action, undefined);
  const failed = newsCardView({ phase: "loaded", offset: 0, news: news("failed") });
  assert.equal(failed.kind, "failed");
  assert.equal(failed.action, "create");
  assert.doesNotMatch(failed.message, /위의/);
});

test("다시 해도 소용없는 오류 뒤에는 버튼이 눌리지 않고, 기다리면 되는 오류는 눌린다", () => {
  const view = (error) => newsCardView({ phase: "loaded", offset: 0, news: news("not_generated"), createError: error });
  assert.equal(view(new ApiError(403, "ai_not_enabled", "")).busy, true);
  assert.equal(view(new ApiError(429, "ai_daily_limit_user", "")).busy, true);
  assert.equal(view(new ApiError(503, "llm_unavailable", "")).busy, true);
  assert.equal(view(new ApiError(429, "ai_cooldown", "", 5)).busy, false);
  assert.equal(view(new ApiError(503, "llm_failed", "")).busy, false);
});

test("만들기 실패는 카드 안 알림으로 보이고 버튼이 남는다", () => {
  const v = newsCardView({
    phase: "loaded",
    offset: 0,
    news: news("not_generated"),
    createError: new ApiError(403, "ai_not_enabled", "서버 문구"),
  });
  assert.equal(v.kind, "offer");
  assert.match(v.notice.message, /AI/);
  assert.equal(v.action, "create");
});

test("오류 코드별 문구: 동의 꺼짐·한도·간격·이른 주·AI 실패", () => {
  assert.equal(describeNewsError(new ApiError(403, "ai_not_enabled", "")).retry, false);
  assert.match(describeNewsError(new ApiError(403, "ai_not_enabled", "")).message, /소유자|관리자/);
  assert.equal(describeNewsError(new ApiError(429, "ai_daily_limit_user", "")).retry, false);
  assert.match(describeNewsError(new ApiError(429, "ai_daily_limit_group", "")).message, /가족/);
  const cool = describeNewsError(new ApiError(429, "ai_cooldown", "", 7));
  assert.equal(cool.retry, true);
  assert.match(cool.message, /7초/);
  assert.equal(describeNewsError(new ApiError(409, "news_not_ready", "")).retry, false);
  assert.equal(describeNewsError(new ApiError(503, "llm_failed", "")).retry, true);
  assert.equal(describeNewsError(new ApiError(503, "llm_unavailable", "")).retry, false);
  assert.equal(describeNewsError(new ApiError(0, "network_error", "")).retry, true);
  assert.equal(describeNewsError(new Error("boom")).retry, true);
});

test("문장의 근거: source_ids 로 근거를 찾고 없는 id 는 건너뛴다", () => {
  const found = sentenceSources({ text: "x", source_ids: ["e1", "zz"] }, ready.sources);
  assert.deepEqual(found.map((s) => s.id), ["e1"]);
});

test("근거가 일정·할 일이면 일정 탭으로, 문서뿐이면 이동하지 않는다", () => {
  assert.equal(itemRoute(ready.items[0], ready.sources), "/schedule");
  assert.equal(itemRoute(ready.items[1], ready.sources), null);
  assert.equal(itemRoute({ text: "x", source_ids: [] }, ready.sources), null);
});
