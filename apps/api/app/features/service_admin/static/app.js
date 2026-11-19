// 가비 서비스 관리자 화면. 서버가 /admin/service/ui 로 내려준다.
// 모든 탭은 로그인한 뒤 /admin/service/* API 의 실제 데이터를 쓴다. 문의·신고(상태·답변)와 공지사항(쓰기·고치기·지우기)만 바꿀 수 있다.
(function () {
  "use strict";

  // 왼쪽 메뉴: 묶음 제목과 그 안의 탭. 요약(데이터 분석)을 먼저, 할 일(문의·공지)은 아래에 모은다. 첫 화면은 맨 위 탭.
  const TAB_GROUPS = [
    ["한눈에", [["analytics", "데이터 분석"]]],
    ["사람", [["members", "회원 관리"], ["groups", "가족 그룹 관리"]]],
    ["사용", [["features", "기능 관리"], ["ai", "AI 이용 현황"]]],
    ["운영 업무", [["alerts", "알림"], ["support", "문의 및 신고"], ["notices", "공지사항"]]],
    // 운영 관리자 화면(서버 상태). 권한은 통합관리자 하나라 로그인한 관리자에게 모두 보인다.
    ["운영", [["ops", "서버 상태"]]],
  ];
  const TABS = TAB_GROUPS.flatMap(([, tabs]) => tabs);
  const TOKEN_KEY = "gabee_admin_token";
  const THEME_KEY = "gabee_admin_theme"; // light 나 dark. 없으면 컴퓨터 설정을 따른다

  /** 지금 보이는 화면 모드. 고른 값이 없으면 컴퓨터 설정이다. */
  function currentTheme() {
    return document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }

  /** 화면 모드를 적용한다. 운영 탭(iframe)이 열려 있으면 같이 바꾼다. */
  function applyTheme(theme) {
    if (theme) document.documentElement.dataset.theme = theme;
    const frame = document.querySelector(".ops-frame");
    if (theme && frame && frame.contentDocument) frame.contentDocument.documentElement.dataset.theme = theme;
    document.getElementById("theme-toggle").setAttribute("aria-checked", String(currentTheme() === "dark"));
  }

  function toggleTheme() {
    const next = currentTheme() === "dark" ? "light" : "dark";
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      // 저장이 막힌 브라우저면 새로고침할 때 컴퓨터 설정으로 돌아간다
    }
    applyTheme(next);
  }

  try {
    applyTheme(localStorage.getItem(THEME_KEY));
  } catch {
    applyTheme(null);
  }

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
    const [me, members, groups, features, ai, support, notices, analytics] = await Promise.all(
      ["/admin/service/me", "/admin/service/members", "/admin/service/groups", "/admin/service/features", "/admin/service/ai-usage", "/admin/service/support", "/admin/service/notices", "/admin/service/analytics"].map((p) => api(p)),
    );
    // 알림은 따로 받는다. 알림 표가 아직 없는 DB 에서도 나머지 화면은 열려야 하므로 실패하면 빈 목록으로 둔다(로그인 만료는 그대로 넘긴다)
    const alerts = await api("/admin/alerts").catch((err) => {
      if (err.message === "unauthorized") throw err;
      return { items: [], unacked: 0 };
    });
    return { me, members, groups, features, ai, support, notices, analytics, alerts };
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
    analytics: "M3 3v18h18M7 15l4-4 3 3 5-6",
    ops: "M3 4h18v6H3zM3 14h18v6H3zM7 7h.01M7 17h.01",
    alerts: "M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0",
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

  // 회원 관리 카드를 누르면 보이는 하루 그래프: 카드 key → (서버 칸, 그래프 제목, 아래 합계 문구)
  const MEMBER_METRICS = {
    total: { field: "daily_total", title: "날짜별 전체 가입자", foot: (s) => `오늘 ${num(s.at(-1))}명` },
    joined: { field: "daily_joined", title: "날짜별 가입", foot: (s) => `30일 동안 ${num(s.reduce((a, c) => a + c, 0))}명` },
    active: { field: "daily_active", title: "날짜별 활성 사용자", foot: (s) => `가장 많은 날 ${num(Math.max(0, ...s))}명` },
    no_family: { field: "daily_no_family", title: "날짜별 가족 없는 회원", foot: (s) => `오늘 ${num(s.at(-1))}명` },
    verified: { field: "daily_verified", title: "날짜별 이메일 인증", foot: (s) => `오늘 ${num(s.at(-1))}명` },
  };
  let memberMetric = "joined";

  /** 누를 수 있는 요약 카드(누르면 아래 그래프가 그 항목으로 바뀐다). */
  function statButton(key, label, value, sub = "", tone = "") {
    const on = key === memberMetric;
    return `<button type="button" class="stat clickable" data-metric="${key}" aria-pressed="${on}"><span class="stat-label">${esc(label)}</span><span class="stat-value">${esc(value)}</span><span class="stat-sub ${tone}">${esc(sub)}</span></button>`;
  }

  /** 30일 전 → 오늘 막대. 날짜는 한국 시간 기준 MM-DD. */
  function dailyChart(series, label) {
    const top = Math.max(1, ...series);
    const kst = (offset) => new Date(Date.now() + 9 * 3600000 - offset * 86400000).toISOString().slice(5, 10);
    const bars = series.map((c, i) => `<div title="${kst(series.length - 1 - i)} · ${c}명"><i style="height:${pct((c / top) * 100)}"></i></div>`).join("");
    return `<div class="chart" role="img" aria-label="${esc(label)}">${bars}</div>
      <div class="axis"><span>${kst(series.length - 1)}</span><span>${kst(Math.floor(series.length / 2))}</span><span>오늘 ${kst(0)}</span></div>`;
  }

  function viewMembers(d) {
    const word = filters.memberQ.toLowerCase();
    const rows = d.rows
      .filter((u) => !word || u.name.toLowerCase().includes(word) || (u.login_id || "").toLowerCase().includes(word))
      .map((u) => `<tr><td><strong>${esc(u.name)}</strong></td><td>${esc(u.login_id || "-")}</td><td>${day(u.joined_at)}</td><td>${u.has_family ? "있음" : "없음"}</td><td><span class="pill ${u.email_verified ? "ok" : ""}">${u.email_verified ? "인증" : "미인증"}</span></td><td>${ago(u.last_login_at)}</td></tr>`);
    const metric = MEMBER_METRICS[memberMetric];
    const series = d[metric.field] || [];
    const share = (n) => (d.total ? Math.round((n / d.total) * 100) : 0);
    const meter = (label, n) => `<div class="meter"><strong>${esc(label)}</strong><div class="bar"><span style="width:${pct(share(n))}"></span></div><span class="num">${num(n)}명 · ${share(n)}%</span></div>`;
    return `${head("회원 관리", "가입자 수 · 가입일 · 계정 상태 · 카드를 누르면 날짜별 그래프")}
      <section class="grid">
        ${statButton("total", "전체 가입자", `${num(d.total)}명`)}
        ${statButton("joined", "이번 주 가입", `${num(d.joined_this_week)}명`, "최근 7일", "up")}
        ${statButton("active", "활성 사용자", `${num(d.active_7d)}명`, "최근 7일")}
        ${statButton("no_family", "가족 없는 회원", `${num(d.no_family)}명`)}
        ${statButton("verified", "이메일 인증", `${num(d.email_verified)}명`, d.total ? `전체의 ${share(d.email_verified)}%` : "")}
        ${stat("계정 상태", "준비 중", "정지 기능은 2단계")}
      </section>
      <div class="row">
        <section class="card wide">
          <div class="card-head"><h2>${esc(metric.title)} (최근 30일)</h2><span class="small">${esc(metric.foot(series.length ? series : [0]))}</span></div>
          ${dailyChart(series, `${metric.title} 최근 30일`)}
        </section>
        <section class="card side">
          <h2>회원 구성</h2>
          ${meter("가족 있음", d.total - d.no_family)}
          ${meter("이메일 인증", d.email_verified)}
          ${meter("최근 7일 활성", d.active_7d)}
          <span class="small">전체 ${num(d.total)}명 기준</span>
        </section>
      </div>
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

  // ── 데이터 분석 ──────────────────────────────────────

  const percent = (v) => (v === null || v === undefined ? "-" : `${v}%`);
  const hours = (h) => (h === null || h === undefined ? "-" : h < 24 ? `${h}시간` : `${Math.round((h / 24) * 10) / 10}일`);
  /** 값이 클수록 진한 칸(비율 % 또는 최대값 대비). */
  const shade = (v, max = 100) => (v === null || v === undefined ? "" : `background: color-mix(in srgb, var(--accent) ${Math.round((Math.min(v, max) / Math.max(max, 1)) * 70)}%, transparent);`);

  // 유입 경로(utm_source) 한글 이름. 목록에 없는 값은 받은 값 그대로(esc) 보여 준다
  const SOURCE_LABEL = {
    youtube: "유튜브",
    instagram: "인스타그램",
    blog: "블로그",
    cafe: "카페",
    news: "뉴스 기사",
    qr: "QR(오프라인)",
    kakao: "카톡 공유",
    "google-play": "직접 검색(플레이 스토어)",
    unknown: "알 수 없음",
  };

  /** 데이터 분석의 유입 경로 구역. 표가 아직 없는 서버면 "준비 중"만 보인다. */
  function acquisitionCard(d) {
    const body = !d.acquisition_ready
      ? `<p class="small">유입 경로 기록표가 아직 서버 DB 에 없어요(준비 중).</p>`
      : table(
          [{ label: "경로" }, { label: "가입", num: true }, { label: "비율" }, { label: "가족 연결", num: true }],
          d.acquisition.map(
            (r) => `<tr><td><strong>${esc(SOURCE_LABEL[r.source] ?? r.source)}</strong></td><td class="num">${num(r.signups)}명</td><td style="min-width:140px">${bar(r.share)}<span class="small">${percent(r.share)}</span></td><td class="num">${percent(r.family_rate)}</td></tr>`,
          ),
        );
    return `<section class="card">
        <div class="card-head"><h2>유입 경로 (어떤 링크로 설치했나)</h2><span class="small">안드로이드 플레이 스토어 설치 꼬리표 기준. 아이폰·APK 설치·기능 이전 가입자는 "알 수 없음"</span></div>
        ${body}
      </section>`;
  }

  // 체류시간 탭 이름(앱 아래쪽 탭과 같은 말)
  const USAGE_TAB_LABEL = { chat: "AI 채팅", "family-chat": "소통", schedule: "일정", care: "지갑", my: "마이", other: "그 밖의 화면" };
  const minutes = (m) => (m === null || m === undefined ? "-" : m < 60 ? `${m}분` : `${Math.floor(m / 60)}시간 ${Math.round(m % 60)}분`);

  /** 데이터 분석의 체류시간 구역(최근 30일). 표가 아직 없는 서버면 "준비 중"만 보인다. */
  function usageCard(d) {
    const u = d.usage;
    if (!d.usage_ready || !u) {
      return `<section class="card"><div class="card-head"><h2>체류시간 (최근 30일)</h2></div><p class="small">체류시간 기록표가 아직 서버 DB 에 없어요(준비 중).</p></section>`;
    }
    const top = Math.max(1, ...u.daily.map((x) => x.avg_minutes || 0));
    const bars = u.daily
      .map((x) => `<div title="${esc(x.day)} · ${x.avg_minutes === null ? "기록 없음" : `${minutes(x.avg_minutes)} · ${num(x.users)}명`}"><i style="height:${pct(((x.avg_minutes || 0) / top) * 100)}"></i></div>`)
      .join("");
    const tabs = u.by_tab
      .map((t) => `<div class="meter"><strong>${esc(USAGE_TAB_LABEL[t.tab] ?? t.tab)}</strong>${bar(t.share)}<span class="num">${minutes(t.minutes)} · ${percent(t.share)}</span></div>`)
      .join("");
    return `<div class="row">
        <section class="card wide">
          <div class="card-head"><h2>체류시간 (최근 30일)</h2><span class="small">앱이 화면에 떠 있던 시간. 앱이 갑자기 꺼지면 그 사용분은 빠져서 실제보다 조금 적을 수 있어요</span></div>
          <section class="grid compact">
            ${stat("1명당 하루 평균", minutes(u.avg_minutes_per_day), "쓴 날 기준")}
            ${stat("1명당 하루 실행", u.avg_opens_per_day === null ? "-" : `${u.avg_opens_per_day}번`)}
            ${stat("기록된 사람", `${num(u.users)}명`)}
          </section>
          <div class="chart" style="height:90px" role="img" aria-label="날짜별 1명당 평균 사용 시간">${bars}</div>
          <div class="axis"><span>${esc(u.daily[0]?.day ?? "")}</span><span>오늘</span></div>
        </section>
        <section class="card side">
          <h2>탭별 사용 시간</h2>
          ${tabs || '<p class="small">아직 기록이 없어요</p>'}
        </section>
      </div>`;
  }

  function viewAnalytics(d) {
    const small = d.users < 30 ? `<p class="note warn">지금은 가입자가 ${num(d.users)}명뿐이라 비율이 크게 흔들려요. 숫자는 흐름만 보고, 사람이 늘면 해석해요.</p>` : "";

    // ① 재방문 코호트
    const cohortRows = d.retention.map(
      (c) => `<tr><td>${esc(c.week_start)} 주</td><td class="num">${num(c.size)}명</td>${[c.w1, c.w2, c.w4].map((v) => `<td class="num" style="${shade(v)}">${c.size ? percent(v) : "-"}</td>`).join("")}</tr>`,
    );

    // ② 가입 퍼널
    const funnel = d.funnel
      .map((s, i) => {
        const drop = i ? d.funnel[i - 1].users - s.users : 0;
        const wait = s.median_hours !== null ? ` · 가입부터 ${hours(s.median_hours)}` : "";
        return `<div><div class="meter"><strong>${esc(s.label)}</strong><div class="bar"><span style="width:${pct(s.share)}"></span></div><span class="num">${num(s.users)}명 · ${percent(s.share)}</span></div><p class="small" style="margin:2px 0 0">${i ? `앞 단계에서 ${num(drop)}명 멈춤` : "전체 가입자"}${wait}</p></div>`;
      })
      .join("");

    // ③ 가족 인원별
    const f = d.families;
    const sizeRows = f.by_size.map((s) => `<tr><td>${esc(s.label)}</td><td class="num">${num(s.families)}곳</td><td class="num">${percent(s.active_share)}</td><td class="num">${s.avg_actions ?? "-"}</td></tr>`);

    // ④ 기능 사용 지도
    const features = d.features.map((x) => `<div class="meter"><strong>${esc(x.label)}</strong><div class="bar"><span style="width:${pct(x.share)}"></span></div><span class="num">${num(x.families)}곳 · ${percent(x.share)}</span></div>`).join("");

    // ⑤ AI 품질·비용
    const ai = d.ai;
    const aiRows = ai.top_families.map((x) => `<tr><td><strong>${esc(x.name)}</strong></td><td class="num">${num(x.requests)}회</td><td class="num">${num(x.tokens)}</td></tr>`);

    // ⑥ 요일 × 시간
    const top = Math.max(1, ...d.heatmap.flat());
    const daysKo = ["월", "화", "수", "목", "금", "토", "일"];
    const heat = d.heatmap
      .map((row, i) => `<div class="heat-row"><span class="heat-day">${daysKo[i]}</span>${row.map((c, h) => `<i title="${daysKo[i]} ${h}시 · ${c}회" style="${c ? shade(Math.max(c, top / 6), top) : ""}"></i>`).join("")}</div>`)
      .join("");

    // ⑦ 고객 응대
    const s = d.support;
    const wTop = Math.max(1, ...s.weekly);
    const weekly = s.weekly.map((c) => `<div title="${c}건"><i style="height:${pct((c / wTop) * 100)}"></i></div>`).join("");

    return `${head("데이터 분석", "재방문 · 가입 퍼널 · 유입 경로 · 체류시간 · 가족 · 기능 · AI · 시간대 · 고객 응대 (개수와 시각만 사용)")}${small}
      <div class="row">
        <section class="card wide">
          <div class="card-head"><h2>① 재방문(리텐션) 코호트</h2><span class="small">가입 주별로, 가입 1·2·4주 뒤에 다시 로그인한 비율</span></div>
          ${table([{ label: "가입 주" }, { label: "가입자", num: true }, { label: "1주 뒤", num: true }, { label: "2주 뒤", num: true }, { label: "4주 뒤", num: true }], cohortRows)}
        </section>
        <section class="card side">
          <h2>② 가입 퍼널</h2>
          ${funnel}
          <span class="small">각 단계는 앞 단계를 모두 지난 사람만 세요</span>
        </section>
      </div>
      ${acquisitionCard(d)}
      ${usageCard(d)}
      <div class="row">
        <section class="card wide">
          <div class="card-head"><h2>③ 가족 인원별 활동 (최근 7일)</h2><span class="small">혼자인 가족 ${num(f.solo_families)}곳 · 두 번째 가족이 들어오기까지 ${f.days_to_second_member ?? "-"}일(중앙값)</span></div>
          ${table([{ label: "가족 인원" }, { label: "가족 수", num: true }, { label: "활동한 가족", num: true }, { label: "가족당 사용 수", num: true }], sizeRows)}
        </section>
        <section class="card side">
          <h2>④ 기능 사용 지도 (최근 30일)</h2>
          ${features}
          <span class="small">전체 가족 ${num(d.total_families)}곳 중 그 기능을 한 번이라도 쓴 가족</span>
        </section>
      </div>
      <section class="card">
        <div class="card-head"><h2>⑤ AI 품질·비용 (최근 30일)</h2><span class="small">요청 수는 메인 비서가 부른 표식·한도 거절 줄을 뺀 값</span></div>
        <section class="grid compact">
          ${stat("요청", `${num(ai.requests)}회`)}
          ${stat("활동한 사람 1명당", ai.per_active_user === null ? "-" : `${ai.per_active_user}회`, `활동 ${num(ai.active_users)}명`)}
          ${stat("오류율", percent(ai.error_rate), "", ai.error_rate > 5 ? "warn" : "")}
          ${stat("캐시 적중률", percent(ai.cache_hit_rate), "저장된 답 재사용")}
          ${stat("한도 거절", percent(ai.limit_rate))}
        </section>
        ${table([{ label: "토큰을 많이 쓴 가족" }, { label: "요청", num: true }, { label: "토큰(입력+출력)", num: true }], aiRows)}
      </section>
      <div class="row">
        <section class="card wide">
          <div class="card-head"><h2>⑥ 요일 · 시간대 활동 (최근 30일)</h2><span class="small">로그인 + AI 요청, 한국 시간. 진할수록 많아요</span></div>
          <div class="heat" role="img" aria-label="요일과 시간대별 활동">${heat}<div class="heat-row heat-axis"><span class="heat-day"></span><span>0시</span><span>6시</span><span>12시</span><span>18시</span><span>23시</span></div></div>
        </section>
        <section class="card side">
          <h2>⑦ 고객 응대</h2>
          <section class="grid compact">
            ${stat("평균 답변 시간", hours(s.avg_hours), `답변 ${num(s.answered)}건`)}
            ${stat("가장 오래 걸린", hours(s.max_hours))}
            ${stat("문의 / 신고", `${num(s.inquiries)} / ${num(s.reports)}`)}
          </section>
          <div class="chart" style="height:90px" role="img" aria-label="주별 문의·신고 수">${weekly}</div>
          <div class="axis"><span>${esc(s.week_start)} 주</span><span>이번 주</span></div>
        </section>
      </div>`;
  }

  // ── 알림 ─────────────────────────────────────────────

  let alertError = "";
  // 심각도 표시: 긴급은 빨강, 주의는 노랑, 보통은 기본 회색
  const SEVERITY_CLASS = { 긴급: "urgent", 주의: "hot", 보통: "" };

  /**
   * 알림 목록을 그린다. 문구는 서버가 만든 숫자·고정 글이라 esc 로만 넣는다.
   * @param {{items: {key: string, severity: string, message: string, menu: string, created_at: string, acked_at: string | null}[], unacked: number}} d
   * @returns {string}
   */
  function viewAlerts(d) {
    const items = d.items || [];
    const error = alertError ? `<p class="note warn">${esc(alertError)}</p>` : "";
    const rows = items.length
      ? items
          .map((a) => {
            const when = (iso) => esc(new Date(iso).toLocaleString("ko-KR"));
            const action = a.acked_at
              ? `<span class="small">확인함 · ${when(a.acked_at)}</span>`
              : `<button type="button" class="btn sm primary" data-alert-ack="${esc(a.key)}">확인함</button>`;
            return `<li class="alert-item${a.acked_at ? " is-acked" : ""}">
              <div class="alert-head"><span class="pill ${SEVERITY_CLASS[a.severity] || ""}">${esc(a.severity)}</span><span class="small">${when(a.created_at)}</span></div>
              <p class="alert-msg">${esc(a.message)}</p>
              <div class="alert-foot"><span class="small">확인할 곳: ${esc(a.menu)}</span>${action}</div>
            </li>`;
          })
          .join("")
      : '<li class="alert-empty">지금 알림이 없어요. 기준을 넘는 일이 생기면 여기에 나타나요.</li>';
    return `${head("알림", "기준을 넘은 서버 신호. 확인하면 목록과 배지에서 빠져요")}${error}
      <section class="card"><div class="card-head"><h2>알림 (확인 안 된 ${num(d.unacked || 0)}건)</h2></div><ul class="alert-list">${rows}</ul></section>`;
  }

  /**
   * 알림을 확인 처리하고 목록을 다시 받는다. 실패하면 화면에 한 줄 안내를 남긴다.
   * @param {string} key
   * @returns {Promise<void>}
   */
  async function ackAlert(key) {
    try {
      await api(`/admin/alerts/${encodeURIComponent(key)}/ack`, undefined, "POST");
      data.alerts = await api("/admin/alerts");
      alertError = "";
    } catch (err) {
      if (err.message === "unauthorized") return;
      alertError = "확인하지 못했어요. 잠시 뒤 다시 해 주세요.";
    }
    render();
  }

  const VIEWS = {
    alerts: (data) => viewAlerts(data.alerts),
    members: (data) => viewMembers(data.members),
    groups: (data) => viewGroups(data.groups),
    features: (data) => viewFeatures(data.features),
    ai: (data) => viewAi(data.ai),
    support: (data) => viewSupport(data.support),
    notices: (data) => viewNotices(data.notices),
    analytics: (data) => viewAnalytics(data.analytics),
    ops: () => viewOps(),
  };

  /**
   * 운영 관리자 화면(apps/ops-admin 복사본, static/ops/)을 같은 출처 iframe 으로 띄운다.
   * 로그인은 이 화면 하나로 끝난다: iframe 은 같은 탭의 sessionStorage 토큰을 읽어 쓴다(ops/js/embed.js).
   */
  function viewOps() {
    head("서버 상태", "운영 관리자 대시보드 · 요청·오류·인프라 상태");
    return '<iframe class="ops-frame" src="ops/?v=2" title="운영 서버 상태"></iframe>';
  }

  // ── 화면 그리기 ───────────────────────────────────────

  let data = null;

  function current() {
    const key = location.hash.replace("#", "");
    return VIEWS[key] ? key : TABS[0][0];
  }

  /** 왼쪽 메뉴(묶음 제목 + 탭). 문의 및 신고에는 아직 처리하지 않은 새 문의 건수를 붙인다. */
  function renderTabs(key) {
    const fresh = data && data.support ? Number(data.support.new) || 0 : 0;
    const unacked = data && data.alerts ? Number(data.alerts.unacked) || 0 : 0;
    const link = ([k, label]) => {
      const badge =
        k === "support" && fresh ? `<span class="tab-badge" aria-label="새 문의 ${fresh}건">${num(fresh)}</span>`
        : k === "alerts" && unacked ? `<span class="tab-badge" aria-label="확인 안 된 알림 ${unacked}건">${num(unacked)}</span>`
        : "";
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
    if (e.target.closest("[data-action='theme-toggle']")) {
      toggleTheme();
      return;
    }
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
    const alertAck = e.target.closest("[data-alert-ack]");
    if (alertAck) {
      ackAlert(alertAck.dataset.alertAck);
      return;
    }
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
    const metric = e.target.closest("[data-metric]");
    if (metric) {
      memberMetric = metric.dataset.metric;
      render();
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

  // ── 챗봇 ─────────────────────────────────────────────
  // 오른쪽 아래 작은 버튼으로 연다. 대화는 화면 메모리에만 있고 서버에 저장하지 않는다.
  // 질문은 서버가 Claude 에게 보낸다.
  const CHAT_HITS = 1;
  const CHAT_HELLO = "안녕하세요. 아래 추천 질문이나 주제를 눌러 보세요. 직접 물어보셔도 돼요.";

  // 탭마다 추천하는 질문. 팀 문서에서 답을 찾을 수 있는 것만 둔다
  const CHAT_TAB_QUESTION = {
    analytics: "활성 사용자는 어떤 기준으로 세?",
    members: "이메일 인증 안 해도 가족에 들어갈 수 있어?",
    groups: "참가 요청은 누가 승인해?",
    features: "503 오류는 언제 나와?",
    ai: "AI 하루 한도는 몇 번이야?",
    support: "답변을 고치면 사용자에게 알림이 또 가?",
    notices: "공지 올리면 사용자에게 알림이 가?",
    ops: "오류율이 몇 퍼센트면 오류 상태야?",
  };
  // 오류가 난 경로가 어느 탭의 일인지. 위에서부터 맞는 첫 줄을 쓴다
  const CHAT_ROUTE_TAB = [
    ["/admin/service/analytics", "analytics"],
    ["/admin/service/members", "members"],
    ["/admin/service/groups", "groups"],
    ["/admin/service/features", "features"],
    ["/admin/service/ai-usage", "ai"],
    ["/admin/service/support", "support"],
    ["/admin/service/notices", "notices"],
    ["/admin/", "ops"],
    ["/support", "support"],
    ["/notices", "notices"],
    ["/ai-assistant", "ai"],
    ["/family-group/groups", "groups"],
    ["/family-group", "members"],
    ["/schedule", "features"],
    ["/billing", "features"],
    ["/family-chat", "features"],
    ["/notifications", "features"],
  ];
  const CHAT_DEFAULT_TABS = ["support", "notices", "ops"]; // 최근 오류가 없을 때
  const CHAT_SUGGEST_TABS = 3;
  // 무엇을 물어볼지 모를 때 고르는 주제. 질문은 모두 admin_knowledge/faq.md 에 답이 있다
  const CHAT_TOPICS = [
    ["회원·가족", ["활성 사용자는 어떤 기준으로 세?", "이메일 인증 안 해도 가족에 들어갈 수 있어?", "참가 요청은 누가 승인해?", "계정 상태 카드는 무슨 뜻이야?"]],
    ["문의·공지", ["답변 없이 완료로 바꿀 수 있어?", "답변을 고치면 사용자에게 알림이 또 가?", "공지 올리면 사용자에게 알림이 가?", "지운 공지를 되살릴 수 있어?", "공지 종류는 어떻게 골라?"]],
    ["서버·오류", ["오류가 갑자기 늘면 뭐부터 봐?", "상태 바가 주의면 무슨 뜻이야?", "오류율이 몇 퍼센트면 오류 상태야?", "503 오류는 언제 나와?", "인스턴스 카드가 미수집이면 고장이야?"]],
    ["AI·비용", ["AI 하루 한도는 몇 번이야?", "AI 한도를 늘리려면 어디를 바꿔?"]],
    ["데이터 분석", ["재방문 코호트 표는 어떻게 읽어?", "가입자가 30명 안 되면 왜 경고가 떠?", "지난 날짜 숫자가 왜 나중에 바뀌어?"]],
    ["배포·DB", ["배포 후 이상하면 어떻게 되돌려?", "공용 DB에 직접 마이그레이션해도 돼?", "Pull Agent 는 뭐야?"]],
    ["권한·보안", ["관리자 계정은 어떻게 추가해?", "관리자 목록이 비면 어떻게 돼?", "권한은 몇 종류야?", "로그인은 얼마나 유지돼?", "관리자도 사용자 채팅 내용을 볼 수 있어?"]],
  ];
  const chatAsked = new Set(); // 이번 대화에서 이미 물어본 질문은 추천에서 뺀다
  let chatErrorChips = []; // 최근 오류 탭의 [탭 이름, 질문]

  /**
   * 오류 목록(최근 7일)에서 마지막 발생이 가장 최근인 순으로 서로 다른 탭 3개를 고른다.
   * @param {{route: string, last_seen: string}[]} items
   * @returns {string[]}
   */
  function chatErrorTabs(items) {
    const tabs = [];
    const latest = [...items].sort((a, b) => new Date(b.last_seen) - new Date(a.last_seen));
    for (const item of latest) {
      const rule = CHAT_ROUTE_TAB.find(([prefix]) => item.route.startsWith(prefix));
      if (rule && !tabs.includes(rule[1])) tabs.push(rule[1]);
      if (tabs.length === CHAT_SUGGEST_TABS) break;
    }
    return tabs;
  }

  /** 최근 오류 탭을 읽어 추천 질문을 만든다. 못 읽으면 자주 묻는 질문을 쓴다(챗봇은 막지 않는다). */
  async function chatLoadErrors() {
    let tabs = [];
    try {
      tabs = chatErrorTabs((await api("/admin/ops/errors?range=7d&limit=100")).items);
    } catch {
      tabs = [];
    }
    chatErrorChips = (tabs.length ? tabs : CHAT_DEFAULT_TABS).map((key) => [TABS.find(([k]) => k === key)[1], CHAT_TAB_QUESTION[key]]);
    return tabs.length > 0;
  }

  const chatChip = (label, question) =>
    `<button type="button" class="chat-chip" data-chat-ask="${esc(question)}">${label ? `<small>${esc(label)}</small>` : ""}${esc(question)}</button>`;

  /**
   * 추천 질문과 주제 버튼을 그린다. 답할 때마다 다시 그려서 언제든 다음 질문을 고를 수 있다.
   * @param {string} title 제목
   * @param {[string, string][]} chips [작은 글씨, 질문]
   */
  function chatRenderSuggest(title, chips) {
    const fresh = chips.filter(([, q]) => !chatAsked.has(q));
    const topics = CHAT_TOPICS.map(([name], i) => `<button type="button" class="chat-topic" data-chat-topic="${i}">${esc(name)}</button>`).join("");
    document.getElementById("chat-suggest").innerHTML =
      `${fresh.length ? `<p class="chat-suggest-title">${esc(title)}</p>${fresh.map(([label, q]) => chatChip(label, q)).join("")}` : ""}` +
      `<p class="chat-suggest-title">주제별로 보기</p><div class="chat-topics">${topics}</div>`;
  }

  /** 다음 질문을 고르는 칸을 대화 맨 아래로 옮긴다. 오류 추천을 다 물어봤으면 주제 질문에서 이어서 추천한다. */
  function chatNext(title) {
    const log = document.getElementById("chat-log");
    log.appendChild(document.getElementById("chat-suggest"));
    const rest = chatErrorChips.filter(([, q]) => !chatAsked.has(q));
    const more = CHAT_TOPICS.flatMap(([name, list]) => list.map((q) => [name, q])).filter(([, q]) => !chatAsked.has(q));
    chatRenderSuggest(title, rest.length ? rest : more.slice(0, CHAT_SUGGEST_TABS));
    log.scrollTop = log.scrollHeight;
  }

  /** 대화를 비우고 처음 상태로 돌아간다. */
  async function chatReset() {
    document.querySelectorAll("#chat-log .chat-msg").forEach((el) => el.remove());
    chatAsked.clear();
    chatAdd("bot", esc(CHAT_HELLO));
    const fromErrors = await chatLoadErrors();
    chatNext(fromErrors ? "최근 오류가 난 탭의 추천 질문" : "자주 묻는 질문");
  }

  function chatAdd(who, html) {
    const log = document.getElementById("chat-log");
    const el = document.createElement("div");
    el.className = `chat-msg ${who}`;
    el.innerHTML = html;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  // 답의 **숫자** 를 굵게 보여 준다. innerHTML 을 쓰지 않아 답에 태그가 있어도 글자로만 보인다
  function chatBold(text) {
    return text.split(/\*\*(.+?)\*\*/s).map((part, i) => {
      if (i % 2 === 0) return document.createTextNode(part);
      const strong = document.createElement("strong");
      strong.textContent = part;
      return strong;
    });
  }

  /**
   * 챗봇 질문을 보내고 서버가 보내는 단계 소식(SSE)을 도착하는 대로 하나씩 넘긴다.
   * EventSource 는 POST 와 Authorization 헤더를 못 써서 fetch 본문을 직접 읽는다.
   * @param {string} question
   * @param {(event: {step: string, label?: string, answer?: string, code?: string, message?: string}) => void} onEvent
   * @returns {Promise<void>} 스트림이 끝나면 끝난다. 401 이면 로그인 화면으로 돌아가고 "unauthorized" 로 실패한다
   */
  async function chatStream(question, onEvent) {
    const res = await fetch("/admin/knowledge/ask/stream", {
      method: "POST",
      headers: { Authorization: `Bearer ${token()}`, "Content-Type": "application/json" },
      body: JSON.stringify({ q: question }),
    });
    if (res.status === 401) {
      setToken(null);
      showLogin("로그인이 만료됐어요. 다시 로그인해 주세요.");
      throw new Error("unauthorized");
    }
    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // 소식 하나는 빈 줄(\n\n)로 끝난다. 조각이 소식 중간에서 끊겨 올 수 있어서 끝난 것만 꺼낸다
      let cut;
      while ((cut = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, cut);
        buf = buf.slice(cut + 2);
        for (const line of block.split("\n")) if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)));
      }
    }
  }

  // 답변 단계. 서버 소식(step)이 오면 그 단계가 진행 중이 되고 앞 단계는 끝난다. 오지 않고 넘어간 단계는 "건너뜀"
  const CHAT_STEPS = [
    { key: "received", label: "질문 확인", detail: "관리자 권한과 글자 수를 확인해요" },
    { key: "masked", label: "개인정보 가리기", detail: "전화번호·이메일·주소를 가린 뒤 보내요" },
    { key: "understand", label: "질문 이해", detail: "필요한 자료를 고르고 있어요" },
    { key: "tool", label: "숫자 조회", detail: "관리자 화면과 같은 기준으로 세요" },
    { key: "write", label: "답 작성", detail: "받은 결과로 문장을 만들고 있어요" },
  ];
  const secs = (ms) => (ms < 100 ? "<0.1초" : `${(ms / 1000).toFixed(1)}초`);

  /**
   * 답변 단계 카드를 대화에 붙인다.
   * @param {() => void} retry 실패했을 때 "다시 물어보기" 가 부른다
   * @returns {{step: (e: {step: string, label?: string}) => void, finish: (answer: string) => void, fail: (message: string) => void}}
   */
  function chatProgress(retry) {
    const log = document.getElementById("chat-log");
    const make = (tag, cls, text) => {
      const el = document.createElement(tag);
      if (cls) el.className = cls;
      if (text !== undefined) el.textContent = text;
      return el;
    };
    const card = make("div", "chat-msg chat-steps");
    const head = make("div", "chat-steps-head");
    const icon = make("span", "chat-steps-icon is-run");
    icon.setAttribute("aria-hidden", "true");
    const titles = make("div", "chat-steps-titles");
    const title = make("div", "chat-steps-title", "답을 찾고 있어요");
    const subtitle = make("div", "chat-steps-sub", "단계마다 진행 상황을 보여 드려요");
    titles.append(title, subtitle);
    const clock = make("span", "chat-steps-time", "0.0초");
    head.append(icon, titles, clock);
    const bar = make("div", "chat-steps-bar");
    const fill = make("div", "chat-steps-fill");
    bar.append(fill);
    const list = make("ol", "chat-steps-list");
    const rows = CHAT_STEPS.map((s) => {
      const li = make("li", "chat-step is-todo");
      const dot = make("span", "chat-step-dot");
      dot.setAttribute("aria-hidden", "true");
      const body = make("div", "chat-step-body");
      const name = make("div", "chat-step-name", s.label);
      const detail = make("div", "chat-step-detail", s.detail);
      const chips = make("div", "chat-step-chips");
      body.append(name, detail, chips);
      const time = make("span", "chat-step-time", "");
      li.append(dot, body, time);
      list.append(li);
      return { li, detail, chips, time, state: "todo", started: 0, tools: [] };
    });
    card.append(head, bar, list);
    log.appendChild(card);
    log.scrollTop = log.scrollHeight;

    const t0 = performance.now();
    let current = -1;
    const timer = setInterval(() => {
      if (!card.isConnected) return clearInterval(timer); // 대화 비우기로 카드가 사라졌다
      clock.textContent = secs(performance.now() - t0);
    }, 100);
    const set = (i, state) => {
      rows[i].state = state;
      rows[i].li.className = `chat-step is-${state}`;
    };
    const close = (i, now) => {
      if (rows[i].state !== "active") return;
      set(i, "done");
      rows[i].time.textContent = secs(now - rows[i].started);
    };
    const progress = () => {
      const done = rows.filter((r) => r.state === "done" || r.state === "skip").length;
      fill.style.width = `${Math.round((done / rows.length) * 100)}%`;
    };
    const stop = (state, heading, sub, end) => {
      clearInterval(timer);
      clock.textContent = secs(end - t0); // 화면을 천천히 넘겨도 총 시간은 실제로 걸린 시간이다
      icon.className = `chat-steps-icon is-${state}`;
      card.classList.add(`is-${state}`);
      title.textContent = heading;
      subtitle.textContent = sub;
    };

    // at 은 소식이 실제로 도착한 시각이다. 단계 시간은 이 값으로 잰다(화면에 그린 시각이 아니다)
    const showStep = (e, at) => {
      const i = CHAT_STEPS.findIndex((s) => s.key === e.step);
      if (i < 0) return;
      if (e.step === "tool" && e.label && !rows[3].tools.includes(e.label)) {
        rows[3].tools.push(e.label);
        rows[3].chips.append(make("span", "chat-step-chip", e.label));
      }
      if (i <= current) return; // 답을 쓰다가 도구를 한 번 더 부른 경우: 칩만 늘린다
      for (let j = 0; j < i; j += 1) {
        if (rows[j].state === "active") close(j, at);
        else if (rows[j].state === "todo") set(j, "skip");
      }
      set(i, "active");
      rows[i].started = at;
      current = i;
      progress();
      log.scrollTop = log.scrollHeight;
    };

    // 숫자 조회는 0.03초, 답 작성은 0.5초쯤이라 그대로 그리면 눈에 안 보인다.
    // 소식은 도착 순서대로 줄을 세우고, 단계가 바뀔 때는 지금 보이는 단계가 MIN_STEP_MS 만큼 보인 뒤에 그린다.
    // 단계 옆 시간과 총 시간은 실제 값이다(보여 주는 속도만 늦춘다)
    const MIN_STEP_MS = { received: 500, masked: 500, understand: 1000, tool: 1500, write: 1500 };
    const DONE_HOLD_MS = 2000; // 다 끝난 카드를 접기 전에 보여 주는 시간
    let queue = Promise.resolve();
    let shownAt = 0;
    const later = (paced, draw) => {
      const at = performance.now();
      queue = queue.then(async () => {
        if (paced()) {
          const min = current >= 0 ? MIN_STEP_MS[CHAT_STEPS[current].key] : 0;
          const wait = shownAt + min - performance.now();
          if (wait > 0) await new Promise((r) => setTimeout(r, wait));
          shownAt = performance.now();
        }
        draw(at);
      });
    };
    const moves = (e) => () => CHAT_STEPS.findIndex((s) => s.key === e.step) > current;

    return {
      step(e) {
        later(moves(e), (at) => showStep(e, at));
      },
      finish(answer) {
        later(() => true, (at) => showFinish(answer, at));
      },
      fail(message) {
        later(() => false, (at) => showFail(message, at)); // 실패는 기다리지 않고 바로 알린다
      },
      /** 줄 선 소식을 다 그리면 끝난다. @returns {Promise<void>} */
      idle: () => queue,
    };

    function showFinish(answer, at) {
      rows.forEach((r, i) => (r.state === "active" ? close(i, at) : r.state === "todo" && set(i, "skip")));
      rows.forEach((r) => r.state === "skip" && (r.time.textContent = "건너뜀"));
      if (rows[3].state === "skip") rows[3].detail.textContent = "숫자가 필요 없는 질문이라 세지 않았어요";
      progress();
      stop("done", "답을 만들었어요", "", at);
      const total = clock.textContent;
      // 답은 바로 보여 주고, 다 끝난 카드는 DONE_HOLD_MS 뒤에 접는다. 아래 버튼으로 다시 펼친다
      const reply = chatAdd("bot", "");
      reply.replaceChildren(...chatBold(answer));
      const used = rows.filter((r) => r.state === "done").length;
      const tools = rows[3].tools.length;
      const toggle = make("button", "chat-msg chat-steps-toggle");
      toggle.type = "button";
      const summary = `처리 과정 보기 · ${used}단계 · ${total} · ${tools ? `도구 ${tools}개` : "도구 없음"}`;
      toggle.textContent = summary;
      toggle.setAttribute("aria-expanded", "false");
      toggle.addEventListener("click", () => {
        const open = card.hidden;
        card.hidden = !open;
        toggle.setAttribute("aria-expanded", String(open));
        toggle.textContent = open ? "처리 과정 접기" : summary;
      });
      log.scrollTop = log.scrollHeight;
      setTimeout(() => {
        if (!card.isConnected) return; // 그 사이 대화를 비웠다
        card.hidden = true;
        reply.after(toggle);
        log.scrollTop = log.scrollHeight;
      }, DONE_HOLD_MS);
    }

    function showFail(message, at) {
      const i = current >= 0 ? current : 0;
      if (rows[i].state === "active" || rows[i].state === "todo") {
        set(i, "fail");
        rows[i].time.textContent = "실패";
      }
      progress();
      stop("fail", "답하지 못했어요", "숫자를 추측해서 답하지 않았어요", at);
      const box = make("div", "chat-steps-error");
      box.append(make("span", "", message));
      const again = make("button", "chat-steps-retry", "다시 물어보기");
      again.type = "button";
      again.addEventListener("click", () => {
        again.disabled = true;
        retry();
      });
      box.append(again);
      card.append(box);
      log.scrollTop = log.scrollHeight;
    }
  }

  async function chatAsk(question) {
    chatAsked.add(question);
    chatAdd("me", esc(question));
    const progress = chatProgress(() => chatAsk(question));
    let ended = false;
    try {
      await chatStream(question, (e) => {
        if (e.step === "answer") {
          ended = true;
          progress.finish(e.answer || "");
        } else if (e.step === "error") {
          ended = true;
          progress.fail(e.message || "지금은 답할 수 없어요. 잠시 뒤 다시 해 주세요.");
        } else {
          progress.step(e);
        }
      });
      // answer·error 없이 끝났다: 중간에 연결이 끊겼다
      if (!ended) progress.fail("연결이 끊겼어요. 잠시 뒤 다시 해 주세요.");
    } catch (err) {
      if (err.message === "unauthorized") {
        // 로그인 화면으로 넘어갔다. 카드가 돌아가는 채로 멈춰 보이지 않게 알려 둔다
        progress.fail("로그인이 풀려서 답하지 못했어요. 다시 로그인한 뒤 물어봐 주세요.");
        chatAsked.delete(question);
      } else {
        progress.fail(err.message === "HTTP 503" ? "AI 연결이 준비되지 않았어요. 잠시 뒤 다시 해 주세요." : "지금은 답할 수 없어요. 잠시 뒤 다시 해 주세요.");
      }
    }
    await progress.idle(); // 단계를 천천히 그리는 중이면 답이 뜬 뒤에 추천 질문을 붙인다
    chatNext("이어서 물어볼 만한 질문");
  }

  function chatToggle() {
    const panel = document.getElementById("chat-panel");
    panel.hidden = !panel.hidden;
    document.querySelector(".chat-fab").setAttribute("aria-expanded", String(!panel.hidden));
    if (panel.hidden) return;
    // 처음 열 때만 인사한다. 이어서 쓰던 대화는 그대로 둔다
    if (!document.querySelector("#chat-log .chat-msg")) chatReset();
    document.querySelector("#chat-form input").focus();
  }

  /** 입력칸의 질문을 보낸다. */
  function chatSend() {
    const input = document.querySelector("#chat-form input");
    const question = input.value.trim();
    if (!question) return;
    // 한글 Enter 는 글자 확정과 Enter 로 두 번 들어올 수 있다. 먼저 비워서 두 번째는 빈칸으로 끝나게 한다
    input.value = "";
    if (question.length < 2) {
      // 서버도 두 글자 미만은 받지 않는다(AdminAskIn). 조용히 무시하면 고장처럼 보인다
      chatAdd("bot", esc("두 글자 이상으로 물어봐 주세요. 예: 회원 몇 명이야"));
      return;
    }
    chatAsk(question);
  }

  document.getElementById("chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    e.stopPropagation();
    chatSend();
  });

  // 한글은 마지막 글자가 조합 중이면 Enter 가 글자 확정으로만 쓰여 전송이 안 될 수 있다.
  // 조합 중의 Enter 는 기억해 두었다가 조합이 끝나면 보낸다.
  let chatSendAfterIme = false;
  const chatInput = document.querySelector("#chat-form input");
  chatInput.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.keyCode !== 229) return;
    if (e.isComposing || e.keyCode === 229) {
      if (e.key === "Enter" || e.code === "Enter" || e.code === "NumpadEnter") chatSendAfterIme = true;
      return;
    }
    e.preventDefault();
    chatSend();
  });
  chatInput.addEventListener("compositionend", () => {
    if (!chatSendAfterIme) return;
    chatSendAfterIme = false;
    setTimeout(chatSend, 0);
  });

  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-action='chat-toggle']")) chatToggle();
    if (e.target.closest("[data-action='chat-clear']")) chatReset();
    const chip = e.target.closest("[data-chat-ask]");
    if (chip) chatAsk(chip.dataset.chatAsk);
    const topic = e.target.closest("[data-chat-topic]");
    if (topic) {
      const [name, list] = CHAT_TOPICS[Number(topic.dataset.chatTopic)];
      chatRenderSuggest(`${name} 질문`, list.map((q) => ["", q]));
      document.getElementById("chat-log").scrollTop = 1e9;
    }
  });

  window.addEventListener("gabee-admin-expired", () => {
    setToken(null);
    showLogin("로그인이 만료됐어요. 다시 로그인해 주세요.");
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
