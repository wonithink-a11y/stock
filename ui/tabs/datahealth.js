/* 탭5 - 데이터 상태 (Data Health)
   data/backfill/manifest/*.json은 이미 GitHub main에 커밋돼 있어 raw URL로
   그대로 읽는다 - 별도 adapter 스크립트나 Actions 워크플로를 새로 만들 필요가
   없다(scoring.js가 docs/data/*.json을 직접 fetch하는 것과 같은 패턴).
   스키마가 단계마다 조금씩 달라서(recordCount/fileCount/corpCount 등) 알려진
   핵심 필드만 표로 보여주고, 나머지는 행 클릭 시 있는 그대로 펼친다 - 없는
   필드를 지어내지 않는다. */
(function () {
  window.TABS = window.TABS || {};

  var STAGES = ["A0.5", "A0.7", "A1a", "A1b", "A2a", "A2b", "A3", "A3b", "A3c", "A3d", "A4", "A5", "A8", "EO"];
  var BASE = "https://raw.githubusercontent.com/wonithink-a11y/stock/main/data/backfill/manifest/";
  var SIZE_KEYS = ["recordCount", "fileCount", "corpCount"];
  var SKIP_KEYS = { schemaVersion: 1, stage: 1, stageVersion: 1, target: 1, targetKind: 1, targetExt: 1, hash: 1, generatedAt: 1 };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function fmt(n) {
    return typeof n === "number" ? n.toLocaleString("ko-KR") : n == null ? "-" : String(n);
  }

  function sizeOf(m) {
    for (var i = 0; i < SIZE_KEYS.length; i++) {
      if (m[SIZE_KEYS[i]] != null) return fmt(m[SIZE_KEYS[i]]);
    }
    return "-";
  }

  function daysSince(iso) {
    if (!iso) return null;
    return Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  }

  /* 단계마다 "정상 주기"가 달라서(법인코드는 몇 달에 한 번, 가격은 매일)
     경과일만으로 pass/fail을 단정하지 않는다 - 색은 참고용 신호일 뿐이다. */
  function freshStyle(days) {
    if (days == null) return "";
    return "color:" + (days <= 7 ? "var(--good)" : days <= 30 ? "var(--warn)" : "var(--down)");
  }

  function detailRowHtml(m, colspan) {
    var rows = Object.keys(m).filter(function (k) { return !SKIP_KEYS[k]; }).map(function (k) {
      var v = m[k];
      var text = v && typeof v === "object" ? JSON.stringify(v) : String(v);
      return '<div style="display:flex;justify-content:space-between;gap:10px;padding:3px 0;' +
        'border-bottom:1px solid var(--panel-border);font-size:11px">' +
        '<span class="dim">' + esc(k) + "</span>" +
        '<span style="text-align:right;word-break:break-all;max-width:65%">' + esc(text) + "</span>" +
        "</div>";
    }).join("");
    return '<tr class="detail-row"><td colspan="' + colspan + '" style="background:var(--surface-2);padding:12px 14px">' +
      '<div style="font-family:var(--mono)">' + (rows || '<div class="dim">추가 필드 없음</div>') + "</div>" +
      "</td></tr>";
  }

  function renderTable(container, manifests) {
    var wrap = container.querySelector("#health-table-wrap");
    var expanded = null;
    var colspan = 5;

    function render() {
      var body = manifests.map(function (m) {
        if (!m.data) {
          return '<tr><td class="mono dim">' + esc(m.stage) + "</td>" +
            '<td class="warn" colspan="' + (colspan - 1) + '">불러오기 실패: ' + esc(m.error || "") + "</td></tr>";
        }
        var d = m.data;
        var days = daysSince(d.generatedAt);
        var isOpen = m.stage === expanded;
        return '<tr data-stage="' + esc(m.stage) + '" style="cursor:pointer' +
          (isOpen ? ";background:var(--row-selected)" : "") + '">' +
          '<td class="mono">' + esc(m.stage) + "</td>" +
          '<td class="dim" style="text-align:left">' + esc(d.target || "-") + "</td>" +
          '<td class="mono">' + sizeOf(d) + "</td>" +
          '<td class="mono" style="' + freshStyle(days) + '">' +
          (d.generatedAt ? esc(d.generatedAt.slice(0, 10)) : "-") +
          (days != null ? " (" + days + "일 전)" : "") + "</td>" +
          '<td class="dim" style="font-size:11px;text-align:left">' +
          esc(d.upstream && Object.keys(d.upstream).length ? Object.keys(d.upstream).join(", ") : "-") + "</td>" +
          "</tr>" + (isOpen ? detailRowHtml(d, colspan) : "");
      }).join("");

      wrap.innerHTML = "<table><thead><tr>" +
        "<th>단계</th><th>산출물</th><th>레코드/파일</th><th>생성 시각</th><th>상류 의존</th>" +
        "</tr></thead><tbody>" + body + "</tbody></table>";

      wrap.querySelectorAll("tbody tr[data-stage]").forEach(function (row) {
        row.addEventListener("click", function () {
          var s = row.dataset.stage;
          expanded = expanded === s ? null : s;
          render();
        });
      });
    }

    render();
  }

  window.TABS.datahealth = {
    title: "데이터 상태",
    render: async function (container) {
      var settled = await Promise.allSettled(STAGES.map(function (stage) {
        return fetch(BASE + stage + ".json").then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        });
      }));

      var manifests = STAGES.map(function (stage, i) {
        var res = settled[i];
        return {
          stage: stage,
          data: res.status === "fulfilled" ? res.value : null,
          error: res.status === "rejected" ? String((res.reason && res.reason.message) || res.reason) : null
        };
      });

      var okCount = manifests.filter(function (m) { return m.data; }).length;

      container.innerHTML = '<div class="panel">' +
        "<h2>백필 파이프라인 상태 (" + okCount + "/" + STAGES.length + "단계 확인됨, 행 클릭시 전체 필드)</h2>" +
        '<div class="dim" style="font-size:11px;margin-bottom:10px">' +
        "GitHub main에 커밋된 manifest를 그대로 읽습니다 - manifest가 있다는 건 그 단계 인수 조건을 " +
        "통과한 산출물이 있다는 뜻입니다. 단계마다 정상 갱신 주기가 다르므로(법인코드는 드물게, 가격은 매일) " +
        "경과일 색은 참고용이지 통과/실패 판정이 아닙니다." +
        "</div>" +
        '<div id="health-table-wrap"><div class="loading">불러오는 중...</div></div>' +
        "</div>";

      renderTable(container, manifests);
    }
  };
})();
