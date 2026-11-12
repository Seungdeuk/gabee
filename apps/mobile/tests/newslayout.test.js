// 우리 가족 뉴스: 소식 수에 따른 구성, 제목·본문 중복 판정, 기사 날짜, 주차 표기, 문구 통일(순수 함수). npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  LEAD_KICKER,
  SECTION_LABEL,
  articleDate,
  articleLayout,
  isRedundantBody,
  issueLabel,
  newsCardView,
  splitArticles,
} from "../src/features/more/news/newsView.js";

const sources = [
  { id: "e1", kind: "event", ref: "ev-1", label: "학교 공연", date: "2026-11-03" },
  { id: "e2", kind: "event", ref: "ev-2", label: "가족 저녁 식사", date: "2026-11-05" },
  { id: "t1", kind: "todo", ref: "td-1", label: "분리수거", date: "2026-11-03" },
  { id: "d1", kind: "document", ref: "doc-1", label: "가정통신문", date: null },
  { id: "x1", kind: "event", ref: "ev-9", label: "연말 모임", date: "2026-10-30" },
  { id: "x2", kind: "event", ref: "ev-8", label: "새해 계획", date: "2026-11-01" },
];

test("소식 수에 따른 구성: 0 없음, 1 짧은 카드, 2~3 메인+단신, 4 이상 메인+기사 목록", () => {
  assert.equal(articleLayout(0), "none");
  assert.equal(articleLayout(1), "single");
  assert.equal(articleLayout(2), "lead_brief");
  assert.equal(articleLayout(3), "lead_brief");
  assert.equal(articleLayout(4), "lead_list");
  assert.equal(articleLayout(5), "lead_list");
  assert.equal(articleLayout(6), "lead_list");
  assert.equal(articleLayout(undefined), "none");
  assert.equal(articleLayout(-1), "none");
});

test("제목과 같은 정보만 되풀이하는 본문은 중복으로 본다", () => {
  assert.equal(isRedundantBody("화요일, 치과 일정 등록", "화요일에는 치과 일정이 잡혀 있었어요."), true);
  assert.equal(isRedundantBody("학부모 상담 일정 공유", "학부모 상담 일정이 공유되어 있었어요."), true);
  assert.equal(isRedundantBody("토요일 저녁, 가족 식사 약속", "토요일 저녁에는 가족 저녁 식사 일정이 있었어요."), true);
  assert.equal(isRedundantBody("학교 공연", ""), true);
});

test("같은 뜻을 다른 표현으로 되풀이한 본문(마쳤어요·완료 등)도 중복이다", () => {
  assert.equal(isRedundantBody("분리수거 완료", "분리수거를 마쳤어요."), true);
  assert.equal(isRedundantBody("가정통신문 등록", "가정통신문이 올라왔어요."), true);
});

test("제목에 없는 내용(취소·연기 등)이 한 낱말이라도 있으면 중복이 아니다 — 정보를 숨기지 않는다", () => {
  assert.equal(isRedundantBody("학교 공연 일정", "학교 공연 일정은 취소되어 다음 주로 연기됐어요."), false);
  assert.equal(isRedundantBody("가족 식사 약속", "가족 저녁 식사 약속이 있었어요"), false); // 저녁 이라는 새 정보
});

test("제목 낱말을 다 담고도 새 말(수량·행동·장소)이 더 있으면 숨기지 않는다", () => {
  assert.equal(isRedundantBody("학교 공연", "학교 공연이 취소됐어요"), false);
  assert.equal(isRedundantBody("병원 예약", "병원 예약이 두 건 있었어요"), false); // 한글 수량 두 건
  assert.equal(isRedundantBody("할머니 생신", "할머니 생신 잔치를 이모 댁에서 열어요"), false);
});

test("기사 날짜: 윤년과 없는 날짜", () => {
  const s = (date) => [{ id: "a", kind: "event", label: "x", date }];
  assert.equal(articleDate({ source_ids: ["a"] }, s("2028-02-29")), "2월 29일(화)");
  assert.equal(articleDate({ source_ids: ["a"] }, s("2027-02-29")), null);
  assert.equal(articleDate({ source_ids: ["a"] }, undefined), null);
});

test("새 정보(시각·숫자)나 다른 내용이 있는 본문은 중복이 아니다", () => {
  assert.equal(isRedundantBody("학교 공연 일정", "화요일 오후 2시 30분에 학교 공연이 있었어요"), false);
  assert.equal(isRedundantBody("학교 공연", "분리수거를 마쳤어요"), false);
  assert.equal(isRedundantBody("가족 저녁 식사 약속", "지민이 학원 일정이 있었어요"), false);
  assert.equal(isRedundantBody("", "본문만 있어요"), false);
});

test("기사 날짜: 근거 일정의 날짜(월·일·요일), 여러 날이면 범위, 없으면 null", () => {
  assert.equal(articleDate({ source_ids: ["e1"] }, sources), "11월 3일(화)");
  assert.equal(articleDate({ source_ids: ["e1", "t1"] }, sources), "11월 3일(화)");
  assert.equal(articleDate({ source_ids: ["e1", "e2"] }, sources), "11월 3일(화) ~ 5일(목)");
  assert.equal(articleDate({ source_ids: ["x1", "x2"] }, sources), "10월 30일(금) ~ 11월 1일(일)");
  assert.equal(articleDate({ source_ids: ["d1"] }, sources), null);
  assert.equal(articleDate({ source_ids: [] }, sources), null);
  assert.equal(articleDate({ source_ids: ["zz"] }, sources), null);
  assert.equal(articleDate({ source_ids: ["q"] }, [{ id: "q", kind: "event", label: "x", date: "not-a-date" }]), null);
});

test("기사에 날짜와 보일 본문이 담긴다(중복 본문은 숨기고 전체 문장은 text 에 남긴다)", () => {
  const items = [
    { headline: "화요일, 학교 공연 일정", text: "화요일 오후 2시 30분에 학교 공연이 있었어요", source_ids: ["e1"], role: "lead" },
    { headline: "분리수거 완료", text: "분리수거를 마쳤어요", source_ids: ["t1"], role: "brief" },
    { headline: "가족 식사 약속", text: "가족 식사 약속이 있었어요", source_ids: ["e2"], role: "brief" },
  ];
  const { lead, briefs } = splitArticles(items, sources);
  assert.equal(lead.body, "화요일 오후 2시 30분에 학교 공연이 있었어요"); // 시각이라는 새 정보
  assert.equal(lead.date, "11월 3일(화)");
  assert.equal(briefs[0].body, ""); // 마쳤어요 는 제목 완료 의 되풀이라 숨긴다
  assert.equal(briefs[1].body, ""); // 제목과 같은 말뿐이라 숨긴다
  assert.equal(briefs[1].text, "가족 식사 약속이 있었어요"); // 전체 문장은 text 에 남는다
  assert.equal(briefs[1].date, "11월 5일(목)");
});

test("주차 표기: 서버 ISO 주차는 몇 호가 아니라 연중 주차다", () => {
  assert.equal(issueLabel({ issue_no: 45, issue_year: 2026 }), "2026년 45주차");
  assert.equal(issueLabel({ issue_no: 1, issue_year: 2026 }), "2026년 1주차");
  assert.equal(issueLabel({}), null);
});

test("이 주의 소식: 선택한 주와 상관없는 문구", () => {
  assert.equal(LEAD_KICKER, "이 주의 주요 소식");
  assert.equal(SECTION_LABEL, "이 주의 소식");
  assert.ok(!LEAD_KICKER.includes("이번"));
  assert.ok(!SECTION_LABEL.includes("이번"));
});

test("가족 뉴스 카드(ready): 기사 수에 따라 구성이 정해진다", () => {
  const item = (n) => ({ headline: `기사 ${n}`, text: `본문 ${n}`, source_ids: ["e1"], role: n === 1 ? "lead" : "brief" });
  const view = (n) =>
    newsCardView({
      phase: "loaded",
      offset: -1,
      news: { status: "ready", items: Array.from({ length: n }, (_, i) => item(i + 1)), sources },
    });
  assert.equal(view(1).layout, "single");
  assert.equal(view(2).layout, "lead_brief");
  assert.equal(view(3).layout, "lead_brief");
  assert.equal(view(4).layout, "lead_list");
  assert.equal(view(5).layout, "lead_list");
  assert.equal(view(0).layout, "none");
});

test("소식이 하나도 없는 주의 안내 문구: 발행할 소식이 없다고 말한다", () => {
  const v = newsCardView({ phase: "loaded", offset: -1, news: { status: "empty", items: [], sources: [] } });
  assert.equal(v.kind, "empty");
  assert.ok(v.message.includes("발행할 소식이 없어요"));
  assert.equal(v.action, "create"); // 다시 확인하기 버튼은 그대로
});
