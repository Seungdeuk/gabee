// 가족 놀이터 초대 문구·링크: 소통방에 올리는 글자와 그 안의 링크를 찾고 앱 경로로 바꾸는 규칙을 시험한다: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { findPlayLink, inviteLink, inviteMessage, playPathFromLink, splitPlayLink } from "../src/features/playground/invite.js";

test("폭탄 초대는 로비 주소를, 그 밖은 놀이터 홈 주소를 만든다", () => {
  assert.equal(inviteLink("bomb"), "gabee://play/bomb-lobby?host=0");
  assert.equal(inviteLink("play"), "gabee://play");
  assert.equal(inviteLink("nope"), "gabee://play");
});

test("링크 앞부분만 바꿀 수 있다(Expo Go 시험용)", () => {
  assert.equal(inviteLink("bomb", "exp://192.168.0.54:8081/--"), "exp://192.168.0.54:8081/--/play/bomb-lobby?host=0");
  assert.equal(inviteLink("bomb", "exp://192.168.0.54:8081/--/"), "exp://192.168.0.54:8081/--/play/bomb-lobby?host=0");
  assert.equal(inviteMessage("아빠", "bomb", "exp://h:8081/--"), "아빠야, 문장 폭탄 방에 들어와!\nexp://h:8081/--/play/bomb-lobby?host=0");
  assert.equal(inviteLink("bomb", ""), "gabee://play/bomb-lobby?host=0"); // 비우면 기본값
});

test("초대 문구는 말 한 줄과 링크 한 줄이다", () => {
  assert.equal(inviteMessage("아빠", "bomb"), "아빠야, 문장 폭탄 방에 들어와!\ngabee://play/bomb-lobby?host=0");
  assert.equal(inviteMessage("", "play"), "가족 놀이터 같이 놀자!\ngabee://play");
});

test("글자에서 놀이터 링크를 찾아 조각으로 나눈다", () => {
  const text = inviteMessage("아빠", "bomb");
  assert.equal(findPlayLink(text), "gabee://play/bomb-lobby?host=0");
  assert.deepEqual(splitPlayLink(text), [
    { text: "아빠야, 문장 폭탄 방에 들어와!\n", link: false },
    { text: "gabee://play/bomb-lobby?host=0", link: true },
  ]);
  assert.deepEqual(splitPlayLink("그냥 말"), [{ text: "그냥 말", link: false }]);
  assert.equal(findPlayLink("gabee://reset-password?token=1"), null);
});

test("링크 뒤에 글자가 이어져도 링크는 공백 앞까지만이다", () => {
  assert.deepEqual(splitPlayLink("gabee://play 와!"), [
    { text: "gabee://play", link: true },
    { text: " 와!", link: false },
  ]);
});

test("앱 경로로 바꾸고, 놀이터 주소가 아니면 열지 않는다", () => {
  assert.equal(playPathFromLink("gabee://play/bomb-lobby?host=0"), "/play/bomb-lobby?host=0");
  assert.equal(playPathFromLink("gabee://play"), "/play");
  assert.equal(playPathFromLink("gabee://reset-password?token=1"), null);
  assert.equal(playPathFromLink("https://evil.example/play"), null);
  assert.equal(playPathFromLink(null), null);
});
