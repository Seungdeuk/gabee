import assert from "node:assert/strict";
import test from "node:test";

import { agentErrorMessage, changedItems, ERROR_TEXT, fromAgentResponse } from "@/features/schedule/agent_response";

const mine = {
  id: "e1",
  kind: "appointment",
  title: "병원",
  date: "2026-10-28",
  startTime: "09:00",
  endTime: null,
  allDay: false,
  place: "",
  memo: "",
  whoIds: ["mom"],
  topicId: null,
  sharedWith: [],
  createdBy: "me",
  checked: false,
};

test("조회 카드는 내 일정이 있으면 그 항목을, 없으면 요약으로 미니 카드를 만든다", () => {
  const res = {
    intent: "query",
    text: "2개예요",
    cards: [
      {
        type: "event_list",
        data: {
          events: [
            {
              id: "e1",
              title: "병원",
              date: "2026-10-28",
              time: "09:00",
              end_time: "",
              note: "",
              status: "",
              checked: true,
            },
            {
              id: "x",
              title: "모임",
              date: "2026-10-30",
              time: "",
              end_time: "",
              note: "",
              status: "",
              checked: false,
            },
          ],
        },
      },
    ],
  };
  const m = fromAgentResponse(res, [mine]);
  assert.equal(m.text, "2개예요");
  assert.deepEqual(m.items[0].whoIds, ["mom"]);
  assert.equal(m.items[0].checked, true);
  assert.equal(m.items[1].startTime, null);
  assert.equal(m.items[1].title, "모임");
});

test("등록 완료 카드와 공유 확인 카드", () => {
  const done = fromAgentResponse(
    {
      intent: "register",
      text: "등록했어요.",
      cards: [
        {
          type: "registered",
          data: {
            event_id: "n1",
            kind: 1,
            title: "점심",
            date: "2026-10-29",
            start_time: "12:00",
            end_time: "",
            place: "",
            who: ["엄마"],
            shared: 1,
          },
        },
      ],
    },
    [],
  );
  assert.deepEqual(done.registered, {
    eventId: "n1",
    title: "점심",
    date: "2026-10-29",
    startTime: "12:00",
    endTime: null,
    place: "",
    who: ["엄마"],
    shared: 1,
  });

  const action = { type: "register", event_id: "", changes: {}, draft: { title: "점심" } };
  const ask = fromAgentResponse(
    {
      intent: "register",
      text: "엄마에게 공유해서 등록할까요?",
      cards: [{ type: "register_confirm", data: { title: "점심", share: [{ id: "u", name: "엄마" }] } }],
      pending_action: action,
    },
    [],
  );
  assert.equal(ask.confirm.kind, "register");
  assert.equal(ask.confirm.state, "pending");
  assert.equal(ask.pending, action);
});

test("수정·삭제 확인, 되묻는 초안, 일정 아님", () => {
  const edit = fromAgentResponse(
    {
      intent: "edit",
      text: "이렇게 바꿀까요?",
      cards: [
        {
          type: "edit_confirm",
          data: { event: { id: "e1", title: "병원" }, changes: [{ label: "시간", before: "09:00", after: "10:00" }] },
        },
      ],
      pending_action: { type: "edit", event_id: "e1" },
    },
    [],
  );
  assert.equal(edit.confirm.kind, "edit");
  assert.deepEqual(edit.confirm.lines, ["시간 09:00 → 10:00"]);

  const del = fromAgentResponse(
    {
      intent: "delete",
      text: "지울까요?",
      cards: [{ type: "delete_confirm", data: { event: { id: "e1", title: "병원" } } }],
    },
    [],
  );
  assert.equal(del.confirm.kind, "delete");

  const ask = fromAgentResponse(
    { intent: "register", text: "언제요?", cards: [], draft: { title: "점심", asks: 1 } },
    [],
  );
  assert.deepEqual(ask.draft, { title: "점심", asks: 1 });

  assert.match(fromAgentResponse({ intent: "not_schedule", text: "", cards: [] }, []).text, /일정/);
});

test("오류 말풍선과 일정이 바뀐 응답", () => {
  assert.deepEqual(agentErrorMessage(new Error("x")), { text: ERROR_TEXT, error: true });
  assert.equal(agentErrorMessage({ status: 429, message: "오늘은 다 썼어요" }).text, "오늘은 다 썼어요");
  assert.ok(changedItems({ intent: "register" }));
  assert.ok(!changedItems({ intent: "query" }));
});
