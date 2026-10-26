// 가족 연락처 순수 함수 모음(화면과 분리해 시험한다). 별명·메모는 나만 보는 값이라 어디에도 기록하지 않는다. 전화번호는 다루지 않는다.
import { roomErrorMessage } from "./chatUtils";
import { memberName } from "./listUtils";

export const NICKNAME_MAX = 40; // 서버 profile_service.NAME_MAX
export const MEMO_MAX = 1000; // 서버 NicknameIn.memo

const RELATION_LABELS = { mom: "엄마", dad: "아빠", son: "아들", daughter: "딸", grandma: "할머니", grandpa: "할아버지" };

/**
 * 관계 라벨: 정해진 관계는 한글, other 는 직접 적은 관계(없으면 "가족"), 관계를 안 정했으면 빈 문자열.
 * @param {{ family_relation?: string | null, family_relation_detail?: string | null } | null | undefined} member
 * @returns {string}
 */
export function relationLabel(member) {
  const relation = member?.family_relation;
  if (!relation) return "";
  if (relation === "other") return String(member.family_relation_detail ?? "").trim() || "가족";
  return RELATION_LABELS[relation] ?? "";
}

/**
 * 별명 목록을 대상 id 로 찾기 쉽게 바꾼다.
 * @param {{ target_user_id: string, nickname?: string | null, memo?: string | null }[] | null | undefined} list
 * @returns {Record<string, { nickname: string, memo: string }>}
 */
export function nicknameMap(list) {
  const map = {};
  for (const row of Array.isArray(list) ? list : []) {
    map[row.target_user_id] = { nickname: String(row.nickname ?? ""), memo: String(row.memo ?? "") };
  }
  return map;
}

/**
 * 한 줄로 보일 메모(줄바꿈은 공백으로).
 * @param {string} memo
 * @returns {string}
 */
export const memoLine = (memo) => String(memo ?? "").split(/\s*\n\s*/).join(" ").trim();

/**
 * 연락처 행. 별명이 있으면 별명을 크게(title), 본래 표시 이름을 작게(subtitle)로 두고, 없으면 표시 이름이 title 이다.
 * 나는 별명을 붙일 수 없고 대화 상대도 아니다(isMe).
 * @param {{ id: string, name: string, display_name?: string | null, photo_url?: string | null, family_relation?: string | null, family_relation_detail?: string | null }[] | null | undefined} members
 * @param {string | null | undefined} myId
 * @param {Record<string, { nickname: string, memo: string }>} [nicknames] nicknameMap 결과
 * @returns {{ id: string, title: string, subtitle: string, relation: string, memo: string, nickname: string, realName: string, photoUrl: string | null, isMe: boolean }[]} 나가 맨 위, 나머지는 받은 순서
 */
export function contactRows(members, myId, nicknames = {}) {
  const rows = (Array.isArray(members) ? members : []).map((m) => {
    const real = memberName(m);
    const mine = nicknames[m.id];
    const nickname = m.id === myId ? "" : (mine?.nickname ?? "");
    return {
      id: m.id,
      title: nickname || real,
      subtitle: nickname ? real : "",
      relation: relationLabel(m),
      memo: m.id === myId ? "" : memoLine(mine?.memo),
      nickname,
      realName: real,
      photoUrl: m.photo_url ?? null,
      isMe: m.id === myId,
    };
  });
  return [...rows.filter((r) => r.isMe), ...rows.filter((r) => !r.isMe)];
}

/**
 * 별명·메모 입력 검사. 둘 다 비워도 되고(저장하면 지워진다) 길이만 본다.
 * @param {string} nickname
 * @param {string} memo
 * @returns {string} 문제가 있으면 안내 문구, 없으면 빈 문자열
 */
export function validateNickname(nickname, memo) {
  if (String(nickname ?? "").trim().length > NICKNAME_MAX) return `별명은 ${NICKNAME_MAX}자 이내로 적어 주세요`;
  if (String(memo ?? "").trim().length > MEMO_MAX) return `메모는 ${MEMO_MAX}자 이내로 적어 주세요`;
  return "";
}

/**
 * 저장 결과(서버 응답)를 별명 맵에 반영한다. 둘 다 비었으면 그 사람 항목을 지운다.
 * @param {Record<string, { nickname: string, memo: string }>} map
 * @param {string} targetId
 * @param {{ nickname?: string | null, memo?: string | null } | null | undefined} saved
 * @returns {Record<string, { nickname: string, memo: string }>}
 */
export function applySavedNickname(map, targetId, saved) {
  const next = { ...map };
  const nickname = String(saved?.nickname ?? "");
  const memo = String(saved?.memo ?? "");
  if (!nickname && !memo) delete next[targetId];
  else next[targetId] = { nickname, memo };
  return next;
}

const BY_CODE = {
  invalid_nickname: "별명은 40자 이내로 적어 주세요",
  cannot_nickname_self: "자기 자신에게는 별명을 붙일 수 없어요",
  not_found: "가족 구성원을 찾을 수 없어요. 새로고침해 주세요",
};

/**
 * 연락처 오류를 사용자 문장으로(별명·메모 내용은 넣지 않는다).
 * @param {{ code?: string } | null | undefined} error
 * @returns {string}
 */
export const contactErrorMessage = (error) => BY_CODE[error?.code] ?? roomErrorMessage(error);
