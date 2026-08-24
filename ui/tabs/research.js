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

  function createListItem(finding, index, onClick) {
    const div = document.createElement('div');
    div.className = 'finding-item';
    div.dataset.index = index;
    div.innerHTML = `
      <div class="finding-title">${escapeHtml(finding.title)}</div>
      <div class="finding-meta">
        <span class="finding-date">${finding.date ? escapeHtml(finding.date) : '날짜 없음'}</span>
        <span class="finding-file mono">${escapeHtml(finding.file)}</span>
      </div>
    `;
    div.addEventListener('click', () => onClick(index));
    return div;
  }

  function renderFindingContent(container, finding) {
    container.innerHTML = '';
    if (!finding) {
      container.classList.add('empty');
      container.textContent = '항목을 선택하세요';
      return;
    }
    container.classList.remove('empty');
    const html = simpleMarkdownToHtml(finding.bodyMarkdown);
    const wrapper = document.createElement('div');
    wrapper.className = 'finding-content mono';
    wrapper.innerHTML = html;
    container.appendChild(wrapper);
  }

  function filterFindings(findings, query) {
    if (!query.trim()) return findings;
    const q = query.toLowerCase();
    return findings.filter(f => f.title.toLowerCase().includes(q));
  }

  window.TABS = window.TABS || {};
  window.TABS.research = {
    title: '리서치랩',
    render: async function (container) {
      container.innerHTML = '';
      container.className = 'research-tab';

      const layout = document.createElement('div');
      layout.className = 'research-layout';
      container.appendChild(layout);

      const sidebar = document.createElement('aside');
      sidebar.className = 'research-sidebar panel';
      layout.appendChild(sidebar);

      const searchWrapper = document.createElement('div');
      searchWrapper.className = 'research-search';
      const searchInput = document.createElement('input');
      searchInput.type = 'search';
      searchInput.placeholder = '제목 검색...';
      searchInput.className = 'mono';
      searchWrapper.appendChild(searchInput);
      sidebar.appendChild(searchWrapper);

      const listContainer = document.createElement('div');
      listContainer.className = 'research-list';
      sidebar.appendChild(listContainer);

      const contentPanel = document.createElement('section');
      contentPanel.className = 'research-content panel';
      layout.appendChild(contentPanel);

      const loadingEl = document.createElement('div');
      loadingEl.className = 'loading';
      loadingEl.textContent = '데이터 로딩 중...';
      listContainer.appendChild(loadingEl);

      let allFindings = [];
      let filteredFindings = [];
      let selectedIndex = -1;

      try {
        const response = await fetch('../data/findings.json');
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const data = await response.json();
        allFindings = data.findings || [];
        filteredFindings = allFindings;
      } catch (e) {
        loadingEl.textContent = '데이터를 불러올 수 없습니다: ' + e.message;
        loadingEl.classList.add('error');
        contentPanel.classList.add('empty');
        contentPanel.textContent = '데이터 로드 실패';
        return;
      }

      loadingEl.remove();

      function renderList() {
        listContainer.innerHTML = '';
        if (filteredFindings.length === 0) {
          const empty = document.createElement('div');
          empty.className = 'empty mono';
          empty.textContent = '검색 결과가 없습니다';
          listContainer.appendChild(empty);
          return;
        }
        filteredFindings.forEach((finding, idx) => {
          const originalIndex = allFindings.indexOf(finding);
          const item = createListItem(finding, originalIndex, (i) => {
            selectedIndex = i;
            document.querySelectorAll('.finding-item').forEach(el => el.classList.remove('selected'));
            const selectedEl = listContainer.querySelector('[data-index="' + i + '"]');
            if (selectedEl) selectedEl.classList.add('selected');
            renderFindingContent(contentPanel, allFindings[i]);
          });
          listContainer.appendChild(item);
        });
      }

      function selectFirst() {
        if (filteredFindings.length > 0) {
          const firstOriginalIndex = allFindings.indexOf(filteredFindings[0]);
          selectedIndex = firstOriginalIndex;
          const firstEl = listContainer.querySelector('[data-index="' + firstOriginalIndex + '"]');
          if (firstEl) firstEl.classList.add('selected');
          renderFindingContent(contentPanel, allFindings[firstOriginalIndex]);
        } else {
          renderFindingContent(contentPanel, null);
        }
      }

      searchInput.addEventListener('input', function () {
        filteredFindings = filterFindings(allFindings, this.value);
        renderList();
        selectFirst();
      });

      renderList();
      selectFirst();
    }
  };
})();