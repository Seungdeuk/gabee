// 우리 가족 뉴스(신문형 화면)의 순수 계산 시험: 메인·단신 나누기, 분류, 주차 표시, 기록 요약. npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  REPORTER_GREETING,
  categoryOf,
  issueForWeek,
  issueLabel,
  newsCardView,
  recordSummary,
  splitArticles,
} from "../src/features/more/news/newsView.js";

test("호수는 지금 보는 주의 응답일 때만 보인다(주를 바꾸는 동안 이전 주 호수가 남지 않는다)", () => {
  const prev = { week_start: "2026-11-02", issue_no: 45, issue_year: 2026 };
  assert.equal(issueForWeek(prev, "2026-11-02"), "2026년 45주차");
  assert.equal(issueForWeek(prev, "2026-11-09"), null); // 새 주를 조회하는 중·실패: 이전 주 응답
  assert.equal(issueForWeek(null, "2026-11-02"), null);
  assert.equal(issueForWeek({ issue_no: 45, issue_year: 2026 }, "2026-11-02"), null); // 주 정보가 없으면 믿지 않는다
});

const sources = [
  { id: "e1", kind: "event", ref: "ev-1", label: "학교 공연", date: "2026-11-03" },
  { id: "e2", kind: "event", ref: "ev-2", label: "가족 저녁 식사", date: "2026-11-03" },
  { id: "t1", kind: "todo", ref: "td-1", label: "분리수거", date: "2026-11-04" },
  { id: "d1", kind: "document", ref: "doc-1", label: "가정통신문", date: "2026-11-03" },
];
const v2Items = [
  { headline: "공연과 저녁 식사", text: "오후 2시 30분 학교 공연과 가족 저녁 식사 일정이 있었어요", source_ids: ["e1", "e2"], role: "lead", category: "일정" },
  { headline: "분리수거 완료", text: "분리수거를 마쳤어요", source_ids: ["t1"], role: "brief", category: "할 일" },
  { headline: null, text: "가정통신문이 올라왔어요", source_ids: ["d1"], role: "brief", category: "문서" },
];
const v1Items = [
  { text: "학교 공연이 있었어요", source_ids: ["e1"], headline: null, role: null, category: null },
  { text: "가정통신문이 올라왔어요", source_ids: ["d1"], headline: null, role: null, category: null },
];

test("기사형 뉴스: 메인 하나와 단신으로 나눈다(헤드라인·본문·분류)", () => {
  const { lead, briefs } = splitArticles(v2Items, sources);
  assert.equal(lead.headline, "공연과 저녁 식사");
  assert.equal(lead.body, "오후 2시 30분 학교 공연과 가족 저녁 식사 일정이 있었어요");
  assert.equal(lead.category, "일정");
  assert.equal(briefs.length, 2);
  assert.equal(briefs[0].headline, "분리수거 완료");
});

test("헤드라인이 없으면 본문을 제목처럼 보이고 본문은 비운다(같은 글이 두 번 나오지 않는다)", () => {
  const { briefs } = splitArticles(v2Items, sources);
  assert.equal(briefs[1].headline, "가정통신문이 올라왔어요");
  assert.equal(briefs[1].body, "");
});

test("메인이 배열 첫 번째가 아니어도 role 로 고른다", () => {
  const { lead, briefs } = splitArticles([v2Items[1], v2Items[0]], sources);
  assert.equal(lead.headline, "공연과 저녁 식사");
  assert.equal(briefs.length, 1);
});

test("옛 뉴스(v1, role 없음): 첫 문장이 메인이고 나머지는 단신, 분류는 근거 종류로 보여 준다", () => {
  const { lead, briefs } = splitArticles(v1Items, sources);
  assert.equal(lead.headline, "학교 공연이 있었어요");
  assert.equal(lead.body, "");
  assert.equal(lead.category, "일정");
  assert.equal(briefs[0].category, "문서");
});

test("메인이 둘로 오면 첫 메인만 메인이다", () => {
  const two = [{ ...v2Items[0] }, { ...v2Items[1], role: "lead" }];
  const { lead, briefs } = splitArticles(two, sources);
  assert.equal(lead.headline, "공연과 저녁 식사");
  assert.equal(briefs.length, 1);
});

test("기사가 없으면 메인도 없다", () => {
  assert.deepEqual(splitArticles([], sources), { lead: null, briefs: [] });
  assert.deepEqual(splitArticles(undefined, undefined), { lead: null, briefs: [] });
});

test("분류: 서버가 준 것을 쓰고, 없으면 근거 종류(섞이면 가족 소식), 근거도 없으면 null", () => {
  assert.equal(categoryOf({ category: "문서", source_ids: ["e1"] }, sources), "문서");
  assert.equal(categoryOf({ source_ids: ["t1"] }, sources), "할 일");
  assert.equal(categoryOf({ source_ids: ["e1", "d1"] }, sources), "가족 소식");
  assert.equal(categoryOf({ source_ids: [] }, sources), null);
  assert.equal(categoryOf({ source_ids: ["zz"] }, sources), null);
});

test("호수: 서버 issue_no 를 그대로 보이고 없으면 보이지 않는다", () => {
  assert.equal(issueLabel({ issue_no: 46, issue_year: 2026 }), "2026년 46주차");
  assert.equal(issueLabel({ issue_no: 1, issue_year: 2026 }), "2026년 1주차");
  assert.equal(issueLabel({}), null);
  assert.equal(issueLabel(null), null);
  assert.equal(issueLabel({ issue_no: 0, issue_year: 2026 }), null);
  assert.equal(issueLabel({ issue_no: "46", issue_year: 2026 }), null);
});

test("가족 뉴스 카드(ready): 기존 값에 메인·단신·호수가 더해진다", () => {
  const v = newsCardView({
    phase: "loaded",
    offset: -1,
    news: { status: "ready", title: "t", items: v2Items, sources, issue_no: 45, issue_year: 2026 },
  });
  assert.equal(v.kind, "ready");
  assert.equal(v.items.length, 3); // 기존 필드는 그대로
  assert.equal(v.lead.headline, "공연과 저녁 식사");
  assert.equal(v.briefs.length, 2);
  assert.equal(v.issue, "2026년 45주차");
});

test("가비 기자 인사는 AI 호출 없는 고정 문구다", () => {
  assert.equal(typeof REPORTER_GREETING, "string");
  assert.ok(REPORTER_GREETING.includes("가비 기자"));
});

test("한 주의 기록 요약 한 줄: 통계는 접힌 영역의 요약으로", () => {
  assert.equal(recordSummary({ sharedCount: 3, todoDone: 0, docCount: 2 }), "공유 일정 3건 · 완료한 할 일 0건 · 공유 문서 2건");
  assert.equal(recordSummary({ sharedCount: 1, todoDone: 2, docCount: null }), "공유 일정 1건 · 완료한 할 일 2건");
  assert.equal(recordSummary(null), "");
});
