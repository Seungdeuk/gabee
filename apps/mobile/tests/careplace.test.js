// 돌봄 위치 표시(시·동 이름, 좌표 키, 지도 주소, 받은 시각) 순수 함수 시험: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { mapUrl, placeKey, placeLabel, timeText } from "../src/features/care/location/place.js";

test("시와 동을 합쳐 짧은 이름을 만든다", () => {
  assert.equal(placeLabel({ city: "서울특별시", district: "명동", region: "서울특별시" }), "서울특별시 명동");
  assert.equal(placeLabel({ city: "성남시", district: "정자동", region: "경기도" }), "성남시 정자동");
});

test("city 가 없으면 subregion, 그것도 없으면 region 을 시 자리에 쓴다", () => {
  assert.equal(placeLabel({ city: null, subregion: "수원시", district: "영통동", region: "경기도" }), "수원시 영통동");
  assert.equal(placeLabel({ city: null, subregion: null, district: "연산동", region: "부산광역시" }), "부산광역시 연산동");
});

test("같은 말은 한 번만, 비어 있는 칸은 건너뛴다", () => {
  assert.equal(placeLabel({ city: "서울특별시", district: "서울특별시" }), "서울특별시");
  assert.equal(placeLabel({ city: "  ", district: " 명동 " }), "명동");
  assert.equal(placeLabel({ city: "대전광역시", district: null }), "대전광역시");
});

test("도로명·번지·건물 이름은 쓰지 않는다(너무 자세한 위치)", () => {
  const label = placeLabel({ city: "서울특별시", district: "명동", street: "명동길", streetNumber: "14", name: "명동성당" });
  assert.equal(label, "서울특별시 명동");
});

test("이름을 만들 수 없으면 null", () => {
  assert.equal(placeLabel(null), null);
  assert.equal(placeLabel(undefined), null);
  assert.equal(placeLabel({}), null);
  assert.equal(placeLabel({ city: null, district: null, subregion: null, region: null }), null);
});

test("가까운 좌표(약 100m 안)는 같은 키, 멀면 다른 키", () => {
  assert.equal(placeKey(37.5662, 126.9782), placeKey(37.5664, 126.9784)); // 소수 셋째 자리까지 같으면 같은 키
  assert.notEqual(placeKey(37.5665, 126.978), placeKey(37.5765, 126.978));
});

test("지도 주소에는 좌표만 들어간다", () => {
  assert.equal(mapUrl(37.5665, 126.978), "https://www.google.com/maps/search/?api=1&query=37.5665,126.978");
});

test("받은 시각을 오전/오후로 읽기 쉽게 보여 주고, 잘못된 값은 빈 글자", () => {
  const d = new Date(2026, 9, 28, 11, 5); // 기기 시간대 기준 10월 28일 11:05
  assert.equal(timeText(d.toISOString()), "10월 28일 오전 11:05");
  assert.equal(timeText(new Date(2026, 9, 28, 0, 7).toISOString()), "10월 28일 오전 12:07");
  assert.equal(timeText(new Date(2026, 9, 28, 15, 30).toISOString()), "10월 28일 오후 3:30");
  assert.equal(timeText(null), "");
  assert.equal(timeText("나쁜값"), "");
});
