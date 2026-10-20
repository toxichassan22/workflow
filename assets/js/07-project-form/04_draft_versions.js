/* 07-project-form/04_draft_versions.js — the version history of a project file.
 *
 * Every save of a project file leaves a version behind, the way a git
 * repository keeps one commit per change. An older version can be restored,
 * and the restore itself becomes a new version — the history is never
 * rewritten, so work that was overwritten stays reachable instead of being
 * lost. The list shows who saved, when, and how many fields the version
 * touched; the restore asks first, because it moves the file back.
 */
    let draftVersionCommits = [];
    let draftVersionDraftId = '';

    function ensureDraftVersionsPage() {
      let overlay = document.getElementById('draftVersionsPage');
      if (overlay) return overlay;
      overlay = document.createElement('div');
      overlay.id = 'draftVersionsPage';
      overlay.className = 'll-modal-overlay change-log-overlay';
      overlay.setAttribute('data-a11y-modal', '');
      overlay.addEventListener('click', event => {
        if (event.target === overlay) closeDraftVersionsPage();
      });
      overlay.innerHTML = '<div class="ll-modal-card change-log-card" role="dialog" aria-modal="true">' +
        '<div class="sag-modal-head"><h2 id="draftVersionsTitle"></h2>' +
        '<button type="button" class="btn ghost small" id="draftVersionsClose"></button></div>' +
        '<div id="draftVersionsBody"></div></div>';
      document.body.appendChild(overlay);
      overlay.querySelector('#draftVersionsClose').addEventListener('click', closeDraftVersionsPage);
      return overlay;
    }

    function closeDraftVersionsPage() {
      const overlay = document.getElementById('draftVersionsPage');
      if (overlay) overlay.style.display = 'none';
      if (typeof a11yModalDidClose === 'function') a11yModalDidClose();
    }

    function draftVersionStamp(value) {
      if (typeof formatChangeLogStamp === 'function') return formatChangeLogStamp(value);
      return String(value || '').slice(0, 16).replace('T', ' ');
    }

    function renderDraftVersions() {
      const overlay = document.getElementById('draftVersionsPage');
      if (!overlay) return;
      const body = overlay.querySelector('#draftVersionsBody');
      if (!draftVersionCommits.length) {
        body.innerHTML = '<p class="tenant-hint">' +
          WFT('draft_versions.empty', 'لا توجد إصدارات محفوظة') + '</p>';
        return;
      }
      body.innerHTML = draftVersionCommits.map(commit => {
        const kind = commit.kind === 'restore'
          ? WFT('draft_versions.kind_restore', 'استرجاع')
          : WFT('draft_versions.kind_save', 'حفظ');
        const author = commit.author_name || commit.author_id || '—';
        const changed = WFT('draft_versions.changed', '{n} حقل', { n: Number(commit.changed_count) || 0 });
        return '<div class="change-log-entry">' +
          '<div class="change-log-head">' +
            '<span class="change-log-badge badge-manual">' + escapeHtml(kind) + '</span>' +
            '<span class="change-log-action">' + escapeHtml(author) + '</span>' +
            '<span class="change-log-stamp">' + escapeHtml(draftVersionStamp(commit.created_at)) + '</span>' +
          '</div>' +
          '<div class="change-log-summary">' + escapeHtml(changed) + '</div>' +
          '<div style="margin-top:8px">' +
            '<button type="button" class="btn small ghost" onclick="restoreDraftVersion(\'' + commit.id + '\')">' +
              WFT('draft_versions.restore', 'استرجاع') +
            '</button>' +
          '</div>' +
        '</div>';
      }).join('');
    }

    async function showDraftVersions(draftId) {
      const overlay = ensureDraftVersionsPage();
      const body = overlay.querySelector('#draftVersionsBody');
      overlay.querySelector('#draftVersionsTitle').textContent = WFT('draft_versions.title', 'إصدارات المشروع');
      overlay.querySelector('#draftVersionsClose').textContent = WFT('common.close', 'إغلاق');
      body.innerHTML = '<p class="tenant-hint">' + WFT('common.loading', 'جاري التحميل...') + '</p>';
      overlay.style.display = 'flex';
      if (typeof a11yModalDidOpen === 'function') a11yModalDidOpen(overlay);
      try {
        const data = await api('GET', '/api/project-draft/' + encodeURIComponent(draftId) + '/commits');
        if (!data || !data.success) {
          body.innerHTML = '<p class="tenant-hint">' +
            escapeHtml((data && data.error) || WFT('common.error', 'حدث خطأ')) + '</p>';
          return;
        }
        draftVersionCommits = data.commits || [];
        draftVersionDraftId = draftId;
        renderDraftVersions();
      } catch (error) {
        body.innerHTML = '<p class="tenant-hint">' + WFT('common.error', 'حدث خطأ') + '</p>';
      }
    }

    async function restoreDraftVersion(commitId) {
      if (!draftVersionDraftId) return;
      const confirmed = window.confirm(WFT('draft_versions.restore_confirm',
        'استرجاع هذه النسخة؟ شغلك الحالي سيبقى في السجل كنسخة جديدة.'));
      if (!confirmed) return;
      try {
        const data = await api('POST',
          '/api/project-draft/' + encodeURIComponent(draftVersionDraftId) +
          '/commits/' + encodeURIComponent(commitId) + '/restore', {});
        if (!data || !data.success) {
          toast(WFT('draft_versions.restore_failed', 'تعذر استرجاع النسخة'));
          return;
        }
        toast(WFT('draft_versions.restored', 'تم استرجاع النسخة'));
        await showDraftVersions(draftVersionDraftId);
      } catch (error) {
        toast(WFT('draft_versions.restore_failed', 'تعذر استرجاع النسخة'));
      }
    }
