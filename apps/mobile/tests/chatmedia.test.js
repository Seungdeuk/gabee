// 채팅방 서랍·사진 모음 순수 함수와 API 경로를 시험한다: npm test
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import {
  FAMILY_LEAVE_NOTICE,
  SOON_NOTICE,
  buildDrawerSections,
  buildGridItems,
  drawerMembers,
  drawerTitle,
  emptyMediaText,
  groupByMonth,
  mediaCaption,
  mediaErrorMessage,
  mediaTabs,
  mergeMedia,
  monthLabel,
  canNavigateFromDrawer,
  normalizeCounts,
  resolveRowAction,
  saveFileName,
  thumbPath,
} from "../src/features/family-chat/mediaUtils.js";
import { canLoadMore, initialMediaState, mediaReducer } from "../src/features/family-chat/mediaState.js";

process.env.TZ = "Asia/Seoul"; // 시간대 시험용(UTC+9). node --test 는 파일마다 별도 프로세스라 다른 시험에 영향이 없다
process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "legacy-dev-token";

const realFetch = globalThis.fetch;
beforeEach(() => {
  globalThis.fetch = realFetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
// 기기 시간대와 상관없게 로컬 시각으로 만든 ISO(Z 포함) 문자열
const local = (y, m, d, h = 12, mi = 0, s = 0) => new Date(y, m - 1, d, h, mi, s).toISOString();
const photo = (id, iso) => ({ attachment_id: id, message_id: 1, kind: "image", user_id: "mom", user_name: "엄마", created_at: iso, url: `/family-chat/photos/${id}`, thumb_url: `/family-chat/photos/${id}?size=thumb`, width: 10, height: 10, size_bytes: 1 });

const members = [
  { id: "me", name: "지민", display_name: null, photo_url: null },
  { id: "mom", name: "엄마", display_name: "우리 엄마", photo_url: "/family-group/users/mom/photo?v=1" },
  { id: "dad", name: "아빠", display_name: null, photo_url: null },
];
const room = { name: "우리 가족", members };

test("monthLabel: '2026년 10월', 읽을 수 없으면 빈 글자", () => {
  assert.equal(monthLabel(local(2026, 10, 5)), "2026년 10월");
  assert.equal(monthLabel("모름"), "");
});

test("groupByMonth: 월말·월초·연말 경계에서 나눈다(기기 시간대 기준)", () => {
  const items = [
    photo("a", local(2027, 1, 1, 0, 0, 0)), // 새해 첫 순간
    photo("b", local(2026, 12, 31, 23, 59, 59)), // 연말 마지막 순간
    photo("c", local(2026, 12, 1, 0, 0, 0)),
    photo("d", local(2026, 11, 30, 23, 59, 59)), // 월말
    photo("e", local(2026, 11, 2)),
  ];
  const groups = groupByMonth(items);
  assert.deepEqual(groups.map((g) => g.label), ["2027년 1월", "2026년 12월", "2026년 11월"]);
  assert.deepEqual(groups.map((g) => g.items.map((i) => i.attachment_id)), [["a"], ["b", "c"], ["d", "e"]]);
  assert.deepEqual(groupByMonth(null), []);
});

test("groupByMonth: 같은 달이어도 사이에 다른 달이 끼면 따로 묶는다(서버 순서 유지)", () => {
  const groups = groupByMonth([photo("a", local(2026, 10, 3)), photo("b", local(2026, 9, 3)), photo("c", local(2026, 10, 1))]);
  assert.equal(groups.length, 3);
});

test("buildGridItems: 월 헤더 다음에 3칸씩 줄을 끊고 마지막 줄은 모자랄 수 있다", () => {
  const items = [1, 2, 3, 4].map((n) => photo(`o${n}`, local(2026, 10, 10 - n))).concat([photo("s1", local(2026, 9, 1))]);
  const rows = buildGridItems(items);
  assert.deepEqual(rows.map((r) => r.type), ["header", "row", "row", "header", "row"]);
  assert.deepEqual(rows[1].items.map((i) => i.attachment_id), ["o1", "o2", "o3"]);
  assert.deepEqual(rows[2].items.map((i) => i.attachment_id), ["o4"]);
  assert.equal(rows[3].label, "2026년 9월");
  assert.equal(new Set(rows.map((r) => r.key)).size, rows.length); // key 중복 없음
  assert.deepEqual(buildGridItems([]), []);
});

test("mergeMedia: 이어 붙이되 같은 사진은 한 번만", () => {
  const a = photo("a", local(2026, 10, 3));
  const b = photo("b", local(2026, 10, 2));
  assert.deepEqual(mergeMedia([a], [a, b]).map((i) => i.attachment_id), ["a", "b"]);
  const same = [a];
  assert.equal(mergeMedia(same, [a]), same);
});

test("counts: 숫자로 다듬고 탭 글자는 '사진 N · 파일 N · 동영상 N'", () => {
  assert.deepEqual(normalizeCounts({ image: 12, file: -1, video: "x" }), { image: 12, file: 0, video: 0 });
  assert.deepEqual(normalizeCounts(null), { image: 0, file: 0, video: 0 });
  assert.deepEqual(mediaTabs({ image: 12, file: 0, video: 3 }).map((t) => t.label), ["사진 12", "파일 0", "동영상 3"]);
  assert.deepEqual(mediaTabs(undefined).map((t) => t.label), ["사진 0", "파일 0", "동영상 0"]);
});

test("빈 상태·오류 문구는 종류와 상태에 따라 다르다", () => {
  assert.equal(emptyMediaText("image"), "아직 공유된 사진이 없어요");
  assert.match(emptyMediaText("file"), /파일은 보낼 수 없어요.*사진부터/);
  assert.match(emptyMediaText("video"), /동영상은 보낼 수 없어요.*사진부터/);
  assert.equal(mediaErrorMessage({ status: 404 }), "채팅방을 찾을 수 없어요");
  assert.equal(mediaErrorMessage({ status: 429 }), "잠시 후 다시 시도해 주세요");
  assert.equal(mediaErrorMessage({ status: 0 }), "서버에 연결하지 못했어요");
  assert.equal(mediaErrorMessage(null), "사진을 불러오지 못했어요");
});

test("mediaCaption: 보낸 사람(별명 우선)과 날짜·시각", () => {
  const item = photo("a", local(2026, 10, 24, 15, 20));
  assert.equal(mediaCaption(item, (id) => (id === "mom" ? "우리 엄마" : undefined)), "우리 엄마 · 2026년 10월 24일 오후 3:20");
  assert.equal(mediaCaption(item), "엄마 · 2026년 10월 24일 오후 3:20");
  assert.equal(mediaCaption({ created_at: "??" }), "가족");
});

test("saveFileName: 시각과 id 앞부분으로 만들고 이상한 글자는 뺀다", () => {
  assert.equal(saveFileName(photo("ab12-cd34ef/..", local(2026, 10, 4, 9, 5, 7))), "gabee-20261004-090507-ab12cd34.jpg");
  assert.equal(saveFileName({ attachment_id: "x1", created_at: "??" }), "gabee-photo-x1.jpg");
  assert.equal(saveFileName({}), "gabee-photo.jpg");
});

test("drawerTitle·drawerMembers: 가족 전체방은 가족 이름과 전원(나 먼저), 1:1 은 상대 이름과 상대 한 명", () => {
  assert.equal(drawerTitle({ direct: false, room }), "우리 가족");
  assert.equal(drawerTitle({ direct: false, room: null }), "가족 채팅");
  assert.equal(drawerTitle({ direct: true, room, peerId: "mom" }), "우리 엄마");
  assert.equal(drawerTitle({ direct: true, room, peerId: "gone" }), "1:1 대화");

  const family = drawerMembers({ direct: false, room, myId: "dad" });
  assert.equal(family.heading, "가족 구성원 3명");
  assert.deepEqual(family.members.map((m) => m.name), ["아빠", "지민", "우리 엄마"]);
  assert.equal(family.members[2].photoUrl, "/family-group/users/mom/photo?v=1");

  const direct = drawerMembers({ direct: true, room, peerId: "mom", myId: "me" });
  assert.equal(direct.heading, "대화 상대");
  assert.deepEqual(direct.members.map((m) => m.id), ["mom"]);
  assert.deepEqual(drawerMembers({ direct: false, room: null }).members, []);
});

const flat = (sections) => sections.flatMap((s) => s.rows);
const byKey = (sections, key) => flat(sections).find((r) => r.key === key);

test("서랍 행: 가족 전체방은 두 구역에 10행, 동작하는 행은 사진·동영상과 구성원 초대·관리뿐", () => {
  const sections = buildDrawerSections({ direct: false });
  assert.deepEqual(sections.map((s) => s.title), ["채팅 관리", "채팅방 설정"]);
  assert.deepEqual(sections[0].rows.map((r) => r.title), ["대화 내용 검색", "고정 메시지", "사진 · 동영상", "공유 문서", "가족 일정 · 할 일"]);
  assert.deepEqual(sections[1].rows.map((r) => r.title), ["알림 설정", "구성원 초대 · 관리", "AI · 개인정보 보호 설정", "채팅방 정보 수정", "채팅방 나가기"]);
  const open = flat(sections).filter((r) => r.state === "open").map((r) => r.key);
  assert.deepEqual(open, ["media", "invite", "leave"]); // leave 는 배지 없이 안내를 보인다
  for (const key of ["search", "pins", "docs", "todos", "notifications", "privacy", "edit"]) assert.equal(byKey(sections, key).state, "soon", key);
  assert.equal(byKey(sections, "media").subtitle, "채팅방에 공유된 미디어");
  assert.equal(byKey(sections, "leave").danger, true);
});

test("서랍 행: 검색은 onOpenSearch 가 연결됐을 때만 동작한다", () => {
  assert.equal(byKey(buildDrawerSections({ direct: false }), "search").state, "soon");
  assert.equal(byKey(buildDrawerSections({ direct: false, searchReady: true }), "search").state, "open");
  assert.equal(byKey(buildDrawerSections({ direct: true, searchReady: true }), "search").state, "open");
});

test("서랍 행: 1:1 방은 공유 문서·구성원 초대·AI 설정을 숨기고 나머지는 같다", () => {
  const sections = buildDrawerSections({ direct: true });
  const keys = flat(sections).map((r) => r.key);
  assert.deepEqual(keys, ["search", "pins", "media", "todos", "notifications", "edit", "leave"]);
  assert.equal(byKey(sections, "media").state, "open");
});

test("나가기 안내: 가족 전체방은 나갈 수 없다고, 1:1 은 준비 중이라고 알린다", () => {
  assert.equal(byKey(buildDrawerSections({ direct: false }), "leave").notice, FAMILY_LEAVE_NOTICE);
  assert.equal(FAMILY_LEAVE_NOTICE, "가족 채팅방은 나갈 수 없어요");
  assert.equal(byKey(buildDrawerSections({ direct: true }), "leave").notice, SOON_NOTICE);
  assert.equal(SOON_NOTICE, "준비 중이에요");
  assert.equal(byKey(buildDrawerSections({ direct: false }), "pins").notice, undefined);
});

test("API listMedia: 쿼리 모양, 가족 전체방은 room_id 없음, limit 범위, 커서", async () => {
  const urls = [];
  const page = { items: [photo("a", local(2026, 10, 3))], next_before_id: 17, counts: { image: 5, file: 0, video: 0 } };
  globalThis.fetch = async (url) => {
    urls.push(String(url));
    return json(200, page);
  };
  const api = await import("../src/features/family-chat/api.js");

  const first = await api.listMedia();
  await api.listMedia({ roomId: "r 1", kind: "video", limit: 500, beforeId: 17 });
  await api.listMedia({ kind: "weird", limit: 0, beforeId: 0 });

  assert.match(urls[0], /\/family-chat\/media\?kind=image&limit=40$/);
  assert.match(urls[1], /\/family-chat\/media\?room_id=r%201&kind=video&limit=100&before_id=17$/);
  assert.match(urls[2], /\/family-chat\/media\?kind=image&limit=40$/); // 0 은 서버가 받지 않아 보내지 않는다
  assert.equal(first.next_before_id, 17);
  assert.deepEqual(normalizeCounts(first.counts), { image: 5, file: 0, video: 0 });
});

test("API listMedia: 404·429 는 ApiError 상태로 올라오고 문구로 바뀐다", async () => {
  const api = await import("../src/features/family-chat/api.js");
  for (const [status, text] of [[404, "채팅방을 찾을 수 없어요"], [429, "잠시 후 다시 시도해 주세요"]]) {
    globalThis.fetch = async () => json(status, { code: "x", message: "m" });
    await assert.rejects(
      () => api.listMedia({ roomId: "r1" }),
      (e) => {
        assert.equal(e.status, status);
        assert.equal(mediaErrorMessage(e), text);
        return true;
      },
    );
  }
});

test("savePhoto: 웹은 낯선 경로를 받지 않는다(인증 헤더가 낯선 주소로 나가지 않는다)", async () => {
  let called = 0;
  globalThis.fetch = async () => {
    called += 1;
    return json(200, {});
  };
  const { savePhoto, SAVE_FAIL_MESSAGE } = await import("../src/features/family-chat/savePhoto.js");
  assert.deepEqual(await savePhoto({ url: "https://evil.test/x.jpg" }, "a.jpg", "web"), { ok: false, message: SAVE_FAIL_MESSAGE });
  assert.equal(called, 0);
});

test("saveTarget·permissionOutcome·permissionMessage: 분기와 권한 해석", async () => {
  const m = await import("../src/features/family-chat/savePhoto.js");
  assert.equal(m.saveTarget("web"), "web");
  assert.equal(m.saveTarget("ios"), "native");
  assert.equal(m.saveTarget("android"), "native");
  assert.equal(m.permissionOutcome({ granted: true, canAskAgain: true }), "granted");
  assert.equal(m.permissionOutcome({ granted: false, canAskAgain: true }), "denied");
  assert.equal(m.permissionOutcome({ granted: false, canAskAgain: false }), "blocked");
  assert.equal(m.permissionOutcome(undefined), "denied");
  assert.equal(m.permissionMessage("granted"), "");
  assert.equal(m.permissionMessage("blocked"), "사진 저장 권한이 필요해요. 설정에서 허용해 주세요");
});

/**
 * 네이티브 저장용 가짜 의존성. 호출 순서와 임시 파일 삭제 횟수를 기록한다.
 * @param {object} [over] 덮어쓸 의존성
 * @returns {{ deps: object, log: { calls: string[], removed: number, saved: string[], downloaded: { url: string, headers: object, fileName: string }[] } }}
 */
function fakeNative(over = {}) {
  const log = { calls: [], removed: 0, saved: [], downloaded: [] };
  const deps = {
    photoRequest: async (path) => {
      log.calls.push("request");
      return { url: `http://api.test${path}`, headers: { "X-Gyeot-Token": "t" } };
    },
    getPermission: async () => {
      log.calls.push("get");
      return { granted: false, canAskAgain: true };
    },
    requestPermission: async () => {
      log.calls.push("ask");
      return { granted: true, canAskAgain: true };
    },
    saveToLibrary: async (uri) => {
      log.calls.push("save");
      log.saved.push(uri);
    },
    download: async (url, headers, fileName) => {
      log.calls.push("download");
      log.downloaded.push({ url, headers, fileName });
      return {
        fetch: async () => {
          log.calls.push("fetch");
          return "file:///cache/tmp.jpg";
        },
        remove: () => {
          log.removed += 1;
        },
      };
    },
    ...over,
  };
  return { deps, log };
}

test("savePhoto 네이티브 성공: 권한 요청 -> 헤더로 받기 -> 저장, 임시 파일 삭제", async () => {
  const { savePhoto } = await import("../src/features/family-chat/savePhoto.js");
  const { deps, log } = fakeNative();
  const r = await savePhoto({ url: "/family-chat/photos/a1" }, "a.jpg", "ios", deps);
  assert.deepEqual(r, { ok: true, message: "저장했어요" });
  assert.deepEqual(log.calls, ["get", "ask", "request", "download", "fetch", "save"]); // 헤더(request)는 권한 뒤에
  assert.deepEqual(log.downloaded, [{ url: "http://api.test/family-chat/photos/a1", headers: { "X-Gyeot-Token": "t" }, fileName: "a.jpg" }]);
  assert.deepEqual(log.saved, ["file:///cache/tmp.jpg"]);
  assert.equal(log.removed, 1);
});

test("savePhoto 네이티브: 이미 허용이면 다시 묻지 않는다", async () => {
  const { savePhoto } = await import("../src/features/family-chat/savePhoto.js");
  const { deps, log } = fakeNative({ getPermission: async () => ({ granted: true, canAskAgain: true }) });
  assert.equal((await savePhoto({ url: "/family-chat/photos/a1" }, "a.jpg", "android", deps)).ok, true);
  assert.ok(!log.calls.includes("ask"));
});

test("savePhoto 네이티브: 권한 거절·영구 거절이면 받지도 저장하지도 않고 안내한다", async () => {
  const { savePhoto, SAVE_DENIED_MESSAGE } = await import("../src/features/family-chat/savePhoto.js");
  for (const resp of [{ granted: false, canAskAgain: true }, { granted: false, canAskAgain: false }]) {
    const { deps, log } = fakeNative({ requestPermission: async () => resp });
    const r = await savePhoto({ url: "/family-chat/photos/a1" }, "a.jpg", "ios", deps);
    assert.deepEqual(r, { ok: false, message: SAVE_DENIED_MESSAGE });
    assert.ok(!log.calls.includes("download") && !log.calls.includes("save"));
    assert.equal(log.removed, 0);
  }
  // 영구 거절이면 요청 창을 다시 띄우지 않는다
  const { deps, log } = fakeNative({ getPermission: async () => ({ granted: false, canAskAgain: false }) });
  assert.equal((await savePhoto({ url: "/family-chat/photos/a1" }, "a.jpg", "ios", deps)).message, SAVE_DENIED_MESSAGE);
  assert.ok(!log.calls.includes("ask"));
});

test("savePhoto 네이티브: 받기·저장 실패여도 임시 파일은 지운다", async () => {
  const { savePhoto, SAVE_FAIL_MESSAGE } = await import("../src/features/family-chat/savePhoto.js");
  const dl = fakeNative();
  dl.deps.download = async () => ({
    fetch: async () => {
      throw new Error("net");
    },
    remove: () => {
      dl.log.removed += 1;
    },
  });
  assert.deepEqual(await savePhoto({ url: "/family-chat/photos/a1" }, "a.jpg", "ios", dl.deps), { ok: false, message: SAVE_FAIL_MESSAGE });
  assert.equal(dl.log.removed, 1);
  assert.ok(!dl.log.calls.includes("save"));

  const sv = fakeNative({
    saveToLibrary: async () => {
      throw new Error("disk");
    },
  });
  assert.deepEqual(await savePhoto({ url: "/family-chat/photos/a1" }, "a.jpg", "android", sv.deps), { ok: false, message: SAVE_FAIL_MESSAGE });
  assert.equal(sv.log.removed, 1);

  // 지우기 자체가 실패해도 성공 결과는 그대로
  const rm = fakeNative();
  const base = rm.deps.download;
  rm.deps.download = async (...a) => {
    const job = await base(...a);
    return {
      ...job,
      remove: () => {
        throw new Error("rm");
      },
    };
  };
  assert.equal((await savePhoto({ url: "/family-chat/photos/a1" }, "a.jpg", "ios", rm.deps)).ok, true);
});

test("savePhoto 네이티브: 낯선 경로는 권한·헤더·네트워크 전에 거절한다(경로 검사는 실제 photoPath)", async () => {
  const { savePhoto, SAVE_FAIL_MESSAGE } = await import("../src/features/family-chat/savePhoto.js");
  const { deps, log } = fakeNative();
  assert.deepEqual(await savePhoto({ url: "https://evil.test/x.jpg" }, "a.jpg", "ios", deps), { ok: false, message: SAVE_FAIL_MESSAGE });
  assert.deepEqual(await savePhoto({ url: "/family-chat/photos/../x" }, "a.jpg", "ios", deps), { ok: false, message: SAVE_FAIL_MESSAGE });
  assert.deepEqual(log.calls, []);
  assert.deepEqual(await savePhoto(undefined, "a.jpg", "ios", deps), { ok: false, message: SAVE_FAIL_MESSAGE });
});

test("savePhoto 네이티브: 권한 API 가 던지면(모듈 없음·Expo Go 제한) 앱이 죽지 않고 안내한다", async () => {
  const { savePhoto, SAVE_UNAVAILABLE_MESSAGE } = await import("../src/features/family-chat/savePhoto.js");
  const { deps, log } = fakeNative({
    getPermission: async () => {
      throw new Error("native module missing");
    },
  });
  assert.deepEqual(await savePhoto({ url: "/family-chat/photos/a1" }, "a.jpg", "ios", deps), { ok: false, message: SAVE_UNAVAILABLE_MESSAGE });
  assert.ok(!log.calls.includes("download"));
  assert.equal(SAVE_UNAVAILABLE_MESSAGE, "이 환경에서는 저장할 수 없어요");
});

test("savePhoto 네이티브: 모듈을 불러오지 못하면(loader 실패) 던지지 않고 안내한다", async () => {
  const { savePhotoNative, importNativeModules, SAVE_UNAVAILABLE_MESSAGE } = await import("../src/features/family-chat/savePhoto.js");
  const r = await savePhotoNative("/family-chat/photos/a1", "a.jpg", undefined, async () => {
    throw new Error("Cannot find module");
  });
  assert.deepEqual(r, { ok: false, message: SAVE_UNAVAILABLE_MESSAGE });
  // node 에는 실제 expo 네이티브 모듈이 없어 진짜 import 도 실패한다(위 결과가 이 실패 때문임을 확인)
  await assert.rejects(importNativeModules());
  assert.deepEqual(await savePhotoNative("/family-chat/photos/a1", "a.jpg"), { ok: false, message: SAVE_UNAVAILABLE_MESSAGE });
});

test("서버 시각에 시간대 표시가 없으면 UTC 로 읽어 월 경계를 계산한다(기기 UTC+9)", () => {
  // chatUtils.parseTime 규칙과 같다: Z·오프셋이 없으면 UTC
  assert.equal(new Date(2026, 9, 1).getTimezoneOffset(), -540); // 시간대 설정이 적용됐는지
  assert.equal(monthLabel("2026-10-31T14:59:59"), "2026년 10월"); // 한국 23:59:59
  assert.equal(monthLabel("2026-10-31T15:00:00"), "2026년 11월"); // 한국 11월 1일 00:00
  assert.equal(monthLabel("2026-10-31T16:00:00"), "2026년 11월");
  assert.equal(monthLabel("2026-12-31T15:00:00"), "2027년 1월"); // 연말 경계
  assert.equal(monthLabel("2026-10-31T16:00:00+09:00"), "2026년 10월"); // 오프셋이 있으면 그대로
  const groups = groupByMonth([photo("a", "2026-10-31T16:00:00"), photo("b", "2026-10-31T14:00:00")]);
  assert.deepEqual(groups.map((g) => g.label), ["2026년 11월", "2026년 10월"]);
  assert.equal(saveFileName({ attachment_id: "z", created_at: "2026-10-31T16:00:00" }), "gabee-20261101-010000-z.jpg");
});

test("resolveRowAction·canNavigateFromDrawer: 이동은 한 번만, 닫히는 중에는 무시", () => {
  const sections = buildDrawerSections({ direct: false });
  const row = (key) => flat(sections).find((r) => r.key === key);
  assert.deepEqual(resolveRowAction(row("media")), { type: "media" });
  assert.deepEqual(resolveRowAction(row("invite")), { type: "invite" });
  assert.deepEqual(resolveRowAction(row("search")), { type: "notice", text: "준비 중이에요" });
  assert.deepEqual(resolveRowAction(byKey(buildDrawerSections({ direct: false, searchReady: true }), "search")), { type: "search" });
  assert.deepEqual(resolveRowAction(row("leave")), { type: "notice", text: FAMILY_LEAVE_NOTICE });
  assert.equal(canNavigateFromDrawer({ visible: true, locked: false }), true);
  assert.equal(canNavigateFromDrawer({ visible: true, locked: true }), false); // 이미 한 번 눌렀다
  assert.equal(canNavigateFromDrawer({ visible: false, locked: false }), false); // 닫히는 중
  let locked = false;
  let moves = 0;
  for (let i = 0; i < 2; i += 1) {
    if (canNavigateFromDrawer({ visible: true, locked })) {
      locked = true;
      moves += 1;
    }
  }
  assert.equal(moves, 1); // 연속 두 번 눌러도 이동은 한 번
});

test("thumbPath: thumb_url 이 null 이면 원본으로 대신한다", () => {
  assert.equal(thumbPath({ thumb_url: null, url: "/family-chat/photos/a" }), "/family-chat/photos/a");
  assert.equal(thumbPath({ thumb_url: "/family-chat/photos/a?size=thumb", url: "/family-chat/photos/a" }), "/family-chat/photos/a?size=thumb");
});

const page = (ids, next, counts = { image: 9, file: 0, video: 0 }) => ({ items: ids.map((id) => photo(id, local(2026, 10, 3))), next_before_id: next, counts });
const run = (state, ...actions) => actions.reduce(mediaReducer, state);

test("mediaReducer: 첫 쪽 → 다음 쪽 이어 붙이기, 마지막 쪽에서 커서가 null", () => {
  let s = run(initialMediaState(), { type: "start", seq: 1 }, { type: "firstOk", seq: 1, page: page(["a", "b"], 5) });
  assert.equal(s.status, "ready");
  assert.equal(canLoadMore(s), true);
  s = run(s, { type: "moreStart", seq: 1 });
  assert.equal(s.loadingMore, true);
  assert.equal(canLoadMore(s), false); // 받는 중에는 또 부르지 않는다
  s = run(s, { type: "moreOk", seq: 1, page: page(["b", "c"], null) });
  assert.deepEqual(s.items.map((i) => i.attachment_id), ["a", "b", "c"]);
  assert.equal(canLoadMore(s), false);
  assert.equal(s.counts.image, 9);
});

test("mediaReducer: 다음 쪽이 실패해도 목록은 남고, 다시 시도하면 오류 문구가 지워진다", () => {
  let s = run(initialMediaState(), { type: "start", seq: 1 }, { type: "firstOk", seq: 1, page: page(["a"], 7) }, { type: "moreStart", seq: 1 }, { type: "moreFail", seq: 1, error: { status: 429 } });
  assert.equal(s.items.length, 1);
  assert.equal(s.error, "잠시 후 다시 시도해 주세요");
  assert.equal(s.status, "ready");
  assert.equal(canLoadMore(s), true); // 다시 시도 가능
  s = run(s, { type: "moreStart", seq: 1 });
  assert.equal(s.error, "");
});

test("mediaReducer: kind·방이 바뀌면 옛 응답(첫 쪽·다음 쪽·실패)은 무시된다", () => {
  let s = run(initialMediaState(), { type: "start", seq: 1 }, { type: "firstOk", seq: 1, page: page(["a"], 3, { image: 4, file: 0, video: 0 }) }, { type: "moreStart", seq: 1 });
  s = run(s, { type: "start", seq: 2 }); // 탭을 바꿨다
  assert.equal(s.status, "loading");
  assert.deepEqual(s.items, []);
  assert.equal(s.counts.image, 4); // 탭 글자는 남는다
  const stale = [
    { type: "moreOk", seq: 1, page: page(["old"], null) },
    { type: "firstOk", seq: 1, page: page(["old"], null) },
    { type: "moreFail", seq: 1, error: { status: 404 } },
    { type: "firstFail", seq: 1, error: { status: 404 } },
  ];
  for (const action of stale) assert.equal(mediaReducer(s, action), s);
  s = run(s, { type: "firstOk", seq: 2, page: page(["new"], null) });
  assert.deepEqual(s.items.map((i) => i.attachment_id), ["new"]);
});

test("mediaReducer: 첫 쪽 실패는 오류 상태이고 다시 시도(start)로 로딩부터 다시 한다", () => {
  let s = run(initialMediaState(), { type: "start", seq: 1 }, { type: "firstFail", seq: 1, error: { status: 0 } });
  assert.equal(s.status, "error");
  assert.equal(s.error, "서버에 연결하지 못했어요");
  assert.equal(canLoadMore(s), false);
  s = run(s, { type: "start", seq: 2 });
  assert.equal(s.status, "loading");
  assert.equal(s.error, "");
});

test("savePhoto 웹 성공: blob 주소로 a 태그를 눌러 내려받고, 주소 해제를 예약한다", async () => {
  const realDoc = globalThis.document;
  const realCreate = URL.createObjectURL;
  const realRevoke = URL.revokeObjectURL;
  const realTimeout = globalThis.setTimeout;
  const log = { revoked: [], clicks: [], appended: 0, removed: 0, delay: 0 };
  const link = {
    click() {
      log.clicks.push({ href: link.href, download: link.download });
    },
    remove() {
      log.removed += 1;
    },
  };
  globalThis.document = {
    createElement: () => link,
    body: {
      appendChild() {
        log.appended += 1;
      },
    },
  };
  URL.createObjectURL = () => "blob:fake-1";
  URL.revokeObjectURL = (u) => log.revoked.push(u);
  let revoke;
  globalThis.setTimeout = (fn, ms) => {
    revoke = fn;
    log.delay = ms;
    return 0;
  };
  let auth;
  globalThis.fetch = async (url, init) => {
    auth = { url: String(url), headers: init.headers };
    return new Response(new Blob(["jpg"]), { status: 200 });
  };
  try {
    const { savePhoto } = await import("../src/features/family-chat/savePhoto.js");
    const item = photo("a1", local(2026, 10, 4, 9, 5, 7));
    const result = await savePhoto(item, saveFileName(item), "web");
    assert.deepEqual(result, { ok: true, message: "저장했어요" });
    assert.equal(auth.url, "http://api.test/family-chat/photos/a1"); // 원본 경로
    assert.equal(auth.headers["X-Gyeot-Token"], "legacy-dev-token"); // 인증은 헤더로, 주소에는 없다
    assert.deepEqual(log.clicks, [{ href: "blob:fake-1", download: "gabee-20261004-090507-a1.jpg" }]);
    assert.equal(log.appended, 1);
    assert.equal(log.removed, 1);
    assert.deepEqual(log.revoked, []); // 바로 해제하지 않는다
    assert.ok(log.delay >= 1000);
    revoke();
    assert.deepEqual(log.revoked, ["blob:fake-1"]);
  } finally {
    globalThis.document = realDoc;
    URL.createObjectURL = realCreate;
    URL.revokeObjectURL = realRevoke;
    globalThis.setTimeout = realTimeout;
  }
});
