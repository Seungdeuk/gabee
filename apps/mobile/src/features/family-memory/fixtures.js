// 개발·시험용 합성 추억 후보(mock 모드). 실제 사진·실제 가족 데이터가 아니다: 사진 주소는 허용된 모양이지만 서버에 없는 가짜 id 라 이미지는 회색 바탕으로 보인다.

const photo = (id, takenAt, rep = false) => ({
  attachment_id: `mock-${id}`,
  thumb_url: `/family-chat/photos/mock-${id}?size=thumb`,
  photo_url: `/family-chat/photos/mock-${id}`,
  taken_at: takenAt,
  is_representative: rep,
});

const camp = [
  photo("a1", "2026-05-02T01:10:00+00:00", true),
  photo("a2", "2026-05-02T01:25:00+00:00"),
  photo("a3", "2026-05-02T03:40:00+00:00"),
  photo("a4", "2026-05-03T00:05:00+00:00"),
  photo("a5", "2026-05-03T02:30:00+00:00"),
];
const dinner = [photo("b1", "2026-09-14T09:00:00+00:00"), photo("b2", "2026-09-14T09:12:00+00:00", true), photo("b3", "2026-09-14T09:20:00+00:00")];
const undatedMix = [photo("c1", "2025-12-24T10:00:00+00:00", true), photo("c2", "2025-12-24T10:20:00+00:00"), photo("c3", null), photo("c4", null)];

const candidate = (id, photos, starts, ends, score) => ({
  id,
  status: "private",
  representative: photos.find((p) => p.is_representative),
  photos,
  photo_count: photos.length,
  dated_count: photos.filter((p) => p.taken_at).length,
  undated_count: photos.filter((p) => !p.taken_at).length,
  starts_at: starts,
  ends_at: ends,
  bridged: false,
  score,
  algorithm_version: "memgrp-1",
  updated_at: "2026-11-19T00:00:00+00:00",
});

/** 서버 응답과 같은 모양의 합성 응답(`GET /family-memory/candidates`). */
export const mockCandidatesResponse = () => ({
  items: [
    candidate("mock-camp", camp, "2026-05-02T01:10:00+00:00", "2026-05-03T02:30:00+00:00", 0.82),
    candidate("mock-dinner", dinner, "2026-09-14T09:00:00+00:00", "2026-09-14T09:20:00+00:00", 0.7),
    candidate("mock-undated", undatedMix, "2025-12-24T10:00:00+00:00", "2025-12-24T10:20:00+00:00", 0.6),
  ],
});

/** mock 모드의 불러오기(네트워크 없이 같은 모양의 응답). */
export const loadMockCandidates = () => Promise.resolve(mockCandidatesResponse());