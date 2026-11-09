// 가족 놀이터 초대 문구와 링크. 화면·네트워크와 분리한 순수 함수(node 테스트로도 돈다).

/** 초대할 게임별 문구와 들어오는 화면 경로. 폭탄 방은 가족마다 열린 방이 하나라 경로에 방 id 가 필요 없다. */
const TARGETS = {
  bomb: { game: "문장 폭탄", path: "/play/bomb-lobby", query: "host=0", call: "방에 들어와!" },
  play: { game: "가족 놀이터", path: "/play", query: "", call: "같이 놀자!" },
};

/** 초대 종류가 아니면 놀이터 홈으로 본다. */
export const inviteTarget = (kind) => TARGETS[kind] ?? TARGETS.play;

/**
 * 앱을 여는 주소 모양: gabee://play/bomb-lobby?host=0
 * base 를 주면 앞부분만 바꾼다(끝의 / 는 뗀다). 예: Expo Go 시험은 exp://<PC 주소>:8081/--
 */
export function inviteLink(kind, base) {
  const t = inviteTarget(kind);
  const head = base ? String(base).replace(/\/+$/, "") : "gabee:/";
  return `${head}${t.path}${t.query ? `?${t.query}` : ""}`;
}

/** 소통방·외부 공유에 쓰는 문구. 줄 1은 말, 줄 2는 링크. base 는 inviteLink 와 같다. */
export function inviteMessage(name, kind, base) {
  const t = inviteTarget(kind);
  const who = String(name ?? "").trim();
  const call = who ? `${who}야, ${t.game} ${t.call}` : `${t.game} ${t.call}`;
  return `${call}\n${inviteLink(kind, base)}`;
}

const LINK_PATTERN = /gabee:\/\/play[^\s]*/;

/** 메시지 글자에서 놀이터 초대 링크를 찾는다. 없으면 null. */
export function findPlayLink(text) {
  const m = LINK_PATTERN.exec(String(text ?? ""));
  return m ? m[0] : null;
}

/**
 * 메시지 글자를 [{ text, link }] 조각으로 쪼갠다. 링크 조각만 link 가 true.
 * 링크가 없으면 한 조각만 돌려준다.
 */
export function splitPlayLink(text) {
  const s = String(text ?? "");
  const m = LINK_PATTERN.exec(s);
  if (!m) return [{ text: s, link: false }];
  const parts = [];
  if (m.index > 0) parts.push({ text: s.slice(0, m.index), link: false });
  parts.push({ text: m[0], link: true });
  const rest = s.slice(m.index + m[0].length);
  if (rest) parts.push({ text: rest, link: false });
  return parts;
}

/** gabee://play/bomb-lobby?host=0 → /play/bomb-lobby?host=0 (앱 안에서 라우터로 열 경로). 놀이터 주소가 아니면 null. */
export function playPathFromLink(link) {
  const m = /^gabee:\/\/(play[^\s]*)$/.exec(String(link ?? ""));
  return m ? `/${m[1]}` : null;
}
