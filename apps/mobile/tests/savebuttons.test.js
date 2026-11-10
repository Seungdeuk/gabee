// 채팅 사진 저장 버튼 정리: "가비 기록에 저장"은 "문서로 저장"과 합쳐져 없어졌고, 남은 버튼은 사진첩에 저장·문서로 저장이다: npm test
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";

const dir = new URL("../src/features/family-chat/", import.meta.url);
const read = (rel) => readFileSync(new URL(rel, dir), "utf8");

test("가비 기록에 저장: 옛 모듈과 업로드 호출이 없어졌다", () => {
  assert.equal(existsSync(new URL("saveToRecord.js", dir)), false);
  assert.doesNotMatch(read("api.js"), /uploadToAssistantRecord/);
});

test("소통 기능 소스 어디에도 옛 버튼(가비 기록에 저장)과 그 속성이 남아 있지 않다", () => {
  const walk = (rel) =>
    readdirSync(new URL(rel, dir), { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(`${rel}${e.name}/`) : [`${rel}${e.name}`]));
  const offenders = walk("").filter((f) => f.endsWith(".js") && /onSaveToRecord|recordOf|recordSaving|recordDone|recordNotice|canSaveToRecord|saveToRecord|RECORD_BUTTON_LABEL|가비 기록에 저장/.test(read(f)));
  assert.deepEqual(offenders, []);
});

test("남은 버튼: 사진 보기와 앨범 뷰어에 사진첩에 저장·문서로 저장이 있다", () => {
  for (const file of ["components/PhotoViewer.js", "components/AlbumViewer.js"]) {
    const src = read(file);
    assert.match(src, /onSaveToDevice/);
    assert.match(src, /onSaveToLibrary/);
    assert.match(src, /LIBRARY_BUTTON_LABEL/);
  }
  assert.match(read("screens/ChatRoomScreen.js"), /onSaveToLibrary=\{canSaveToLibrary\(/);
});
