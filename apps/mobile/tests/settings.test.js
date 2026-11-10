// 환경설정 화면 구성·마이 페이지 헤더 시험: npm test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { settingsAction, settingsSections } from "../src/features/more/settingsItems.js";

const src = (rel) => readFileSync(new URL(`../src/${rel}`, import.meta.url), "utf8");
const more = src("features/more/screens/MoreScreen.js");
const header = src("features/more/components/HeaderActions.js");
const settings = src("features/more/screens/SettingsScreen.js");

test("환경설정 구역은 일반·시스템 설정·알림설정·개인 보안 순서다", () => {
  const sections = settingsSections("v1.2.3");
  assert.deepEqual(sections.map((s) => s.title), ["일반", "시스템 설정", "알림설정", "개인 보안"]);
  assert.equal(sections.every((s) => s.items.length === 1), true);
});

test("일반: 앱 버전 줄은 오른쪽에 버전 문구를 보이고 눌러도 아무 일 없다", () => {
  const [item] = settingsSections("v1.2.3")[0].items;
  assert.equal(item.title, "앱 버전");
  assert.equal(item.value, "v1.2.3");
  assert.deepEqual(settingsAction(item), { type: "none" });
});

test("시스템 설정: 준비 중이에요 안내 줄만 있고 눌러도 아무 일 없다", () => {
  const [item] = settingsSections("v1")[1].items;
  assert.equal(item.title, "준비 중이에요");
  assert.deepEqual(settingsAction(item), { type: "none" });
});

test("알림설정 줄은 /push-settings 로 이동한다", () => {
  const [item] = settingsSections("v1")[2].items;
  assert.equal(item.title, "알림설정");
  assert.deepEqual(settingsAction(item), { type: "route", path: "/push-settings" });
});

test("개인 보안: 로그아웃 줄은 로그아웃 동작이다", () => {
  const [item] = settingsSections("v1")[3].items;
  assert.equal(item.title, "로그아웃");
  assert.deepEqual(settingsAction(item), { type: "logout" });
});

test("환경설정 화면: 로그아웃(signOut 후 시작 화면)·앱 버전 출처를 마이 페이지가 쓰던 것과 같게 쓴다", () => {
  assert.match(settings, /useAuth\(\)/);
  assert.match(settings, /await signOut\(\)/);
  assert.match(settings, /router\.replace\("\/"\)/);
  assert.match(settings, /versionText\(Constants\.expoConfig\?\.version\)/);
  assert.match(settings, /title="환경설정"/);
  assert.match(settings, /chevron-back/);
  assert.match(settings, /\/\/ ?처음/); // 기존 주석(처음 화면으로 돌아간다) 유지
});

test("라우트 /settings 가 환경설정 화면을 가리킨다", () => {
  assert.match(src("app/settings.js"), /features\/more\/screens\/SettingsScreen/);
});

test("마이 페이지 헤더: 알림설정 없이 톱니 환경설정만, 누르면 /settings", () => {
  assert.doesNotMatch(more, /notifications-outline/);
  assert.doesNotMatch(more, /push-settings/);
  assert.match(more, /icon: "settings-outline", label: "환경설정"/);
  assert.match(more, /router\.push\("\/settings"\)/);
  // 환경설정이 더는 준비 중 안내가 아니다
  assert.doesNotMatch(more, /label: "환경설정", onPress: \(\) => showNotice/);
});

test("헤더 버튼은 글자·둥근 바탕 없이 아이콘만이고 누르는 영역이 44 이상이다", () => {
  assert.doesNotMatch(header, /<Text/);
  assert.doesNotMatch(header, /bubble|backgroundColor/);
  assert.match(header, /accessibilityLabel=\{item\.label\}/);
  assert.match(header, /minWidth: 44/);
  assert.match(header, /minHeight: 44/);
});

test("마이 페이지 맨 아래에는 로그아웃·앱 버전 버튼이 더 없다", () => {
  assert.doesNotMatch(more, /signOut/);
  assert.doesNotMatch(more, /로그아웃/);
  assert.doesNotMatch(more, /app-version|앱 버전|versionText/);
  assert.match(more, /<ShortcutGrid/);
  assert.match(more, /<MenuList/);
});
