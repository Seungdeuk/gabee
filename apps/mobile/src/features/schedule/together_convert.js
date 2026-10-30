import { ALL_DAY_END, ALL_DAY_START } from "./api";

// 같이(부탁) 서버 응답 ↔ 화면 모델 변환. 화면·테마에 의존하지 않는 순수 파일이라 node 테스트로 읽는다.
// family 는 members.js 의 buildFamily 결과(toApp·toUser).

const hhmm = (time) => (time ? time.slice(0, 5) : null);

/**
 * 서버 RequestOut → TogetherRequest. "누구"(whoIds)는 서버에 없어 빈 목록이다. 종일은 00:00~23:59 로 읽는다.
 * @param {import("./api").ServerRequest} r
 * @param {import("./api").Family} family
 * @returns {import("./model").TogetherRequest}
 */
export function toRequest(r, family) {
  const start = hhmm(r.start_time);
  const end = hhmm(r.end_time);
  const allDay = start === ALL_DAY_START && end === ALL_DAY_END;
  const toIds = [];
  const replies = {};
  for (const rec of r.recipients) {
    const appId = family.toApp(rec.user_id) ?? rec.user_id;
    toIds.push(appId);
    if (rec.status === "accepted" || rec.status === "declined") replies[appId] = rec.status;
  }
  return {
    id: r.id,
    fromId: family.toApp(r.from_id) ?? r.from_id,
    toIds,
    title: r.title,
    date: r.start_date,
    startTime: allDay ? null : start,
    endTime: allDay ? null : end,
    allDay,
    place: r.place ?? "",
    memo: r.memo ?? "",
    whoIds: [],
    replies,
    cancelled: Boolean(r.canceled),
    itemId: r.my_event_id ?? null,
    editedAt: r.edited_at ?? null,
  };
}

/**
 * 보내기 값 → POST /schedule/requests 본문. 종일이면 00:00/23:59, 시간이 없으면 null, 시작이 없으면 끝도 null.
 * @param {Pick<import("./model").TogetherRequest, "title" | "date" | "startTime" | "endTime" | "allDay" | "place" | "memo" | "toIds">} data
 * @param {import("./api").Family} family
 */
export function toRequestBody(data, family) {
  return {
    title: data.title,
    start_date: data.date,
    start_time: data.allDay ? ALL_DAY_START : (data.startTime ?? null),
    end_time: data.allDay ? ALL_DAY_END : data.startTime ? (data.endTime ?? null) : null,
    place: data.place ?? "",
    memo: data.memo ?? "",
    to_ids: data.toIds.map(family.toUser).filter(Boolean),
  };
}
