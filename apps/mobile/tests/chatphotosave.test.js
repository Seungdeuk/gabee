// 사진 저장(네이티브)의 서버 호출부(photoDownloadRequest)와 expo 연결부(loadNativeDeps)를 시험한다: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

let fetchCalls = 0;
globalThis.fetch = async () => {
  fetchCalls += 1;
  return new Response("{}", { status: 200 });
};

test("photoDownloadRequest: 서버가 준 사진 경로만 받고, 토큰은 주소가 아니라 헤더에만 둔다", async () => {
  const { photoDownloadRequest } = await import("../src/features/family-chat/api.js");
  for (const path of ["/family-chat/photos/a1", "/family-chat/photos/a1?size=thumb"]) {
    const req = await photoDownloadRequest(path);
    assert.equal(req.url, `http://api.test${path}`);
    assert.equal(req.headers["X-Gyeot-Token"], "legacy-dev-token");
    assert.ok(!req.url.includes("legacy-dev-token") && !/token/i.test(req.url));
  }
  assert.equal(fetchCalls, 0); // 주소·헤더를 만들 뿐 네트워크는 쓰지 않는다
});

test("photoDownloadRequest: 낯선 경로는 던지고 네트워크·헤더를 쓰지 않는다", async () => {
  const { photoDownloadRequest } = await import("../src/features/family-chat/api.js");
  const bad = [
    "https://evil.test/family-chat/photos/a1",
    "//evil.test/family-chat/photos/a1",
    "/family-chat/photos/../secret",
    "/family-chat/photos/a/b",
    "/family-chat/photos/a1?token=x",
    "/other/path",
    "",
    undefined,
    null,
    42,
  ];
  for (const path of bad) {
    await assert.rejects(photoDownloadRequest(path), /photo_unavailable/, String(path));
  }
  assert.equal(fetchCalls, 0);
});

/** 시험용 가짜 expo 모듈 한 벌과 호출 기록. */
function fakeModules() {
  const log = { permissions: [], saved: [], downloads: [], deleted: [], files: [] };
  class File {
    constructor(dir, name) {
      this.uri = `${dir.uri}/${name}`;
      this.exists = true;
      log.files.push(this);
    }
    delete() {
      log.deleted.push(this.uri);
    }
    static async downloadFileAsync(url, target, options) {
      log.downloads.push({ url, target, options });
      return { uri: `${target.uri}#done` };
    }
  }
  const MediaLibrary = {
    getPermissionsAsync: async (w) => (log.permissions.push(["get", w]), { granted: true }),
    requestPermissionsAsync: async (w) => (log.permissions.push(["ask", w]), { granted: true }),
    saveToLibraryAsync: async (uri) => void log.saved.push(uri),
  };
  return { log, modules: { MediaLibrary, FileSystem: { File, Paths: { cache: { uri: "file:///cache" } } } } };
}

test("loadNativeDeps: 쓰기 전용 권한, 헤더 전달·idempotent 다운로드, 결과 uri, 저장 연결", async () => {
  const { loadNativeDeps } = await import("../src/features/family-chat/savePhoto.js");
  const { log, modules } = fakeModules();
  const deps = await loadNativeDeps(modules, { now: () => 1000, random: () => 0.5 });
  await deps.getPermission();
  await deps.requestPermission();
  assert.deepEqual(log.permissions, [["get", true], ["ask", true]]);

  const job = await deps.download("http://api.test/family-chat/photos/a1", { "X-Gyeot-Token": "t" }, "gabee-1.jpg");
  const uri = await job.fetch();
  assert.equal(log.downloads.length, 1);
  assert.equal(log.downloads[0].url, "http://api.test/family-chat/photos/a1");
  assert.deepEqual(log.downloads[0].options, { headers: { "X-Gyeot-Token": "t" }, idempotent: true });
  assert.ok(log.downloads[0].target.uri.startsWith("file:///cache/gabee-save-"));
  assert.equal(uri, `${log.downloads[0].target.uri}#done`); // file.uri 를 돌려준다
  await deps.saveToLibrary(uri);
  assert.deepEqual(log.saved, [uri]);
});

test("loadNativeDeps: 임시 파일은 있을 때만 지우고, 작업마다 이름이 달라 동시 저장이 충돌하지 않는다", async () => {
  const { loadNativeDeps } = await import("../src/features/family-chat/savePhoto.js");
  const { log, modules } = fakeModules();
  let n = 0;
  const deps = await loadNativeDeps(modules, { now: () => 1000, random: () => (n += 1) / 10 });
  const a = await deps.download("u", {}, "same.jpg");
  const b = await deps.download("u", {}, "same.jpg");
  await a.fetch();
  await b.fetch();
  const [ta, tb] = log.downloads.map((d) => d.target.uri);
  assert.notEqual(ta, tb);
  assert.ok(/^file:\/\/\/cache\/gabee-save-[\w-]+\.jpg$/.test(ta)); // 슬래시 등 쓸 수 없는 글자 없음

  a.remove();
  assert.deepEqual(log.deleted, [ta]); // 상대 파일은 건드리지 않는다
  log.files[1].exists = false; // b 의 파일이 이미 없으면 delete 를 부르지 않는다
  b.remove();
  assert.deepEqual(log.deleted, [ta]);
});

test("loadNativeDeps: 파일명에 이상한 글자가 있어도 경로가 폴더 밖으로 나가지 않는다", async () => {
  const { loadNativeDeps } = await import("../src/features/family-chat/savePhoto.js");
  const { log, modules } = fakeModules();
  const deps = await loadNativeDeps(modules);
  await (await deps.download("u", {}, "../../x/y.jpg")).fetch();
  assert.ok(!log.downloads[0].target.uri.slice("file:///cache/".length).includes("/"));
});
