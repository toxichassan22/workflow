/* 07-project-form/06_draft_merge_decisions.js — deciding a save conflict.
 *
 * Two people saved the same project file at the same time. The server merges
 * what it can and asks for a decision on the fields both sides changed — the
 * same three-way merge the branch merge uses. The answer goes back with the
 * save, and the file keeps both sides' work.
 */
    let draftMergeDecisionPicks = {};

    function ensureDraftMergeDecisionsPage() {
      let overlay = document.getElementById('draftMergeDecisionsPage');
      if (overlay) return overlay;
      overlay = document.createElement('div');
      overlay.id = 'draftMergeDecisionsPage';
      overlay.className = 'll-modal-overlay change-log-overlay';
      overlay.setAttribute('data-a11y-modal', '');
      overlay.innerHTML = '<div class="ll-modal-card change-log-card" role="dialog" aria-modal="true">' +
        '<div class="sag-modal-head"><h2 id="draftMergeDecisionsTitle"></h2>' +
        '<button type="button" class="btn ghost small" id="draftMergeDecisionsCancel"></button></div>' +
        '<div id="draftMergeDecisionsBody"></div></div>';
      document.body.appendChild(overlay);
      return overlay;
    }

    function draftMergeValueText(value, absent) {
      if (absent) return '—';
      if (value === null || value === undefined) return '—';
      const text = typeof value === 'string' ? value : JSON.stringify(value);
      return text.length > 80 ? text.slice(0, 80) + '…' : text;
    }

    function renderDraftMergeDecisions(conflicts) {
      const overlay = document.getElementById('draftMergeDecisionsPage');
      if (!overlay) return;
      const body = overlay.querySelector('#draftMergeDecisionsBody');
      const rows = conflicts.map(item => {
        const picked = draftMergeDecisionPicks[item.key] || '';
        return '<div class="change-log-entry">' +
          '<div class="change-log-action">' + escapeHtml(item.key) + '</div>' +
          '<div class="change-log-summary">' +
            '<div>' + escapeHtml(WFT('draft_merge.keep_ours', 'نسخة المشروع')) + ': ' +
              escapeHtml(draftMergeValueText(item.ours, item.ours_absent)) + '</div>' +
            '<div>' + escapeHtml(WFT('draft_merge.keep_mine', 'نسختي')) + ': ' +
              escapeHtml(draftMergeValueText(item.theirs, item.theirs_absent)) + '</div>' +
          '</div>' +
          '<div class="change-log-summary" style="display:flex;gap:8px;margin-top:8px">' +
            '<button type="button" class="btn small ' + (picked === 'ours' ? 'primary' : 'ghost') +
              '" onclick="pickDraftMergeSide(\'' + item.key + '\', \'ours\')">' +
              WFT('draft_merge.keep_ours', 'نسخة المشروع') + '</button>' +
            '<button type="button" class="btn small ' + (picked === 'theirs' ? 'primary' : 'ghost') +
              '" onclick="pickDraftMergeSide(\'' + item.key + '\', \'theirs\')">' +
              WFT('draft_merge.keep_mine', 'نسختي') + '</button>' +
          '</div>' +
        '</div>';
      }).join('');
      const ready = conflicts.every(item => draftMergeDecisionPicks[item.key]);
      body.innerHTML = '<p class="tenant-hint">' +
        WFT('draft_merge.intro', 'شخص آخر عدّل نفس الحقول. اختار النسخة اللي تتبقى لكل تعارض.') +
        '</p>' + rows +
        '<div style="margin-top:12px">' +
          '<button type="button" class="btn primary" ' + (ready ? '' : 'disabled ') +
            'id="draftMergeDecisionsApply">' +
            WFT('draft_merge.apply', 'دمج وحفظ') + '</button>' +
        '</div>';
      const apply = body.querySelector('#draftMergeDecisionsApply');
      if (apply) {
        apply.addEventListener('click', () => {
          const decisions = conflicts.map(item => ({
            key: item.key,
            choice: draftMergeDecisionPicks[item.key],
          }));
          closeDraftMergeDecisionsPage();
          draftMergeDecisionPicks = {};
          resolveDraftMergeDecisions(decisions);
        });
      }
    }

    let draftMergeDecisionResolver = null;

    function resolveDraftMergeDecisions(decisions) {
      const resolver = draftMergeDecisionResolver;
      draftMergeDecisionResolver = null;
      if (resolver) resolver(decisions);
    }

    function closeDraftMergeDecisionsPage() {
      const overlay = document.getElementById('draftMergeDecisionsPage');
      if (overlay) overlay.style.display = 'none';
      if (typeof a11yModalDidClose === 'function') a11yModalDidClose();
    }

    function pickDraftMergeSide(key, choice) {
      draftMergeDecisionPicks[key] = choice;
      const overlay = document.getElementById('draftMergeDecisionsPage');
      const body = overlay && overlay.querySelector('#draftMergeDecisionsBody');
      if (!body) return;
      const conflicts = (draftMergeDecisionConflicts || []).filter(
        item => item.key in draftMergeDecisionPicks);
      renderDraftMergeDecisions(conflicts);
    }

    let draftMergeDecisionConflicts = [];

    function askDraftMergeDecisions(conflicts) {
      return new Promise(resolve => {
        if (!conflicts || !conflicts.length) {
          resolve([]);
          return;
        }
        const overlay = ensureDraftMergeDecisionsPage();
        overlay.querySelector('#draftMergeDecisionsTitle').textContent =
          WFT('draft_merge.title', 'تعارض في الحفظ');
        overlay.querySelector('#draftMergeDecisionsCancel').textContent =
          WFT('draft_merge.cancel', 'إلغاء');
        overlay.querySelector('#draftMergeDecisionsCancel').onclick = () => {
          closeDraftMergeDecisionsPage();
          draftMergeDecisionPicks = {};
          resolveDraftMergeDecisions(null);
        };
        draftMergeDecisionConflicts = conflicts;
        draftMergeDecisionPicks = {};
        renderDraftMergeDecisions(conflicts);
        overlay.style.display = 'flex';
        if (typeof a11yModalDidOpen === 'function') a11yModalDidOpen(overlay);
        draftMergeDecisionResolver = resolve;
      });
    }
