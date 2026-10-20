/* 07-project-form/05_draft_branches.js — working on a branch and merging it.
 *
 * A branch is a forked copy of the project file: the person forks the
 * version they opened, works on their own copy, and merges it back when it
 * is ready. The merge is a three-way merge — a field only the branch
 * changed comes over, a field both sides changed differently is a conflict
 * the person decides by hand.
 */
    let draftBranchItems = [];
    let draftBranchDraftId = '';
    let draftBranchMerge = null;

    function draftBranchStateLabel(branch) {
      return branch.status === 'merged'
        ? WFT('draft_branch.merged', 'تم الدمج')
        : WFT('draft_branch.state_open', 'مفتوح');
    }

    function renderDraftBranches() {
      const host = document.getElementById('draftVersionsBranches');
      if (!host) return;
      if (!draftBranchItems.length) {
        host.innerHTML = '';
        return;
      }
      host.innerHTML = '<h3 class="change-log-day">' +
        WFT('draft_branch.title', 'فروع المشروع') + '</h3>' +
        draftBranchItems.map(branch => {
          const label = branch.branch_label || branch.name || '';
          return '<div class="change-log-entry">' +
            '<div class="change-log-head">' +
              '<span class="change-log-badge badge-manual">' +
                escapeHtml(draftBranchStateLabel(branch)) + '</span>' +
              '<span class="change-log-action">' + escapeHtml(label) + '</span>' +
              '<span class="change-log-stamp">' +
                escapeHtml(branch.created_by_name || branch.created_by || '—') + '</span>' +
            '</div>' +
            '<div class="change-log-summary" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">' +
              '<button type="button" class="btn small ghost" onclick="openDraftBranch(\'' +
                branch.branch_draft_id + '\')">' +
                WFT('draft_branch.open', 'فتح الفرع') + '</button>' +
              (branch.status === 'merged' ? '' :
                '<button type="button" class="btn small ghost" onclick="previewDraftBranchMerge(\'' +
                  branch.id + '\')">' +
                  WFT('draft_branch.merge', 'دمج الفرع') + '</button>') +
              (branch.status === 'merged' ? '' :
                '<button type="button" class="btn small ghost danger" onclick="discardDraftBranch(\'' +
                  branch.id + '\')">' +
                  WFT('draft_branch.discard', 'حذف الفرع') + '</button>') +
            '</div>' +
          '</div>';
        }).join('');
    }

    async function loadDraftBranches(draftId) {
      draftBranchDraftId = draftId;
      try {
        const data = await api('GET', '/api/project-draft/' + encodeURIComponent(draftId) + '/branches');
        draftBranchItems = (data && data.branches) || [];
      } catch (error) {
        draftBranchItems = [];
      }
      renderDraftBranches();
    }

    async function createDraftBranch(commitId) {
      if (!draftVersionDraftId) return;
      const name = window.prompt(WFT('draft_branch.name', 'اسم الفرع'), '');
      if (name === null) return;
      try {
        const data = await api('POST', '/api/project-draft/' + encodeURIComponent(draftVersionDraftId) +
          '/branches', { name: (name || '').trim(), baseCommitId: commitId });
        if (!data || !data.success) {
          toast(WFT('draft_branch.create_failed', 'تعذر إنشاء الفرع'));
          return;
        }
        toast(WFT('draft_branch.created', 'تم إنشاء الفرع'));
        await loadDraftBranches(draftVersionDraftId);
        if (data.branchDraftId && typeof openProjectDraftById === 'function') {
          openProjectDraftById(data.branchDraftId);
        }
      } catch (error) {
        toast(WFT('draft_branch.create_failed', 'تعذر إنشاء الفرع'));
      }
    }

    function openDraftBranch(branchDraftId) {
      if (typeof openProjectDraftById === 'function') openProjectDraftById(branchDraftId);
    }

    async function discardDraftBranch(branchId) {
      if (!draftBranchDraftId) return;
      const confirmed = window.confirm(WFT('draft_branch.discard_confirm',
        'حذف الفرع وكل ما فيه؟'));
      if (!confirmed) return;
      try {
        const data = await api('DELETE', '/api/project-draft/' + encodeURIComponent(draftBranchDraftId) +
          '/branches/' + encodeURIComponent(branchId), {});
        if (!data || !data.success) {
          toast(WFT('draft_branch.merge_failed', 'تعذر دمج الفرع'));
          return;
        }
        toast(WFT('draft_branch.discarded', 'تم حذف الفرع'));
        await loadDraftBranches(draftBranchDraftId);
      } catch (error) {
        toast(WFT('draft_branch.merge_failed', 'تعذر دمج الفرع'));
      }
    }

    function ensureDraftBranchMergePage() {
      let overlay = document.getElementById('draftBranchMergePage');
      if (overlay) return overlay;
      overlay = document.createElement('div');
      overlay.id = 'draftBranchMergePage';
      overlay.className = 'll-modal-overlay change-log-overlay';
      overlay.setAttribute('data-a11y-modal', '');
      overlay.addEventListener('click', event => {
        if (event.target === overlay) closeDraftBranchMergePage();
      });
      overlay.innerHTML = '<div class="ll-modal-card change-log-card" role="dialog" aria-modal="true">' +
        '<div class="sag-modal-head"><h2 id="draftBranchMergeTitle"></h2>' +
        '<button type="button" class="btn ghost small" id="draftBranchMergeClose"></button></div>' +
        '<div id="draftBranchMergeBody"></div></div>';
      document.body.appendChild(overlay);
      overlay.querySelector('#draftBranchMergeClose')
        .addEventListener('click', closeDraftBranchMergePage);
      return overlay;
    }

    function closeDraftBranchMergePage() {
      const overlay = document.getElementById('draftBranchMergePage');
      if (overlay) overlay.style.display = 'none';
      if (typeof a11yModalDidClose === 'function') a11yModalDidClose();
    }

    function draftBranchValueText(value, absent) {
      if (absent) return '—';
      if (value === null || value === undefined) return '—';
      const text = typeof value === 'string' ? value : JSON.stringify(value);
      return text.length > 80 ? text.slice(0, 80) + '…' : text;
    }

    function renderDraftBranchMerge() {
      const overlay = document.getElementById('draftBranchMergePage');
      if (!overlay || !draftBranchMerge) return;
      const body = overlay.querySelector('#draftBranchMergeBody');
      const changes = draftBranchMerge.changes || [];
      const conflicts = draftBranchMerge.conflicts || [];
      const blocks = [];
      if (changes.length) {
        blocks.push('<div class="change-log-day">' +
          WFT('draft_branch.changes', 'تغييرات الدمج') + '</div>');
        blocks.push('<div class="change-log-entry"><div class="change-log-summary">' +
          changes.map(item => '<div>' + escapeHtml(item.key) + ': ' +
            escapeHtml(draftBranchValueText(item.value, item.action === 'delete')) +
            '</div>').join('') + '</div></div>');
      }
      if (conflicts.length) {
        blocks.push('<div class="change-log-day">' +
          WFT('draft_branch.conflicts', 'تعارضات تحتاج قرار') + '</div>');
        blocks.push(conflicts.map((item, index) => {
          const picked = draftBranchMerge.picks[item.key] || '';
          return '<div class="change-log-entry">' +
            '<div class="change-log-action">' + escapeHtml(item.key) + '</div>' +
            '<div class="change-log-summary">' +
              '<div>' + escapeHtml(WFT('draft_branch.keep_ours', 'نسخة المشروع')) + ': ' +
                escapeHtml(draftBranchValueText(item.ours, item.ours_absent)) + '</div>' +
              '<div>' + escapeHtml(WFT('draft_branch.keep_theirs', 'نسخة الفرع')) + ': ' +
                escapeHtml(draftBranchValueText(item.theirs, item.theirs_absent)) + '</div>' +
            '</div>' +
            '<div class="change-log-summary" style="display:flex;gap:8px;margin-top:8px">' +
              '<button type="button" class="btn small ' + (picked === 'ours' ? 'primary' : 'ghost') +
                '" onclick="pickDraftBranchSide(\'' + item.key + '\', \'ours\')">' +
                WFT('draft_branch.keep_ours', 'نسخة المشروع') + '</button>' +
              '<button type="button" class="btn small ' + (picked === 'theirs' ? 'primary' : 'ghost') +
                '" onclick="pickDraftBranchSide(\'' + item.key + '\', \'theirs\')">' +
                WFT('draft_branch.keep_theirs', 'نسخة الفرع') + '</button>' +
            '</div>' +
          '</div>';
        }).join(''));
      }
      if (!blocks.length) {
        blocks.push('<p class="tenant-hint">' +
          WFT('draft_branch.changes', 'تغييرات الدمج') + ': —</p>');
      }
      const ready = conflicts.every(item => draftBranchMerge.picks[item.key]);
      blocks.push('<div style="margin-top:12px">' +
        '<button type="button" class="btn primary" ' + (ready ? '' : 'disabled ') +
          'onclick="commitDraftBranchMerge()">' +
          WFT('draft_branch.merge', 'دمج الفرع') + '</button></div>');
      body.innerHTML = blocks.join('');
    }

    function pickDraftBranchSide(key, choice) {
      if (!draftBranchMerge) return;
      draftBranchMerge.picks[key] = choice;
      renderDraftBranchMerge();
    }

    async function previewDraftBranchMerge(branchId) {
      if (!draftBranchDraftId) return;
      const overlay = ensureDraftBranchMergePage();
      overlay.querySelector('#draftBranchMergeTitle').textContent =
        WFT('draft_branch.merge', 'دمج الفرع');
      overlay.querySelector('#draftBranchMergeClose').textContent = WFT('common.close', 'إغلاق');
      overlay.querySelector('#draftBranchMergeBody').innerHTML =
        '<p class="tenant-hint">' + WFT('common.loading', 'جاري التحميل...') + '</p>';
      overlay.style.display = 'flex';
      if (typeof a11yModalDidOpen === 'function') a11yModalDidOpen(overlay);
      try {
        const data = await api('GET', '/api/project-draft/' + encodeURIComponent(draftBranchDraftId) +
          '/branches/' + encodeURIComponent(branchId) + '/preview');
        if (!data || !data.success) {
          overlay.querySelector('#draftBranchMergeBody').innerHTML =
            '<p class="tenant-hint">' + WFT('draft_branch.merge_failed', 'تعذر دمج الفرع') + '</p>';
          return;
        }
        draftBranchMerge = {
          branchId: branchId,
          changes: data.changes || [],
          conflicts: data.conflicts || [],
          picks: {},
        };
        renderDraftBranchMerge();
      } catch (error) {
        overlay.querySelector('#draftBranchMergeBody').innerHTML =
          '<p class="tenant-hint">' + WFT('draft_branch.merge_failed', 'تعذر دمج الفرع') + '</p>';
      }
    }

    async function commitDraftBranchMerge() {
      if (!draftBranchMerge || !draftBranchDraftId) return;
      const conflicts = draftBranchMerge.conflicts || [];
      if (conflicts.some(item => !draftBranchMerge.picks[item.key])) {
        toast(WFT('draft_branch.needs_decision', 'اختر النسخة التيتبقى لكل تعارض قبل الدمج'));
        return;
      }
      const resolutions = conflicts.map(item => ({
        key: item.key,
        choice: draftBranchMerge.picks[item.key],
      }));
      try {
        const data = await api('POST', '/api/project-draft/' + encodeURIComponent(draftBranchDraftId) +
          '/branches/' + encodeURIComponent(draftBranchMerge.branchId) + '/merge',
          { resolutions: resolutions });
        if (!data || !data.success) {
          toast(WFT('draft_branch.merge_failed', 'تعذر دمج الفرع'));
          return;
        }
        toast(WFT('draft_branch.merged_toast', 'تم دمج الفرع'));
        closeDraftBranchMergePage();
        draftBranchMerge = null;
        await loadDraftBranches(draftBranchDraftId);
        if (typeof showDraftVersions === 'function') await showDraftVersions(draftBranchDraftId);
      } catch (error) {
        toast(WFT('draft_branch.merge_failed', 'تعذر دمج الفرع'));
      }
    }
