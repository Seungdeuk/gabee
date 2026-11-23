// PR8: AI 추억 안전성 보강의 앱 쪽 시험 — 이미지 캐시 정리, 사라진 사진 계산, 동의 UI 준비(T31, 고지문 확정 전 수집 꺼짐), 서버와 앱이 공유하는 응답 계약. npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { consentBody, consentUiState, MEMORY_NOTICE_FINAL, REQUIRED_CONSENT_VERSION } from "../src/features/family-memory/consent.js";
import { normalizeCandidates, removedPhotoPaths } from "../src/features/family-memory/memories.js";
import { clearAllImageCaches, evictCachedPhotos } from "../src/shared/imageCacheLogic.js";

const fixture = JSON.parse(readFileSync(new URL("../../../docs/contracts/fixtures/family_memory_candidates.json", import.meta.url), "utf8"));

// ---------- 서버가 같이 검증하는 응답 계약 ----------
test("서버 응답 계약 fixture 는 앱 정리를 통과해 후보 1개(사진 3장)로 보인다", () => {
  const items = normalizeCandidates(fixture);
  assert.equal(items.length, 1);
  assert.equal(items[0].photo_count, 3);
  assert.equal(items[0].representative.attachment_id, "a1b2c3d4e5f6");
  assert.equal(items[0].status, "private");
});

// ---------- 사라진 사진의 캐시 정리 ----------
const photo = (id) => ({ attachment_id: id, thumb_url: `/family-chat/photos/${id}?size=thumb`, photo_url: `/family-chat/photos/${id}` });
const cand = (id, ids) => ({ id, photos: ids.map(photo) });

test("목록에서 사라진 사진만 작은 사진·원본 주소로 돌려준다(남은 사진·다른 후보에 남은 사진은 제외)", () => {
  const prev = [cand("m1", ["a", "b", "c", "d"]), cand("m2", ["x", "y", "z"])];
  const moved = [cand("m1", ["a", "b", "c"]), cand("m2", ["x", "y", "z", "d"])]; // d 는 m2 로 옮겨 가 남아 있다
  assert.deepEqual(removedPhotoPaths(prev, moved), []);
  const gone = removedPhotoPaths(prev, [cand("m1", ["a", "b", "c"]), cand("m2", ["x", "y", "z"])]);
  assert.deepEqual(gone.sort(), ["/family-chat/photos/d", "/family-chat/photos/d?size=thumb"].sort());
});

test("가족 전환·로그아웃으로 목록이 비워지면 이전 목록의 사진이 모두 정리 대상이다", () => {
  const prev = [cand("m1", ["a", "b", "c"])];
  assert.equal(removedPhotoPaths(prev, []).length, 6);
  assert.deepEqual(removedPhotoPaths([], prev), []);
});

test("디스크 캐시 정리는 캐시에 있는 사진만 지우고 없는 사진·실패한 사진이 있어도 계속한다", async () => {
  const cached = new Map([["https://api/x?size=thumb", "/cache/1"], ["https://api/y", "/cache/2"]]);
  const removed = [];
  const image = {
    getCachePathAsync: async (key) => {
      if (key === "https://api/boom") throw new Error("native failure");
      return cached.get(key) ?? null;
    },
  };
  const n = await evictCachedPhotos(["/x?size=thumb", "/y", "/none", "/boom", "/y"], {
    image,
    remove: (p) => removed.push(p),
    toUrl: (path) => `https://api${path}`,
  });
  assert.equal(n, 2);
  assert.deepEqual(removed.sort(), ["/cache/1", "/cache/2"]);
  assert.equal(await evictCachedPhotos([], { image, remove: () => assert.fail(), toUrl: String }), 0);
  const failingRemove = await evictCachedPhotos(["/y"], { image, remove: () => { throw new Error("fs"); }, toUrl: (p) => `https://api${p}` });
  assert.equal(failingRemove, 0); // 파일 삭제가 실패해도 던지지 않는다
});

test("로그아웃 때 메모리·디스크 캐시를 모두 비우고 하나가 실패해도 다음을 한다", async () => {
  const calls = [];
  const ok = await clearAllImageCaches({ clearMemoryCache: async () => (calls.push("m"), true), clearDiskCache: async () => (calls.push("d"), true) });
  assert.deepEqual(ok, { memory: true, disk: true });
  assert.deepEqual(calls, ["m", "d"]);
  const partial = await clearAllImageCaches({ clearMemoryCache: async () => { throw new Error("x"); }, clearDiskCache: async () => true });
  assert.deepEqual(partial, { memory: false, disk: true });
  assert.deepEqual(await clearAllImageCaches({}), { memory: false, disk: false }); // 모듈이 없는 환경
});

// ---------- 동의 UI 준비(T31): 고지문 확정 전에는 수집하지 않는다 ----------
const settings = (over = {}, me = {}) => ({ server_enabled: true, family_enabled: true, can_manage: true, me: { consented: false, retro_consented: false, consent_version: null, ...me }, ...over });

test("고지문 확정 전(기본)에는 동의·활성화·소급 동의 컨트롤이 모두 막히지만 철회·끄기는 가능하다", () => {
  assert.equal(MEMORY_NOTICE_FINAL, false);
  const consented = consentUiState(settings({}, { consented: true, consent_version: 1, retro_consented: true }));
  assert.equal(consented.collecting, false);
  assert.equal(consented.blockedReason, "notice_not_final");
  assert.equal(consented.me.canConsent, false);
  assert.equal(consented.me.canWithdraw, true); // 철회는 언제나
  assert.equal(consented.family.canEnable, false);
  assert.equal(consented.family.canDisable, true); // 끄기는 언제나(관리자)
  assert.equal(consented.retro.canEnable, false);
  assert.equal(consented.retro.canDisable, true);
  assert.equal(consentBody(true), null); // 동의 본문을 만들지 않는다
  assert.deepEqual(consentBody(false), { consent: false }); // 철회 본문은 만든다(버전 없음)
});

test("고지문이 확정되고 서버가 열려 있으면 업로더별 동의·가족 활성화·소급 동의가 구분돼 열린다", () => {
  const on = { noticeFinal: true };
  const fresh = consentUiState(settings(), on);
  assert.equal(fresh.collecting, true);
  assert.equal(fresh.me.canConsent, true);
  assert.equal(fresh.retro.canEnable, false); // 기본 동의 없이는 소급 동의 불가
  const ok = consentUiState(settings({}, { consented: true, consent_version: REQUIRED_CONSENT_VERSION }), on);
  assert.equal(ok.me.canConsent, false);
  assert.equal(ok.me.needsReconsent, false);
  assert.equal(ok.retro.canEnable, true);
  const member = consentUiState(settings({ can_manage: false }), on);
  assert.equal(member.family.canEnable, false); // 구성원은 가족 활성화를 못 한다(업로더 동의와 별개)
  assert.equal(member.me.canConsent, true);
  assert.deepEqual(consentBody(true, on), { consent: true, consent_version: REQUIRED_CONSENT_VERSION });
});

test("동의한 고지문 버전이 현재와 다르면 다시 동의가 필요하고 소급 동의도 막힌다", () => {
  const old = consentUiState(settings({}, { consented: true, consent_version: 0 }), { noticeFinal: true });
  assert.equal(old.me.needsReconsent, true);
  assert.equal(old.me.canConsent, true);
  assert.equal(old.retro.canEnable, false);
});

test("서버가 닫혀 있으면 고지문이 확정돼도 받지 않는다(철회·끄기만)", () => {
  const s = consentUiState(settings({ server_enabled: false }, { consented: true, consent_version: 1 }), { noticeFinal: true });
  assert.equal(s.blockedReason, "server_off");
  assert.equal(s.me.canConsent, false);
  assert.equal(s.me.canWithdraw, true);
});

test("설정 응답이 비어 있어도 안전한 기본값(아무것도 열지 않음)", () => {
  const s = consentUiState(null);
  assert.equal(s.collecting, false);
  assert.equal(s.me.canWithdraw, false);
  assert.equal(s.family.canEnable, false);
});