/* 03_source_links.js - competitor source cell editor and the summary source register. */

    function marketSourcesTableHtml() {
      return '<div class="table-wrap"><table class="market-sources-table">' +
        '<thead><tr><th>المصدر</th><th>الرابط</th><th>تاريخ البيانات</th>' +
        '<th>تاريخ الوصول</th><th>الموثوقية</th><th>ملاحظة</th><th></th></tr></thead><tbody></tbody></table></div>';
    }

    function selectMarketSourceTab(key) {
      const value = String(key || 'general');
      document.querySelectorAll('#marketSourcesTabs .market-source-tab').forEach(button => {
        const active = button.dataset.sourceTab === value;
        button.classList.toggle('active', active);
        button.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      document.querySelectorAll('#marketSourcesPanels .market-source-panel').forEach(panel => {
        panel.hidden = panel.dataset.sourceTab !== value;
      });
    }

    function marketCompetitorDomRow(competitorId) {
      return Array.from(document.querySelectorAll('#marketCompetitorsTable tbody tr'))
        .find(row => row.dataset.competitorId === String(competitorId || ''));
    }

    function rewriteMarketCompetitorSourceUrl(competitor, previousUrl, nextUrl) {
      if (!competitor) return;
      const previous = String(previousUrl || '').trim().toLowerCase();
      const next = safeMarketUrl(nextUrl) ? String(nextUrl).trim() : '';
      const nextKey = next.toLowerCase();
      if (previous && previous !== nextKey) {
        let replacedInput = false;
        competitor.querySelectorAll('[data-source-url]').forEach(input => {
          if (String(input.value || '').trim().toLowerCase() !== previous) return;
          if (next && !replacedInput) {
            input.value = next;
            input.dataset.previousUrl = next;
            replacedInput = true;
          } else {
            input.closest('[data-source-url-row]')?.remove();
          }
        });
        const host = competitor.querySelector('[data-source-links]');
        let replaced = false;
        host?.querySelectorAll('a[href]').forEach(anchor => {
          const href = String(anchor.getAttribute('href') || '').trim();
          if (href.toLowerCase() !== previous) return;
          if (next && !replaced) {
            anchor.setAttribute('href', next);
            anchor.textContent = next;
            replaced = true;
          } else {
            anchor.remove();
          }
        });
        if (next && !replaced && host) {
          host.insertAdjacentHTML('beforeend', '<a href="' + escapeHtml(next) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(next) + '</a>');
        }
        let fieldSources = {};
        try { fieldSources = JSON.parse(competitor.dataset.fieldSources || '{}') || {}; } catch (error) { fieldSources = {}; }
        Object.keys(fieldSources).forEach(field => {
          const values = marketValueList(fieldSources[field])
            .map(item => String(item || '').trim().toLowerCase() === previous ? next : item)
            .filter(Boolean);
          if (values.length) fieldSources[field] = Array.from(new Set(values));
          else delete fieldSources[field];
        });
        competitor.dataset.fieldSources = JSON.stringify(fieldSources);
        const sourceInput = competitor.querySelector('[data-field="source"]');
        if (sourceInput && String(sourceInput.value || '').toLowerCase().includes(previous)) {
          sourceInput.value = String(sourceInput.value || '').replace(new RegExp(previousUrl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'ig'), next).trim();
        }
        if (String(competitor.dataset.logoSourceUrl || '').trim().toLowerCase() === previous) {
          competitor.dataset.logoSourceUrl = next;
        }
      }
    }

    function competitorSourceUrlValues(tr) {
      return Array.from(tr?.querySelectorAll('[data-source-url]') || [])
        .map(input => String(input.value || '').trim())
        .filter(value => /^https?:\/\//i.test(value) && safeMarketUrl(value));
    }

    function renderCompetitorSourceLinks(tr) {
      const host = tr?.querySelector('[data-source-links]');
      if (!host) return;
      // One final page per competitor — never the chain of search/list pages
      // the model walked to reach it.
      const url = competitorSourceUrlValues(tr)[0] || '';
      const safeUrl = safeMarketUrl(url);
      host.innerHTML = safeUrl
        ? '<a href="' + escapeHtml(safeUrl) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(url) + '</a>'
        : '';
    }

    function renderCompetitorSourceUrlEditor(tr, row = {}) {
      const editor = tr?.querySelector('[data-source-url-editor]');
      if (!editor) return;
      const primary = competitorPrimarySourceUrl(row);
      editor.innerHTML = '<div class="tenant-hint">الروابط المرجعية</div>' +
        '<div class="market-source-url-row" data-source-url-row>' +
        '<input data-source-url value="' + escapeHtml(primary || '') + '" placeholder="https://..." inputmode="url">' +
        '</div>';
      const input = editor.querySelector('[data-source-url]');
      input.dataset.previousUrl = primary;
      input.addEventListener('input', () => {
        const previous = input.dataset.previousUrl || '';
        const next = String(input.value || '').trim();
        if (previous && previous.toLowerCase() !== next.toLowerCase()) {
          rewriteMarketCompetitorSourceUrl(tr, previous, next);
        }
        // From here on the client owns this link: a typed URL, a replacement
        // or a deliberate deletion must survive verification and citation
        // upgrades.
        tr.dataset.sourceUrlManual = '1';
        input.dataset.previousUrl = next;
        renderCompetitorSourceLinks(tr);
        persistMarketStudyFromDom();
      });
      refreshDynamicI18n(editor);
    }

    function attachMarketSourceToCompetitor(sourceRow) {
      const competitor = marketCompetitorDomRow(sourceRow?.dataset?.competitorId);
      const url = String(sourceRow?.querySelector('[data-field="url"]')?.value || '').trim();
      const previousUrl = sourceRow?.dataset?.previousUrl || '';
      rewriteMarketCompetitorSourceUrl(competitor, previousUrl, url);
      sourceRow.dataset.previousUrl = safeMarketUrl(url) ? url : '';
    }

    function removeMarketSourcePermanently(sourceRow) {
      if (!sourceRow) return;
      const url = String(sourceRow.querySelector('[data-field="url"]')?.value || '').trim();
      const competitor = marketCompetitorDomRow(sourceRow.dataset.competitorId);
      rewriteMarketCompetitorSourceUrl(competitor, url, '');
      sourceRow.remove();
      persistMarketStudyFromDom();
    }

    function addMarketSourceRow(row = {}, targetBody) {
      const sourceRow = { ...(row || {}) };
      let tb = targetBody;
      if (!tb) {
        let panel = document.querySelector('#marketSourcesPanels .market-source-panel:not([hidden])')
          || document.querySelector('#marketSourcesPanels .market-source-panel');
        if (!panel) {
          renderMarketSources([]);
          panel = document.querySelector('#marketSourcesPanels .market-source-panel');
        }
        if (panel && !sourceRow.competitor_id && panel.dataset.competitorId) {
          sourceRow.competitor_id = panel.dataset.competitorId;
          sourceRow.competitor_name = panel.dataset.competitorName || '';
        }
        tb = panel?.querySelector('tbody');
      }
      if (!tb) return;
      const tr = document.createElement('tr');
      tr.dataset.sourceKind = sourceRow.source_kind || '';
      tr.dataset.competitorId = sourceRow.competitor_id || '';
      tr.dataset.previousUrl = sourceRow.url || '';
      tr.dataset.sourceFields = JSON.stringify(sourceRow.source_fields || {});
      const safeUrl = safeMarketUrl(sourceRow.url || '');
      sourceRow.reliability = sourceRow.reliability || marketOfficialSourceReliability(
        sourceRow.competitor_name, sourceRow.name, sourceRow.url);
      const link = safeUrl
        ? '<a href="' + escapeHtml(safeUrl) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(sourceRow.url || '') + '</a>'
        : '';
      tr.innerHTML =
        '<td><textarea data-field="name" rows="2">' + escapeHtml(sourceRow.name || '') + '</textarea></td>' +
        '<td><input data-field="url" value="' + escapeHtml(sourceRow.url || '') + '"><div data-source-link class="market-source-links">' + link + '</div></td>' +
        '<td><input data-field="data_date" value="' + escapeHtml(sourceRow.data_date || '') + '"></td>' +
        '<td><input data-field="accessed_at" value="' + escapeHtml(sourceRow.accessed_at || '') + '"></td>' +
        '<td><textarea data-field="reliability" rows="2">' + escapeHtml(sourceRow.reliability || '') + '</textarea></td>' +
        '<td><textarea data-field="note" rows="2">' + escapeHtml(sourceRow.note || '') + '</textarea></td>' +
        '<td><button type="button" class="btn ghost small" data-remove-source>حذف</button></td>';
      tb.appendChild(tr);
      tr.querySelector('[data-remove-source]').addEventListener('click', () => removeMarketSourcePermanently(tr));
      tr.querySelector('[data-field="url"]').addEventListener('input', () => {
        const value = tr.querySelector('[data-field="url"]')?.value || '';
        const current = safeMarketUrl(value);
        const host = tr.querySelector('[data-source-link]');
        if (host) host.innerHTML = current
          ? '<a href="' + escapeHtml(current) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(value) + '</a>'
          : '';
        attachMarketSourceToCompetitor(tr);
        const reliability = tr.querySelector('[data-field="reliability"]');
        if (reliability && !reliability.value) {
          reliability.value = marketOfficialSourceReliability(
            tr.querySelector('[data-field="competitor_name"]')?.value,
            tr.querySelector('[data-field="name"]')?.value,
            value);
        }
      });
      tr.querySelectorAll('input,textarea').forEach(input => input.addEventListener('input', persistMarketStudyFromDom));
      refreshDynamicI18n(tr);
    }

    function collectMarketSourceRows() {
      return Array.from(document.querySelectorAll('#marketSourcesPanels .market-sources-table tbody tr')).map(tr => {
        const read = (field) => tr.querySelector('[data-field="' + field + '"]')?.value || '';
        let source_fields = {};
        try {
          source_fields = JSON.parse(tr.dataset.sourceFields || '{}') || {};
        } catch (error) {
          source_fields = {};
        }
        return {
          competitor_id: tr.dataset.competitorId || '',
          competitor_name: read('competitor_name'),
          source_kind: tr.dataset.sourceKind || '',
          source_fields,
          name: read('name'),
          url: read('url'),
          data_date: read('data_date'),
          accessed_at: read('accessed_at'),
          reliability: read('reliability'),
          note: read('note')
        };
      }).filter(row => row.name || row.url);
    }

    function renderMarketSources(rows) {
      const tabs = document.getElementById('marketSourcesTabs');
      const panels = document.getElementById('marketSourcesPanels');
      if (!tabs || !panels) return;
      const currentKey = tabs.querySelector('.market-source-tab.active')?.dataset.sourceTab || '';
      const groups = new Map();
      (Array.isArray(rows) ? rows : []).forEach(row => {
        const key = row.competitor_id || row.competitor_name
          ? 'competitor|' + (row.competitor_id || row.competitor_name)
          : 'general';
        if (!groups.has(key)) {
          groups.set(key, {
            key,
            label: row.competitor_name || 'مصادر عامة',
            competitorId: row.competitor_id || '',
            competitorName: row.competitor_name || '',
            rows: []
          });
        }
        groups.get(key).rows.push(row);
      });
      if (!groups.size) groups.set('general', {
        key: 'general', label: 'مصادر عامة', competitorId: '', competitorName: '', rows: []
      });
      const selectedKey = groups.has(currentKey) ? currentKey : groups.keys().next().value;
      tabs.innerHTML = '';
      panels.innerHTML = '';
      groups.forEach(group => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'market-source-tab';
        button.dataset.sourceTab = group.key;
        button.setAttribute('role', 'tab');
        button.textContent = group.label;
        button.addEventListener('click', () => selectMarketSourceTab(group.key));
        tabs.appendChild(button);

        const panel = document.createElement('section');
        panel.className = 'market-source-panel';
        panel.dataset.sourceTab = group.key;
        panel.dataset.competitorId = group.competitorId;
        panel.dataset.competitorName = group.competitorName;
        panel.hidden = group.key !== selectedKey;
        panel.innerHTML = marketSourcesTableHtml();
        panels.appendChild(panel);
        const body = panel.querySelector('tbody');
        group.rows.forEach(row => addMarketSourceRow(row, body));
      });
      selectMarketSourceTab(selectedKey);
      refreshDynamicI18n(tabs);
      refreshDynamicI18n(panels);
    }

