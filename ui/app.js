/* 탭 셸 - 각 탭 모듈(ui/tabs/*.js)은 로드되면서
     window.TABS.<id> = { title: "표시이름", render: async (container) => {...} }
   를 등록한다. 이 파일은 그 목록을 읽어 사이드바 nav를 만들고 클릭 시 해당
   컨테이너에 처음 한 번만 render()를 호출한다(지연 로딩, 중복 호출 없음).

   탭 순서는 index.html의 <script> 로드 순서를 그대로 따른다
   (TAB_GROUPS로 고정 - window.TABS는 순서를 보장 안 하는 plain object).
   2026-09-14 전면 개편 - 페이퍼 트레이딩 5탭(Overview/Positions/거래내역/
   Performance/System)을 1군으로, 기존 리서치 도구 4개를 2군으로 나눴다. */
const TAB_GROUPS = [
  { label: null, ids: ["overview", "positions", "activity", "performance", "system"] },
  { label: "리서치", ids: ["scoring", "research", "macro", "themes", "datahealth"] },
];
const TAB_ORDER = TAB_GROUPS.flatMap((g) => g.ids);
const ICON = (d) => '<svg viewBox="0 0 24 24" aria-hidden="true">' + d + "</svg>";
const TAB_ICONS = {
  overview: ICON('<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>'),
  positions: ICON('<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 13h18"/>'),
  activity: ICON('<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>'),
  performance: ICON('<path d="M3 17l6-6 4 4 8-8"/><path d="M14 7h7v7"/>'),
  system: ICON('<path d="M4 6h10M18 6h2M4 12h2M10 12h10M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="8" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>'),
  scoring: ICON('<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>'),
  research: ICON('<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"/>'),
  macro: ICON('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>'),
  themes: ICON('<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>'),
  datahealth: ICON('<path d="M3 12h4l3-7 4 14 3-7h4"/>'),
};
const THEME_ICON = {
  light: ICON('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19"/>'),
  dark: ICON('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>'),
};

/* 다크/라이트 테마 - localStorage에 기억, 기본은 다크(기존 동작 무변경).
   .themechange 이벤트를 document에 쏴서 canvas처럼 CSS 변수를 못 읽는
   탭이 직접 다시 그릴 수 있게 한다. */
const THEME_KEY = "ui_theme";

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const btn = document.getElementById("theme-toggle");
  if (btn) btn.innerHTML = theme === "light" ? THEME_ICON.light : THEME_ICON.dark;
}

function initTheme() {
  applyTheme(localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark");
  const btn = document.getElementById("theme-toggle");
  if (btn) {
    btn.addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
      localStorage.setItem(THEME_KEY, next);
      applyTheme(next);
      document.dispatchEvent(new CustomEvent("themechange", { detail: { theme: next } }));
    });
  }
}

// 장중 여부 - 순수 시각 계산(공휴일 미반영, PT.marketSession이 그대로 정직하게
// 알려준다). 지어낸 "자동 갱신 10분" 같은 문구는 안 쓴다 - 이 정적 사이트는
// 실제로 그런 주기가 없다.
function initMarketStatus() {
  const slot = document.getElementById("market-status-slot");
  if (!slot || !window.PT) return;
  const s = window.PT.marketSession();
  const cls = s.open ? "pill-good" : "pill-dim";
  slot.innerHTML = '<span class="pill ' + cls + '"><span class="pill-dot"></span>' + s.label + "</span>";
}

function initRefreshButton() {
  const btn = document.getElementById("refresh-btn");
  if (btn) btn.addEventListener("click", () => location.reload());
}

function boot() {
  initTheme();
  initMarketStatus();
  initRefreshButton();
  const nav = document.getElementById("tab-nav");
  const main = document.getElementById("tab-main");
  const rendered = new Set();
  let first = true;

  TAB_GROUPS.forEach((group) => {
    if (group.label) {
      const label = document.createElement("div");
      label.className = "sidebar-group-label";
      label.textContent = group.label;
      nav.appendChild(label);
    }
    group.ids.forEach((id) => {
      const spec = window.TABS && window.TABS[id];
      const isFirst = first;
      first = false;

      const btn = document.createElement("button");
      btn.className = "tab-btn" + (isFirst ? " active" : "");
      btn.innerHTML = '<span class="tab-icon" aria-hidden="true">' + (TAB_ICONS[id] || "•") + "</span><span>" +
        (spec ? spec.title : id + " (미구현)") + "</span>";
      btn.disabled = !spec;
      btn.setAttribute("aria-current", isFirst ? "page" : "false");

      const panel = document.createElement("section");
      panel.className = "tab-panel" + (isFirst ? " active" : "");
      panel.id = "panel-" + id;
      panel.setAttribute("tabindex", "-1");
      panel.innerHTML = spec ? "" : '<div class="empty">이 탭은 아직 구현되지 않았습니다.</div>';

      btn.addEventListener("click", () => {
        document.querySelectorAll(".tab-btn").forEach((b) => { b.classList.remove("active"); b.setAttribute("aria-current", "false"); });
        document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
        btn.classList.add("active");
        btn.setAttribute("aria-current", "page");
        panel.classList.add("active");
        if (spec && !rendered.has(id)) {
          rendered.add(id);
          panel.innerHTML = '<div class="loading">불러오는 중...</div>';
          Promise.resolve(spec.render(panel)).catch((e) => {
            panel.innerHTML = '<div class="empty">탭 로드 실패: ' + String(e && e.message || e) + "</div>";
          });
        }
      });

      nav.appendChild(btn);
      main.appendChild(panel);

      if (isFirst && spec) {
        rendered.add(id);
        panel.innerHTML = '<div class="loading">불러오는 중...</div>';
        Promise.resolve(spec.render(panel)).catch((e) => {
          panel.innerHTML = '<div class="empty">탭 로드 실패: ' + String(e && e.message || e) + "</div>";
        });
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", boot);
