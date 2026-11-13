// 사진 촬영일 전송(앱, T05-c): EXIF 에서 촬영 시각 한 값만 꺼내고(시간대가 확인된 값만), EXIF 객체는 버리며, 업로드에는 taken_at 한 칸만 더한다: npm test
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "secret-dev-token";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

const { extractTakenAt, withTakenAt } = await import("../src/features/family-chat/takenAt.js");
const { sendPhoto } = await import("../src/features/family-chat/api.js");

const NOW = new Date("2026-11-13T12:00:00Z");
const exif = (dt, off) => ({ DateTimeOriginal: dt, ...(off === undefined ? {} : { OffsetTimeOriginal: off }) });

test("촬영 시각: 시간대(오프셋)가 있으면 ISO 8601 한 값으로 돌려준다", () => {
  assert.equal(extractTakenAt(exif("2024:10:05 14:30:00", "+09:00"), NOW), "2024-10-05T14:30:00+09:00");
  assert.equal(extractTakenAt(exif("2024:10:05 14:30:00", "-05:00"), NOW), "2024-10-05T14:30:00-05:00");
  assert.equal(extractTakenAt(exif("2024:10:05 14:30:00", "+05:30"), NOW), "2024-10-05T14:30:00+05:30");
  assert.equal(extractTakenAt(exif("2024:10:05 14:30:00", "+00:00"), NOW), "2024-10-05T14:30:00+00:00"); // UTC 로 적힌 값은 그대로 확인된 시간대다
});

test("시간대를 알 수 없으면 한국·UTC 로 추측하지 않고 null 이다(서버가 보낸 날 기준으로 둔다)", () => {
  assert.equal(extractTakenAt(exif("2024:10:05 14:30:00"), NOW), null); // 오프셋 없음
  assert.equal(extractTakenAt(exif("2024:10:05 14:30:00", ""), NOW), null);
  assert.equal(extractTakenAt(exif("2024:10:05 14:30:00", null), NOW), null);
  for (const bad of ["KST", "Z", "09:00", "+9:00", "+25:00", "+09:60", "+0900", "+09:00 ", 9, {}]) {
    assert.equal(extractTakenAt(exif("2024:10:05 14:30:00", bad), NOW), null, `오프셋 ${JSON.stringify(bad)}`);
  }
});

test("촬영 시각이 없거나 형식·값이 틀리면 null 이다", () => {
  for (const e of [null, undefined, {}, [], "x", 42, exif(""), exif(undefined, "+09:00"), exif(20241005, "+09:00"), exif(null, "+09:00")]) {
    assert.equal(extractTakenAt(e, NOW), null, JSON.stringify(e));
  }
  for (const dt of [
    "0000:00:00 00:00:00",
    "2024:13:05 14:30:00", // 13월
    "2024:02:30 14:30:00", // 없는 날
    "2023:02:29 14:30:00", // 평년 2월 29일
    "2024:10:05 24:00:00",
    "2024:10:05 14:60:00",
    "2024:10:05 14:30:60",
    "2024-10-05 14:30:00", // 형식이 다름
    "2024:10:05T14:30:00",
    " 2024:10:05 14:30:00",
    "2024:10:05 14:30:00 ",
  ]) {
    assert.equal(extractTakenAt(exif(dt, "+09:00"), NOW), null, dt);
  }
  assert.equal(extractTakenAt(exif("2024:02:29 14:30:00", "+09:00"), NOW), "2024-02-29T14:30:00+09:00"); // 윤일은 정상
});

test("범위: 1990-01-01 보다 이르거나 현재+1일보다 먼 미래면 null(서버 규칙과 같다)", () => {
  assert.equal(extractTakenAt(exif("1989:12:31 23:59:59", "+00:00"), NOW), null);
  assert.equal(extractTakenAt(exif("1990:01:01 00:00:00", "+00:00"), NOW), "1990-01-01T00:00:00+00:00");
  assert.equal(extractTakenAt(exif("1990:01:01 00:00:00", "+09:00"), NOW), null); // UTC 로는 1989-12-31 15:00
  assert.equal(extractTakenAt(exif("2026:11:14 12:00:00", "+00:00"), NOW), "2026-11-14T12:00:00+00:00"); // 정확히 +1일
  assert.equal(extractTakenAt(exif("2026:11:14 12:00:01", "+00:00"), NOW), null);
  assert.equal(extractTakenAt(exif("2030:01:01 00:00:00", "+09:00"), NOW), null);
});

test("중첩 EXIF('{Exif}') 안은 읽지 않는다(iOS 네이티브가 이미 바깥 키로 펼쳐 준다). 바깥 키만 본다", () => {
  const nested = { "{Exif}": { DateTimeOriginal: "2024:10:05 14:30:00", OffsetTimeOriginal: "+09:00" } };
  assert.equal(extractTakenAt(nested, NOW), null);
  const both = { ...exif("2024:10:05 14:30:00", "+09:00"), "{Exif}": { DateTimeOriginal: "2020:01:01 00:00:00", OffsetTimeOriginal: "+00:00" } };
  assert.equal(extractTakenAt(both, NOW), "2024-10-05T14:30:00+09:00");
});

test("경계: 오프셋 상·하한(+14:00, -12:00 은 받고 +15:00 은 거절), 연도 보정(0095 년), 분 단위 오프셋의 범위 경계", () => {
  assert.equal(extractTakenAt(exif("2024:10:05 14:30:00", "+14:00"), NOW), "2024-10-05T14:30:00+14:00");
  assert.equal(extractTakenAt(exif("2024:10:05 14:30:00", "-12:00"), NOW), "2024-10-05T14:30:00-12:00");
  assert.equal(extractTakenAt(exif("2024:10:05 14:30:00", "+14:59"), NOW), "2024-10-05T14:30:00+14:59");
  assert.equal(extractTakenAt(exif("2024:10:05 14:30:00", "+15:00"), NOW), null);
  assert.equal(extractTakenAt(exif("2024:10:05 14:30:00", "+23:00"), NOW), null);
  // Date.UTC 는 0~99 년을 1900 년대로 보정하므로, 되읽어 비교하지 않으면 0095 년이 1995 년으로 통과한다
  assert.equal(extractTakenAt(exif("0095:06:15 12:00:00", "+09:00"), NOW), null);
  assert.equal(extractTakenAt(exif("0000:06:15 12:00:00", "+09:00"), NOW), null);
  // 분 단위 오프셋: UTC 로 1990-01-01 00:00:00 정각이 하한, 현재+1일(2026-11-14T12:00:00Z) 정각이 상한
  assert.equal(extractTakenAt(exif("1990:01:01 05:30:00", "+05:30"), NOW), "1990-01-01T05:30:00+05:30");
  assert.equal(extractTakenAt(exif("1990:01:01 05:29:59", "+05:30"), NOW), null);
  assert.equal(extractTakenAt(exif("2026:11:14 17:30:00", "+05:30"), NOW), "2026-11-14T17:30:00+05:30");
  assert.equal(extractTakenAt(exif("2026:11:14 17:30:01", "+05:30"), NOW), null);
  assert.equal(extractTakenAt(exif("2026:11:14 06:30:00", "-05:30"), NOW), "2026-11-14T06:30:00-05:30");
  assert.equal(extractTakenAt(exif("2026:11:14 06:30:01", "-05:30"), NOW), null);
});

test("EXIF 객체가 예외를 던지는 이상한 값이어도 사진 고르기를 막지 않고 null 이다", () => {
  const hostile = {
    get DateTimeOriginal() {
      throw new Error("boom");
    },
  };
  assert.equal(extractTakenAt(hostile, NOW), null);
  const picked = { uri: "file:///a.jpg" };
  Object.defineProperty(picked, "exif", {
    enumerable: true,
    get() {
      throw new Error("boom");
    },
  });
  assert.equal(withTakenAt(picked, NOW).takenAt, null);
  assert.ok(!("exif" in withTakenAt(picked, NOW)));
});

test("개인정보: 위치·기기 같은 다른 EXIF 키는 읽지 않는다(접근한 키가 허용 목록 안에만 있다)", () => {
  const touched = new Set();
  const raw = {
    DateTimeOriginal: "2024:10:05 14:30:00",
    OffsetTimeOriginal: "+09:00",
    GPSLatitude: 37.5,
    GPSLongitude: 127.0,
    Make: "Acme",
    Model: "Phone 1",
    "{GPS}": { Latitude: 37.5 },
    "{Exif}": { LensModel: "x" },
  };
  const spy = new Proxy(raw, {
    get(target, key) {
      touched.add(String(key));
      return target[key];
    },
    has(target, key) {
      touched.add(String(key));
      return key in target;
    },
    ownKeys() {
      throw new Error("키 목록을 훑으면 안 된다");
    },
  });
  assert.equal(extractTakenAt(spy, NOW), "2024-10-05T14:30:00+09:00");
  const allowed = new Set(["DateTimeOriginal", "OffsetTimeOriginal"]); // "{Exif}" 같은 중첩 키도 읽지 않는다
  for (const key of touched) assert.ok(allowed.has(key), `허용되지 않은 키를 읽었다: ${key}`);
  const out = extractTakenAt(raw, NOW);
  assert.ok(!/GPS|Make|Model|37\.5|127/.test(out), "결과에는 날짜만 있다");
});

test("withTakenAt: EXIF 객체를 떼어 내고 takenAt 한 값만 붙인 새 asset 을 돌려준다(원본은 그대로)", () => {
  const picked = { uri: "file:///a.jpg", fileName: "a.jpg", mimeType: "image/jpeg", fileSize: 1000, width: 10, height: 20, exif: { ...exif("2024:10:05 14:30:00", "+09:00"), GPSLatitude: 37.5 } };
  const frozen = JSON.stringify(picked);
  const out = withTakenAt(picked, NOW);
  assert.equal(out.takenAt, "2024-10-05T14:30:00+09:00");
  assert.ok(!("exif" in out), "exif 칸이 남으면 안 된다");
  assert.deepEqual({ ...out, takenAt: undefined }, { uri: "file:///a.jpg", fileName: "a.jpg", mimeType: "image/jpeg", fileSize: 1000, width: 10, height: 20, takenAt: undefined });
  assert.equal(JSON.stringify(picked), frozen, "원본 asset 을 바꾸지 않는다");
  assert.ok(!JSON.stringify(out).includes("GPS"));
});

test("withTakenAt: EXIF 가 없거나(웹) 쓸 수 없으면 takenAt 은 null 이고 exif 는 역시 남지 않는다", () => {
  for (const e of [undefined, null, {}, exif("2024:10:05 14:30:00")]) {
    const out = withTakenAt({ uri: "blob:x", exif: e }, NOW);
    assert.equal(out.takenAt, null);
    assert.ok(!("exif" in out));
  }
  assert.equal(withTakenAt({ uri: "blob:x" }, NOW).takenAt, null);
});

function formOf(call) {
  const body = call.init.body;
  assert.ok(body instanceof FormData);
  return [...body.keys()];
}
function capture() {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify({ id: 1 }), { status: 201, headers: { "Content-Type": "application/json" } });
  };
  return calls;
}
const asset = (extra = {}) => ({ uri: "blob:x", file: new Blob(["x"], { type: "image/jpeg" }), fileName: "a.jpg", mimeType: "image/jpeg", ...extra });

test("업로드: takenAt 이 있으면 taken_at 한 칸만 더하고 다른 EXIF 칸은 없다", async () => {
  const calls = capture();
  await sendPhoto(asset({ takenAt: "2024-10-05T14:30:00+09:00", exif: { GPSLatitude: 37.5 } }), "room1", "batch-12345678");
  assert.deepEqual(formOf(calls[0]).sort(), ["batch_id", "file", "room_id", "taken_at"]);
  assert.equal(calls[0].init.body.get("taken_at"), "2024-10-05T14:30:00+09:00");
  assert.ok(![...calls[0].init.body.values()].some((v) => typeof v === "string" && /GPS|37\.5/.test(v)), "위치 값이 폼에 없다");
});

test("업로드: takenAt 이 없거나 쓸 수 없으면 taken_at 을 보내지 않는다(업로드는 그대로 된다)", async () => {
  for (const bad of [undefined, null, "", 123, {}, "x".repeat(41)]) {
    const calls = capture();
    await sendPhoto(asset({ takenAt: bad }), null, undefined);
    assert.deepEqual(formOf(calls[0]), ["file"], JSON.stringify(bad));
  }
});
