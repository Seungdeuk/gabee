// 가비 소개 사이트: 기능 무대(탭·시연 재생)와 화면 나타나기.
// 스크립트가 없어도 모든 글은 그대로 보인다(html 에 js 클래스가 없으면 전부 펼친다).
(function () {
  "use strict";
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // 머리줄: 조금 내려가면 아래 선을 보인다
  const top = document.querySelector(".top");
  if (top) {
    const onScroll = () => top.classList.toggle("stuck", window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  // 구역이 화면에 들어올 때 한 번 떠오른다
  const reveals = document.querySelectorAll(".rv");
  if ("IntersectionObserver" in window && !still) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
    }, { rootMargin: "0px 0px -8% 0px" });
    reveals.forEach((el) => io.observe(el));
  } else {
    reveals.forEach((el) => el.classList.add("in"));
  }

  // ── 기능 무대 ─────────────────────────────────────────
  const stage = document.querySelector(".stage");
  const panels = [...document.querySelectorAll(".panel")];
  const tabs = [...document.querySelectorAll(".tab")];
  if (!stage || !panels.length) return;

  const PLAY = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4.5v15a1 1 0 0 0 1.5.86l12-7.5a1 1 0 0 0 0-1.72l-12-7.5A1 1 0 0 0 7 4.5z"/></svg>';
  const PAUSE = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="5" y="4" width="5" height="16" rx="1.5"/><rect x="14" y="4" width="5" height="16" rx="1.5"/></svg>';

  let current = 0;
  let elapsed = 0;       // 지금 시연이 흐른 시간(초)
  let last = 0;          // 직전 프레임 시각
  let paused = false;    // 사용자가 멈춤
  let visible = true;    // 무대가 화면 안에 있나
  let raf = 0;

  /** 시연 한 편의 지금 시각 t(초)에 맞는 모습을 그린다. 같은 t 면 언제 불러도 같은 화면이 나온다. */
  function render(panel, t) {
    const demo = panel.querySelector(".demo");
    const length = Number(demo.dataset.length);
    demo.querySelectorAll("[data-at]").forEach((el) => {
      if (el.dataset.type !== undefined) {
        // 입력창에 글자가 한 자씩 찍힌다. 여러 번 입력하면 값들을 | 와 , 로 나눠 적는다
        const texts = el.dataset.type.split("|");
        const ats = el.dataset.at.split(",").map(Number);
        const durs = el.dataset.dur.split(",").map(Number);
        const offs = el.dataset.off.split(",").map(Number);
        const i = ats.findIndex((at, k) => t >= at && t < offs[k]);
        if (i < 0) {
          el.textContent = el.dataset.ph || "";
          el.classList.remove("typed");
        } else {
          const n = Math.min(texts[i].length, Math.ceil(((t - ats[i]) / durs[i]) * texts[i].length));
          el.textContent = texts[i].slice(0, n);
          el.classList.add("typed");
        }
        return;
      }
      const at = Number(el.dataset.at);
      const off = el.dataset.off ? Number(el.dataset.off) : Infinity;
      el.classList.toggle("on", t >= at && t < off);
      el.classList.toggle("off", t >= off);
    });
    const bar = panel.querySelector(".track i");
    const time = panel.querySelector(".time");
    if (bar) bar.style.width = Math.min(100, (t / length) * 100) + "%";
    if (time) time.textContent = "0:" + String(Math.min(Math.floor(t), Math.floor(length))).padStart(2, "0");
    const fill = tabs[current] && tabs[current].querySelector(".fill");
    if (fill) fill.style.transform = "scaleX(" + Math.min(1, t / length) + ")";
  }

  function frame(now) {
    raf = 0;
    const panel = panels[current];
    const length = Number(panel.querySelector(".demo").dataset.length);
    elapsed += Math.max(0, Math.min(0.1, (now - last) / 1000));
    last = now;
    if (elapsed >= length) { show(current + 1); return; }   // 끝나면 다음 기능으로
    render(panel, elapsed);
    loop();
  }

  function loop() {
    if (raf || paused || !visible || still) return;
    last = performance.now();
    raf = requestAnimationFrame(frame);
  }

  function halt() {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
  }

  function setButton(panel) {
    const btn = panel.querySelector(".player button");
    if (!btn) return;
    btn.innerHTML = paused ? PLAY : PAUSE;
    btn.setAttribute("aria-label", paused ? "시연 재생" : "시연 일시정지");
  }

  function show(index, focusTab) {
    halt();
    current = (index + panels.length) % panels.length;
    elapsed = 0;
    paused = false;
    stage.dataset.on = String(current);
    panels.forEach((p, i) => { p.hidden = i !== current; });
    tabs.forEach((t, i) => {
      t.setAttribute("aria-selected", String(i === current));
      t.tabIndex = i === current ? 0 : -1;
      const fill = t.querySelector(".fill");
      if (fill) fill.style.transform = "scaleX(0)";
    });
    const panel = panels[current];
    setButton(panel);
    // 움직임 줄이기 설정이면 끝난 모습을 그대로 보여 준다
    render(panel, still ? Number(panel.querySelector(".demo").dataset.length) - 0.05 : 0);
    if (focusTab) tabs[current].focus();
    const strip = tabs[current].parentElement;
    strip.scrollLeft = Math.max(0, tabs[current].offsetLeft - strip.offsetLeft - 24);
    loop();
  }

  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => show(i));
    tab.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight") show(current + 1, true);
      if (e.key === "ArrowLeft") show(current - 1, true);
    });
  });
  document.querySelectorAll(".next").forEach((btn) => btn.addEventListener("click", () => show(current + 1)));
  panels.forEach((panel) => {
    const btn = panel.querySelector(".player button");
    if (!btn) return;
    btn.addEventListener("click", () => {
      paused = !paused;
      setButton(panel);
      if (paused) halt(); else loop();
    });
  });

  // 무대가 화면 밖이면 시간을 멈춘다(안 보는 사이 넘어가지 않게)
  if ("IntersectionObserver" in window) {
    new IntersectionObserver((entries) => {
      visible = entries[0].isIntersecting;
      if (visible) loop(); else halt();
    }, { threshold: 0.25 }).observe(stage);
  }
  document.addEventListener("visibilitychange", () => { if (document.hidden) halt(); else loop(); });

  show(0);
})();
