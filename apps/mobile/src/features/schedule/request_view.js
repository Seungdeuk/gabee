// 내가 보낸 부탁을 일정 메인 브리핑에 섞어 보이는 규칙과 수락 현황 문구. 화면에 의존하지 않아 node 테스트로 확인한다.

/**
 * 이 날 브리핑에 보일 내가 보낸 부탁. 취소된 것과 날짜가 지난 것은 뺀다.
 * @param {import("./model").TogetherRequest[]} requests
 * @param {string} meId
 * @param {string} dateKey "YYYY-MM-DD" 브리핑 구역의 날짜
 * @param {string} today "YYYY-MM-DD"
 */
export function briefingRequests(requests, meId, dateKey, today) {
  return requests.filter((r) => r.fromId === meId && !r.cancelled && r.date === dateKey && r.date >= today);
}

/**
 * 일정과 부탁을 한 목록으로 합친다. 부탁은 약속처럼 시간 자리에 끼고(종일 → 시간 있음 → 시간 없음), 같은 자리면 일정이 먼저다.
 * @param {import("./model").ScheduleItem[]} items
 * @param {import("./model").TogetherRequest[]} requests
 * @param {(a: object, b: object) => number} compareItems model.js 의 일정 정렬(테마를 불러오는 파일이라 시험에서 직접 못 읽어 받는다)
 * @returns {({ type: "item", item: import("./model").ScheduleItem } | { type: "request", request: import("./model").TogetherRequest })[]}
 */
export function mergeBriefing(items, requests, compareItems) {
  const entries = [
    ...items.map((item) => ({ type: "item", item, order: item })),
    ...requests.map((request) => ({
      type: "request",
      request,
      order: { kind: "appointment", allDay: request.allDay, startTime: request.startTime },
    })),
  ];
  return entries.sort((a, b) => compareItems(a.order, b.order)).map(({ order, ...entry }) => entry);
}

/**
 * 부탁 카드의 수락 현황. 아무도 수락하지 않았으면 "기다려요", 아니면 "수락 n/m"이고 전원 수락이면 full 이다.
 * 보낸 사람 화면에서만 쓴다(받는 사람 화면의 toIds 는 일부만 내려와 m 을 알 수 없다).
 * @param {Pick<import("./model").TogetherRequest, "toIds" | "replies">} request
 * @returns {{ label: string, full: boolean }}
 */
export function acceptSummary(request) {
  const total = request.toIds.length;
  const accepted = request.toIds.filter((id) => request.replies[id] === "accepted").length;
  if (accepted === 0) return { label: "기다려요", full: false };
  return { label: `수락 ${accepted}/${total}`, full: accepted === total };
}
