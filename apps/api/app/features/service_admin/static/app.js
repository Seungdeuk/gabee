// 가비 서비스 관리자 화면. 서버가 /admin/service/ui 로 내려준다.
// 모든 탭은 로그인한 뒤 /admin/service/* API 의 실제 데이터를 쓴다. 문의·신고(상태·답변)와 공지사항(쓰기·고치기·지우기)만 바꿀 수 있다.
(function () {
  "use strict";

  // 왼쪽 메뉴: 묶음 제목과 그 안의 탭. 비슷한 것끼리 묶고 할 일(문의·공지)은 아래에 모은다. 첫 화면은 맨 위 탭.
  const TAB_GROUPS = [
    ["사람", [["members", "회원 관리"], ["groups", "가족 그룹 관리"]]],
    ["사용", [["features", "기능 관리"], ["ai", "AI 이용 현황"]]],
    ["운영 업무", [["support", "문의 및 신고"], ["notices", "공지사항"]]],
  ];
  const TABS = TAB_GROUPS.flatMap(([, tabs]) => tabs);
  const TOKEN_KEY = "gabee_admin_token";

  // 문의·신고 상태: 화면 글자, 표시 색, 버튼 글자, 버튼을 누르면 바뀔 상태.
  // 답변 완료(done)는 버튼이 아니라 답변을 저장할 때만 된다(서버가 자동으로 바꾼다).
  const STATUS = {
    new: { label: "접수", cls: "hot", action: "처리 시작", next: "working" },
    working: { label: "처리 중", cls: "" },
    done: { label: "답변 완료", cls: "ok" },
  };
  const KIND = { inquiry: "문의", report: "신고" };
  // 공지 종류: 앱의 칩과 같은 이름
  const CATEGORY = { update: "업데이트", info: "안내", maintenance: "점검" };

  /**
   * 화면에 넣을 글자를 HTML 로 해석되지 않게 바꾼다.
   * @param {unknown} v
   * @returns {string}
   */
  function esc(v) {
    return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  // ── 서버 호출 ─────────────────────────────────────────

  function token() {
    try {
      return sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  }

  function setToken(value) {
    try {
      if (value) sessionStorage.setItem(TOKEN_KEY, value);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      // 저장이 막힌 브라우저면 새로고침할 때 다시 로그인한다
    }
  }

  /**
   * 관리자 API 를 부른다. 로그인이 풀렸으면(401) 로그인 화면으로 돌아간다.
   * @param {string} path
   * @param {object} [body] 주면 method(기본 PATCH)로 보낸다(문의·신고 상태·답변, 공지 쓰기·고치기)
   * @param {string} [method] body 없이 DELETE 처럼 보낼 때도 쓴다
   * @returns {Promise<any>}
   */
  async function api(path, body, method = body ? "PATCH" : "GET") {
    const init = { method, headers: { Authorization: `Bearer ${token()}` } };
    if (body) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const res = await fetch(path, init);
    if (res.status === 401) {
      setToken(null);
      showLogin("로그인이 만료됐어요. 다시 로그인해 주세요.");
      throw new Error("unauthorized");
    }
    if (res.status === 403 && path === "/admin/service/me") throw new Error("not_staff"); // 허용 목록에 없는 회원
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.status === 204 ? null : res.json();
  }

  /**
   * 화면 데이터를 가져온다.
   * @returns {Promise<object>}
   */
  async function loadData() {
    const [me, members, groups, features, ai, support, notices] = await Promise.all(
      ["/admin/service/me", "/admin/service/members", "/admin/service/groups", "/admin/service/features", "/admin/service/ai-usage", "/admin/service/support", "/admin/service/notices"].map((p) => api(p)),
    );
    return { me, members, groups, features, ai, support, notices };
  }

  // ── 그리기 도우미 ─────────────────────────────────────

  const num = (n) => Number(n).toLocaleString("ko-KR");
  const pct = (n) => `${Math.max(0, Math.min(100, Number(n) || 0))}%`;
  const day = (iso) => (iso ? new Date(iso).toLocaleDateString("sv-SE") : "-"); // YYYY-MM-DD

  function ago(iso) {
    if (!iso) return "기록 없음";
    const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
    return days <= 0 ? "오늘" : days === 1 ? "어제" : `${days}일 전`;
  }

  function stat(label, value, sub = "", tone = "") {
    return `<div class="stat"><span class="stat-label">${esc(label)}</span><span class="stat-value">${esc(value)}</span><span class="stat-sub ${tone}">${esc(sub)}</span></div>`;
  }

  let pageHead = { title: "", sub: "" }; // 화면 제목은 본문이 아니라 위 고정 머리줄에 쓴다(render 가 옮긴다)

  function head(title, sub) {
    pageHead = { title, sub };
    return "";
  }

  // 왼쪽 메뉴 아이콘(선 아이콘, 운영 관리자 웹과 같은 굵기)
  const ICON_PATHS = {
    members: "M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6M22 19v-1a4 4 0 0 0-3-3.9M16 4.1a3 3 0 0 1 0 5.8",
    groups: "M3 10.5 12 4l9 6.5M5 9v10h14V9M10 19v-5h4v5",
    features: "M4 20V10M10 20V4M16 20v-7M22 20H2",
    ai: "M12 3l1.8 4.6L18 9.5l-4.2 1.9L12 16l-1.8-4.6L6 9.5l4.2-1.9zM19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z",
    support: "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z",
    notices: "M3 11v2a1 1 0 0 0 1 1h2l5 4V6L6 10H4a1 1 0 0 0-1 1zM15 9a4 4 0 0 1 0 6M18 6a8 8 0 0 1 0 12",
  };
  const icon = (key) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${ICON_PATHS[key]}"/></svg>`;

  function bar(n) {
    return `<div class="bar"><span style="width:${pct(n)}"></span></div>`;
  }

  function table(columns, rows) {
    const th = columns.map((c) => `<th class="${c.num ? "num" : ""}">${esc(c.label)}</th>`).join("");
    const body = rows.length ? rows.join("") : `<tr><td colspan="${columns.length}" class="small">해당하는 항목이 없어요</td></tr>`;
    return `<div class="table-wrap"><table><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  /** 문의·신고 상태 표시 + 다음 상태로 바꾸는 버튼. */
  function statusCells(row) {
    const s = STATUS[row.status];
    const btn = s.next ? `<button type="button" class="btn sm" data-ticket="${esc(row.id)}" data-next="${s.next}">${esc(s.action)}</button>` : "";
    const reply = `<button type="button" class="btn sm ${row.answer ? "" : "primary"}" data-reply="${esc(row.id)}">${row.answer ? "답변 수정" : "답변하기"}</button>`;
    return `<td><span class="pill ${s.cls}">${esc(s.label)}</span></td><td class="num"><div class="row-actions">${reply}${btn}</div></td>`;
  }

  // ── 탭별 화면 ─────────────────────────────────────────

  const filters = { memberQ: "" };

  function viewMembers(d) {
    const word = filters.memberQ.toLowerCase();
    const rows = d.rows
      .filter((u) => !word || u.name.toLowerCase().includes(word) || (u.login_id || "").toLowerCase().includes(word))
      .map((u) => `<tr><td><strong>${esc(u.name)}</strong></td><td>${esc(u.login_id || "-")}</td><td>${day(u.joined_at)}</td><td>${u.has_family ? "있음" : "없음"}</td><td><span class="pill ${u.email_verified ? "ok" : ""}">${u.email_verified ? "인증" : "미인증"}</span></td><td>${ago(u.last_login_at)}</td></tr>`);
    return `${head("회원 관리", "가입자 수 · 가입일 · 계정 상태")}
      <section class="grid">
        ${stat("전체 가입자", `${num(d.total)}명`)}
        ${stat("이번 주 가입", `${num(d.joined_this_week)}명`, "최근 7일", "up")}
        ${stat("활성 사용자", `${num(d.active_7d)}명`, "최근 7일")}
        ${stat("가족 없는 회원", `${num(d.no_family)}명`)}
        ${stat("이메일 인증", `${num(d.email_verified)}명`, d.total ? `전체의 ${Math.round((d.email_verified / d.total) * 100)}%` : "")}
        ${stat("계정 상태", "준비 중", "정지 기능은 2단계")}
      </section>
      <section class="card">
        <div class="filters">
          <label class="field">이름·아이디 검색<input type="search" data-filter="memberQ" value="${esc(filters.memberQ)}" placeholder="예: test"></label>
        </div>
        ${table([{ label: "이름" }, { label: "아이디" }, { label: "가입일" }, { label: "가족" }, { label: "이메일 인증" }, { label: "마지막 로그인" }], rows)}
        <span class="small">최근 가입순 최대 200명</span>
      </section>`;
  }

  function viewGroups(d) {
    const memberSum = d.rows.reduce((a, g) => a + g.members, 0);
    const maxSize = Math.max(1, ...d.sizes.map((s) => s.groups));
    const sizes = d.sizes.length
      ? d.sizes.map((s) => `<div><div class="line-item" style="border:0;padding:0 0 6px"><span>${esc(s.members)}명</span><strong>${esc(s.groups)}개</strong></div>${bar((s.groups / maxSize) * 100)}</div>`).join("")
      : '<p class="small">아직 가족 그룹이 없어요</p>';
    const rows = d.rows.map((g) => `<tr><td><strong>${esc(g.name)}</strong></td><td>${esc(g.owner_name || "-")}</td><td class="num">${esc(g.members)}명</td><td class="num">${num(g.pending || 0)}건</td><td><span class="pill ${g.ai_enabled ? "ok" : ""}">${g.ai_enabled ? "켬" : "꺼짐"}</span></td><td>${day(g.created_at)}</td></tr>`);
    return `${head("가족 그룹 관리", "가족 그룹 수 · 구성원 수")}
      <section class="grid">
        ${stat("가족 그룹", `${num(d.total)}개`)}
        ${stat("평균 구성원", d.rows.length ? `${(memberSum / d.rows.length).toFixed(1)}명` : "-")}
        ${stat("1명뿐인 가족", `${num(d.single_member)}곳`, "아직 아무도 초대 안 함")}
        ${stat("승인 대기", `${num(d.pending_total)}건`, d.oldest_pending_at ? `가장 오래된 요청: ${ago(d.oldest_pending_at)}` : "", d.pending_total ? "warn" : "")}
        ${stat("AI 켠 가족", `${num(d.ai_enabled)}곳`, `전체 ${num(d.total)}곳 중`)}
      </section>
      <section class="row">
        <div class="card wide"><h2>가족 그룹 목록</h2>${table([{ label: "그룹 이름" }, { label: "대표" }, { label: "구성원", num: true }, { label: "승인 대기", num: true }, { label: "AI" }, { label: "만든 날" }], rows)}</div>
        <div class="card side"><h2>구성원 수별 그룹</h2>${sizes}</div>
      </section>
      <p class="note">가족 안의 채팅·문서·정산 내용은 이 화면에 나오지 않아요.</p>`;
  }

  function change(f) {
    if (!f.prev_uses) return f.uses ? '<span class="up">새로 씀</span>' : '<span class="small">-</span>';
    const p = Math.round(((f.uses - f.prev_uses) / f.prev_uses) * 100);
    return `<span class="${p >= 0 ? "up" : "warn"}">${p >= 0 ? "+" : ""}${p}%</span>`;
  }

  function viewFeatures(d) {
    const rows = d.rows.map((f) => {
      const share = d.families_total ? (f.families / d.families_total) * 100 : 0;
      return `<tr><td><strong>${esc(f.name)}</strong></td><td class="num">${esc(f.families)}가족</td><td style="width:160px">${bar(share)}</td><td class="num">${num(f.uses)}회</td><td class="num">${change(f)}</td></tr>`;
    });
    return `${head("기능 관리", "기능별 사용 현황 · 최근 7일")}
      <section class="card">
        <h2>기능별 사용</h2>
        ${table([{ label: "기능" }, { label: "쓴 가족", num: true }, { label: `전체 ${d.families_total}가족 중` }, { label: "사용 횟수", num: true }, { label: "그 전 7일 대비", num: true }], rows)}
        <span class="small">일정은 만든 일정, 소통은 보낸 메시지, 정산은 등록한 지출 개수예요. AI 채팅은 'AI 이용 현황'에서 봐요.</span>
      </section>`;
  }

  function viewAi(d) {
    const max = Math.max(1, ...d.daily);
    const days = d.daily.map((c) => `<div title="${c}회"><i style="height:${pct((c / max) * 100)}"></i></div>`).join("");
    const top = Math.max(1, ...d.rows.map((r) => r.calls));
    const rows = d.rows.length === 0 ? '<p class="note">최근 30일에 AI를 쓴 기록이 없어요.</p>' : d.rows
      .map((r) => {
        const split = r.via_assistant ? `<p class="small" style="margin:4px 0 0">직접 ${num(r.direct)}회 · AI 비서가 부름 ${num(r.via_assistant)}회</p>` : "";
        return `<div><div class="meter"><strong>${esc(r.name)}</strong><div class="bar plain"><span style="width:${pct((r.calls / top) * 100)}"></span></div><span class="num">${num(r.calls)}회</span></div>${split}</div>`;
      })
      .join("");
    const famRows = (d.families || []).map((f) => `<tr><td><strong>${esc(f.name || "-")}</strong></td><td class="num">${num(f.requests)}회</td><td class="num">${num(f.errors)}회</td></tr>`);
    const userRows = (d.users || []).map((u) => `<tr><td><strong>${esc(u.name || "-")}</strong></td><td>${esc(u.login_id || "-")}</td><td class="num">${num(u.requests)}회</td><td class="num">${num(u.errors)}회</td></tr>`);
    const limited = d.limited || [];
    const limitedRows = limited.map((u) => `<tr><td><strong>${esc(u.name || "-")}</strong></td><td>${esc(u.group_name || "-")}</td><td class="num">${num(u.days)}일</td><td>${ago(u.last_at)}</td></tr>`);
    const limitedBody = limited.length
      ? table([{ label: "이름" }, { label: "가족" }, { label: "걸린 날", num: true }, { label: "마지막으로 걸린 때" }], limitedRows)
      : '<p class="note">최근 30일에 하루 한도에 걸린 사람이 없어요.</p>';
    return `${head("AI 이용 현황", "AI 기능 사용 횟수 · 기능별 사용량")}
      <section class="grid compact">
        ${stat("오늘", `${num(d.today)}회`)}
        ${stat("최근 7일", `${num(d.week)}회`)}
        ${stat("최근 30일", `${num(d.month)}회`)}
      </section>
      <div class="dash">
        <section class="card span2">
          <h2>하루별 AI 사용 (최근 14일)</h2>
          <div class="chart" role="img" aria-label="최근 14일 하루 AI 사용 횟수">${days}</div>
          <div class="axis"><span>14일 전</span><span>오늘</span></div>
        </section>
        <section class="card">
          <h2>기능별 사용량 (최근 30일)</h2>
          <div class="scroll">
            <p class="note">AI 비서가 부른 에이전트도 넣고 따로 적어요. 위 요청 수에는 안 넣어요.</p>
            ${rows}
          </div>
        </section>
        <section class="card">
          <h2>가족별 AI 사용 (최근 30일)</h2>
          <div class="scroll">${table([{ label: "가족" }, { label: "요청 수", num: true }, { label: "오류", num: true }], famRows)}</div>
        </section>
        <section class="card">
          <h2>사용자별 AI 사용 (최근 30일)</h2>
          <div class="scroll">${table([{ label: "이름" }, { label: "아이디" }, { label: "요청 수", num: true }, { label: "오류", num: true }], userRows)}</div>
        </section>
        <section class="card">
          <h2>하루 한도에 걸린 사람 (최근 30일)</h2>
          <div class="scroll">${limitedBody}</div>
        </section>
      </div>`;
  }

  let openTicket = null; // 펼쳐 둔 문의(다시 그려도 열린 채로 둔다)
  let supportError = ""; // 마지막 저장 실패 안내
  let lastSupportAt = null; // 문의 목록을 마지막으로 받은 시각

  /** 제목을 누르면 내용과 답변 칸이 펼쳐진다. 내용은 사용자가 직접 쓴 글뿐이다. 답변을 저장하면 답변 완료가 되고, 다시 저장하면 고쳐진다. */
  function ticketTitle(t) {
    const answered = t.answered_at ? `<span class="small">답변 ${day(t.answered_at)}</span>` : '<span class="small">저장하면 답변 완료가 돼요</span>';
    return `<details data-open="${esc(t.id)}" ${t.id === openTicket ? "open" : ""}><summary>${esc(t.title)}</summary>
      <p class="ticket-body">${esc(t.body)}</p>
      <form class="answer" data-answer="${esc(t.id)}">
        <label class="small" for="answer-${esc(t.id)}">답변</label>
        <textarea id="answer-${esc(t.id)}" name="answer" rows="3" maxlength="2000" required>${esc(t.answer || "")}</textarea>
        <div class="answer-row">${answered}<button type="submit" class="btn sm primary">${t.answer ? "수정 저장" : "답변 저장"}</button></div>
      </form></details>`;
  }

  /** 새로고침 버튼과 마지막 확인 시각. */
  function refreshRow() {
    const at = lastSupportAt ? lastSupportAt.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }) : "";
    return `<p class="small"><button type="button" class="btn sm" data-action="refresh-support">새로고침</button> ${at ? `마지막 확인 ${esc(at)} · ` : ""}15초마다 새 문의를 자동으로 확인해요</p>`;
  }

  function viewSupport(d) {
    const rows = d.rows.map(
      (t) => `<tr><td>#${esc(t.id.slice(0, 6))}</td><td><span class="pill ${t.kind === "report" ? "bad" : ""}">${KIND[t.kind]}</span></td><td>${ticketTitle(t)}</td><td>${esc(t.user_name || "-")}<br><span class="small">${esc(t.login_id || "")}</span></td><td>${esc(t.group_name || "-")}</td><td>${day(t.created_at)}</td>${statusCells(t)}</tr>`,
    );
    const error = supportError ? `<p class="note warn">${esc(supportError)}</p>` : "";
    return `${head("문의 및 신고", "문의 현황 · 처리 상태 · 답변")}${refreshRow()}${error}
      <section class="grid">
        ${stat("새 문의·신고", `${num(d.new)}건`, "", d.new ? "warn" : "")}
        ${stat("처리 중", `${num(d.working)}건`)}
        ${stat("답변 완료", `${num(d.done)}건`, "", "up")}
        ${stat("신고", `${num(d.reports)}건`, "문의와 따로 셈")}
      </section>
      <section class="card"><h2>문의·신고 목록</h2><p class="small">사용자가 직접 쓴 글만 있어요. 가족 채팅 내용은 담기지 않아요.</p>${table([{ label: "번호" }, { label: "종류" }, { label: "제목 (누르면 내용)" }, { label: "보낸 사람" }, { label: "가족" }, { label: "받은 날" }, { label: "상태" }, { label: "" }], rows)}</section>`;
  }

  /** 문의·신고를 바꾸고 목록을 다시 받아 그린다. 실패하면 화면 위에 알려 준다. */
  async function updateTicket(id, body) {
    try {
      await api(`/admin/service/support/${encodeURIComponent(id)}`, body);
      data.support = await api("/admin/service/support");
      supportError = "";
    } catch (err) {
      if (err.message === "unauthorized") return;
      supportError = "저장하지 못했어요. 잠시 뒤 다시 해 주세요.";
    }
    render();
  }

  let editingNotice = null; // 고치는 중인 공지 번호(없으면 새 공지 쓰기)
  let writingNotice = false; // '글쓰기'를 눌러 쓰기 칸을 연 상태. 평소에는 칸을 숨기고 버튼만 둔다
  let noticeError = "";

  /** 공지 쓰기·고치기 칸. 고치는 중이면 그 공지 내용을 채워 둔다. 글쓰기·고치기를 눌렀을 때만 보인다. */
  function noticeForm(rows) {
    if (!writingNotice && !editingNotice) return "";
    const n = rows.find((r) => r.id === editingNotice) || { category: "info", title: "", body: "" };
    const options = Object.entries(CATEGORY)
      .map(([k, label]) => `<option value="${k}" ${k === n.category ? "selected" : ""}>${label}</option>`)
      .join("");
    const cancel = '<button type="button" class="btn sm" data-action="cancel-notice">취소</button>';
    return `<section class="card"><h2>${editingNotice ? "공지 고치기" : "새 공지 쓰기"}</h2>
      <form class="notice-form" data-notice-form>
        <div class="notice-fields">
          <label class="small">종류 <select name="category">${options}</select></label>
          <label class="small notice-title">제목 <input name="title" maxlength="100" required value="${esc(n.title)}"></label>
        </div>
        <label class="small" for="notice-body">내용</label>
        <textarea id="notice-body" name="body" rows="6" maxlength="5000" required>${esc(n.body)}</textarea>
        <div class="answer-row"><span class="small">저장하면 바로 앱 더보기 › 공지사항에 보여요. 알림은 가지 않아요.</span><div class="row-actions">${cancel}<button type="submit" class="btn sm primary">${editingNotice ? "고친 내용 저장" : "공지 올리기"}</button></div></div>
      </form></section>`;
  }

  function viewNotices(d) {
    const rows = d.rows.map(
      (n) => `<tr><td><span class="pill">${esc(CATEGORY[n.category])}</span></td><td><details><summary>${esc(n.title)}</summary><p class="ticket-body">${esc(n.body)}</p></details></td><td>${day(n.created_at)}</td><td>${n.updated_at !== n.created_at ? day(n.updated_at) : "-"}</td><td class="num"><div class="row-actions"><button type="button" class="btn sm" data-notice-edit="${esc(n.id)}">고치기</button><button type="button" class="btn sm" data-notice-delete="${esc(n.id)}">지우기</button></div></td></tr>`,
    );
    const error = noticeError ? `<p class="note warn">${esc(noticeError)}</p>` : "";
    const write = writingNotice || editingNotice ? "" : '<button type="button" class="btn sm primary" data-action="write-notice">글쓰기</button>';
    return `${head("공지사항", "앱 사용자 모두에게 보이는 서비스 공지")}${error}
      ${noticeForm(d.rows)}
      <section class="card"><div class="card-head"><h2>올린 공지 (${num(d.rows.length)}건)</h2>${write}</div>${table([{ label: "종류" }, { label: "제목 (누르면 내용)" }, { label: "올린 날" }, { label: "고친 날" }, { label: "" }], rows)}</section>`;
  }

  /** 공지를 쓰거나 고치거나 지우고 목록을 다시 받아 그린다. */
  async function saveNotice(path, body, method) {
    try {
      await api(path, body, method);
      data.notices = await api("/admin/service/notices");
      editingNotice = null;
      writingNotice = false;
      noticeError = "";
    } catch (err) {
      if (err.message === "unauthorized") return;
      noticeError = "저장하지 못했어요. 잠시 뒤 다시 해 주세요.";
    }
    render();
  }

  const VIEWS = {
    members: (data) => viewMembers(data.members),
    groups: (data) => viewGroups(data.groups),
    features: (data) => viewFeatures(data.features),
    ai: (data) => viewAi(data.ai),
    support: (data) => viewSupport(data.support),
    notices: (data) => viewNotices(data.notices),
  };

  // ── 화면 그리기 ───────────────────────────────────────

  let data = null;

  function current() {
    const key = location.hash.replace("#", "");
    return VIEWS[key] ? key : TABS[0][0];
  }

  /** 왼쪽 메뉴(묶음 제목 + 탭). 문의 및 신고에는 아직 처리하지 않은 새 문의 건수를 붙인다. */
  function renderTabs(key) {
    const fresh = data && data.support ? Number(data.support.new) || 0 : 0;
    const link = ([k, label]) => {
      const badge = k === "support" && fresh ? `<span class="tab-badge" aria-label="새 문의 ${fresh}건">${num(fresh)}</span>` : "";
      return `<a href="#${k}" aria-current="${k === key ? "page" : "false"}">${icon(k)}<span>${label}</span>${badge}</a>`;
    };
    document.getElementById("tabs").innerHTML = TAB_GROUPS.map(([title, tabs]) => `<p class="nav-group">${esc(title)}</p>${tabs.map(link).join("")}`).join("");
  }

  /** 답변 칸에 쓰던 글이 있는지. 있으면 다시 그리다 지워지지 않도록 화면은 그대로 둔다. */
  function typing() {
    return [...document.querySelectorAll("#view textarea")].some((t) => t === document.activeElement || t.value !== t.defaultValue);
  }

  /** 문의·신고 목록만 새로 받아 온다. 실패해도 지금 화면은 그대로 둔다(로그인 만료는 api() 가 처리한다). */
  async function refreshSupport() {
    if (!data || !token()) return;
    let fresh;
    try {
      fresh = await api("/admin/service/support");
    } catch {
      return;
    }
    if (!data) return;
    data.support = fresh;
    lastSupportAt = new Date();
    if (current() === "support" && !typing()) render();
    else renderTabs(current());
  }

  function render() {
    if (!data) return;
    const key = current();
    renderTabs(key);
    document.getElementById("view").innerHTML = VIEWS[key](data);
    document.getElementById("page-title").textContent = pageHead.title;
    document.getElementById("page-sub").textContent = pageHead.sub;
    document.title = `가비 서비스 관리자 · ${TABS.find(([k]) => k === key)[1]}`;
  }

  function showLogin(message = "") {
    data = null;
    document.getElementById("app").hidden = true;
    document.getElementById("login").hidden = false;
    document.getElementById("login-error").textContent = message;
  }

  async function start() {
    document.getElementById("view").innerHTML = '<p class="note">불러오는 중…</p>';
    try {
      data = await loadData();
    } catch (err) {
      if (err.message === "not_staff") {
        setToken(null);
        showLogin("관리자 계정이 아니에요.");
      } else if (err.message !== "unauthorized") {
        document.getElementById("view").innerHTML = '<p class="note warn">데이터를 불러오지 못했어요. 잠시 뒤 새로고침해 주세요.</p>';
      }
      return;
    }
    document.getElementById("login").hidden = true;
    document.getElementById("app").hidden = false;
    document.getElementById("who").textContent = data.me.login_id || data.me.name;
    lastSupportAt = new Date();
    render();
  }

  document.getElementById("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const error = document.getElementById("login-error");
    error.textContent = "";
    const res = await fetch("/family-group/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ login_id: form.login_id.value.trim(), password: form.password.value }),
    }).catch(() => null);
    if (!res || !res.ok) {
      error.textContent = res && res.status < 500 ? "아이디 또는 비밀번호가 맞지 않아요." : "로그인하지 못했어요. 잠시 뒤 다시 해 주세요.";
      return;
    }
    setToken((await res.json()).access_token);
    form.password.value = "";
    document.getElementById("app").hidden = false;
    start();
  });

  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-action='logout']")) {
      setToken(null);
      showLogin();
      return;
    }
    // 좁은 화면: 햄버거로 메뉴를 열고, 바깥이나 메뉴 항목을 누르면 닫는다
    if (e.target.closest("[data-action='open-menu']")) {
      document.getElementById("app").classList.add("open");
      return;
    }
    if (e.target.closest("[data-action='close-menu']") || e.target.closest("#tabs a")) {
      document.getElementById("app").classList.remove("open");
      if (!e.target.closest("#tabs a")) return;
    }
    if (e.target.closest("[data-action='refresh-support']")) {
      refreshSupport();
      return;
    }
    // '답변하기': 그 문의를 펼치고 답변 칸으로 바로 간다
    const reply = e.target.closest("[data-reply]");
    if (reply) {
      const box = document.querySelector(`details[data-open="${CSS.escape(reply.dataset.reply)}"]`);
      if (!box) return;
      box.open = true;
      openTicket = reply.dataset.reply;
      const area = box.querySelector("textarea");
      area.scrollIntoView({ block: "center" });
      area.focus();
      return;
    }
    const step = e.target.closest("[data-ticket]");
    if (step) {
      step.disabled = true;
      updateTicket(step.dataset.ticket, { status: step.dataset.next });
      return;
    }
    const edit = e.target.closest("[data-notice-edit]");
    if (edit) {
      editingNotice = edit.dataset.noticeEdit;
      render();
      document.querySelector("[data-notice-form] input[name=title]").focus();
      return;
    }
    if (e.target.closest("[data-action='write-notice']")) {
      writingNotice = true;
      render();
      document.querySelector("[data-notice-form] input[name=title]").focus();
      return;
    }
    if (e.target.closest("[data-action='cancel-notice']")) {
      editingNotice = null;
      writingNotice = false;
      render();
      return;
    }
    const del = e.target.closest("[data-notice-delete]");
    if (del && window.confirm("이 공지를 지울까요? 앱에서도 바로 사라지고 되돌릴 수 없어요.")) {
      del.disabled = true;
      saveNotice(`/admin/service/notices/${encodeURIComponent(del.dataset.noticeDelete)}`, undefined, "DELETE");
    }
  });

  // 펼친 문의를 기억해 두면 저장 뒤 다시 그려도 열린 채로 남는다
  document.addEventListener(
    "toggle",
    (e) => {
      const el = e.target;
      if (!el.dataset || !el.dataset.open) return;
      if (el.open) openTicket = el.dataset.open;
      else if (openTicket === el.dataset.open) openTicket = null;
    },
    true,
  );

  document.addEventListener("submit", (e) => {
    const nf = e.target.closest("[data-notice-form]");
    if (nf) {
      e.preventDefault();
      const f = nf.elements; // form.title 은 폼의 title 속성이라 elements 로 칸을 찾는다
      const body = { category: f.category.value, title: f.title.value.trim(), body: f.body.value.trim() };
      if (!body.title || !body.body) return;
      nf.querySelector("button[type=submit]").disabled = true;
      if (editingNotice) saveNotice(`/admin/service/notices/${encodeURIComponent(editingNotice)}`, body, "PUT");
      else saveNotice("/admin/service/notices", body, "POST");
      return;
    }
    const form = e.target.closest("[data-answer]");
    if (!form) return;
    e.preventDefault();
    const answer = form.answer.value.trim();
    if (!answer) return;
    form.querySelector("button").disabled = true;
    updateTicket(form.dataset.answer, { answer });
  });

  document.addEventListener("change", (e) => {
    const el = e.target.closest("[data-filter]");
    if (!el) return;
    filters[el.dataset.filter] = el.value;
    render();
  });

  window.addEventListener("hashchange", () => {
    render();
    if (current() === "support") refreshSupport(); // 탭에 들어올 때마다 최신으로
  });
  // 새 문의가 F5 없이 보이도록: 창으로 돌아올 때와 15초마다 목록만 다시 받는다
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refreshSupport();
  });
  setInterval(() => {
    if (document.visibilityState === "visible") refreshSupport();
  }, 15000);

  if (token()) start();
  else showLogin();
})();
