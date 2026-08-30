(function () {
  'use strict';

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function simpleMarkdownToHtml(md) {
    if (!md) return '';
    let html = escapeHtml(md);
    html = html
      .replace(/^### (.*$)/gm, '<h3>$1</h3>')
      .replace(/^## (.*$)/gm, '<h2>$1</h2>')
      .replace(/^# (.*$)/gm, '<h1>$1</h1>')
      .replace(/\n\n+/g, '</p><p>')
      .replace(/\n/g, '<br>');
    html = '<p>' + html + '</p>';
    html = html
      .replace(/<p><h([1-3])>(.*?)<\/h[1-3]><\/p>/g, '<h$1>$2</h$1>')
      .replace(/<p><br><\/p>/g, '')
      .replace(/<p><\/p>/g, '');
    html = html.replace(/\|(.+?)\|/g, function (match) {
      return '<code>' + match.slice(1, -1) + '</code>';
    });
    return html;
  }

  function stripFrontmatter(md) {
    return (md || '').replace(/^---\s*\n[\s\S]*?\n---\s*\n/, '');
  }

  const VERDICTS = ['KEEP', 'HOLD', 'REJECT', 'UNCLASSIFIED'];
  const TRACKS = ['kr', 'crypto', 'macro', 'us'];
  const METRIC_FIELDS = ['cagr', 'sharpe', 'mdd', 'win_rate', 'n', 't_stat'];

  // ---- 공용 조각(뱃지/조건/결과지표) - 실제로 값이 있을 때만 렌더링(교훈57) ----

  function verdictBadge(finding) {
    if (!finding.verdict) return '';
    const orig = finding.original_verdict ? ` <span class="v-orig">(원문: ${escapeHtml(finding.original_verdict)})</span>` : '';
    return `<span class="v-badge v-${finding.verdict.toLowerCase()}">${finding.verdict}</span>${orig}`;
  }

  function trackBadge(finding) {
    if (!finding.track) return '';
    return `<span class="v-badge t-${finding.track}">${finding.track}</span>`;
  }

  function conditionsHtml(finding) {
    if (!finding.conditions || !finding.conditions.length) return '';
    return '<div class="v-cond">' + finding.conditions.map(c => `<span>${escapeHtml(c)}</span>`).join('') + '</div>';
  }

  function fmtPct(v) { return (v > 0 ? '+' : '') + v.toFixed(2) + '%'; }
  function fmtNum(v) { return v.toFixed(2); }
  function signCls(v) { return v > 0 ? 'pos' : (v < 0 ? 'neg' : ''); }
  function has(v) { return v !== null && v !== undefined; }

  function statsHtml(finding) {
    const parts = [];
    if (has(finding.cagr)) parts.push(`CAGR <b class="${signCls(finding.cagr)}">${fmtPct(finding.cagr)}</b>`);
    if (has(finding.sharpe)) parts.push(`Sharpe <b class="${signCls(finding.sharpe)}">${fmtNum(finding.sharpe)}</b>`);
    if (has(finding.mdd)) parts.push(`MDD <b class="neg">${fmtPct(finding.mdd)}</b>`);
    if (has(finding.win_rate)) parts.push(`WinRate <b>${finding.win_rate.toFixed(1)}%</b>`);
    if (has(finding.n)) parts.push(`N <b>${Math.round(finding.n)}</b>`);
    if (has(finding.t_stat)) parts.push(`t <b class="${Math.abs(finding.t_stat) >= 2 ? 'pos' : 'neg'}">${fmtNum(finding.t_stat)}</b>`);
    if (!parts.length) return '';
    return `<div class="v-stats">${parts.join(' &middot; ')}</div>`;
  }

  function metricCell(finding, field) {
    const v = finding[field];
    if (!has(v)) return '<span class="dim">-</span>';
    if (field === 'cagr' || field === 'mdd') return `<b class="${field === 'mdd' ? 'neg' : signCls(v)}">${fmtPct(v)}</b>`;
    if (field === 'win_rate') return `<b>${v.toFixed(1)}%</b>`;
    if (field === 'n') return `<b>${Math.round(v)}</b>`;
    return `<b class="${field === 't_stat' ? (Math.abs(v) >= 2 ? 'pos' : 'neg') : signCls(v)}">${fmtNum(v)}</b>`;
  }

  const METRIC_LABELS = { cagr: 'CAGR', sharpe: 'Sharpe', mdd: 'MDD', win_rate: 'WinRate', n: 'N', t_stat: 't-stat' };

  // 상세 모달용 - 인라인 문자열 대신 표(행=지표)로 보여준다. 실제로 계산된
  // 지표만 행으로 넣는다(교훈57).
  function statsTableHtml(finding) {
    const rows = METRIC_FIELDS.filter(f => has(finding[f]))
      .map(f => `<tr><th>${METRIC_LABELS[f]}</th><td>${metricCell(finding, f)}</td></tr>`);
    if (!rows.length) return '';
    return `<table class="rl-stats-table"><tbody>${rows.join('')}</tbody></table>`;
  }

  // "비슷한 실험끼리" 보기용 - 검증된 관계가 아니라 순수 이름 기반 시각적
  // 묶음이다(Lineage와 다름, 사용자 확인 2026-08-30 - 추정 관계 주장 아님).
  // factor slug에서 뒤쪽 날짜(YYYY-MM)·버전 접미사를 떼고 앞 1~2토큰을 쓴다.
  function familyKey(finding) {
    const base = finding.file.replace(/\.md$/, '').split('/').pop()
      .replace(/[-_]\d{4}-?\d{2}$/, '')
      .replace(/[-_]v\d+$/i, '');
    const tokens = base.split(/[-_]/).filter(Boolean);
    return tokens.slice(0, 2).join('-') || base || '(기타)';
  }

  function filterFindings(findings, query, trackFilter, verdictFilter) {
    let out = findings;
    if (trackFilter !== 'all') out = out.filter(f => f.track === trackFilter);
    if (verdictFilter !== 'all') out = out.filter(f => f.verdict === verdictFilter);
    if (query.trim()) {
      const q = query.toLowerCase();
      out = out.filter(f => f.title.toLowerCase().includes(q));
    }
    return out;
  }

  function chipRow(options, current, onPick) {
    const row = document.createElement('div');
    row.className = 'v-chip-row';
    ['all', ...options].forEach(opt => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'v-chip' + (opt === current ? ' active' : '');
      btn.textContent = opt;
      btn.addEventListener('click', () => onPick(opt));
      row.appendChild(btn);
    });
    return row;
  }

  // 실험 하나의 구조화 상세(Conditions/Result/Verdict/Reason) + 원본 마크다운.
  // Hypothesis/Design/Interpretation은 파일마다 절 제목이 제각각이라(교훈57 -
  // 억지로 구조를 지어내지 않는다) 별도 절로 안 쪼개고 원문 그대로 아래에 둔다.
  function detailHtml(finding) {
    const badges = [trackBadge(finding), verdictBadge(finding)].filter(Boolean).join(' ');
    const cond = conditionsHtml(finding);
    const stats = statsTableHtml(finding);
    const body = simpleMarkdownToHtml(stripFrontmatter(finding.bodyMarkdown));
    return `
      <div class="finding-summary">
        ${badges ? `<div>${badges}</div>` : ''}
        ${cond}
        ${finding.reason ? `<div class="v-reason">${escapeHtml(finding.reason)}</div>` : ''}
        ${stats}
      </div>
      <div class="finding-content mono">${body}</div>
    `;
  }

  // ---- Detail 모달 - Experiments/Compare/Overview 어디서든 같은 방식으로 연다 ----

  let modalEl = null;
  function openDetailModal(finding) {
    closeDetailModal();
    modalEl = document.createElement('div');
    modalEl.className = 'rl-modal-backdrop';
    modalEl.innerHTML = `
      <div class="rl-modal panel">
        <div class="rl-modal-head">
          <div class="finding-title">${escapeHtml(finding.title)}</div>
          <button type="button" class="rl-modal-close">&times;</button>
        </div>
        <div class="rl-modal-body">${detailHtml(finding)}</div>
      </div>
    `;
    modalEl.addEventListener('click', (e) => { if (e.target === modalEl) closeDetailModal(); });
    modalEl.querySelector('.rl-modal-close').addEventListener('click', closeDetailModal);
    document.body.appendChild(modalEl);
  }
  function closeDetailModal() {
    if (modalEl) { modalEl.remove(); modalEl = null; }
  }

  // ---- Overview ----

  function renderOverview(container, allFindings, goToExperiments) {
    const counts = { KEEP: 0, HOLD: 0, REJECT: 0, UNCLASSIFIED: 0 };
    allFindings.forEach(f => { if (counts[f.verdict] !== undefined) counts[f.verdict]++; });
    const trackCounts = {};
    TRACKS.forEach(t => trackCounts[t] = allFindings.filter(f => f.track === t).length);

    const recent = [...allFindings]
      .filter(f => f.date)
      .sort((a, b) => (b.date || '').localeCompare(a.date || ''))
      .slice(0, 8);

    const tile = (label, val, cls) => `
      <div class="rl-stat-tile">
        <div class="rl-stat-val ${cls || ''}">${val}</div>
        <div class="rl-stat-label">${label}</div>
      </div>`;

    container.innerHTML = `
      <div class="rl-stat-grid">
        ${tile('전체 실험', allFindings.length)}
        ${tile('KEEP', counts.KEEP, 'v-keep-text')}
        ${tile('HOLD', counts.HOLD, 'v-hold-text')}
        ${tile('REJECT', counts.REJECT, 'v-reject-text')}
        ${tile('UNCLASSIFIED', counts.UNCLASSIFIED, 'dim')}
      </div>
      <div class="panel rl-panel">
        <h2>트랙별 실험 수</h2>
        <div class="v-chip-row">
          ${TRACKS.map(t => `<span class="v-chip">${t} <b>${trackCounts[t]}</b></span>`).join('')}
        </div>
      </div>
      <div class="panel rl-panel">
        <h2>최근 실험</h2>
        <div class="rl-recent-list"></div>
      </div>
    `;

    const recentList = container.querySelector('.rl-recent-list');
    if (!recent.length) {
      recentList.innerHTML = '<div class="empty mono">날짜 정보가 있는 실험이 없습니다</div>';
    } else {
      recent.forEach(f => {
        const row = document.createElement('div');
        row.className = 'rl-recent-row';
        row.innerHTML = `
          <span class="rl-recent-date mono">${escapeHtml(f.date)}</span>
          ${trackBadge(f)}${verdictBadge(f)}
          <span class="rl-recent-title">${escapeHtml(f.title)}</span>
        `;
        row.addEventListener('click', () => openDetailModal(f));
        recentList.appendChild(row);
      });
    }

    const seeAllBtn = document.createElement('button');
    seeAllBtn.type = 'button';
    seeAllBtn.className = 'v-chip';
    seeAllBtn.textContent = '실험 전체 보기 →';
    seeAllBtn.style.marginTop = '8px';
    seeAllBtn.addEventListener('click', goToExperiments);
    container.querySelector('.rl-panel:last-child').appendChild(seeAllBtn);
  }

  // ---- Experiments (카드) ----

  function renderExperiments(container, allFindings, filterState) {
    container.innerHTML = '';

    const toolbar = document.createElement('div');
    toolbar.className = 'rl-toolbar';
    const trackRow = chipRow(TRACKS, filterState.track, (opt) => { filterState.track = opt; renderExperiments(container, allFindings, filterState); });
    const verdictRow = chipRow(VERDICTS, filterState.verdict, (opt) => { filterState.verdict = opt; renderExperiments(container, allFindings, filterState); });
    const searchInput = document.createElement('input');
    searchInput.type = 'search';
    searchInput.className = 'mono';
    searchInput.placeholder = '제목 검색...';
    searchInput.value = filterState.query;
    searchInput.addEventListener('input', function () { filterState.query = this.value; renderGrid(); });
    toolbar.appendChild(trackRow);
    toolbar.appendChild(verdictRow);
    toolbar.appendChild(searchInput);
    container.appendChild(toolbar);

    const list = document.createElement('div');
    list.className = 'rl-exp-list panel';
    container.appendChild(list);

    function renderList() {
      const filtered = filterFindings(allFindings, filterState.query, filterState.track, filterState.verdict);
      list.innerHTML = '';
      if (!filtered.length) {
        list.innerHTML = '<div class="empty mono">조건에 맞는 실험이 없습니다</div>';
        return;
      }
      // 트랙 -> family(이름 기반, 검증된 관계 아님) -> 제목 순 정렬해 비슷한
      // 실험끼리 인접하게 묶는다. 그룹 헤더는 순수 표시용.
      const sorted = [...filtered].sort((a, b) =>
        (a.track || '').localeCompare(b.track || '') ||
        familyKey(a).localeCompare(familyKey(b)) ||
        a.title.localeCompare(b.title));

      let lastGroup = null;
      sorted.forEach(f => {
        const groupKey = (f.track || '') + '/' + familyKey(f);
        if (groupKey !== lastGroup) {
          lastGroup = groupKey;
          const header = document.createElement('div');
          header.className = 'rl-exp-group-header dim mono';
          header.textContent = familyKey(f) + ' (이름 기준 묶음)';
          list.appendChild(header);
        }
        const row = document.createElement('div');
        row.className = 'rl-exp-row';
        row.innerHTML = `
          <span class="rl-exp-badges">${trackBadge(f)}${verdictBadge(f)}</span>
          <span class="rl-exp-title">${escapeHtml(f.title)}</span>
          <span class="rl-exp-date dim mono">${f.date ? escapeHtml(f.date) : ''}</span>
          ${statsHtml(f)}
        `;
        row.addEventListener('click', () => openDetailModal(f));
        list.appendChild(row);
      });
    }
    renderList();
  }

  // ---- Compare ----

  function renderCompare(container, allFindings, filterState, selection) {
    container.innerHTML = '';

    const toolbar = document.createElement('div');
    toolbar.className = 'rl-toolbar';
    const trackRow = chipRow(TRACKS, filterState.track, (opt) => { filterState.track = opt; renderCompare(container, allFindings, filterState, selection); });
    const verdictRow = chipRow(VERDICTS, filterState.verdict, (opt) => { filterState.verdict = opt; renderCompare(container, allFindings, filterState, selection); });
    const searchInput = document.createElement('input');
    searchInput.type = 'search';
    searchInput.className = 'mono';
    searchInput.placeholder = '제목 검색...';
    searchInput.value = filterState.query;
    toolbar.appendChild(trackRow);
    toolbar.appendChild(verdictRow);
    toolbar.appendChild(searchInput);
    container.appendChild(toolbar);

    const body = document.createElement('div');
    body.className = 'rl-compare-layout';
    container.appendChild(body);

    const pickList = document.createElement('div');
    pickList.className = 'rl-compare-pick panel';
    const table = document.createElement('div');
    table.className = 'rl-compare-table-wrap panel';
    body.appendChild(pickList);
    body.appendChild(table);

    function renderPickList() {
      const filtered = filterFindings(allFindings, filterState.query, filterState.track, filterState.verdict);
      pickList.innerHTML = `<h2>비교할 실험 선택 (${selection.size}개 선택됨)</h2>`;
      const list = document.createElement('div');
      list.className = 'rl-compare-list';
      if (!filtered.length) {
        list.innerHTML = '<div class="empty mono">조건에 맞는 실험이 없습니다</div>';
      }
      filtered.forEach(f => {
        const row = document.createElement('label');
        row.className = 'rl-compare-row';
        const checked = selection.has(f.file);
        row.innerHTML = `
          <input type="checkbox" ${checked ? 'checked' : ''}>
          ${trackBadge(f)}${verdictBadge(f)}
          <span class="rl-recent-title">${escapeHtml(f.title)}</span>
        `;
        row.querySelector('input').addEventListener('change', (e) => {
          if (e.target.checked) selection.add(f.file); else selection.delete(f.file);
          renderPickList();
          renderTable();
        });
        list.appendChild(row);
      });
      pickList.appendChild(list);
    }

    function renderTable() {
      const chosen = allFindings.filter(f => selection.has(f.file));
      if (!chosen.length) {
        table.innerHTML = '<h2>비교</h2><div class="empty mono">왼쪽에서 실험을 선택하세요</div>';
        return;
      }
      const rows = [];
      rows.push(['실험', ...chosen.map(f => escapeHtml(f.title))]);
      rows.push(['Track / Verdict', ...chosen.map(f => `${trackBadge(f)}${verdictBadge(f)}`)]);
      rows.push(['Conditions', ...chosen.map(f => conditionsHtml(f) || '<span class="dim">-</span>')]);
      METRIC_FIELDS.forEach(field => {
        rows.push([METRIC_LABELS[field], ...chosen.map(f => metricCell(f, field))]);
      });
      rows.push(['Reason', ...chosen.map(f => f.reason ? escapeHtml(f.reason) : '<span class="dim">-</span>')]);

      const html = ['<h2>비교</h2><div class="rl-compare-scroll"><table class="rl-compare-table">'];
      rows.forEach((r, i) => {
        html.push('<tr>' + r.map((cell, j) => `<${i === 0 || j === 0 ? 'th' : 'td'}>${cell}</${i === 0 || j === 0 ? 'th' : 'td'}>`).join('') + '</tr>');
      });
      html.push('</table></div>');
      table.innerHTML = html.join('');
    }

    renderPickList();
    renderTable();
  }

  // ---- Findings (기존 마크다운 브라우저 - 그대로 유지, 보조 화면) ----

  function renderFindingsBrowser(container, allFindings, filterState) {
    container.innerHTML = '';
    const layout = document.createElement('div');
    layout.className = 'research-layout';
    container.appendChild(layout);

    const sidebar = document.createElement('aside');
    sidebar.className = 'research-sidebar panel';
    layout.appendChild(sidebar);

    const trackRow = chipRow(TRACKS, filterState.track, (opt) => { filterState.track = opt; applyFilters(); });
    const verdictRow = chipRow(VERDICTS, filterState.verdict, (opt) => { filterState.verdict = opt; applyFilters(); });
    sidebar.appendChild(trackRow);
    sidebar.appendChild(verdictRow);

    const searchWrapper = document.createElement('div');
    searchWrapper.className = 'research-search';
    const searchInput = document.createElement('input');
    searchInput.type = 'search';
    searchInput.placeholder = '제목 검색...';
    searchInput.className = 'mono';
    searchInput.value = filterState.query;
    searchWrapper.appendChild(searchInput);
    sidebar.appendChild(searchWrapper);

    const listContainer = document.createElement('div');
    listContainer.className = 'research-list';
    sidebar.appendChild(listContainer);

    const contentPanel = document.createElement('section');
    contentPanel.className = 'research-content panel';
    layout.appendChild(contentPanel);

    let filteredFindings = allFindings;

    function renderList() {
      listContainer.innerHTML = '';
      if (!filteredFindings.length) {
        listContainer.innerHTML = '<div class="empty mono">검색 결과가 없습니다</div>';
        return;
      }
      filteredFindings.forEach((finding) => {
        const div = document.createElement('div');
        div.className = 'finding-item';
        div.innerHTML = `
          <div class="finding-badges">${trackBadge(finding)}${verdictBadge(finding)}</div>
          <div class="finding-title">${escapeHtml(finding.title)}</div>
          <div class="finding-meta">
            <span class="finding-date">${finding.date ? escapeHtml(finding.date) : '날짜 없음'}</span>
            <span class="finding-file mono">${escapeHtml(finding.file)}</span>
          </div>
          ${finding.reason ? `<div class="v-reason">${escapeHtml(finding.reason)}</div>` : ''}
        `;
        div.addEventListener('click', () => {
          listContainer.querySelectorAll('.finding-item').forEach(el => el.classList.remove('selected'));
          div.classList.add('selected');
          renderContent(finding);
        });
        listContainer.appendChild(div);
      });
    }

    function renderContent(finding) {
      contentPanel.classList.remove('empty');
      contentPanel.innerHTML = finding ? detailHtml(finding) : '';
      if (!finding) {
        contentPanel.classList.add('empty');
        contentPanel.textContent = '항목을 선택하세요';
      }
    }

    function applyFilters() {
      filteredFindings = filterFindings(allFindings, searchInput.value, filterState.track, filterState.verdict);
      renderList();
      if (filteredFindings.length) {
        const firstEl = listContainer.querySelector('.finding-item');
        if (firstEl) firstEl.classList.add('selected');
        renderContent(filteredFindings[0]);
      } else {
        renderContent(null);
      }
    }

    searchInput.addEventListener('input', function () { filterState.query = this.value; applyFilters(); });
    applyFilters();
  }

  // ---- 탭 오케스트레이션 ----

  const VIEWS = [
    { id: 'overview', label: 'Overview' },
    { id: 'experiments', label: 'Experiments' },
    { id: 'compare', label: 'Compare' },
    { id: 'findings', label: 'Findings' },
  ];

  window.TABS = window.TABS || {};
  window.TABS.research = {
    title: '리서치랩',
    render: async function (container) {
      container.innerHTML = '';
      container.classList.add('research-tab', 'rl-console');

      const nav = document.createElement('div');
      nav.className = 'rl-nav';
      container.appendChild(nav);

      const viewMount = document.createElement('div');
      viewMount.className = 'rl-view';
      container.appendChild(viewMount);

      const loadingEl = document.createElement('div');
      loadingEl.className = 'loading';
      loadingEl.textContent = '데이터 로딩 중...';
      viewMount.appendChild(loadingEl);

      let allFindings = [];
      try {
        // 배포 경로가 도메인 루트인지 서브경로(/paper-trading/)인지에 따라
        // 같은 파일의 상대 위치가 달라진다 - macro.js의 fetchFirst 패턴과
        // 동일하게 순서대로 시도한다.
        const candidates = ['data/findings.json', '../data/findings.json', 'ui/data/findings.json'];
        let data = null;
        let lastErr = null;
        for (const path of candidates) {
          try {
            const response = await fetch(path);
            if (!response.ok) throw new Error('HTTP ' + response.status);
            data = await response.json();
            break;
          } catch (e) {
            lastErr = e;
          }
        }
        if (!data) throw lastErr || new Error('findings.json not found');
        allFindings = data.findings || [];
      } catch (e) {
        loadingEl.textContent = '데이터를 불러올 수 없습니다: ' + e.message;
        loadingEl.classList.add('error');
        return;
      }
      loadingEl.remove();

      const expFilter = { track: 'all', verdict: 'all', query: '' };
      const compareFilter = { track: 'all', verdict: 'all', query: '' };
      const findingsFilter = { track: 'all', verdict: 'all', query: '' };
      const compareSelection = new Set();
      let activeView = 'overview';

      function renderNav() {
        nav.innerHTML = '';
        VIEWS.forEach(v => {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'rl-nav-btn' + (v.id === activeView ? ' active' : '');
          btn.textContent = v.label;
          btn.addEventListener('click', () => { activeView = v.id; renderNav(); renderView(); });
          nav.appendChild(btn);
        });
      }

      function renderView() {
        viewMount.innerHTML = '';
        if (activeView === 'overview') {
          renderOverview(viewMount, allFindings, () => { activeView = 'experiments'; renderNav(); renderView(); });
        } else if (activeView === 'experiments') {
          renderExperiments(viewMount, allFindings, expFilter);
        } else if (activeView === 'compare') {
          renderCompare(viewMount, allFindings, compareFilter, compareSelection);
        } else if (activeView === 'findings') {
          renderFindingsBrowser(viewMount, allFindings, findingsFilter);
        }
      }

      renderNav();
      renderView();
    }
  };
})();
