// 채팅 사진 -> 가비 기록 저장("가비 기록에 저장")의 순수 로직과 웹·네이티브 흐름을 시험한다: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

const MOD = "../src/features/family-chat/saveToRecord.js";
const GOOD = { id: "a1b2c3", url: "/family-chat/photos/a1b2c3" };

test("canSaveToRecord: 가족 전체방의 사진 메시지에만 버튼을 보인다(1:1 방·사진 없음·주소 없음은 아님)", async () => {
  const { canSaveToRecord } = await import(MOD);
  assert.equal(canSaveToRecord({ direct: false, attachment: GOOD }), true);
  assert.equal(canSaveToRecord({ direct: true, attachment: GOOD }), false); // 1:1 사진은 가족 전체가 보는 기록으로 옮기지 않는다
  assert.equal(canSaveToRecord({ direct: false, attachment: null }), false);
  assert.equal(canSaveToRecord({ direct: false, attachment: undefined }), false);
  assert.equal(canSaveToRecord({ direct: false, attachment: { id: "x" } }), false);
  assert.equal(canSaveToRecord({ direct: false, attachment: { id: "x", url: "" } }), false);
});

test("recordFileName: 사진 id 앞부분으로 JPEG 이름을 만들고 이상한 글자는 뗀다", async () => {
  const { recordFileName } = await import(MOD);
  assert.equal(recordFileName({ id: "a1b2c3" }), "gabee-chat-a1b2c3.jpg");
  assert.equal(recordFileName({ id: "../../etc/passwd" }), "gabee-chat-etcpasswd.jpg");
  assert.equal(recordFileName({ id: "x".repeat(40) }), `gabee-chat-${"x".repeat(12)}.jpg`);
  assert.equal(recordFileName({}), "gabee-chat-photo.jpg");
  assert.equal(recordFileName(null), "gabee-chat-photo.jpg");
});

test("recordTarget: 웹만 blob, 나머지는 네이티브", async () => {
  const { recordTarget } = await import(MOD);
  assert.equal(recordTarget("web"), "web");
  assert.equal(recordTarget("ios"), "native");
  assert.equal(recordTarget("android"), "native");
});

test("saveToRecord(웹): 받은 blob 을 multipart 'file' 로 올리고 성공 문구를 돌려준다", async () => {
  const { saveToRecord, RECORD_DONE_MESSAGE, recordFileName } = await import(MOD);
  const calls = { downloaded: [], uploaded: [] };
  const blob = new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: "image/jpeg" });
  const result = await saveToRecord(GOOD, "web", {
    download: async (path) => (calls.downloaded.push(path), blob),
    upload: async (form) => void calls.uploaded.push(form),
  });
  assert.deepEqual(result, { ok: true, message: RECORD_DONE_MESSAGE });
  assert.deepEqual(calls.downloaded, [GOOD.url]);
  assert.equal(calls.uploaded.length, 1);
  const file = calls.uploaded[0].get("file");
  assert.equal(file.name, recordFileName(GOOD)); // blob 이 이름 있는 파일로 담긴다("[object Object]" 글자가 아니다)
  assert.equal(file.size, 3);
});

test("saveToRecord(웹): 내려받기나 올리기가 실패하면 실패 문구를 돌려주고 던지지 않는다", async () => {
  const { saveToRecord, RECORD_FAIL_MESSAGE } = await import(MOD);
  const blob = new Blob(["x"]);
  const downloadFails = await saveToRecord(GOOD, "web", {
    download: async () => {
      throw new Error("photo_unavailable");
    },
    upload: async () => assert.fail("내려받기에 실패하면 올리지 않는다"),
  });
  assert.deepEqual(downloadFails, { ok: false, message: RECORD_FAIL_MESSAGE });
  const uploadFails = await saveToRecord(GOOD, "web", {
    download: async () => blob,
    upload: async () => {
      throw new Error("503");
    },
  });
  assert.deepEqual(uploadFails, { ok: false, message: RECORD_FAIL_MESSAGE });
});

test("saveToRecord: 낯선 경로·주소 없음은 내려받기·올리기 없이 거절한다", async () => {
  const { saveToRecord, RECORD_FAIL_MESSAGE } = await import(MOD);
  const never = {
    download: async () => assert.fail("내려받으면 안 된다"),
    upload: async () => assert.fail("올리면 안 된다"),
    native: { photoRequest: async () => assert.fail("요청하면 안 된다") },
  };
  const bad = [
    { id: "a", url: "https://evil.test/family-chat/photos/a1" },
    { id: "a", url: "/family-chat/photos/../secret" },
    { id: "a", url: "/other/path" },
    { id: "a", url: "" },
    { id: "a" },
    null,
    undefined,
  ];
  for (const attachment of bad) {
    for (const os of ["web", "ios"]) {
      assert.deepEqual(await saveToRecord(attachment, os, never), { ok: false, message: RECORD_FAIL_MESSAGE }, `${os} ${JSON.stringify(attachment)}`);
    }
  }
});

/** 시험용 네이티브 의존성과 호출 기록(실제 expo 모듈 없이). */
function fakeNative({ failDownload = false } = {}) {
  const log = { requests: [], downloads: [], fetched: 0, removed: 0 };
  const native = {
    photoRequest: async (path) => (log.requests.push(path), { url: `http://api.test${path}`, headers: { "X-Gyeot-Token": "t" } }),
    download: async (url, headers, fileName) => {
      log.downloads.push({ url, headers, fileName });
      return {
        fetch: async () => {
          log.fetched += 1;
          if (failDownload) throw new Error("download failed");
          return "file:///cache/gabee-save-1.jpg";
        },
        remove: () => void (log.removed += 1),
      };
    },
  };
  return { log, native };
}

test("saveToRecord(네이티브): 캐시 파일로 받아 {uri,name,type} 으로 올리고 임시 파일을 지운다", async () => {
  const { saveToRecord, RECORD_DONE_MESSAGE, recordFileName } = await import(MOD);
  const { log, native } = fakeNative();
  const uploaded = [];
  const result = await saveToRecord(GOOD, "android", { native, upload: async (form) => void uploaded.push(form) });
  assert.deepEqual(result, { ok: true, message: RECORD_DONE_MESSAGE });
  assert.deepEqual(log.requests, [GOOD.url]);
  assert.equal(log.downloads[0].fileName, recordFileName(GOOD));
  assert.equal(log.downloads[0].headers["X-Gyeot-Token"], "t"); // 인증은 헤더로만
  assert.equal(uploaded.length, 1);
  assert.equal(log.removed, 1); // 임시 파일 정리
});

test("saveToRecord(네이티브): 받기나 올리기가 실패해도 임시 파일은 지우고 실패 문구를 돌려준다", async () => {
  const { saveToRecord, RECORD_FAIL_MESSAGE } = await import(MOD);
  const a = fakeNative({ failDownload: true });
  assert.deepEqual(await saveToRecord(GOOD, "ios", { native: a.native, upload: async () => assert.fail("받지 못했으면 올리지 않는다") }), {
    ok: false,
    message: RECORD_FAIL_MESSAGE,
  });
  assert.equal(a.log.removed, 1);
  const b = fakeNative();
  assert.deepEqual(
    await saveToRecord(GOOD, "ios", {
      native: b.native,
      upload: async () => {
        throw new Error("503");
      },
    }),
    { ok: false, message: RECORD_FAIL_MESSAGE },
  );
  assert.equal(b.log.removed, 1);
});

test("saveToRecord(네이티브): 파일 시스템 모듈을 못 불러오면 사용할 수 없다는 문구", async () => {
  const { saveToRecord, RECORD_UNAVAILABLE_MESSAGE } = await import(MOD);
  const result = await saveToRecord(GOOD, "ios", {
    loader: async () => {
      throw new Error("no module");
    },
    upload: async () => assert.fail("올리면 안 된다"),
  });
  assert.deepEqual(result, { ok: false, message: RECORD_UNAVAILABLE_MESSAGE });
});

test("uploadToAssistantRecord: POST /ai-assistant/files 에 multipart 로 보낸다(Content-Type 은 fetch 가 붙인다)", async () => {
  const seen = [];
  globalThis.fetch = async (url, init) => {
    seen.push({ url, init });
    return new Response(JSON.stringify({ id: "r1", filename: "x.jpg", status: "received" }), { status: 201, headers: { "Content-Type": "application/json" } });
  };
  const { uploadToAssistantRecord } = await import("../src/features/family-chat/api.js");
  const form = new FormData();
  form.append("file", new Blob(["x"]), "gabee-chat-a1.jpg");
  const out = await uploadToAssistantRecord(form);
  assert.equal(out.status, "received");
  const call = seen.find((c) => String(c.url).endsWith("/ai-assistant/files"));
  assert.ok(call, "ai-assistant/files 를 불렀다");
  assert.equal(call.init.method, "POST");
  assert.ok(call.init.body instanceof FormData);
  const contentType = Object.entries(call.init.headers ?? {}).find(([k]) => k.toLowerCase() === "content-type");
  assert.equal(contentType, undefined); // multipart boundary 는 fetch 가 붙이므로 직접 넣지 않는다
});
