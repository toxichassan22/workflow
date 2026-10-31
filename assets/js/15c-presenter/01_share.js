/* Owner-side presentation sharing: create a read-only public link with an
   optional password and a chosen lifetime, copy it, open it, or revoke it. */

    function shareText(key, fallback, params) {
      return (typeof WFT === 'function') ? WFT(key, fallback, params) : fallback;
    }

    function shareFormatDate(value) {
      const text = String(value || '').trim();
      if (!text) return '';
      try {
        const parsed = new Date(text.replace(' ', 'T') + 'Z');
        if (isNaN(parsed.getTime())) return text;
        return (typeof wfDate === 'function') ? wfDate(parsed) : parsed.toISOString().slice(0, 10);
      } catch (error) {
        return text;
      }
    }

    function ensurePresentationShareModal() {
      let modal = document.getElementById('presentationShareModal');
      if (modal) return modal;
      modal = document.createElement('div');
      modal.id = 'presentationShareModal';
      modal.className = 'share-modal';
      modal.innerHTML = '<div class="share-card" role="dialog" aria-modal="true">'
        + '<div class="share-head"><h3>' + escapeHtml(shareText('sh.title', 'مشاركة العرض')) + '</h3>'
        + '<button type="button" class="share-close" onclick="closePresentationShareDialog()">'
        + escapeHtml(shareText('sh.close', 'إغلاق')) + '</button></div>'
        + '<div class="share-create">'
        + '<label for="sharePasswordInput">' + escapeHtml(shareText('sh.password', 'كلمة المرور (اختياري)')) + '</label>'
        + '<input type="password" id="sharePasswordInput" autocomplete="new-password">'
        + '<label for="shareExpirySelect">' + escapeHtml(shareText('sh.expiry', 'مدة الصلاحية')) + '</label>'
        + '<select id="shareExpirySelect">'
        + '<option value="1d">' + escapeHtml(shareText('sh.expiry_1d', '24 ساعة')) + '</option>'
        + '<option value="7d" selected>' + escapeHtml(shareText('sh.expiry_7d', '7 أيام')) + '</option>'
        + '<option value="30d">' + escapeHtml(shareText('sh.expiry_30d', '30 يومًا')) + '</option>'
        + '<option value="never">' + escapeHtml(shareText('sh.expiry_never', 'دائم حتى الإلغاء')) + '</option>'
        + '</select>'
        + '<button type="button" class="btn primary share-create-btn" id="shareCreateButton" onclick="createPresentationShare()">'
        + escapeHtml(shareText('sh.create_button', 'إنشاء رابط')) + '</button>'
        + '</div>'
        + '<div class="share-list" id="shareList"></div>'
        + '</div>';
      modal.addEventListener('click', event => {
        if (event.target === modal) closePresentationShareDialog();
      });
      document.body.appendChild(modal);
      return modal;
    }

    async function openPresentationShareDialog() {
      if (!tenantPresentationId) {
        toast(shareText('sh.need_save', 'احفظ العرض أولًا لإنشاء رابط مشاركة'));
        return;
      }
      if (!hasPermission('create_presentation')) return;
      const modal = ensurePresentationShareModal();
      modal.classList.add('is-open');
      await refreshPresentationShareList();
    }

    function closePresentationShareDialog() {
      const modal = document.getElementById('presentationShareModal');
      if (modal) modal.classList.remove('is-open');
    }

    function shareStatusLabel(share) {
      const status = String(share.status || 'active');
      if (status === 'revoked') return shareText('sh.status_revoked', 'ملغى');
      if (status === 'expired') return shareText('sh.status_expired', 'منتهي');
      return shareText('sh.status_active', 'نشط');
    }

    function shareRowHtml(share) {
      const expiredOrRevoked = ['revoked', 'expired'].includes(String(share.status || 'active'));
      const details = [];
      if (share.createdAt) details.push(shareText('sh.created_at', 'أُنشئ') + ': ' + shareFormatDate(share.createdAt));
      details.push(share.expiresAt
        ? shareText('sh.expires_at', 'ينتهي') + ': ' + shareFormatDate(share.expiresAt)
        : shareText('sh.no_expiry', 'بلا انتهاء'));
      details.push(shareText('sh.views', 'المشاهدات') + ': ' + (share.viewCount || 0));
      details.push(share.hasPassword ? shareText('sh.password_on', 'بكلمة مرور') : shareText('sh.password_off', 'بلا كلمة مرور'));
      return '<div class="share-row is-' + escapeHtml(String(share.status || 'active')) + '" data-share-id="'
        + escapeHtml(share.id || '') + '">'
        + '<div class="share-row-main">'
        + '<span class="share-status">' + escapeHtml(shareStatusLabel(share)) + '</span>'
        + '<span class="share-meta">' + escapeHtml(details.join(' · ')) + '</span>'
        + '</div>'
        + '<div class="share-row-actions">'
        + (expiredOrRevoked ? '' :
          '<button type="button" onclick="copyPresentationShareUrl(\'' + escapeHtml(share.url || '') + '\')">'
          + escapeHtml(shareText('sh.copy', 'نسخ الرابط')) + '</button>'
          + '<button type="button" onclick="window.open(this.dataset.url, \'_blank\', \'noopener\')" data-url="'
          + escapeHtml(share.url || '') + '">' + escapeHtml(shareText('sh.open', 'فتح')) + '</button>'
          + '<button type="button" class="is-danger" onclick="revokePresentationShare(\'' + escapeHtml(share.id || '') + '\')">'
          + escapeHtml(shareText('sh.revoke', 'إلغاء')) + '</button>')
        + '</div></div>';
    }

    async function refreshPresentationShareList() {
      const box = document.getElementById('shareList');
      if (!box || !tenantPresentationId) return;
      box.innerHTML = '<div class="share-empty">' + escapeHtml(shareText('common.loading', 'جاري التحميل...')) + '</div>';
      try {
        const response = await api('GET', '/api/presentations/' + encodeURIComponent(tenantPresentationId) + '/shares');
        if (!response?.success) throw new Error(response?.error || shareText('sh.load_error', 'تعذر تحميل روابط المشاركة'));
        const shares = Array.isArray(response.shares) ? response.shares : [];
        box.innerHTML = shares.length
          ? shares.map(shareRowHtml).join('')
          : '<div class="share-empty">' + escapeHtml(shareText('sh.empty', 'لا توجد روابط مشاركة لهذا العرض')) + '</div>';
      } catch (error) {
        box.innerHTML = '<div class="share-empty is-error">'
          + escapeHtml(error?.message || shareText('sh.load_error', 'تعذر تحميل روابط المشاركة')) + '</div>';
      }
    }

    async function createPresentationShare() {
      const button = document.getElementById('shareCreateButton');
      const passwordInput = document.getElementById('sharePasswordInput');
      const expirySelect = document.getElementById('shareExpirySelect');
      if (!tenantPresentationId || !button) return;
      button.disabled = true;
      button.textContent = shareText('sh.creating', 'جاري الإنشاء...');
      try {
        const response = await api('POST', '/api/presentations/'
          + encodeURIComponent(tenantPresentationId) + '/shares', {
          password: passwordInput ? String(passwordInput.value || '') : '',
          expiresIn: expirySelect ? expirySelect.value : 'never'
        });
        if (!response?.success || !response.share) {
          throw new Error(response?.error || shareText('sh.error', 'تعذر إنشاء رابط المشاركة'));
        }
        if (passwordInput) passwordInput.value = '';
        await refreshPresentationShareList();
        if (navigator.clipboard && response.share.url) {
          navigator.clipboard.writeText(response.share.url).then(() => {
            toast(shareText('sh.created_and_copied', 'أُنشئ الرابط ونُسخ'));
          }).catch(() => {
            toast(shareText('sh.created', 'أُنشئ رابط المشاركة'));
          });
        } else {
          toast(shareText('sh.created', 'أُنشئ رابط المشاركة'));
        }
      } catch (error) {
        toast(error?.message || shareText('sh.error', 'تعذر إنشاء رابط المشاركة'));
      } finally {
        button.disabled = false;
        button.textContent = shareText('sh.create_button', 'إنشاء رابط');
      }
    }

    function copyPresentationShareUrl(url) {
      if (!url) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(
          () => toast(shareText('sh.copied', 'نُسخ الرابط')),
          () => window.prompt(shareText('sh.copy', 'نسخ الرابط'), url)
        );
        return;
      }
      window.prompt(shareText('sh.copy', 'نسخ الرابط'), url);
    }

    async function revokePresentationShare(shareId) {
      if (!tenantPresentationId || !shareId) return;
      if (!confirm(shareText('sh.revoke_confirm', 'سيتوقف هذا الرابط عن العمل فورًا. إلغاء الرابط؟'))) return;
      try {
        const response = await api('POST', '/api/presentations/'
          + encodeURIComponent(tenantPresentationId) + '/shares/'
          + encodeURIComponent(shareId) + '/revoke');
        if (!response?.success) throw new Error(response?.error || shareText('sh.revoke_error', 'تعذر إلغاء الرابط'));
        toast(shareText('sh.revoked', 'أُلغي الرابط'));
        await refreshPresentationShareList();
      } catch (error) {
        toast(error?.message || shareText('sh.revoke_error', 'تعذر إلغاء الرابط'));
      }
    }
