// 찰칵! 탐정단 가비 추천 화면의 순수 함수: 추천 카드 → 문제 내기 칸, 보낼 사진 부분(recId 가 새지 않는 규칙)
import assert from "node:assert/strict";
import { test } from "node:test";

import { activeDraft, EMPTY_REC_PHOTO, isRecUnavailable, photoRecLabel, photoSendPart, photoSendPartFor, recDraftFromItem, recToDraft } from "../src/features/playground/photoRec.js";

const item = { id: "r1", kind: "month", source: "album", question: "몇 월일까?", options: ["3월", "5월", "8월"], answer_index: 1, box_x: 0.3, box_y: 0.7, zoom: 16, image_url: "/play/photo/recommendations/r1/image" };

test("출처 알약 글자", () => {
  assert.equal(photoRecLabel({ source: "album" }), "가족 사진");
  assert.equal(photoRecLabel({ source: "common" }), "가비가 고른 사진");
});

test("카드를 고르면 사진 상태에 recId 와 확대 위치가 담기고 질문·보기·정답·배율이 채워진다", () => {
  const d = recToDraft(item);
  assert.deepEqual(d.photo, { kind: "rec", recId: "r1", imageUrl: item.image_url, boxX: 0.3, boxY: 0.7 });
  assert.equal(d.zoom, 16);
  assert.equal(d.question, "몇 월일까?");
  assert.equal(d.count, 3);
  assert.deepEqual(d.opts, ["3월", "5월", "8월", ""]);
  assert.equal(d.ansIdx, 1);
});

test("모르는 배율은 8배, 시안(image_url 없음)은 imageUrl null", () => {
  const d = recToDraft({ ...item, zoom: 5, image_url: undefined });
  assert.equal(d.zoom, 8);
  assert.equal(d.photo.imageUrl, null);
});

test("보낼 사진: 추천 카드만 recId(파일 없이)", () => {
  assert.deepEqual(photoSendPart(recToDraft(item).photo), { recId: "r1" });
});

test("내 폰 사진으로 바꾸면 recId 가 절대 따라가지 않는다", () => {
  const asset = { uri: "file:///a.jpg" };
  const part = photoSendPart({ kind: "phone", uri: asset.uri, asset, recId: "r1" }); // 혹시 recId 가 남아 있어도
  assert.deepEqual(part, { image: asset, source: 2 });
  assert.equal("recId" in part, false);
});

test("사진이 없거나 가족 앨범 시안이면 보낼 부분이 없다", () => {
  assert.equal(photoSendPart({ kind: "none" }), null);
  assert.equal(photoSendPart({ kind: "album", id: "a1", recId: "r1" }), null);
  assert.equal(photoSendPart(null), null);
});

test("409 photo_not_available·rec_already_sent 만 추천 불가로 본다", () => {
  assert.equal(isRecUnavailable({ status: 409, code: "photo_not_available" }), true);
  assert.equal(isRecUnavailable({ status: 409, code: "rec_already_sent" }), true);
  assert.equal(isRecUnavailable({ status: 409, code: "other" }), false);
  assert.equal(isRecUnavailable({ status: 404, code: "rec_not_found" }), false);
  assert.equal(isRecUnavailable(new Error("x")), false);
});

test("추천 탭 초안: 고른 카드로 채우고 pickedId·질문 종류가 정해진다", () => {
  const d = recDraftFromItem(item);
  assert.equal(d.pickedId, "r1");
  assert.equal(d.ask, "직접 쓰기");
  assert.equal(d.photo.recId, "r1");
  assert.equal(d.note, "");
});

test("탭별 보낼 사진: 추천 탭은 추천 카드만, 직접 내기 탭은 내 폰 사진만", () => {
  const rec = recToDraft(item).photo;
  const asset = { uri: "file:///a.jpg" };
  const phone = { kind: "phone", uri: asset.uri, asset };
  assert.deepEqual(photoSendPartFor("rec", rec), { recId: "r1" });
  assert.equal(photoSendPartFor("rec", phone), null);
  assert.deepEqual(photoSendPartFor("manual", phone), { image: asset, source: 2 });
  assert.equal(photoSendPartFor("manual", rec), null); // 추천 사진·recId 가 직접 내기 보내기로 새지 않는다
  assert.equal(photoSendPartFor("manual", { kind: "phone", asset, recId: "r1" }).recId, undefined);
  assert.equal(photoSendPartFor("rec", EMPTY_REC_PHOTO), null);
});

test("두 초안은 따로: 탭에 맞는 것을 고른다", () => {
  const recDraft = { name: "rec" };
  const manualDraft = { name: "manual" };
  assert.equal(activeDraft("rec", recDraft, manualDraft), recDraft);
  assert.equal(activeDraft("manual", recDraft, manualDraft), manualDraft);
});
