// 가비 관리자 화면(서비스 관리). 서버가 /admin/ui 로 내려준다.
// 회원·가족 그룹·기능·테스터는 로그인한 뒤 /admin/* API 의 실제 데이터를 쓴다.
// AI 이용·피드백·문의는 저장할 표가 아직 없어 mock.js 예시를 보여 준다(2단계에서 연결). 그쪽 상태 버튼은 화면에서만 바뀐다.
(function () {
  "use strict";

  const TABS = [
    ["members", "회원 관리"],
    ["groups", "가족 그룹 관리"],
    ["features", "기능 관리"],
    ["ai", "AI 이용 현황"],
    ["testers", "테스터 관리"],
    ["feedback", "사용자 피드백"],
    ["support", "문의 및 신고"],
  ];
  const TOKEN_KEY = "gabee_admin_token";

  // 예시 목록의 상태: 화면 글자, 표시 색, 버튼 글자, 버튼을 누르면 바뀔 상태
  const STATUS = {
    feedback: {
      new: { label: "새로 옴", cls: "hot", action: "확인함", next: "seen" },
      seen: { label: "확인함", cls: "", action: "반영 예정", next: "planned" },
      planned: { label: "반영 예정", cls: "ok", action: "반영됨", next: "done" },
      done: { label: "반영됨", cls: "ok" },
    },
    support: {
      new: { label: "접수", cls: "hot", action: "처리 시작", next: "working" },
      working: { label: "처리 중", cls: "", action: "처리 완료", next: "done" },
      done: { label: "처리 완료", cls: "ok" },
    },
  };

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
   * @returns {Promise<any>}
   */
  async function api(path) {
    const res = await fetch(path, { headers: { Authorization: `Bearer ${token()}` } });
    if (res.status === 401) {
      setToken(null);
      showLogin("로그인이 만료됐어요. 다시 로그인해 주세요.");
      throw new Error("unauthorized");
    }
    if (res.status === 404 && path === "/admin/me") throw new Error("not_staff");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  /**
   * 화면 데이터를 가져온다. 실제 데이터 4개 + 아직 표가 없는 메뉴의 예시.
   * @returns {Promise<object>}
   */
  async function loadData() {
    const [me, members, groups, features, testers] = await Promise.all(
      ["/admin/me", "/admin/members", "/admin/groups", "/admin/features", "/admin/testers"].map(api),
    );
    const mock = window.ADMIN_MOCK;
    return { me, members, groups, features, testers, ai: mock.ai, feedback: mock.feedback, support: mock.support };
  }

  // ── 그리기 도우미 ─────────────────────────────────────

  const num = (n) => Number(n).toLocaleString("ko-KR");
  const pct = (n) => `${Math.max(0, Math.min(100, Number(n) || 0))}%`;
  const count = (rows, status) => rows.filter((r) => r.status === status).length;
  const day = (iso) => (iso ? new Date(iso).toLocaleDateString("sv-SE") : "-"); // YYYY-MM-DD

  function ago(iso) {
    if (!iso) return "기록 없음";
    const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
    return days <= 0 ? "오늘" : days === 1 ? "어제" : `${days}일 전`;
  }

  function stat(label, value, sub = "", tone = "") {
    return `<div class="stat"><span class="stat-label">${esc(label)}</span><span class="stat-value">${esc(value)}</span><span class="stat-sub ${tone}">${esc(sub)}</span></div>`;
  }

  function head(title, sub, sample = false) {
    const banner = sample ? '<p class="sample">예시 화면이에요. 저장할 곳이 아직 없어서 2단계에서 실제 데이터로 연결돼요.</p>' : "";
    return `<div class="head"><div><h1>${esc(title)}</h1><p class="sub">${esc(sub)}</p></div></div>${banner}`;
  }

  function bar(n) {
    return `<div class="bar"><span style="width:${pct(n)}"></span></div>`;
  }

  function table(columns, rows) {
    const th = columns.map((c) => `<th class="${c.num ? "num" : ""}">${esc(c.label)}</th>`).join("");
    const body = rows.length ? rows.join("") : `<tr><td colspan="${columns.length}" class="small">해당하는 항목이 없어요</td></tr>`;
    return `<div class="table-wrap"><table><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  /** 상태 표시 + 상태 바꾸기 버튼(예시 목록 전용). i 는 원래 목록에서의 위치다. */
  function statusCells(list, row, i) {
    const s = STATUS[list][row.status];
    const btn = s.next ? `<button type="button" class="btn sm" data-list="${list}" data-i="${i}">${esc(s.action)}</button>` : "";
    return `<td><span class="pill ${s.cls}">${esc(s.label)}</span></td><td class="num">${btn}</td>`;
  }

  // ── 탭별 화면 ─────────────────────────────────────────

  const filters = { memberQ: "", feedbackKind: "" };

  function viewMembers(d) {
    const word = filters.memberQ.toLowerCase();
    const rows = d.rows
      .filter((u) => !word || u.name.toLowerCase().includes(word) || (u.login_id || "").toLowerCase().includes(word))
      .map((u) => `<tr><td><strong>${esc(u.name)}</strong></td><td>${esc(u.login_id || "-")}</td><td>${day(u.joined_at)}</td><td>${u.has_family ? "있음" : "없음"}</td><td>${ago(u.last_login_at)}</td></tr>`);
    return `${head("회원 관리", "가입자 수 · 가입일 · 계정 상태")}
      <section class="grid">
        ${stat("전체 가입자", `${num(d.total)}명`)}
        ${stat("이번 주 가입", `${num(d.joined_this_week)}명`, "최근 7일", "up")}
        ${stat("가족 없는 회원", `${d.rows.filter((u) => !u.has_family).length}명`, "아래 목록 기준")}
        ${stat("계정 상태", "준비 중", "정지 기능은 2단계")}
      </section>
      <section class="card">
        <div class="filters">
          <label class="field">이름·아이디 검색<input type="search" data-filter="memberQ" value="${esc(filters.memberQ)}" placeholder="예: test"></label>
        </div>
        ${table([{ label: "이름" }, { label: "아이디" }, { label: "가입일" }, { label: "가족" }, { label: "마지막 로그인" }], rows)}
        <span class="small">최근 가입순 최대 200명</span>
      </section>`;
  }

  function viewGroups(d) {
    const memberSum = d.rows.reduce((a, g) => a + g.members, 0);
    const maxSize = Math.max(1, ...d.sizes.map((s) => s.groups));
    const alone = d.sizes.find((s) => s.members <= 1);
    const sizes = d.sizes.length
      ? d.sizes.map((s) => `<div><div class="line-item" style="border:0;padding:0 0 6px"><span>${esc(s.members)}명</span><strong>${esc(s.groups)}개</strong></div>${bar((s.groups / maxSize) * 100)}</div>`).join("")
      : '<p class="small">아직 가족 그룹이 없어요</p>';
    const rows = d.rows.map((g) => `<tr><td><strong>${esc(g.name)}</strong></td><td>${esc(g.owner_name || "-")}</td><td class="num">${esc(g.members)}명</td><td>${day(g.created_at)}</td></tr>`);
    return `${head("가족 그룹 관리", "가족 그룹 수 · 구성원 수")}
      <section class="grid">
        ${stat("가족 그룹", `${num(d.total)}개`)}
        ${stat("평균 구성원", d.rows.length ? `${(memberSum / d.rows.length).toFixed(1)}명` : "-")}
        ${stat("혼자인 그룹", `${alone ? alone.groups : 0}개`, "아직 아무도 초대 안 함")}
      </section>
      <section class="row">
        <div class="card wide"><h2>가족 그룹 목록</h2>${table([{ label: "그룹 이름" }, { label: "대표" }, { label: "구성원", num: true }, { label: "만든 날" }], rows)}</div>
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
        <span class="small">일정은 만든 일정, 소통은 보낸 메시지, 돌봄은 기록, 정산은 등록한 지출 개수예요. AI 채팅은 'AI 이용 현황'에서 봐요.</span>
      </section>`;
  }

  function viewAi(d) {
    const max = Math.max(...d.daily);
    const days = d.daily.map((c) => `<div title="${c}회"><i style="height:${pct((c / max) * 100)}"></i></div>`).join("");
    const top = Math.max(...d.rows.map((r) => r.calls));
    const rows = d.rows
      .map((r) => `<div class="meter"><strong>${esc(r.name)}</strong><div class="bar plain"><span style="width:${pct((r.calls / top) * 100)}"></span></div><span class="num">${num(r.calls)}회</span></div>`)
      .join("");
    return `${head("AI 이용 현황", "AI 채팅 횟수 · 기능별 호출량", true)}
      <section class="grid">
        ${stat("오늘 AI 채팅", `${num(d.today)}회`)}
        ${stat("이번 주", `${num(d.week)}회`)}
        ${stat("이번 달", `${num(d.month)}회`)}
      </section>
      <section class="card">
        <h2>일별 AI 채팅 (최근 14일)</h2>
        <div class="chart" role="img" aria-label="최근 14일 하루 AI 채팅 횟수">${days}</div>
        <div class="axis"><span>14일 전</span><span>오늘</span></div>
      </section>
      <section class="card">
        <h2>기능별 호출량 (이번 달)</h2>
        <p class="note">각 기능이 AI를 몇 번 불렀는지예요. 가장 많은 기능을 꽉 찬 막대로 놓고 비교해요.</p>
        ${rows}
      </section>`;
  }

  function viewTesters(d) {
    const rows = d.rows.map((t) => `<tr><td><strong>${esc(t.name)}</strong></td><td>${esc(t.login_id || "-")}</td><td>${day(t.consent_at)}</td><td>${esc(t.consent_version || "-")}</td></tr>`);
    return `${head("테스터 관리", "테스터 목록 · 테스트 진행 상황")}
      <section class="grid">
        ${stat("테스터", `${d.rows.length}명`, "테스터 참여에 동의한 회원")}
        ${stat("테스트 진행 상황", "준비 중", "2단계에서 연결")}
      </section>
      <section class="card"><h2>테스터 목록</h2>${table([{ label: "이름" }, { label: "아이디" }, { label: "동의한 날" }, { label: "동의서 버전" }], rows)}</section>`;
  }

  function viewFeedback(d) {
    const kinds = ["의견", "불편 사항", "개선 요청"];
    const chips = ["", ...kinds]
      .map((k) => `<button type="button" class="chip" data-kind="${k}" aria-pressed="${filters.feedbackKind === k}">${k || "전체"}</button>`)
      .join("");
    const rows = d.rows
      .map((f, i) => [f, i])
      .filter(([f]) => !filters.feedbackKind || f.kind === filters.feedbackKind)
      .map(([f, i]) => `<tr><td><span class="pill">${esc(f.kind)}</span></td><td>${esc(f.feature)}</td><td>${esc(f.text)}</td><td>${esc(f.date)}</td>${statusCells("feedback", f, i)}</tr>`);
    return `${head("사용자 피드백", "의견 · 불편 사항 · 개선 요청", true)}
      <section class="grid">
        ${kinds.map((k) => stat(k, `${d.rows.filter((f) => f.kind === k).length}건`)).join("")}
        ${stat("새로 온 피드백", `${count(d.rows, "new")}건`, "아직 확인 안 함", "warn")}
      </section>
      <section class="card">
        <div class="card-head"><h2>피드백 목록</h2><div role="group" aria-label="종류" style="display:flex;gap:6px;flex-wrap:wrap">${chips}</div></div>
        ${table([{ label: "종류" }, { label: "기능" }, { label: "내용" }, { label: "받은 날" }, { label: "상태" }, { label: "" }], rows)}
      </section>`;
  }

  function viewSupport(d) {
    const rows = d.rows.map((s, i) => `<tr><td>#${esc(s.no)}</td><td><span class="pill ${s.kind === "신고" ? "bad" : ""}">${esc(s.kind)}</span></td><td>${esc(s.title)}</td><td>${esc(s.date)}</td>${statusCells("support", s, i)}</tr>`);
    return `${head("문의 및 신고", "문의 현황 · 처리 상태", true)}
      <section class="grid">
        ${stat("새 문의·신고", `${count(d.rows, "new")}건`, "", "warn")}
        ${stat("처리 중", `${count(d.rows, "working")}건`)}
        ${stat("처리 완료", `${count(d.rows, "done")}건`, "", "up")}
        ${stat("신고", `${d.rows.filter((s) => s.kind === "신고").length}건`, "문의와 따로 셈")}
      </section>
      <section class="card"><h2>문의·신고 목록</h2>${table([{ label: "번호" }, { label: "종류" }, { label: "제목" }, { label: "받은 날" }, { label: "상태" }, { label: "" }], rows)}</section>`;
  }

  const VIEWS = {
    members: (data) => viewMembers(data.members),
    groups: (data) => viewGroups(data.groups),
    features: (data) => viewFeatures(data.features),
    ai: (data) => viewAi(data.ai),
    testers: (data) => viewTesters(data.testers),
    feedback: (data) => viewFeedback(data.feedback),
    support: (data) => viewSupport(data.support),
  };

  // ── 화면 그리기 ───────────────────────────────────────

  let data = null;

  function current() {
    const key = location.hash.replace("#", "");
    return VIEWS[key] ? key : "members";
  }

  function render() {
    if (!data) return;
    const key = current();
    document.getElementById("tabs").innerHTML = TABS.map(
      ([k, label]) => `<a href="#${k}" aria-current="${k === key ? "page" : "false"}">${label}</a>`,
    ).join("");
    document.getElementById("view").innerHTML = VIEWS[key](data);
    document.title = `가비 관리자 · ${TABS.find(([k]) => k === key)[1]}`;
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
    document.getElementById("who").textContent = `관리자 · ${data.me.login_id || data.me.name}`;
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
    const step = e.target.closest("[data-list]");
    if (step) {
      const row = data[step.dataset.list].rows[Number(step.dataset.i)];
      row.status = STATUS[step.dataset.list][row.status].next;
      render();
      return;
    }
    const chip = e.target.closest("[data-kind]");
    if (chip) {
      filters.feedbackKind = chip.dataset.kind;
      render();
    }
  });

  document.addEventListener("change", (e) => {
    const el = e.target.closest("[data-filter]");
    if (!el) return;
    filters[el.dataset.filter] = el.value;
    render();
  });

  window.addEventListener("hashchange", render);

  if (token()) start();
  else showLogin();
})();
