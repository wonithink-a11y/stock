/* 탭 셸 - 각 탭 모듈(ui/tabs/*.js)은 로드되면서
     window.TABS.<id> = { title: "표시이름", render: async (container) => {...} }
   를 등록한다. 이 파일은 그 목록을 읽어 nav 버튼을 만들고 클릭 시 해당
   컨테이너에 처음 한 번만 render()를 호출한다(지연 로딩, 중복 호출 없음).

   탭 순서는 index.html의 <script> 로드 순서를 그대로 따른다
   (TAB_ORDER로 고정 - window.TABS는 순서를 보장 안 하는 plain object).
*/
const TAB_ORDER = ["chart", "scoring", "research", "macro", "datahealth"];

/* 다크/라이트 테마 - localStorage에 기억, 기본은 다크(기존 동작 무변경).
   .themechange 이벤트를 document에 쏴서 canvas처럼 CSS 변수를 못 읽는
   탭(chart.js)이 직접 다시 그릴 수 있게 한다. */
const THEME_KEY = "ui_theme";

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const btn = document.getElementById("theme-toggle");
  if (btn) btn.textContent = theme === "light" ? "🌞" : "🌙";
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

function boot() {
  initTheme();
  const nav = document.getElementById("tab-nav");
  const main = document.getElementById("tab-main");
  const rendered = new Set();

  TAB_ORDER.forEach((id, i) => {
    const spec = window.TABS && window.TABS[id];
    const btn = document.createElement("button");
    btn.className = "tab-btn" + (i === 0 ? " active" : "");
    btn.textContent = spec ? spec.title : id + " (미구현)";
    btn.disabled = !spec;

    const panel = document.createElement("section");
    panel.className = "tab-panel" + (i === 0 ? " active" : "");
    panel.id = "panel-" + id;
    panel.innerHTML = spec ? "" : '<div class="empty">이 탭은 아직 구현되지 않았습니다.</div>';

    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
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
  });

  // 첫 탭은 클릭 없이도 바로 보이므로 즉시 렌더한다.
  const first = TAB_ORDER[0];
  const firstSpec = window.TABS && window.TABS[first];
  if (firstSpec) {
    rendered.add(first);
    const panel = document.getElementById("panel-" + first);
    panel.innerHTML = '<div class="loading">불러오는 중...</div>';
    Promise.resolve(firstSpec.render(panel)).catch((e) => {
      panel.innerHTML = '<div class="empty">탭 로드 실패: ' + String(e && e.message || e) + "</div>";
    });
  }
}

document.addEventListener("DOMContentLoaded", boot);
