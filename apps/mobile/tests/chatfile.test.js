// 채팅 문서 파일 첨부(앱): 형식·크기 검사, 크기 문구, + 메뉴 항목, 파일 판별, 요청 모양, 저장 안내 문구: npm test
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

process.env.EXPO_PUBLIC_API_URL = "http://api.test";
process.env.EXPO_PUBLIC_DEV_TOKEN = "secret-dev-token";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

const u = await import("../src/features/family-chat/fileUtils.js");
const { previewText } = await import("../src/features/family-chat/chatUtils.js");
const { replyLine, replyPreview } = await import("../src/features/family-chat/messageActions.js");
const { sendFile, fileDownloadRequest } = await import("../src/features/family-chat/api.js");

const fileAtt = { id: "f1", kind: "file", url: "/family-chat/files/f1", thumb_url: null, width: null, height: null, filename: "계획서.pdf", size_bytes: 1258291, content_type: "application/pdf" };

test("허용 확장자와 크기 검사", () => {
  for (const name of ["a.pdf", "a.DOCX", "b.xls", "c.pptx", "d.hwp", "e.hwpx", "f.txt", "g.csv"]) assert.equal(u.validateChatFile({ name, size: 10 }).ok, true, name);
  assert.equal(u.validateChatFile({ name: "a.exe", size: 10 }).code, "unsupported_file_type");
  assert.equal(u.validateChatFile({ name: "noext", size: 10 }).code, "unsupported_file_type");
  assert.equal(u.validateChatFile({ name: "a.pdf", size: u.MAX_CHAT_FILE_BYTES }).ok, true);
  const big = u.validateChatFile({ name: "a.pdf", size: u.MAX_CHAT_FILE_BYTES + 1 });
  assert.equal(big.code, "file_too_large");
  assert.equal(big.message, u.FILE_TOO_LARGE_MESSAGE);
  assert.equal(u.validateChatFile({ name: "a.pdf", size: 0 }).code, "file_empty");
  assert.equal(u.validateChatFile({ name: "a.pdf" }).ok, true); // 크기를 모르면 서버에 맡긴다
});

test("크기 문구", () => {
  assert.equal(u.formatFileSize(512), "512B");
  assert.equal(u.formatFileSize(348160), "340KB");
  assert.equal(u.formatFileSize(1258291), "1.2MB");
  assert.equal(u.formatFileSize(null), "");
  assert.equal(u.formatFileSize(-1), "");
});

test("+ 메뉴 항목은 일정·정산·안부 순서", () => {
  assert.deepEqual(u.PLUS_MENU_ITEMS.map((i) => i.label), ["사진", "파일", "일정", "정산", "안부"]);
  assert.equal(u.isPlusFile("file"), true);
  assert.equal(u.isPlusFile("photo"), false);
  assert.equal(u.isPlusPhoto("photo"), true);
  assert.equal(u.isPlusPhoto("schedule"), false);
  assert.ok(u.PLUS_MENU_ITEMS.every((i) => i.icon && i.key));
  assert.equal(u.PLUS_SOON_NOTICE, "준비 중이에요");
});

test("파일 메시지 판별: kind 없음·image 는 사진(하위 호환)", () => {
  assert.equal(u.isFileMessage({ attachment: fileAtt }), true);
  assert.equal(u.isFileMessage({ attachment: { id: "a", url: "/family-chat/photos/a" } }), false);
  assert.equal(u.isFileMessage({ attachment: { id: "a", kind: "image" } }), false);
  assert.equal(u.isFileMessage({ attachment: null }), false);
});

test("미리보기: 파일은 '파일', 사진은 '사진', 답장 인용도 같다", () => {
  const m = { id: 1, user_id: "mom", user_name: "엄마", text: "", attachment: fileAtt };
  assert.equal(previewText(m, "me"), "파일");
  assert.equal(previewText({ ...m, user_id: "me" }, "me"), "나: 파일");
  assert.equal(previewText({ ...m, attachment: { id: "a", kind: "image" } }, "me"), "사진");
  assert.equal(replyLine(replyPreview(m)), "파일");
  assert.equal(replyLine(replyPreview({ ...m, attachment: { id: "a" } })), "사진");
});

test("파일 보내기 오류 문구", () => {
  assert.equal(u.fileSendErrorMessage({ status: 413 }), u.FILE_TOO_LARGE_MESSAGE);
  assert.equal(u.fileSendErrorMessage({ code: "unsupported_file_type" }), u.FILE_TYPE_MESSAGE);
  assert.equal(u.fileSendErrorMessage({ status: 415 }), u.FILE_TYPE_MESSAGE);
  assert.match(u.fileSendErrorMessage({ status: 429 }), /너무 자주/);
  assert.equal(u.fileSendErrorMessage(new Error("network")), u.FILE_SEND_FAIL_MESSAGE);
});

test("sendFile: POST /family-chat/files, multipart file + room_id, 응답은 그대로", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify({ id: 9, attachment: fileAtt }), { status: 201, headers: { "Content-Type": "application/json" } });
  };
  const blob = new Blob(["hello"], { type: "text/plain" });
  const saved = await sendFile({ uri: "blob:x", file: blob, name: "메모.txt" }, "room-1");
  assert.equal(calls[0].url, "http://api.test/family-chat/files");
  assert.equal(calls[0].init.method, "POST");
  assert.ok(calls[0].init.body instanceof FormData);
  assert.equal(calls[0].init.body.get("room_id"), "room-1");
  assert.equal(calls[0].init.body.get("file").name, "메모.txt");
  assert.equal(calls[0].init.headers?.["Content-Type"], undefined); // boundary 는 fetch 가 붙인다
  assert.equal(saved.attachment.kind, "file");
  await sendFile({ uri: "blob:x", file: blob, name: "a.csv" }, null);
  assert.equal(calls[1].init.body.has("room_id"), false); // 가족 전체방은 room_id 를 보내지 않는다
});

test("파일 받기 요청: 우리 경로만, 인증 헤더 포함", async () => {
  const r = await fileDownloadRequest("/family-chat/files/f1");
  assert.equal(r.url, "http://api.test/family-chat/files/f1");
  assert.equal(typeof r.headers, "object");
  await assert.rejects(() => fileDownloadRequest("https://evil.test/x"));
  await assert.rejects(() => fileDownloadRequest("/family-chat/files/../photos/a"));
});

test("저장 방식과 안내 문구: 사진은 사진첩, 문서는 내 파일/드라이브", () => {
  assert.equal(u.fileSaveMode("web"), "web");
  assert.equal(u.fileSaveMode("android"), "folder");
  assert.equal(u.fileSaveMode("ios"), "share");
  assert.equal(u.fileSaveHelp("web"), "");
  assert.match(u.fileSaveHelp("android"), /저장할 위치를 선택해 주세요/);
  assert.match(u.fileSaveHelp("ios"), /드라이브/);
  assert.deepEqual(u.fileSaveResult("done"), { ok: true, message: "저장했어요" });
  assert.deepEqual(u.fileSaveResult("canceled"), { ok: false, message: "저장을 취소했어요" });
  assert.deepEqual(u.fileSaveResult("unavailable"), { ok: false, message: "이 환경에서는 저장할 수 없어요" });
  assert.deepEqual(u.fileSaveResult("failed"), { ok: false, message: "파일을 저장하지 못했어요" });
  assert.equal(u.PHOTO_SAVE_LABEL, "사진첩에 저장");
  assert.equal(u.FILE_SAVE_LABEL, "내 파일/드라이브에 저장");
});

test("저장 파일 이름: 경로 문자 제거, 비면 file", () => {
  assert.equal(u.safeFileName("a/b?c:d.pdf"), "a_b_c_d.pdf");
  assert.equal(u.safeFileName(""), "file");
  assert.equal(u.safeFileName(null), "file");
  assert.equal(u.chatFileMimeType({ name: "x.hwp" }), "application/x-hwp");
  assert.equal(u.chatFileMimeType({ name: "x.zzz", mimeType: "a/b" }), "a/b");
});

test("서버 오류 코드별 문구: invalid_file 은 서버 안내 우선, file_busy, file_failed", () => {
  assert.equal(u.fileSendErrorMessage({ status: 400, code: "invalid_file", message: "확장자와 내용이 달라요" }), "확장자와 내용이 달라요");
  assert.equal(u.fileSendErrorMessage({ status: 400, code: "invalid_file", message: "" }), u.FILE_INVALID_MESSAGE);
  assert.equal(u.fileSendErrorMessage({ status: 400, code: "invalid_file" }), "지원하지 않는 파일이거나 내용이 맞지 않아요");
  assert.equal(u.fileSendErrorMessage({ status: 503, code: "file_busy" }), "지금 파일을 처리하는 중이 많아요. 잠시 후 다시 해 주세요");
  assert.equal(u.fileSendErrorMessage({ status: 500, code: "file_failed" }), u.FILE_SEND_FAIL_MESSAGE);
  assert.equal(u.fileSendErrorMessage({ status: 413, code: "file_too_large" }), u.FILE_TOO_LARGE_MESSAGE);
  assert.equal(u.fileSendErrorMessage({ code: "file_empty" }), u.FILE_EMPTY_MESSAGE);
});

test("답장 인용: attachment_kind 가 있으면 그 값, 없으면 has_attachment 로 사진", () => {
  assert.equal(replyLine({ text: "", deleted: false, has_attachment: true, attachment_kind: "file" }), "파일");
  assert.equal(replyLine({ text: "", deleted: false, has_attachment: true, attachment_kind: "image" }), "사진");
  assert.equal(replyLine({ text: "", deleted: false, has_attachment: true }), "사진");
  assert.equal(replyLine({ text: "", deleted: false, attachment_kind: "file" }), "파일");
  assert.equal(replyLine({ text: "", deleted: false, has_attachment: false, attachment_kind: null }), "");
  assert.equal(replyLine({ text: "안녕", has_attachment: true, attachment_kind: "file" }), "안녕");
});

test("임시 폴더: 한글 파일명 보존, 하루 넘은 폴더만 정리 대상", () => {
  assert.equal(u.safeFileName("계획서 최종.pdf"), "계획서 최종.pdf");
  assert.equal(u.safeFileName("../../etc/한글.txt"), ".._.._etc_한글.txt");
  const now = Date.parse("2026-10-30T12:00:00Z");
  const old = u.cacheDirName(now - 25 * 3600 * 1000, 0.5);
  const fresh = u.cacheDirName(now - 3600 * 1000, 0.1);
  assert.match(old, /^gabee-file-[0-9a-z]+-[0-9a-z]+$/);
  assert.deepEqual(u.staleCacheDirs([old, fresh, "other", "gabee-file-zzz"], now), [old]);
});

test("폴더 선택 취소 판별과 hwpx 형식", () => {
  assert.equal(u.isPickerCanceled({ code: "ERR_PICKER_CANCELLED" }), true);
  assert.equal(u.isPickerCanceled(new Error("The file picker was cancelled by the user")), true);
  assert.equal(u.isPickerCanceled(new Error("disk full")), false);
  assert.equal(u.chatFileMimeType({ name: "a.hwpx" }), "application/vnd.hancom.hwpx");
  assert.ok(u.PLUS_SOON_MS >= 2000 && u.PLUS_SOON_MS <= 5000);
});
