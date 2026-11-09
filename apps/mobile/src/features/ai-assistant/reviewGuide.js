// 확인 필요(needs_review) 기록에서 "어느 부분을 고쳐야 하는지"를 알려 주는 규칙. 화면과 분리해 둔 순수 함수다.
const UNREADABLE = "[판독불가]";
const DOUBT = "[불확실]";
const UNREAD_PART = "[읽지 못한 부분]";

/**
 * 글자의 받침 유무에 맞는 조사(이/가)를 고른다. 한글이 아니면 "가".
 * @param {string} word 조사가 붙을 낱말
 * @returns {string} "이" 또는 "가"
 */
function subjectParticle(word) {
  const code = word.charCodeAt(word.length - 1);
  if (code < 0xac00 || code > 0xd7a3) return "가";
  return (code - 0xac00) % 28 === 0 ? "가" : "이";
}

/**
 * 본문에서 내용 줄만 골라낸다. 맨 앞 `# 제목` 줄과 `분류:` 줄은 내용이 아니다.
 * @param {string} body body_md
 * @returns {string[]} 내용 줄들
 */
function contentLines(body) {
  const lines = body.split(/\r?\n/);
  if (lines[0]?.startsWith("# ")) lines.shift();
  if (lines[0]?.startsWith("분류:")) lines.shift();
  return lines;
}

/**
 * 확인 필요 기록에서 고칠 부분을 알려 주는 안내 목록을 만든다.
 * 순서: 제목 → 내용(못 읽은 글자) → 내용(자신 없는 줄) → 내용(일부 못 읽음) → 종류(다른 이유가 없을 때만).
 * @param {{ title?: string, kind_label?: string, body_md?: string, has_unread_parts?: boolean } | null | undefined} record 기록(없는 값은 무시)
 * @returns {{ field: string, text: string }[]} 해당하는 항목만. 없으면 빈 목록
 */
export function reviewGuide(record) {
  const title = typeof record?.title === "string" ? record.title : "";
  const kind = typeof record?.kind_label === "string" ? record.kind_label.trim() : "";
  const body = typeof record?.body_md === "string" ? record.body_md : "";
  const lines = contentLines(body);
  const guide = [];

  if (title.includes(UNREADABLE) || title.includes("[?]")) {
    guide.push({ field: "제목", text: "제목에 못 읽은 글자가 있어요. 원본을 보고 제목을 고쳐 주세요." });
  }
  const unreadable = lines.filter((l) => l.includes(UNREADABLE)).length;
  if (unreadable > 0) {
    guide.push({ field: "내용", text: `내용에 못 읽은 글자가 ${unreadable}곳 있어요. 원본을 보고 ${UNREADABLE} 자리에 맞는 글자로 고쳐 주세요.` });
  }
  const doubts = lines.filter((l) => l.trimEnd().endsWith(DOUBT) && !l.includes(UNREADABLE)).length;
  if (doubts > 0) {
    guide.push({ field: "내용", text: `내용에 글자가 흐려 자신 없는 줄이 ${doubts}개 있어요. 원본과 비교해 틀린 곳을 고쳐 주세요.` });
  }
  if (record?.has_unread_parts === true || body.includes(UNREAD_PART)) {
    guide.push({ field: "내용", text: "일부를 읽지 못했어요. 원본을 보고 빠진 내용을 적어 주세요." });
  }
  if (guide.length === 0 && kind) {
    guide.push({ field: "종류", text: `종류가 확실하지 않아요. '${kind}'${subjectParticle(kind)} 맞는지 보고, 틀리면 종류를 바꿔 주세요.` });
  }
  return guide;
}
