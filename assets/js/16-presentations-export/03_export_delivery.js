/* 16-presentations-export/03_export_delivery.js — export runs, the final-approval
   gate modal and the downloads library. */


    async function exportTenantSlides(format) {
      if (!Array.isArray(tenantSlidesData) || !tenantSlidesData.length) {
        toast('لا توجد شرائح للتصدير');
        return;
      }
      await repairVisualConceptStoredImages();
      persistVisualConceptDraftState();
      const projectName = tenantProjectData.project_name || tenantProjectData.projectName || 'presentation';
      renumberTenantSlides();
      try { syncSlideEditSessionsAfterRender(); } catch (err) {}
      tenantProjectData = { ...tenantProjectData, tenantSlidePlan };
      const exportProjectData = { ...tenantProjectData };
      delete exportProjectData.tenantSlidesData;
      delete exportProjectData.designerChat;
      delete exportProjectData.tenantArchiveCache;
      delete exportProjectData.draftHistory;
      delete exportProjectData.chatHistory;
      delete exportProjectData.designerChatSessions;
      const exportCover = (
        (tenantCreativeImages && (tenantCreativeImages.cover || tenantCreativeImages.coverImage || tenantCreativeImages.mainImageData)) ||
        (exportProjectData && (exportProjectData.cover || exportProjectData.coverImage || exportProjectData.mainImageData)) ||
        ''
      );
      if (exportCover && Array.isArray(tenantSlidesData)) {
        tenantSlidesData.forEach(item => {
          if (!item || typeof item !== 'object') return;
          let sHtml = String(item.html || '');
          const sType = String(item.type || '').toLowerCase();
          sHtml = sHtml.replace(/#*(?:IMAGE_COVER|COVER_IMAGE|MAIN_IMAGE|PROJECT_IMAGE_COVER)#*/gi, exportCover);
          if (sType === 'section_divider') {
            sHtml = forceSectionDividerBackgroundHtml(sHtml, exportCover);
          }
          item.html = sHtml;
        });
      }
      const payload = {
        format: format,
        presentationId: tenantPresentationId,
        projectName: projectName,
        projectData: exportProjectData,
        slidesData: tenantSlidesData
      };
      let data = null;
      showLoader('جاري تصدير الملف', 'الصيغة: ' + format.toUpperCase(), 8);
      try {
        data = await api('POST', '/api/export', payload);
        if (!data.success || !data.url) {
          toast(data.error || 'فشل التصدير');
          return;
        }
        updateLoaderProgress(82, 'تم إنشاء الملف، جاري بدء التحميل...');
        const fileName = data.url.split('/').pop() || ('presentation.' + format);
        let downloadRecord = null;
        try {
          const recResp = await api('POST', '/api/downloads', {
            fileName,
            presentationId: tenantPresentationId,
            draftId: tenantProjectData && (tenantProjectData.draftId || tenantProjectData.draft_id),
            format,
            versionLabel: 'v' + (tenantPresentationRevision || 1),
            exportId: data.exportId || null
          });
          if (recResp && recResp.success) downloadRecord = recResp.download;
        } catch (recErr) {
          console.warn('Download ledger record error:', recErr);
        }

        const token = getTenantToken();
        const resp = await fetch(data.url, { headers: token ? { 'Authorization': 'Bearer ' + token } : {} });
        if (!resp.ok) throw new Error('Download failed');
        const blob = await readBlobWithProgress(resp, 84, 98);
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = fileName;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(blobUrl);

        if (downloadRecord && downloadRecord.id) {
          api('POST', '/api/downloads/' + encodeURIComponent(downloadRecord.id) + '/delivered').catch(() => {});
        }

        updateLoaderProgress(100, 'اكتمل تحميل الملف');
        toast('تم تحميل الملف');
      } catch (e) {
        console.warn('Export download:', e);
        if (data && data.url) {
          window.open(data.url, '_blank');
          toast('تم إنشاء الملف، افتح نافذة التحميل');
        } else {
          toast('تعذر إكمال التصدير');
        }
      } finally {
        hideLoader();
      }
    }

    async function showFinalApprovalModal() {
      if (!tenantPresentationId) {
        toast(WFT('proposal.open_first_for_final', 'افتح عرضاً أولاً لطلب الاعتماد النهائي'));
        return;
      }
      let approvals = [];
      try {
        const resp = await api('GET', '/api/final-file-approvals?presentationId=' + encodeURIComponent(tenantPresentationId));
        if (resp && resp.success) approvals = resp.approvals || [];
      } catch (err) {
        console.warn('Final file approvals fetch:', err);
      }

      const pendingApproval = approvals.find(a => a.status === 'pending');
      const latestApproved = approvals.find(a => a.status === 'approved');
      const canApprove = hasPermission('approve_final_file');
      const isCompanyAdmin = Boolean(tenantUser && tenantUser.isAdmin) ||
        ((tenantUser && tenantUser._userRole) === 'company_admin');
      const isOwnRequest = Boolean(pendingApproval && pendingApproval.requested_by &&
        String(pendingApproval.requested_by) === String((tenantUser && tenantUser._userId) || ''));
      const canDecide = canApprove && (!isOwnRequest || isCompanyAdmin);

      const modal = document.createElement('div');
      modal.id = 'finalApprovalModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10000;display:flex;align-items:center;justify-content:center;padding:16px;';
      modal.innerHTML =
        '<div style="background:#fff;border-radius:16px;max-width:540px;width:100%;padding:24px;box-shadow:0 12px 32px rgba(0,0,0,.2);direction:rtl;text-align:right;">' +
        '<h3 style="margin:0 0 8px;color:#1a3a52;font-size:18px;">اعتماد الملف النهائي</h3>' +
        '<p style="margin:0 0 16px;color:#64748b;font-size:13px;">بوابة الاعتماد الثالثة — قفل إصدار العرض وختم البصمة الرقمية للملف</p>' +
        '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px;margin-bottom:16px;font-size:13px;line-height:1.8;">' +
        '<div><span style="color:#64748b;">العرض الحالي:</span> <strong>' + escapeHtml(tenantPresentationTitle || 'عرض بدون عنوان') + '</strong></div>' +
        '<div><span style="color:#64748b;">رقم الإصدار:</span> <strong>v' + (tenantPresentationRevision || 1) + '</strong></div>' +
        (latestApproved
          ? '<div style="margin-top:8px;padding-top:8px;border-top:1px solid #e2e8f0;color:#1c7a2e;">' +
            '<strong>معتمد نهائياً:</strong> معتمد بواسطة ' + escapeHtml(latestApproved.decided_by_name || '') +
            (latestApproved.stamped_file ? '<br><span style="font-size:11px;color:#475569;">البصمة الرقمية: ' + escapeHtml(latestApproved.stamped_file) + '</span>' : '') +
            '</div>'
          : '') +
        (pendingApproval
          ? '<div style="margin-top:8px;padding-top:8px;border-top:1px solid #e2e8f0;color:#a67c00;">' +
            'يوجد طلب اعتماد قيد المراجعة مقدم من ' + escapeHtml(pendingApproval.requested_by_name || '') +
            '</div>'
          : '') +
        '</div>' +
        '<div style="display:flex;gap:10px;justify-content:flex-end;">' +
        '<button type="button" id="closeFinalApproveBtn" class="btn ghost" style="padding:8px 18px;">إغلاق</button>' +
        (pendingApproval && canDecide
          ? '<button type="button" id="decideFinalApproveBtn" class="btn primary green" style="padding:8px 20px;">اعتماد وختم الملف</button>'
          : (!pendingApproval && !latestApproved
            ? '<button type="button" id="requestFinalApproveBtn" class="btn primary" style="padding:8px 20px;">إرسال طلب الاعتماد</button>'
            : '')) +
        '</div></div>';

      document.body.appendChild(modal);

      const close = () => { if (modal.parentNode) modal.parentNode.removeChild(modal); };
      const closeBtn = modal.querySelector('#closeFinalApproveBtn');
      if (closeBtn) closeBtn.onclick = close;

      const reqBtn = modal.querySelector('#requestFinalApproveBtn');
      if (reqBtn) {
        reqBtn.onclick = async () => {
          reqBtn.disabled = true;
          const res = await api('POST', '/api/presentations/' + encodeURIComponent(tenantPresentationId) + '/final-approval/request', {
            revision: tenantPresentationRevision || 1
          });
          if (res && res.success) {
            toast(WFT('proposal.final_approval_requested', 'تم إرسال طلب اعتماد الملف النهائي'));
            close();
          } else {
            toast(res?.error || 'فشل إرسال طلب الاعتماد');
            reqBtn.disabled = false;
          }
        };
      }

      const decideBtn = modal.querySelector('#decideFinalApproveBtn');
      if (decideBtn) {
        decideBtn.onclick = async () => {
          decideBtn.disabled = true;
          const res = await api('POST', '/api/final-file-approvals/' + encodeURIComponent(pendingApproval.id) + '/decision', {
            decision: 'approved'
          });
          if (res && res.success) {
            toast(WFT('proposal.final_approval_sealed', 'تم اعتماد وختم الملف النهائي بنجاح'));
            close();
          } else {
            toast(res?.error || 'فشل الاعتماد');
            decideBtn.disabled = false;
          }
        };
      }
    }

    async function showDownloadsLibraryModal(presentationId) {
      const scopePresentationId = presentationId || tenantPresentationId;
      let downloads = [];
      try {
        const query = scopePresentationId ? '?presentationId=' + encodeURIComponent(scopePresentationId) : '';
        const resp = await api('GET', '/api/downloads' + query);
        if (resp && resp.success) downloads = resp.downloads || [];
      } catch (err) {
        console.warn('Load downloads error:', err);
      }

      const modal = document.createElement('div');
      modal.id = 'downloadsLibraryModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10000;display:flex;align-items:center;justify-content:center;padding:16px;';
      const rows = downloads.length
        ? downloads.map(d => {
            const date = (d.downloaded_at || d.created_at || d.generated_at || '').slice(0, 16).replace('T', ' ');
            const approved = d.approval_status === 'approved';
            const statusLabel = approved
              ? (d.downloaded_at ? 'معتمد — تم التحميل' : 'معتمد — متاح للتحميل')
              : 'بانتظار الاعتماد النهائي';
            const statusStyle = approved
              ? 'background:#eef7ee;color:#1c7a2e;'
              : 'background:#fef3c7;color:#92400e;';
            const safeName = escapeHtml(d.file_name || 'ملف');
            const safeUrl = approved && d.download_url ? String(d.download_url) : '';
            return '<tr style="border-bottom:1px solid #e2e8f0;">' +
              '<td style="padding:10px 8px;font-weight:600;">' + safeName + '</td>' +
              '<td style="padding:10px 8px;text-transform:uppercase;">' + escapeHtml(d.format || '') + '</td>' +
              '<td style="padding:10px 8px;">' + escapeHtml(d.version_label || 'v1') + '</td>' +
              '<td style="padding:10px 8px;color:#64748b;font-size:12px;">' + escapeHtml(date) + '</td>' +
              '<td style="padding:10px 8px;"><span style="font-size:11px;padding:3px 8px;border-radius:10px;' + statusStyle + '">' + statusLabel + '</span></td>' +
              '<td style="padding:10px 8px;">' +
              (safeUrl
                ? '<button type="button" class="btn small primary" onclick="downloadLibraryFile(\'' + safeUrl + '\', \'' + safeName + '\', \'' + d.id + '\')">تحميل</button>'
                : '—') +
              '</td></tr>';
          }).join('')
        : '<tr><td colspan="6" style="padding:24px;text-align:center;color:#64748b;">لا توجد ملفات مصدرة في السجل</td></tr>';

      modal.innerHTML =
        '<div style="background:#fff;border-radius:16px;max-width:760px;width:100%;max-height:85vh;display:flex;flex-direction:column;padding:24px;box-shadow:0 12px 32px rgba(0,0,0,.2);direction:rtl;text-align:right;">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">' +
        '<h3 style="margin:0;color:#1a3a52;font-size:18px;">مكتبة التنزيلات وسجل الملفات المصدرة</h3>' +
        '<button type="button" id="closeDownloadsModalBtn" class="btn ghost small" style="padding:4px 12px;">إغلاق</button>' +
        '</div>' +
        '<p style="margin:0 0 16px;color:#64748b;font-size:13px;">تنزيل مجاني مكرر للملفات المعتمدة طالما لم يتغير المحتوى أو الإصدار</p>' +
        '<div style="flex:1;overflow-y:auto;border:1px solid #e2e8f0;border-radius:8px;">' +
        '<table style="width:100%;border-collapse:collapse;font-size:13px;text-align:right;">' +
        '<thead><tr style="background:#f8fafc;border-bottom:1px solid #e2e8f0;color:#475569;">' +
        '<th style="padding:10px 8px;">اسم الملف</th>' +
        '<th style="padding:10px 8px;">الصيغة</th>' +
        '<th style="padding:10px 8px;">الإصدار</th>' +
        '<th style="padding:10px 8px;">التاريخ</th>' +
        '<th style="padding:10px 8px;">الحالة</th>' +
        '<th style="padding:10px 8px;">الإجراء</th>' +
        '</tr></thead><tbody>' + rows + '</tbody></table>' +
        '</div></div>';

      document.body.appendChild(modal);
      const closeBtn = modal.querySelector('#closeDownloadsModalBtn');
      if (closeBtn) closeBtn.onclick = () => { if (modal.parentNode) modal.parentNode.removeChild(modal); };
    }

    async function downloadLibraryFile(url, fileName, downloadId) {
      try {
        const token = getTenantToken();
        const resp = await fetch(url, { headers: token ? { 'Authorization': 'Bearer ' + token } : {} });
        if (!resp.ok) throw new Error('Download failed');
        const blob = await resp.blob();
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = fileName;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(blobUrl);
        if (downloadId) {
          api('POST', '/api/downloads/' + encodeURIComponent(downloadId) + '/delivered').catch(() => {});
        }
        toast(WFT('downloads.download_started', 'تم بدء التحميل'));
      } catch (err) {
        toast(WFT('downloads.load_failed', 'تعذر تحميل الملف'));
      }
    }
