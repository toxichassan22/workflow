/* 12-files-media.js - index.html lines 20144-21641, shared global scope, classic scripts in order */

    async function getProjectFileObjectUrl(fileId) {
      if (projectFileObjectUrls.has(fileId)) return projectFileObjectUrls.get(fileId);
      const token = getTenantToken();
      const response = await fetch('/api/project-files/' + encodeURIComponent(fileId), {
        headers: token ? { Authorization: 'Bearer ' + token } : {}
      });
      if (!response.ok) {
        let message = 'تعذر تحميل الملف من السيرفر';
        try { message = (await response.json())?.error || message; } catch (e) { }
        throw new Error(message);
      }
      const objectUrl = URL.createObjectURL(await response.blob());
      projectFileObjectUrls.set(fileId, objectUrl);
      return objectUrl;
    }

    function closeProjectFilePreview() {
      document.getElementById('projectFilePreviewModal')?.remove();
    }

    async function openProjectFilePreview(fileId, fileName, mimeType) {
      if (!fileId) {
        toast('لم يُحفظ هذا الملف على السيرفر بعد — انتظر اكتمال الحفظ ثم أعد المحاولة');
        return;
      }
      closeProjectFilePreview();
      const modal = document.createElement('div');
      modal.id = 'projectFilePreviewModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
      modal.innerHTML = '<div style="background:#fff;border-radius:20px;padding:20px;max-width:1000px;width:100%;max-height:90vh;display:flex;flex-direction:column;gap:12px">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;gap:12px">' +
        '<h3 style="margin:0;font-size:1rem">' + escapeHtml(fileName || 'معاينة المستند') + '</h3>' +
        '<div style="display:flex;gap:8px">' +
        '<button class="btn ghost" id="projectFileDownloadBtn">تنزيل</button>' +
        '<button class="btn ghost" onclick="closeProjectFilePreview()">إغلاق</button></div></div>' +
        '<div id="projectFilePreviewBody" style="flex:1;min-height:320px;overflow:auto;background:#f6f7f9;border-radius:12px;display:flex;align-items:center;justify-content:center">' +
        '<span class="tenant-hint">جاري تحميل الملف...</span></div></div>';
      modal.addEventListener('click', event => { if (event.target === modal) closeProjectFilePreview(); });
      document.body.appendChild(modal);

      const body = modal.querySelector('#projectFilePreviewBody');
      try {
        const objectUrl = await getProjectFileObjectUrl(fileId);
        const isPdf = String(mimeType || '').includes('pdf') || /\.pdf$/i.test(fileName || '');
        body.innerHTML = isPdf
          ? '<iframe src="' + objectUrl + '" style="width:100%;height:74vh;border:0;border-radius:12px"></iframe>'
          : '<img src="' + objectUrl + '" alt="' + escapeHtml(fileName || '') + '" style="max-width:100%;max-height:74vh;display:block;border-radius:12px">';
        const download = modal.querySelector('#projectFileDownloadBtn');
        if (download) download.onclick = () => {
          const link = document.createElement('a');
          link.href = objectUrl;
          link.download = fileName || 'document';
          link.click();
        };
      } catch (error) {
        body.innerHTML = '<span class="tenant-hint">' + escapeHtml(error.message || 'تعذر عرض الملف') + '</span>';
      }
    }

    // A blob URL lives only inside the tab that created it, so it must never be saved into a
    // draft: every uploaded image then pointed at nothing once the file was reopened. This
    // publishes the stored file under /uploads/creative/... — the same durable place a
    // generated image goes — and reports a failure instead of storing a dead reference.
    async function publishProjectFileImageUrl(fileId) {
      if (!fileId) return '';
      const response = await api('POST', '/api/project-files/' + encodeURIComponent(fileId) + '/publish-image');
      if (!response?.success || !response.url) throw new Error(response?.error || 'تعذر حفظ الصورة على السيرفر');
      return response.url;
    }

    function isSessionOnlyImageUrl(url) {
      return String(url || '').toLowerCase().startsWith('blob:');
    }

    function durableImageUrl(url) {
      return isSessionOnlyImageUrl(url) ? '' : String(url || '');
    }

    const LAND_PHOTOS_MAX = 4;
    // Croquis + licence + deed + supporting documents share one upload box; the
    // analysis endpoint accepts up to 10 documents per request.
    const LAND_DOCUMENTS_MAX = 4;

    // Thumbnails render through the authenticated preview route, so each card needs a blob URL.
    async function attachProjectFileThumbnail(imageElement, fileId) {
      if (!imageElement || !fileId) return;
      try {
        imageElement.src = await getProjectFileObjectUrl(fileId);
      } catch (error) {
        imageElement.replaceWith(Object.assign(document.createElement('span'), {
          className: 'tenant-hint', textContent: 'تعذر تحميل الصورة'
        }));
      }
    }

    function syncLandPhotoDescriptions() {
      const meta = Array.isArray(tenantProjectData.land_photos_file_meta)
        ? tenantProjectData.land_photos_file_meta : [];
      document.querySelectorAll('#landPhotosUploadStatus [data-land-photo-id]').forEach(field => {
        const entry = meta.find(item => item && item.id === field.dataset.landPhotoId);
        if (entry) entry.description = field.value.trim();
      });
      tenantProjectData.land_photos_file_meta = meta;
      triggerAutoSaveDraft();
    }

    function removeProjectLogo() {
      tenantProjectData.project_logo = '';
      tenantProjectData.project_logo_file_id = null;
      tenantProjectData.project_logo_file_meta = null;
      const input = document.querySelector('#tenantProjectForm [data-key="project_logo"]');
      if (input) {
        input.value = '';
        delete input.dataset.uploadSignature;
        delete input.dataset.projectFileId;
      }
      renderProjectLogoState(null);
      triggerAutoSaveDraft();
    }

    function renderProjectLogoState(meta) {
      const host = document.getElementById('projectLogoUploadStatus');
      if (!host) return;
      const fileMeta = meta || tenantProjectData.project_logo_file_meta;
      const fileId = fileMeta?.id || tenantProjectData.project_logo_file_id;
      const filePath = tenantProjectData.project_logo || (fileMeta?.path ? ('/' + fileMeta.path.replace(/^\/+/, '')) : '');
      if (!fileMeta && !fileId && !filePath) {
        host.innerHTML = '';
        return;
      }
      const name = fileMeta?.originalName || fileMeta?.name || 'شعار المشروع';
      const pending = fileMeta?.status === 'pending' || (!fileId && !filePath);
      const safeId = String(fileId || '').replace(/'/g, "\\'");
      const safeName = name.replace(/\\/g, '\\\\').replace(/'/g, "\\'");

      host.innerHTML = '<div style="border:1px solid var(--line);border-radius:10px;padding:8px 12px;background:#fff;display:flex;align-items:center;gap:12px;max-width:380px">' +
        '<div style="width:48px;height:48px;border-radius:8px;overflow:hidden;background:#f2f4f7;display:flex;align-items:center;justify-content:center;flex-shrink:0">' +
        (pending
          ? '<span class="tenant-hint" style="font-size:0.75rem">جاري الحفظ...</span>'
          : '<img data-project-logo-thumb="' + safeId + '" src="' + (filePath ? escapeHtml(filePath) : '') + '" alt="' + escapeHtml(name) + '" style="width:100%;height:100%;object-fit:contain;padding:2px;cursor:zoom-in">') +
        '</div>' +
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:4px">' +
        '<span style="font-size:.82rem;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + escapeHtml(name) + '</span>' +
        (pending ? '' : '<div style="display:flex;gap:6px">' +
          (fileId ? '<button type="button" class="btn ghost" style="padding:2px 8px;font-size:.75rem" onclick="openProjectFilePreview(\'' + safeId + '\',\'' + safeName + '\',\'image/*\')">معاينة</button>' : '') +
          '<button type="button" class="btn ghost danger" style="padding:2px 8px;font-size:.75rem" onclick="removeProjectLogo()">حذف</button></div>') +
        '</div></div>';

      if (!pending && fileId) {
        host.querySelectorAll('img[data-project-logo-thumb]').forEach(image => {
          attachProjectFileThumbnail(image, fileId);
          image.addEventListener('click', () => openProjectFilePreview(fileId, image.alt, 'image/*'));
        });
      }
    }

    async function uploadProjectLogo(input) {
      const file = input?.files?.[0];
      if (!file) return;
      renderProjectLogoState({ originalName: file.name, status: 'pending' });
      try {
        const uploaded = await uploadTenantProjectFileInput(input, 'project_logo');
        if (uploaded && (uploaded.id || uploaded.path)) {
          tenantProjectData.project_logo_file_meta = uploaded;
          tenantProjectData.project_logo_file_id = uploaded.id;
          const path = uploaded.path ? ('/' + uploaded.path.replace(/^\/+/, '')) : ('/api/project-files/' + uploaded.id);
          tenantProjectData.project_logo = path;
          renderProjectLogoState(uploaded);
          triggerAutoSaveDraft();
        }
      } catch (error) {
        toast('تعذر رفع شعار المشروع: ' + (error.message || error));
        renderProjectLogoState(tenantProjectData.project_logo_file_meta || (tenantProjectData.project_logo ? { path: tenantProjectData.project_logo } : null));
      }
    }

    function removeLandPhoto(fileId) {
      tenantProjectData.land_photos_file_meta = (tenantProjectData.land_photos_file_meta || [])
        .filter(item => item && item.id !== fileId);
      tenantProjectData.land_photos_file_ids = (tenantProjectData.land_photos_file_meta || [])
        .map(item => item.id);
      const input = document.querySelector('#tenantProjectForm [data-key="land_photos"]');
      if (input) {
        input.value = '';
        delete input.dataset.uploadSignatures;
      }
      renderLandPhotos(tenantProjectData.land_photos_file_meta);
      triggerAutoSaveDraft();
    }

    function renderLandPhotos(photos) {
      const host = document.getElementById('landPhotosUploadStatus');
      if (!host) return;
      const items = (Array.isArray(photos) ? photos : []).filter(Boolean).slice(0, LAND_PHOTOS_MAX);
      if (!items.length) {
        host.innerHTML = '<div class="tenant-hint">لم تُرفع صور للأرض.</div>';
        return;
      }
      host.innerHTML = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px">' +
        items.map(photo => {
          const name = photo.originalName || photo.name || 'صورة الأرض';
          const pending = photo.status === 'pending' || !photo.id;
          const safeId = String(photo.id || '').replace(/'/g, "\\'");
          return '<div style="border:1px solid var(--line);border-radius:10px;padding:8px;background:#fff;display:flex;flex-direction:column;gap:6px">' +
            '<div style="height:120px;border-radius:8px;overflow:hidden;background:#f2f4f7;display:flex;align-items:center;justify-content:center">' +
            (pending
              ? '<span class="tenant-hint">جاري الحفظ...</span>'
              : '<img data-land-photo-thumb="' + safeId + '" alt="' + escapeHtml(name) + '" style="width:100%;height:100%;object-fit:cover;cursor:zoom-in">') +
            '</div>' +
            '<span style="font-size:.78rem;word-break:break-word">' + escapeHtml(name) + '</span>' +
            '<label>وصف الصورة</label>' +
            '<textarea data-land-photo-id="' + safeId + '" rows="2" ' +
            'style="width:100%;font-family:inherit;font-size:.8rem">' + escapeHtml(photo.description || '') + '</textarea>' +
            (pending ? '' : '<div style="display:flex;gap:6px">' +
              '<button type="button" class="btn ghost" style="flex:1;padding:4px 8px;font-size:.75rem" onclick="openProjectFilePreview(\'' + safeId + '\',\'' + name.replace(/\\/g, '\\\\').replace(/'/g, "\\'") + '\',\'image/*\')">تكبير</button>' +
              '<button type="button" class="btn ghost danger" style="flex:1;padding:4px 8px;font-size:.75rem" onclick="removeLandPhoto(\'' + safeId + '\')">حذف</button></div>') +
            '</div>';
        }).join('') + '</div>';
      host.querySelectorAll('textarea[data-land-photo-id]').forEach(field => {
        field.addEventListener('change', syncLandPhotoDescriptions);
      });
      host.querySelectorAll('img[data-land-photo-thumb]').forEach(image => {
        const fileId = image.dataset.landPhotoThumb;
        attachProjectFileThumbnail(image, fileId);
        image.addEventListener('click', () => openProjectFilePreview(fileId, image.alt, 'image/*'));
      });
    }

    async function uploadLandPhotos(input) {
      const chosen = Array.from(input?.files || []).slice(0, LAND_PHOTOS_MAX);
      if (!chosen.length) return;
      renderLandPhotos(chosen.map(file => ({ originalName: file.name, status: 'pending' })));
      try {
        const uploaded = await uploadTenantProjectFileInput(input, 'land_photos');
        const previous = Array.isArray(tenantProjectData.land_photos_file_meta)
          ? tenantProjectData.land_photos_file_meta : [];
        // Keep any caption the user already typed for a re-selected photo.
        const merged = await Promise.all((Array.isArray(uploaded) ? uploaded : []).slice(0, LAND_PHOTOS_MAX).map(async file => ({
          ...file,
          imageUrl: previous.find(item => item && item.id === file.id)?.imageUrl || await publishProjectFileImageUrl(file.id),
          description: previous.find(item => item && item.id === file.id)?.description || ''
        })));
        tenantProjectData.land_photos_file_meta = merged;
        tenantProjectData.land_photos_file_ids = merged.map(file => file.id);
        renderLandPhotos(merged);
        triggerAutoSaveDraft();
      } catch (error) {
        toast('تعذر رفع صور الأرض: ' + (error.message || error));
        renderLandPhotos(tenantProjectData.land_photos_file_meta || []);
      }
    }

    function renderLandDocumentsUploadState(files) {
      const host = document.getElementById('landDocumentsUploadStatus');
      if (!host) return;
      const items = Array.isArray(files) ? files.filter(Boolean) : [];
      if (!items.length) {
        host.innerHTML = '<div class="tenant-hint">لم تُحفظ ملفات على السيرفر بعد — الكروكي والرخصة وأي مستندات مساندة (حتى 4 ملفات).</div>';
        return;
      }
      host.innerHTML = '<div style="border:1px solid #b9e1d1;background:#edf7f3;border-radius:8px;padding:10px">' +
        '<strong style="color:#126247">الملفات محفوظة على السيرفر</strong>' +
        '<div style="margin-top:8px;display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px">' +
        items.map(file => {
          const name = file.originalName || file.name || 'ملف مستند';
          const size = Number(file.fileSize || file.size || 0);
          const sizeText = size ? (size / 1024 / 1024).toFixed(2) + ' MB' : '';
          const pending = file.status === 'pending' || !file.id;
          const isPdf = String(file.mimeType || '').includes('pdf') || /\.pdf$/i.test(name);
          const args = "'" + String(file.id || '').replace(/'/g, "\\'") + "','" +
            name.replace(/\\/g, '\\\\').replace(/'/g, "\\'") + "','" +
            String(file.mimeType || '').replace(/'/g, "\\'") + "'";
          return '<div style="border:1px solid #b9e1d1;background:#fff;border-radius:10px;padding:10px;display:flex;flex-direction:column;gap:8px">' +
            '<div style="display:flex;align-items:center;gap:8px">' +
            '<span style="font-size:.7rem;font-weight:900;color:#6f7780;border:1px solid #d9dee5;' +
            'border-radius:6px;padding:2px 6px;flex:none">' + (isPdf ? 'PDF' : 'صورة') + '</span>' +
            '<span style="font-weight:600;word-break:break-word;flex:1">' + escapeHtml(name) + '</span></div>' +
            '<span class="tenant-hint" style="margin:0">' + escapeHtml(sizeText) +
            (sizeText ? ' — ' : '') + (pending ? 'جاري الرفع...' : 'محفوظ') + '</span>' +
            (pending ? '' :
              '<div style="display:flex;gap:6px">' +
              '<button type="button" class="btn ghost" style="flex:1;padding:6px 10px" onclick="openProjectFilePreview(' + args + ')">معاينة الملف</button>' +
              '<button type="button" class="btn ghost danger" style="flex:none;padding:6px 12px" onclick="removeLandDocument(\'' +
              String(file.id || '').replace(/'/g, "\\'") + '\')">حذف</button></div>') +
            '</div>';
        }).join('') + '</div></div>';
    }

    // The panel lives next to the upload box so the reason sits where the retry button is.
    function showLandAnalysisFailure(reason, providerError) {
      const host = document.getElementById('landDocumentsUploadStatus');
      if (!host) return;
      let panel = document.getElementById('landAnalysisFailure');
      if (!panel) {
        panel = document.createElement('div');
        panel.id = 'landAnalysisFailure';
        panel.style.cssText = 'margin-top:10px;padding:11px 13px;border-radius:12px;background:#fff0f0;' +
          'border:1px solid #efb3b3;color:#9c1d1d;font-weight:700;font-size:13px;line-height:1.6';
        host.insertAdjacentElement('afterend', panel);
      }
      panel.hidden = false;
      panel.innerHTML = escapeHtml(String(reason || '')) +
        (providerError && providerError !== reason
          ? '<div style="margin-top:6px;font-weight:400;font-size:12px">' +
          escapeHtml(String(providerError)) + '</div>'
          : '');
    }

    function clearLandAnalysisFailure() {
      const panel = document.getElementById('landAnalysisFailure');
      if (panel) panel.hidden = true;
    }

    // Uploading is its own explicit action, triggered by choosing a file. It used to happen only
    // inside collectTenantFormData, which ran from the autosave, so once autosave was removed the
    // files sat on "saving" forever and the analyse button saw no ids to send.
    async function uploadLandDocuments(input) {
      const chosen = Array.from(input?.files || []).slice(0, LAND_DOCUMENTS_MAX);
      if (!chosen.length) return;
      const existing = tenantProjectData.land_documents_files_file_meta || [];
      renderLandDocumentsUploadState(existing.concat(chosen.map(file => ({
        originalName: file.name, fileSize: file.size, status: 'pending'
      }))));
      try {
        const uploaded = await uploadTenantProjectFileInput(input, 'land_documents_files');
        renderLandDocumentsUploadState(Array.isArray(uploaded) ? uploaded : []);
        triggerAutoSaveDraft();
      } catch (error) {
        toast('تعذر رفع الملفات: ' + (error.message || error));
        renderLandDocumentsUploadState(tenantProjectData.land_documents_files_file_meta || []);
      }
    }

    // Detaches the document from this draft the same way removeLandPhoto does. The stored file is
    // left in place because an older draft revision may still reference it, and the analysis reads
    // this metadata list, so a detached file is no longer sent to the model.
    function removeLandDocument(fileId) {
      const meta = (tenantProjectData.land_documents_files_file_meta || [])
        .filter(item => item && item.id !== fileId);
      tenantProjectData.land_documents_files_file_meta = meta;
      tenantProjectData.land_documents_files_file_ids = meta.map(item => item.id);
      // The file input keeps its own upload signatures; clearing them lets the same file be
      // re-selected after a mistake instead of being skipped as already uploaded.
      const input = document.querySelector('#tenantProjectForm [data-key="land_documents_files"]');
      if (input) {
        input.value = '';
        delete input.dataset.uploadSignatures;
      }
      renderLandDocumentsUploadState(meta);
      triggerAutoSaveDraft();
      toast(meta.length ? 'تم حذف الملف من هذا المشروع' : 'تم حذف الملفات — ارفع مستندات الأرض من جديد');
    }

    async function uploadTenantProjectFileInput(input, key) {
      // The client decides how many 2D plans a project has, so that key is not capped at 2.
      const multiLimit = key === 'land_photos' ? LAND_PHOTOS_MAX
        : (key === 'land_documents_files' ? LAND_DOCUMENTS_MAX
          : (key === 'visual_style_reference' ? 5
            : (key === 'visual_plan_2d' ? VISUAL_CONCEPT_MAX_PLANS : 2)));
      const files = Array.from(input?.files || []).slice(0, input?.multiple ? multiLimit : 1);
      const fileType = input?.dataset?.projectFileType;
      if (!files.length || !fileType) {
        return tenantProjectData[key + (input?.multiple ? '_file_ids' : '_file_id')] || null;
      }
      const uploaded = [];
      let multiCache = {};
      if (input.multiple) {
        try { multiCache = JSON.parse(input.dataset.uploadSignatures || '{}') || {}; } catch (e) { multiCache = {}; }
      }
      // A file input only holds the latest picker gesture, so a second selection must ADD to
      // the stored list — overwriting it used to drop the licence (or the croquis) picked
      // earlier, and the analysis then saw a single document.
      const mergeExisting = input.multiple && key === 'land_documents_files';
      const previousMeta = mergeExisting && Array.isArray(tenantProjectData[key + '_file_meta'])
        ? tenantProjectData[key + '_file_meta'].filter(item => item && item.id) : [];
      const storedIds = new Set(previousMeta.map(item => item.id));
      const storedIdentities = new Set(previousMeta.map(item =>
        String(item.originalName || item.name || '') + ':' + Number(item.fileSize || item.size || 0)));
      let remainingSlots = mergeExisting ? Math.max(0, multiLimit - previousMeta.length) : multiLimit;
      let overflowCount = 0;
      for (const file of files) {
        const signature = [file.name, file.size, file.lastModified, fileType].join(':');
        const cachedId = input.multiple ? multiCache[signature] : input.dataset.projectFileId;
        if (mergeExisting) {
          const alreadyStored = (cachedId && storedIds.has(cachedId))
            || storedIdentities.has(file.name + ':' + Number(file.size || 0));
          if (alreadyStored) continue;
          if (!remainingSlots) { overflowCount += 1; continue; }
          remainingSlots -= 1;
        }
        if (cachedId) {
          uploaded.push({ id: cachedId, originalName: file.name, mimeType: file.type });
          continue;
        }
        const formData = new FormData();
        formData.append('file', file, file.name);
        formData.append('fileType', fileType);
        if (tenantProjectData?.draftId) formData.append('draftId', tenantProjectData.draftId);
        const response = await api('POST', '/api/project-files', formData, true);
        if (!response?.success || !response.file?.id) {
          throw new Error(response?.error || 'تعذر حفظ ملف المشروع');
        }
        uploaded.push(response.file);
        if (input.multiple) {
          multiCache[signature] = response.file.id;
          input.dataset.uploadSignatures = JSON.stringify(multiCache);
        } else {
          input.dataset.uploadSignature = signature;
          input.dataset.projectFileId = response.file.id;
        }
      }
      if (mergeExisting && overflowCount) {
        toast(WFT('land.docs.overflow', 'الحد الأقصى {n} ملفات — تم تجاهل {m} ملف إضافي', { n: multiLimit, m: overflowCount }));
      }
      const ids = uploaded.map(file => file.id);
      if (input.multiple) {
        // Re-uploads return fresh metadata, so any caption already typed has to be carried over.
        const earlierMeta = Array.isArray(tenantProjectData[key + '_file_meta'])
          ? tenantProjectData[key + '_file_meta'] : [];
        const fresh = uploaded.map(file => {
          const previous = earlierMeta.find(item => item && item.id === file.id);
          return previous?.description ? { ...file, description: previous.description } : file;
        });
        const merged = mergeExisting
          ? previousMeta.concat(fresh.filter(file => file && !storedIds.has(file.id)))
          : fresh;
        tenantProjectData[key + '_file_ids'] = mergeExisting ? merged.map(item => item.id) : ids;
        tenantProjectData[key + '_file_meta'] = merged;
        if (key === 'land_documents_files') renderLandDocumentsUploadState(merged);
        if (key === 'land_photos') renderLandPhotos(merged);
        return merged;
      }
      tenantProjectData[key + '_file_id'] = ids[0];
      tenantProjectData[key + '_file_meta'] = uploaded[0];
      return uploaded[0];
    }

    function projectNumberKeepsPrecision(key) {
      return /(?:^|_)(?:lat|lng|latitude|longitude|date|year|phone|mobile|deed|plot|document|id|number)(?:_|$)/i.test(String(key || ''));
    }

    function normalizedProjectNumber(key, value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return 0;
      return projectNumberKeepsPrecision(key) ? number : roundSystemNumber(number);
    }

    async function collectTenantFormData() {
      if (typeof persistClassificationDraftState === 'function') persistClassificationDraftState();
      if (typeof persistVisualConceptDraftState === 'function') persistVisualConceptDraftState();
      if (typeof persistFinancialStudyDraftState === 'function') persistFinancialStudyDraftState();
      if (typeof persistExecutiveContentFromDom === 'function') persistExecutiveContentFromDom();
      const result = {};
      const inputs = document.querySelectorAll('#tenantProjectForm input, #tenantProjectForm textarea, #tenantProjectForm select');
      for (const input of inputs) {
        const key = input.dataset.key;
        if (!key) continue;
        const type = input.dataset.type;
        if (type === 'image' || type === 'pdf' || type === 'file') {
          if (input.files && input.files[0]) {
            const uploaded = await uploadTenantProjectFileInput(input, key);
            if (input.multiple) {
              result[key + '_file_ids'] = Array.isArray(uploaded) ? uploaded.map(file => file.id) : [];
              result[key + '_file_meta'] = Array.isArray(uploaded) ? uploaded : [];
            } else {
              result[key + '_file_id'] = uploaded?.id || uploaded || '';
              result[key + '_file_meta'] = uploaded || null;
            }
            const resolvedPath = uploaded?.path ? ('/' + uploaded.path.replace(/^\/+/, '')) : (uploaded?.id ? ('/api/project-files/' + uploaded.id) : '');
            result[key] = resolvedPath || tenantProjectData[key] || '';
            if (resolvedPath) tenantProjectData[key] = resolvedPath;
          } else {
            result[key] = tenantProjectData[key] || '';
            if (input.multiple && tenantProjectData[key + '_file_ids']) {
              result[key + '_file_ids'] = tenantProjectData[key + '_file_ids'];
              result[key + '_file_meta'] = tenantProjectData[key + '_file_meta'] || [];
            } else if (tenantProjectData[key + '_file_id']) {
              result[key + '_file_id'] = tenantProjectData[key + '_file_id'];
              result[key + '_file_meta'] = tenantProjectData[key + '_file_meta'] || null;
            }
          }
        } else if (type === 'number') {
          result[key] = normalizedProjectNumber(key, input.value);
        } else if (key === 'financial_study_model') {
          const parsed = parseFinancialStudySnapshot(input.value);
          result[key] = parsed || tenantProjectData.financial_study_model || '';
        } else {
          result[key] = input.value || '';
        }
      }
      if (!tenantProjectFormIsFilled()) {
        // Every caller merges this over tenantProjectData, and the draft save then writes the
        // result, so blanks from a form that was built but never filled would erase saved fields.
        let kept = 0;
        Object.keys(result).forEach(key => {
          if (isBlankProjectValue(result[key]) && !isBlankProjectValue(tenantProjectData[key])) {
            delete result[key];
            kept += 1;
          }
        });
        console.warn('[PROJECT FORM] Form is not filled from the draft yet; kept ' + kept + ' stored values.');
      }
      return result;
    }

    async function generateProjectSectionPresentation(sectionKey, sectionLabel = '') {
      const resolvedLabel = PROJECT_SECTION_PRESENTATION_TITLES[sectionKey] || sectionLabel;
      if (!resolvedLabel) {
        toast('قسم المشروع غير صالح');
        return;
      }
      if (isGeneratingTenantSlides || tenantSlidePlanRequest) {
        toast('يوجد عرض قيد التوليد حاليًا');
        return;
      }
      // Section generation is bound to that section's own approval — the
      // all-sections requirement belongs to the full-file run only.
      if ((tenantProjectSectionStatuses || {})[sectionKey] !== 'approved') {
        toast('توليد هذا القسم يتطلب اعتماده أولًا');
        return;
      }

      const formData = await collectTenantFormData();
      tenantProjectData = { ...tenantProjectData, ...formData };
      if (!tenantProjectData.project_name && tenantProjectData.projectName) {
        tenantProjectData.project_name = tenantProjectData.projectName;
      }
      await repairVisualConceptStoredImages();
      if (sectionKey === 'section-financial-calc' && !(await validateFinancialStudyBeforeProceed())) return;
      tenantFinancialPresentationReport = financialStudyHasRealInput(tenantProjectData.financial_study_model)
        && typeof collectFinancialStudyReport === 'function' ? collectFinancialStudyReport() : null;
      resetDesignerChatForNewPresentation();
      // A paid run must not start on data the server never received — when the
      // pre-save fails the save function already said why, and the run stops.
      if (!(await saveProjectAsDraftNow(true, false))) return;

      if (!(await preparePresentationGenerationTarget('section:' + sectionKey))) return;
      const projectName = tenantProjectData.project_name || tenantProjectData.projectName || 'عرض بدون عنوان';
      const presentationTitle = projectName + ' - ' + resolvedLabel;
      showTenantPage('tenantSlidesPage');
      clearTenantSlidesStage('جاري إعداد عرض ' + resolvedLabel);
      setSlidesEditorInfo(presentationTitle, 0);
      setLiveGenBanner(true, 'إعداد عرض ' + resolvedLabel, 'تحليل بيانات القسم وبناء الشرائح', 5);

      const planResponse = await requestTenantSlidePlan(tenantProjectData, job => {
        setLiveGenBanner(true, 'إعداد عرض ' + resolvedLabel,
          (job && job.message) || 'تحليل بيانات القسم وبناء الشرائح', 8);
      }, sectionKey);
      if (!planResponse?.success || !planResponse.plan) {
        const errorMessage = planResponse?.error || 'تعذر إعداد عرض القسم';
        setLiveGenBanner(true, 'تعذر إعداد عرض القسم', errorMessage, 5);
        toast(errorMessage);
        renderTenantSlides();
        return;
      }

      tenantSlidePlan = planResponse.plan;
      tenantProjectData.tenantSlidePlan = tenantSlidePlan;
      tenantPresentationTitle = presentationTitle;
      await generateTenantSlides({
        sectionKey,
        sectionLabel: resolvedLabel,
        presentationTitle,
        financialValidated: sectionKey === 'section-financial-calc',
        markDraftDirty: false
      });
    }

    async function validateFileInputAgainstRegistry(file, typeKey) {
      if (!file) return true;
      try {
        const resp = await api('GET', '/api/file-types');
        if (resp && resp.success && Array.isArray(resp.fileTypes)) {
          const matched = resp.fileTypes.find(t => t.key === typeKey);
          if (matched) {
            const maxMb = Number(matched.max_size_mb) || 25;
            const fileSizeMb = file.size / (1024 * 1024);
            if (fileSizeMb > maxMb) {
              toast('حجم الملف (' + fileSizeMb.toFixed(1) + ' ميجابايت) يتجاوز الحد المسموح (' + maxMb + ' ميجابايت)');
              return false;
            }
            if (matched.allowed_extensions) {
              const exts = matched.allowed_extensions.split(',').map(e => e.trim().toLowerCase().replace(/^\./, ''));
              const fileExt = (file.name.split('.').pop() || '').toLowerCase();
              if (exts.length && !exts.includes(fileExt)) {
                toast('امتداد الملف (.' + fileExt + ') غير مدعوم');
                return false;
              }
            }
          }
        }
      } catch (err) {
        console.warn('File type registry check:', err);
      }
      return true;
    }

    async function showGenerationApprovalModal(opts = {}) {
      const draftId = opts.draftId || (tenantProjectData && (tenantProjectData.draftId || tenantProjectData.draft_id));
      const slidesCount = opts.slidesCount || (tenantSlidePlan && (tenantSlidePlan.slides || []).length) || 10;
      const projectName = opts.projectName || (tenantProjectData && (tenantProjectData.project_name || tenantProjectData.projectName)) || 'عرض بدون عنوان';
      const sectionKey = String(opts.sectionKey || '').trim();

      let estimateData = null;
      try {
        estimateData = await api('POST', '/api/generation-approvals', { draftId, slidesCount, sectionKey: sectionKey || undefined });
      } catch (err) {
        console.warn('Generation approval estimate error:', err);
      }
      // A second open on the same draft reuses the pending request instead of
      // dying — the gate it opened is still the one being decided.
      if (estimateData && estimateData.error_code === 'approval_already_pending' && estimateData.approval_id) {
        try {
          const existing = await api('GET', '/api/generation-approvals/' + encodeURIComponent(estimateData.approval_id));
          if (existing && existing.success && existing.approval) {
            estimateData = {
              success: true,
              approval: existing.approval,
              estimate: {
                estimated_points: existing.approval.estimated_points,
                estimated_cost_usd: existing.approval.estimated_cost_usd,
                estimated_cost_sar: existing.approval.estimated_cost_sar,
                slides_count: existing.approval.slides_count,
              },
            };
          }
        } catch (err) {
          console.warn('Generation approval reuse error:', err);
        }
      }
      // The request itself is the gate: when it cannot be opened there is
      // nothing to approve, so generation does not proceed on a failure.
      if (!estimateData || !estimateData.success) {
        toast((estimateData && estimateData.error) || 'تعذر فتح طلب اعتماد التوليد');
        return null;
      }
      const estimate = estimateData.estimate || {};
      const approval = estimateData.approval || {};
      const approvalId = approval.id;
      if (!approvalId) {
        toast('تعذر فتح طلب اعتماد التوليد');
        return null;
      }
      const points = estimate.estimated_points ?? 500;
      const costSar = Number(estimate.estimated_cost_sar ?? ((estimate.estimated_cost_usd ?? 0) * 3.75) ?? 0);
      const sectionLabel = sectionKey
        ? ((typeof PROJECT_SECTION_PRESENTATION_TITLES !== 'undefined' && PROJECT_SECTION_PRESENTATION_TITLES[sectionKey]) || sectionKey)
        : '';

      // d02: the requester never decides their own request unless the company
      // policy opens it (generation_self_approval='allow', reported by the
      // server as can_self_decide). Otherwise only a company-level
      // administrator may carry both hats; every other requester waits here
      // while a generation approver decides from the approvals page.
      const canSelfDecide = Boolean(tenantUser && tenantUser.isAdmin) ||
        ((tenantUser && tenantUser._userRole) || 'company_admin') === 'company_admin' ||
        Boolean(estimateData && estimateData.can_self_decide);

      let remainingSar = 0;
      try {
        const ov = await api('GET', '/api/client/overview');
        if (ov?.package) {
          remainingSar = Number(ov.package.remaining_sar ?? ov.package.remaining_usd) || 0;
        } else {
          remainingSar = Number(ov?.balance_sar ?? ov?.balance_usd) || 0;
        }
      } catch (err) {
        console.warn('Overview fetch error:', err);
      }

      const isBalanceSufficient = remainingSar >= costSar || remainingSar > 0;

      return new Promise((resolve) => {
        const modal = document.createElement('div');
        modal.id = 'generationApprovalModal';
        modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10000;display:flex;align-items:center;justify-content:center;padding:16px;';
        modal.innerHTML =
          '<div style="background:#fff;border-radius:16px;max-width:520px;width:100%;padding:24px;box-shadow:0 12px 32px rgba(0,0,0,.2);direction:rtl;text-align:right;">' +
          '<h3 style="margin:0 0 8px;color:#1a3a52;font-size:18px;">اعتماد بدء التوليد وحجز النقاط</h3>' +
          '<p style="margin:0 0 16px;color:#64748b;font-size:13px;">بوابة الاعتماد الثانية — تقدير التكلفة وحجز رصيد المحفظة</p>' +
          '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px;margin-bottom:16px;display:grid;grid-template-columns:1fr 1fr;gap:10px;font-size:13px;">' +
          '<div><span style="color:#64748b;">المشروع:</span> <strong>' + escapeHtml(projectName) + '</strong></div>' +
          (sectionLabel ? '<div><span style="color:#64748b;">القسم:</span> <strong>' + escapeHtml(sectionLabel) + '</strong></div>' : '') +
          '<div><span style="color:#64748b;">الشرائح المتوقعة:</span> <strong>' + slidesCount + ' شريحة</strong></div>' +
          '<div><span style="color:#64748b;">النقاط التقديرية:</span> <strong>' + points + ' نقطة</strong></div>' +
          '<div><span style="color:#64748b;">التكلفة التقديرية:</span> <strong>' + costSar.toFixed(2) + ' ريال</strong></div>' +
          '<div style="grid-column:1/-1;border-top:1px solid #e2e8f0;padding-top:8px;display:flex;justify-content:space-between;">' +
          '<span>رصيد المحفظة المتاح:</span><strong>' + remainingSar.toFixed(2) + ' ريال</strong>' +
          '</div></div>' +
          (!isBalanceSufficient
            ? '<div style="background:#fef2f2;border:1px solid #fecaca;color:#991b1b;padding:10px;border-radius:8px;font-size:12px;margin-bottom:14px;">' +
              'الرصيد المتاح في باقة الشركة غير كافٍ لتغطية التكلفة التقديرية. يرجى شحن الرصيد أولاً.' +
              '</div>'
            : '') +
          '<div style="display:flex;gap:10px;justify-content:flex-end;align-items:center;">' +
          '<button type="button" id="genApproveCancelBtn" class="btn ghost" style="padding:8px 18px;">إلغاء</button>' +
          (isBalanceSufficient
            ? (canSelfDecide
              ? '<button type="button" id="genApproveConfirmBtn" class="btn primary" style="padding:8px 20px;">تعميد وبدء التوليد</button>'
              : '<span class="tenant-hint" id="genApproveWaiting">أُرسل الطلب — بانتظار قرار معتمد التوليد</span>')
            : '<button type="button" id="genApproveRechargeBtn" class="btn primary" style="padding:8px 20px;">شحن الرصيد</button>') +
          '</div></div>';

        document.body.appendChild(modal);

        let pollTimer = null;
        const close = (res) => {
          if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
          if (modal.parentNode) modal.parentNode.removeChild(modal);
          resolve(res);
        };

        if (!canSelfDecide) {
          pollTimer = setInterval(async () => {
            try {
              const res = await api('GET', '/api/generation-approvals/' + encodeURIComponent(approvalId));
              const status = res && res.approval && res.approval.status;
              if (status === 'approved') {
                window.currentGenerationApprovalId = approvalId;
                close(approvalId);
              } else if (status === 'rejected' || status === 'cancelled') {
                toast('رُفض طلب اعتماد التوليد');
                close(null);
              }
            } catch (err) { /* transient poll failure — keep waiting */ }
          }, 4000);
        }

        const cancelBtn = modal.querySelector('#genApproveCancelBtn');
        if (cancelBtn) {
          cancelBtn.onclick = async () => {
            if (approvalId) {
              await api('POST', '/api/generation-approvals/' + encodeURIComponent(approvalId) + '/decision', { decision: 'cancelled' }).catch(() => {});
            }
            close(null);
          };
        }

        const rechargeBtn = modal.querySelector('#genApproveRechargeBtn');
        if (rechargeBtn) {
          rechargeBtn.onclick = () => {
            close(null);
            showTenantPage('tenantSettingsPage');
            if (typeof showTenantSettingsTab === 'function') showTenantSettingsTab('packages');
          };
        }

        const confirmBtn = modal.querySelector('#genApproveConfirmBtn');
        if (confirmBtn) {
          confirmBtn.onclick = async () => {
            confirmBtn.disabled = true;
            confirmBtn.textContent = 'جاري الحجز...';
            try {
              if (approvalId) {
                const dec = await api('POST', '/api/generation-approvals/' + encodeURIComponent(approvalId) + '/decision', { decision: 'approved' });
                if (!dec || !dec.success) {
                  toast(dec?.error || 'تعذر حجز النقاط');
                  close(null);
                  return;
                }
              }
              window.currentGenerationApprovalId = approvalId;
              close(approvalId || true);
            } catch (err) {
              toast('فشل اعتماد التوليد');
              close(null);
            }
          };
        }
      });
    }

    async function directGenerateProposalFile() {
      if (isGeneratingTenantSlides || tenantSlidePlanRequest || tenantPresentationSavePromise) return;
      const formData = await collectTenantFormData();
      tenantProjectData = { ...tenantProjectData, ...formData };
      if (!tenantProjectData.project_name && tenantProjectData.projectName) tenantProjectData.project_name = tenantProjectData.projectName;
      tenantProjectData.tenantSlidePlan = tenantSlidePlan;
      tenantProjectData.tenantCreativeImages = tenantCreativeImages;
      tenantPresentationTitle = tenantProjectData.project_name || tenantProjectData.projectName || 'عرض بدون عنوان';
      await repairVisualConceptStoredImages();
      if (!(await validateFinancialStudyBeforeProceed())) return;
      tenantFinancialPresentationReport = financialStudyHasRealInput(tenantProjectData.financial_study_model)
        && typeof collectFinancialStudyReport === 'function' ? collectFinancialStudyReport() : null;

      const factCount = countProjectFacts(tenantProjectData);
      if (factCount < GENERATION_MIN_FACTS && !confirm('بيانات المشروع المحفوظة ' + factCount +
        ' حقل. الذكاء الاصطناعي سيكتب محتوى الشرائح من عنده لأن الحقائق غير موجودة. متابعة؟')) return;

      if (!(await preparePresentationGenerationTarget('full'))) return;

      // Persist the project snapshot before the gate: the approval request needs a
      // real draft row, and this snapshot is the one the presentation is built on.
      // A paid run must not start on data the server never received — the shared
      // save path carries expectedRevision and reports failure, and the run stops.
      resetDesignerChatForNewPresentation();
      if (!(await saveProjectAsDraftNow(true, false))) return;

      // Gate 2 (t14 + d04): Preflight generation approval, cost estimate and atomic points reservation
      const gateApproved = await showGenerationApprovalModal({
        draftId: tenantProjectData.draftId || tenantProjectData.draft_id,
        slidesCount: (tenantSlidePlan && (tenantSlidePlan.slides || []).length) || 10,
        projectName: tenantPresentationTitle,
      });
      if (!gateApproved) return;

      // Navigate to the presentation page with the stage empty. Rendering the file's saved slides
      // here showed the previous deck for the whole planning wait, so the reader watched an old
      // presentation while a new one was being built.
      showTenantPage('tenantSlidesPage');
      clearTenantSlidesStage('جاري إعداد خطة وهيكل العرض');
      setSlidesEditorInfo(tenantProjectData.project_name || tenantProjectData.projectName || '', 0);

      try {
        // The plan is always rebuilt from the current project data. Reusing the saved plan meant a
        // regenerated file kept the previous structure and slide count no matter how much the
        // project had changed, which read as a fixed slide count that nobody had asked for.
        setLiveGenBanner(true, 'إعداد خطة وهيكل العرض الاستثماري...', 'تحليل متطلبات المشروع والهيكل الأنسب', 5);
        const planResponse = await requestTenantSlidePlan(tenantProjectData, job => {
          setLiveGenBanner(true, 'إعداد خطة وهيكل العرض الاستثماري...',
            (job && job.message) || 'تحليل متطلبات المشروع والهيكل الأنسب', 8);
        });
        if (planResponse.success && planResponse.plan) {
          tenantSlidePlan = planResponse.plan;
          tenantProjectData.tenantSlidePlan = tenantSlidePlan;
          const planCount = (tenantSlidePlan.slides || []).length;
          // A fallback plan is a failed planner, not a proposal: it always has the same generic
          // titles and the same count, so it is stated instead of passing as the model's work.
          if (tenantSlidePlan.source === 'fallback') {
            setLiveGenBanner(true, 'تعذر تحليل بيانات المشروع — هيكل عام',
              planCount + ' شريحة بعناوين عامة لا تعبّر عن هذا المشروع', 12);
            toast('لم ينتج المحلل خطة لهذا المشروع، والهيكل المستخدم عام.');
          } else {
            setLiveGenBanner(true, 'تم إعداد خطة الشرائح', planCount + ' شريحة — بدء التوليد المباشر', 12);
          }
          triggerAutoSaveDraft();
        } else {
          // The gate already escrowed the hold: a dead plan releases it and
          // returns the draft from 'generating' instead of stranding both.
          if (window.currentGenerationApprovalId) {
            api('POST', '/api/generation-approvals/' + encodeURIComponent(window.currentGenerationApprovalId) + '/settle', {
              consumed: false,
              note: 'تعذر إعداد خطة الشرائح'
            }).catch(err => console.warn('Settlement release error:', err));
            window.currentGenerationApprovalId = null;
          }
          const errorMessage = planResponse.error || 'تعذر إعداد خطة الشرائح';
          setLiveGenBanner(true, 'تعذر إعداد الخطة', errorMessage, 5);
          console.error('[SLIDE PLAN]', planResponse);
          toast(errorMessage);
          renderTenantSlides();
          return;
        }

        await generateTenantSlides({ approvalGranted: true });
      } catch (generationError) {
        // A throw anywhere after approval must still close the gate: the hold
        // stays escrowed and the draft stays 'generating' until it settles.
        console.error('[GENERATE FILE]', generationError);
        try {
          await settleGenerationRun(false, (generationError && generationError.message) || 'تعذر إكمال التوليد');
        } catch (settleError) {
          console.warn('[GENERATION SETTLE]', settleError);
        }
        setLiveGenBanner(true, 'تعذر إكمال التوليد', (generationError && generationError.message) || '', 5);
        toast((generationError && generationError.message) || 'تعذر إكمال التوليد');
      }
    }

    async function submitTenantProject() {
      return directGenerateProposalFile();
    }

    // The slide structure is not a client-facing object: there is no panel that lists it, no
    // editable plan titles and no button that rebuilds it on its own. It is produced inside
    // «توليد العرض» from the project data and never shown as something to operate.

    const VISUAL_CONCEPT_SLOTS = [
      { id: 'cover', label: 'الصورة الرئيسية', group: 'external' },
      { id: 'right', label: 'يمين', group: 'external' },
      { id: 'left', label: 'شمال', group: 'external' },
      { id: 'top', label: 'فوق', group: 'external' },
      { id: 'back', label: 'خلف', group: 'external' },
      { id: 'interior', label: 'التصميم الداخلي', group: 'internal' }
    ];
    const VISUAL_CONCEPT_EXTERNAL_SLOTS = VISUAL_CONCEPT_SLOTS.filter(item => item.group === 'external');
    const VISUAL_CONCEPT_INTERNAL_SLOTS = VISUAL_CONCEPT_SLOTS.filter(item => item.group === 'internal');
    const VISUAL_CONCEPT_INTERNAL_PREFIX = 'interior';
    const VISUAL_CONCEPT_MAX_INTERIOR_IMAGES = 30;
    const VISUAL_CONCEPT_MAX_PLANS = 30;
    const VISUAL_CONCEPT_PLAN_KINDS = [
      { kind: 'site', id: 'plan_site', label: 'الموقع العام المبسط' },
      { kind: 'uses', id: 'plan_uses', label: 'توزيع الاستخدامات على الأدوار' },
      { kind: 'massing', id: 'plan_massing', label: 'المنظور الكتلي ثلاثي الأبعاد' }
    ];
    const VISUAL_CONCEPT_SLOT_ALIASES = {
      cover: ['cover', 'main', 'hero'],
      right: ['right', 'east', 'east_facade'],
      left: ['left', 'west', 'west_facade'],
      top: ['top', 'aerial', 'above'],
      back: ['back', 'rear', 'behind'],
      interior: ['interior', 'inside', 'internal']
    };

    function emptyVisualConceptSlot(id) {
      return { id, mode: 'ai', label: visualConceptDefaultSlotLabel(id), caption: '', prompt: '', imageUrl: '', approvedImageUrl: '', status: 'pending', chat: [], styleReferenceFileIds: [], styleReferenceNames: [], sourceFileId: '', sourceFileName: '' };
    }

    function visualConceptDefaultSlotLabel(slotId) {
      return VISUAL_CONCEPT_SLOTS.find(item => item.id === slotId)?.label
        || visualConceptPlanDefinition(slotId)?.label
        || (isVisualConceptInteriorSlot(slotId) ? 'التصور الداخلي' : (isVisualConceptPlanSlot(slotId) ? 'مخطط' : 'الصورة'));
    }

    function visualConceptCanRenameSlot(slotId) {
      return VISUAL_CONCEPT_EXTERNAL_SLOTS.slice(1).some(item => item.id === slotId)
        || (isVisualConceptPlanSlot(slotId) && !isVisualConceptWorkflowPlan(slotId));
    }

    function isVisualConceptPlanSlot(slotId) {
      return String(slotId || '').startsWith('plan_');
    }

    function visualConceptPlanDefinition(value) {
      const raw = value && typeof value === 'object' ? value : { id: value };
      const kind = String(raw.kind || '').trim().toLowerCase();
      const id = String(raw.id || '').trim();
      return VISUAL_CONCEPT_PLAN_KINDS.find(item => item.kind === kind || item.id === id) || null;
    }

    function isVisualConceptWorkflowPlan(value) {
      return Boolean(visualConceptPlanDefinition(value));
    }

    function visualConceptPlanKind(value) {
      return visualConceptPlanDefinition(value)?.kind || '';
    }

    function visualConceptBoundaryPoints(value) {
      let parsed = value;
      if (typeof value === 'string') {
        try { parsed = JSON.parse(value); } catch (error) { parsed = []; }
      }
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        parsed = parsed.points || parsed.survey_coordinates || parsed.coordinates || [];
      }
      if (!Array.isArray(parsed)) return [];
      return parsed.map((item, index) => {
        const source = Array.isArray(item)
          ? { eastings: item[0], northings: item[1], point: index + 1 }
          : (item && typeof item === 'object' ? item : {});
        const eastings = Number(String(source.eastings ?? source.easting ?? source.x ?? '').replace(/,/g, ''));
        const northings = Number(String(source.northings ?? source.northing ?? source.y ?? '').replace(/,/g, ''));
        return {
          parcel_id: String(source.parcel_id || source.parcelId || '').trim(),
          point: String(source.point || source.point_number || index + 1).trim(),
          eastings,
          northings
        };
      }).filter(item => Number.isFinite(item.eastings) && Number.isFinite(item.northings)).slice(0, 60);
    }

    function emptyVisualConceptPlansWorkflow() {
      return {
        status: 'idle',
        verification: { checks: [], issues: [], summary: '', canProceed: false, approved: false },
        boundary: { points: [], referenceUrl: '', instruction: '', approved: false },
        distribution: { rows: [], totals: [], notes: [], checks: [], issues: [], approved: false },
        prompts: { site: '', uses: '', massing: '' },
        planContext: null,
        viewStage: 'verify',
        promptReady: false,
        promptsError: ''
      };
    }

    function normalizeVisualConceptPlansWorkflow(raw) {
      let value = raw;
      if (typeof value === 'string') {
        try { value = JSON.parse(value); } catch (error) { value = null; }
      }
      const source = value && typeof value === 'object' ? value : {};
      const empty = emptyVisualConceptPlansWorkflow();
      const verification = source.verification && typeof source.verification === 'object' ? source.verification : {};
      const boundary = source.boundary && typeof source.boundary === 'object' ? source.boundary : {};
      const distribution = source.distribution && typeof source.distribution === 'object' ? source.distribution : {};
      const prompts = source.prompts && typeof source.prompts === 'object' ? source.prompts : {};
      return {
        ...empty,
        status: ['idle', 'verified', 'boundary', 'ready'].includes(source.status) ? source.status : 'idle',
        verification: {
          checks: Array.isArray(verification.checks) ? verification.checks.slice(0, 40) : [],
          issues: Array.isArray(verification.issues) ? verification.issues.slice(0, 30) : [],
          summary: String(verification.summary || '').slice(0, 1600),
          canProceed: Boolean(verification.canProceed),
          approved: Boolean(verification.approved)
        },
        boundary: {
          points: visualConceptBoundaryPoints(boundary.points || boundary.survey_coordinates),
          referenceUrl: durableImageUrl(boundary.referenceUrl || boundary.reference_url),
          instruction: String(boundary.instruction || '').slice(0, 2000),
          approved: Boolean(boundary.approved)
        },
        distribution: {
          rows: (Array.isArray(distribution.rows) ? distribution.rows.slice(0, 60) : []).map((row, index) => ({
            id: String((row && row.id) || 'row_' + (index + 1)).slice(0, 40),
            building: String((row && row.building) || '').slice(0, 160),
            floor_range: String((row && (row.floor_range || row.floorRange)) || '').slice(0, 80),
            component: String((row && row.component) || '').slice(0, 160),
            units_per_floor: (row && row.units_per_floor) ?? '',
            floor_area_sqm: (row && row.floor_area_sqm) ?? '',
            circulation: String((row && row.circulation) || '').slice(0, 400)
          })),
          totals: Array.isArray(distribution.totals) ? distribution.totals.slice(0, 60) : [],
          notes: Array.isArray(distribution.notes) ? distribution.notes.slice(0, 12) : [],
          checks: Array.isArray(distribution.checks) ? distribution.checks.slice(0, 40) : [],
          issues: Array.isArray(distribution.issues) ? distribution.issues.slice(0, 30) : [],
          approved: Boolean(distribution.approved)
        },
        prompts: {
          site: String(prompts.site || '').slice(0, 12000),
          uses: String(prompts.uses || '').slice(0, 12000),
          massing: String(prompts.massing || '').slice(0, 12000)
        },
        planContext: source.planContext && typeof source.planContext === 'object' ? source.planContext : null,
        viewStage: ['verify', 'boundary', 'generate'].includes(source.viewStage) ? source.viewStage : 'verify',
        promptReady: Boolean(source.promptReady || (prompts.site && prompts.uses && prompts.massing)),
        promptsError: String(source.promptsError || '').slice(0, 400)
      };
    }

    function visualConceptWorkflowPlanSeed(definition, workflow) {
      const prompt = workflow?.prompts?.[definition.kind] || '';
      return {
        mode: 'ai',
        label: definition.label,
        caption: definition.label,
        prompt,
        imageUrl: '',
        approvedImageUrl: '',
        status: 'pending',
        chat: [],
        styleReferenceFileIds: [],
        styleReferenceNames: [],
        sourceFileId: '',
        sourceFileName: ''
      };
    }

    function visualConceptPlansWorkflowState() {
      tenantVisualConceptState = tenantVisualConceptState || normalizeVisualConceptState({});
      tenantVisualConceptState.plansWorkflow = normalizeVisualConceptPlansWorkflow(tenantVisualConceptState.plansWorkflow);
      return tenantVisualConceptState.plansWorkflow;
    }

    function visualConceptInteriorSlotId(componentId, viewIndex = 1) {
      const index = Math.max(1, Math.min(VISUAL_CONCEPT_MAX_INTERIOR_IMAGES, Number(viewIndex) || 1));
      return VISUAL_CONCEPT_INTERNAL_PREFIX + '_' + String(componentId || '').trim() + '::' + index;
    }

    function visualConceptInteriorComponentIdFromSlot(slotId) {
      const value = String(slotId || '');
      const prefix = VISUAL_CONCEPT_INTERNAL_PREFIX + '_';
      if (!value.startsWith(prefix)) return '';
      const rest = value.slice(prefix.length);
      return rest.includes('::') ? rest.split('::')[0] : rest;
    }

    function visualConceptInteriorViewIndexFromSlot(slotId) {
      const value = String(slotId || '');
      if (!value.includes('::')) return 1;
      const index = Number(value.split('::').pop());
      return Number.isFinite(index) && index > 0 ? index : 1;
    }

    function isVisualConceptInteriorSlot(slotId) {
      const value = String(slotId || '');
      return value === VISUAL_CONCEPT_INTERNAL_PREFIX || value.startsWith(VISUAL_CONCEPT_INTERNAL_PREFIX + '_');
    }

    function visualConceptInteriorComponents() {
      const rows = typeof getComponentRowsData === 'function' ? getComponentRowsData() : [];
      const fallback = Array.isArray(tenantProjectData?.financial_study_model?.dynamicRows?.components)
        ? tenantProjectData.financial_study_model.dynamicRows.components
        : [];
      const source = rows.length ? rows : fallback;
      const seen = new Set();
      return source.map((item, index) => {
        const id = String(item.id || item.componentId || ('component_' + (index + 1))).trim();
        const name = String(item.name || item.component || item.title || '').trim();
        if (!id || !name || seen.has(id)) return null;
        seen.add(id);
        return {
          id,
          name,
          useType: item.useType || item.type || '',
          units: item.units,
          unitArea: item.unitArea,
          builtArea: item.builtArea || item.totalArea
        };
      }).filter(Boolean).slice(0, 40);
    }

    function visualConceptSlotSource(sourceSlots, itemId) {
      const slots = sourceSlots && typeof sourceSlots === 'object' ? sourceSlots : {};
      const aliases = VISUAL_CONCEPT_SLOT_ALIASES[itemId] || [itemId];
      for (const key of aliases) {
        if (slots[key] && typeof slots[key] === 'object') return slots[key];
      }
      return null;
    }

    function visualConceptReferenceList(value) {
      if (Array.isArray(value)) return value.map(item => String(item || '').trim()).filter(Boolean);
      if (typeof value !== 'string' || !value.trim()) return [];
      try {
        const parsed = JSON.parse(value);
        return Array.isArray(parsed) ? parsed.map(item => String(item || '').trim()).filter(Boolean) : [value.trim()];
      } catch (error) {
        return [value.trim()];
      }
    }

    // A plan is a slot too: plans2d keeps the durable record the slides and exports read
    // (title, description, file, published image), while slots[plan.id] carries the working
    // state (mode, prompt, chat, approval) so plans run through the same prompt-edit-
    // generate-approve flow as every other visual card.
    function normalizeVisualConceptPlans(raw) {
      let value = raw;
      if (typeof value === 'string') {
        try { value = JSON.parse(value); } catch (error) { value = null; }
      }
      const list = Array.isArray(value) ? value : [];
      const seen = new Set();
      return list.map((item, index) => {
        const source = item && typeof item === 'object' ? item : {};
        let id = String(source.id || '').trim() || ('plan_' + (index + 1));
        if (!id.startsWith('plan_')) id = 'plan_' + id;
        while (seen.has(id)) id = id + '_' + (index + 1);
        seen.add(id);
        const fileId = String(source.fileId || source.file_id || '');
        const imageUrl = durableImageUrl(source.imageUrl || source.image_url);
        const mode = ['ai', 'upload'].includes(source.mode) ? source.mode : (fileId ? 'upload' : 'ai');
        return {
          id,
          mode,
          title: String(source.title || '').slice(0, 120),
          description: String(source.description || '').slice(0, 2000),
          fileId,
          fileName: String(source.fileName || source.file_name || ''),
          imageUrl
        };
      }).filter(item => item.fileId || item.imageUrl || item.mode === 'ai').slice(0, VISUAL_CONCEPT_MAX_PLANS);
    }

    function visualConceptPlanSeed(plan) {
      if (!plan) return null;
      return {
        mode: plan.mode === 'upload' ? 'upload' : 'ai',
        label: plan.title || '',
        caption: plan.description || '',
        sourceFileId: plan.fileId || '',
        sourceFileName: plan.fileName || '',
        imageUrl: plan.imageUrl || '',
        status: plan.imageUrl ? 'review' : 'pending'
      };
    }

    function normalizeVisualConceptState(raw) {
      let value = raw;
      if (typeof value === 'string') {
        try { value = JSON.parse(value); } catch (error) { value = null; }
      }
      const source = value && typeof value === 'object' ? value : {};
      const deletedInteriorSlots = new Set(visualConceptReferenceList(
        source.deletedInteriorSlots || source.deleted_interior_slots));
      const hasStateReferenceIds = ['styleReferenceFileIds', 'style_reference_file_ids', 'styleReferenceFileId', 'style_reference_file_id']
        .some(key => Object.prototype.hasOwnProperty.call(source, key));
      const savedReferenceIds = visualConceptReferenceList(source.styleReferenceFileIds || source.style_reference_file_ids);
      const legacyReferenceId = String(source.styleReferenceFileId || source.style_reference_file_id || '').trim();
      if (legacyReferenceId && !savedReferenceIds.includes(legacyReferenceId)) savedReferenceIds.unshift(legacyReferenceId);
      if (!hasStateReferenceIds && typeof tenantProjectData !== 'undefined') {
        visualConceptReferenceList(tenantProjectData.visual_style_reference_file_ids).forEach(fileId => {
          if (!savedReferenceIds.includes(fileId)) savedReferenceIds.push(fileId);
        });
      }
      const plans = normalizeVisualConceptPlans(source.plans2d);
      const plansWorkflow = normalizeVisualConceptPlansWorkflow(source.plansWorkflow || source.plans_workflow);
      const styleReferenceFileIds = savedReferenceIds.slice(0, 5);
      const styleReferenceNames = visualConceptReferenceList(source.styleReferenceNames || source.style_reference_names);
      const legacyReferenceName = String(source.styleReferenceName || '').trim();
      if (legacyReferenceName && !styleReferenceNames.includes(legacyReferenceName)) styleReferenceNames.unshift(legacyReferenceName);
      styleReferenceNames.splice(5);
      const slots = {};
      // A slot that already carries its own state must never be rebuilt from the legacy
      // tenantCreativeImages mirrors: those hold previews too, so they used to re-approve
      // an image the user had just unapproved, or never approved at all.
      const stated = {};
      const slotIds = new Set(VISUAL_CONCEPT_SLOTS.map(item => item.id));
      VISUAL_CONCEPT_PLAN_KINDS.forEach(definition => slotIds.add(definition.id));
      Object.keys(source.slots && typeof source.slots === 'object' ? source.slots : {}).forEach(id => {
        if (isVisualConceptInteriorSlot(id) && !deletedInteriorSlots.has(id)) slotIds.add(id);
        if (isVisualConceptPlanSlot(id) && plans.some(plan => plan.id === id)) slotIds.add(id);
      });
      plans.forEach(plan => slotIds.add(plan.id));
      visualConceptInteriorComponents().forEach(item => {
        const firstId = visualConceptInteriorSlotId(item.id, 1);
        if (!deletedInteriorSlots.has(firstId)) slotIds.add(firstId);
        const legacyId = VISUAL_CONCEPT_INTERNAL_PREFIX + '_' + item.id;
        if (source.slots && source.slots[legacyId]) slotIds.add(visualConceptInteriorSlotId(item.id, 1));
        for (let view = 2; view <= VISUAL_CONCEPT_MAX_INTERIOR_IMAGES; view += 1) {
          const viewId = visualConceptInteriorSlotId(item.id, view);
          if (source.slots && source.slots[viewId] && !deletedInteriorSlots.has(viewId)) slotIds.add(viewId);
        }
      });
      slotIds.forEach(id => {
        let sourceId = id;
        if (isVisualConceptInteriorSlot(id) && id.includes('::') && visualConceptInteriorViewIndexFromSlot(id) === 1) {
          const legacyId = VISUAL_CONCEPT_INTERNAL_PREFIX + '_' + visualConceptInteriorComponentIdFromSlot(id);
          if ((!source.slots || !source.slots[id]) && source.slots && source.slots[legacyId]) sourceId = legacyId;
        }
        const workflowDefinition = visualConceptPlanDefinition(id);
        const slot = visualConceptSlotSource(source.slots, sourceId) || visualConceptSlotSource(source.slots, id)
          || visualConceptPlanSeed(plans.find(plan => plan.id === id))
          || (workflowDefinition ? visualConceptWorkflowPlanSeed(workflowDefinition, plansWorkflow) : null)
          || emptyVisualConceptSlot(id);
        const chat = Array.isArray(slot.chat) ? slot.chat.filter(entry => entry && typeof entry.text === 'string').slice(-30).map(entry => ({
          role: entry.role === 'assistant' ? 'assistant' : 'user',
          text: String(entry.text).slice(0, 4000)
        })) : [];
        // A blob: URL is a handle into the tab that created it, so a stored one is dead and is
        // dropped here; repairVisualConceptStoredImages republishes it from the file id.
        const approved = durableImageUrl(slot.approvedImageUrl);
        const imageUrl = durableImageUrl(slot.imageUrl);
        const mode = ['ai', 'upload'].includes(slot.mode)
          ? slot.mode
          : (slot.sourceFileId && !slot.prompt && !(slot.chat && slot.chat.length) ? 'upload' : 'ai');
        const rawStatus = slot.status;
        const safeStatus = (rawStatus === 'generating')
          ? (approved ? 'approved' : imageUrl ? 'review' : 'pending')
          : (['approved', 'review', 'pending'].includes(rawStatus)
            ? rawStatus
            : (approved ? 'approved' : imageUrl ? 'review' : 'pending'));
        stated[id] = Boolean(slot.status || approved || imageUrl);
        slots[id] = {
          id,
          mode,
          prompt: String(slot.prompt || '').slice(0, 12000),
          imageUrl,
          approvedImageUrl: approved,
          status: safeStatus,
          chat,
          styleReferenceFileIds: visualConceptReferenceList(slot.styleReferenceFileIds).slice(0, 5),
          styleReferenceNames: visualConceptReferenceList(slot.styleReferenceNames).slice(0, 5),
          sourceFileId: String(slot.sourceFileId || ''),
          sourceFileName: String(slot.sourceFileName || ''),
          label: String(slot.label || visualConceptDefaultSlotLabel(id)).slice(0, 80),
          caption: String(slot.caption || '').slice(0, 400)
        };
      });
      if (!stated.cover && tenantCreativeImages.cover) {
        slots.cover.approvedImageUrl = tenantCreativeImages.cover;
        slots.cover.imageUrl = slots.cover.imageUrl || tenantCreativeImages.cover;
        slots.cover.prompt = slots.cover.prompt || tenantCreativeImages.cover_prompt || '';
        slots.cover.status = 'approved';
      }
      const moodboardImages = Array.isArray(tenantCreativeImages.moodboard) ? tenantCreativeImages.moodboard : [];
      const moodboardPrompts = Array.isArray(tenantCreativeImages.moodboard_prompts) ? tenantCreativeImages.moodboard_prompts : [];
      VISUAL_CONCEPT_EXTERNAL_SLOTS.slice(1).forEach((item, index) => {
        const slot = slots[item.id];
        if (!stated[item.id] && moodboardImages[index]) {
          slot.approvedImageUrl = moodboardImages[index];
          slot.imageUrl = slot.imageUrl || moodboardImages[index];
          slot.status = 'approved';
        }
        if (!slot.prompt && moodboardPrompts[index]) slot.prompt = String(moodboardPrompts[index] || '').slice(0, 12000);
      });
      return {
        version: 1,
        slots,
        plans2d: plans,
        plansWorkflow,
        styleReferenceFileIds,
        styleReferenceFileId: styleReferenceFileIds[0] || '',
        styleReferenceNames,
        styleReferenceName: styleReferenceNames[0] || '',
        deletedInteriorSlots: Array.from(deletedInteriorSlots),
        selectedInteriorComponentId: String(source.selectedInteriorComponentId || '').trim()
      };
    }

    function persistVisualConceptDraftState() {
      const previousImages = tenantCreativeImages || {};
      const previousMoodboard = Array.isArray(previousImages.moodboard) ? previousImages.moodboard : [];
      const previousPrompts = Array.isArray(previousImages.moodboard_prompts) ? previousImages.moodboard_prompts : [];
      tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState || tenantProjectData.visual_concept);
      tenantProjectData.visual_concept = tenantVisualConceptState;
      tenantVisualConceptState.plansWorkflow = normalizeVisualConceptPlansWorkflow(tenantVisualConceptState.plansWorkflow);
      VISUAL_CONCEPT_PLAN_KINDS.forEach(definition => {
        const slot = tenantVisualConceptState.slots[definition.id];
        if (!slot || (!slot.prompt && !slot.imageUrl && !slot.approvedImageUrl)) return;
        let plan = (tenantVisualConceptState.plans2d || []).find(item => item.id === definition.id);
        if (!plan) {
          plan = { id: definition.id, mode: 'ai', title: definition.label, description: definition.label, fileId: '', fileName: '', imageUrl: '' };
          tenantVisualConceptState.plans2d.push(plan);
        }
      });
      // The durable plan record mirrors its slot so slides and exports keep reading plans2d.
      (tenantVisualConceptState.plans2d || []).forEach(plan => {
        const slot = tenantVisualConceptState.slots[plan.id];
        if (!slot) return;
        plan.mode = slot.mode === 'upload' ? 'upload' : 'ai';
        plan.title = String(slot.label || '').slice(0, 120);
        plan.description = String(slot.caption || '').slice(0, 2000);
        plan.fileId = String(slot.sourceFileId || '');
        plan.fileName = String(slot.sourceFileName || '');
        plan.imageUrl = durableImageUrl(slot.approvedImageUrl) || durableImageUrl(slot.imageUrl);
      });
      const referenceIds = Array.isArray(tenantVisualConceptState.styleReferenceFileIds)
        ? tenantVisualConceptState.styleReferenceFileIds.slice(0, 5) : [];
      tenantProjectData.visual_style_reference_file_ids = referenceIds;
      tenantProjectData.visual_style_reference_file_id = referenceIds[0] || '';
      const cover = tenantVisualConceptState.slots.cover || {};
      tenantCreativeImages = previousImages;
      // These mirrors reach the export and the slide prompts, so a session-only blob URL is
      // dropped here: it would arrive on the server as an image that can never be read.
      tenantCreativeImages.cover = durableImageUrl(cover.approvedImageUrl) || durableImageUrl(tenantCreativeImages.cover);
      tenantCreativeImages.cover_prompt = cover.prompt || tenantCreativeImages.cover_prompt || '';
      tenantCreativeImages.moodboard = VISUAL_CONCEPT_EXTERNAL_SLOTS.slice(1).map((item, index) => {
        const slot = tenantVisualConceptState.slots[item.id] || {};
        return durableImageUrl(slot.approvedImageUrl) || durableImageUrl(slot.imageUrl) || durableImageUrl(previousMoodboard[index]);
      });
      tenantCreativeImages.moodboard_prompts = VISUAL_CONCEPT_EXTERNAL_SLOTS.slice(1).map((item, index) => {
        const slot = tenantVisualConceptState.slots[item.id] || {};
        return slot.prompt || previousPrompts[index] || '';
      });
      tenantProjectData.tenantCreativeImages = tenantCreativeImages;
      const hidden = document.getElementById('visualConceptData');
      if (hidden) hidden.value = JSON.stringify(tenantVisualConceptState);
    }

    function markVisualConceptDirty() {
      persistVisualConceptDraftState();
      setDraftDirty(true);
    }

    function visualConceptMissingMessage(response) {
      const missing = Array.isArray(response?.missingFields) ? response.missingFields : [];
      if (!missing.length) return response?.error || '';
      return 'أكمل الحقول الناقصة: ' + missing.map(item => item.label || item.key).join('، ');
    }

    async function collectVisualConceptPayload(slotId) {
      if (typeof persistClassificationDraftState === 'function') persistClassificationDraftState();
      if (typeof persistMarketStudyFromDom === 'function' && document.getElementById('marketStudyData')) persistMarketStudyFromDom();
      if (typeof persistExecutiveContentFromDom === 'function' && document.getElementById('executiveContentData')) persistExecutiveContentFromDom();
      persistVisualConceptDraftState();
      let projectData = { ...tenantProjectData };
      if (typeof collectTenantFormData === 'function' && document.getElementById('tenantProjectForm')) {
        projectData = { ...projectData, ...(await collectTenantFormData()) };
      }
      if (document.getElementById('section-financial-calc') && typeof collectFinancialStudyModel === 'function') {
        projectData.financial_study_model = collectFinancialStudyModel();
      }
      tenantProjectData = projectData;
      return {
        slotId,
        projectData,
        creativeImages: tenantCreativeImages,
        coverImage: tenantVisualConceptState.slots.cover.approvedImageUrl || tenantVisualConceptState.slots.cover.imageUrl || '',
        coverFileId: tenantVisualConceptState.slots.cover.sourceFileId || '',
        slotLabel: visualConceptSlotLabel(slotId),
        currentPrompt: document.querySelector('[data-visual-prompt="' + slotId + '"]')?.value
          || tenantVisualConceptState.slots[slotId]?.prompt || '',
        prompt: document.querySelector('[data-visual-prompt="' + slotId + '"]')?.value
          || tenantVisualConceptState.slots[slotId]?.prompt || '',
        componentId: isVisualConceptInteriorSlot(slotId)
          ? (visualConceptInteriorComponentIdFromSlot(slotId) || selectedVisualConceptInteriorComponentId())
          : '',
        referenceFileIds: isVisualConceptInteriorSlot(slotId)
          ? visualConceptInteriorReferenceIds(slotId)
          : [],
        planDescription: isVisualConceptPlanSlot(slotId)
          ? (visualConceptPlans().find(item => item.id === slotId)?.description || '')
          : '',
        planKind: visualConceptPlanKind(slotId),
        // Exterior slots also ship the workflow + the approved plan diagrams:
        // the server grounds their prompts on the deterministic measurements and
        // feeds the three plan images as generation references.
        plansWorkflow: normalizeVisualConceptPlansWorkflow(tenantVisualConceptState.plansWorkflow),
        planImages: visualConceptPlanImageMap(),
        planBoundaryPoints: isVisualConceptWorkflowPlan(slotId)
          ? normalizeVisualConceptPlansWorkflow(tenantVisualConceptState.plansWorkflow).boundary.points
          : [],
        planBoundaryReferenceUrl: isVisualConceptWorkflowPlan(slotId)
          ? normalizeVisualConceptPlansWorkflow(tenantVisualConceptState.plansWorkflow).boundary.referenceUrl
          : ''
      };
    }

    function visualConceptPlansApproved() {
      const slots = tenantVisualConceptState?.slots || {};
      return VISUAL_CONCEPT_PLAN_KINDS.every(item => Boolean(slots[item.id]?.approvedImageUrl));
    }

    function visualConceptPlanImageMap() {
      const slots = tenantVisualConceptState?.slots || {};
      const map = {};
      VISUAL_CONCEPT_PLAN_KINDS.forEach(item => {
        const url = durableImageUrl(slots[item.id]?.approvedImageUrl);
        if (url) map[item.kind] = url;
      });
      return map;
    }

    function visualConceptLockMessage(slotId) {
      if (isVisualConceptPlanSlot(slotId)) {
        const planKind = visualConceptPlanKind(slotId);
        if (planKind === 'uses') return 'مقفل حتى اعتماد مخطط الموقع العام.';
        if (planKind === 'massing') return 'مقفل حتى اعتماد مخططي الموقع العام وتوزيع الأدوار.';
      }
      if (isVisualConceptInteriorSlot(slotId)) return 'أضف مكونات المشروع واعتمد الصورة الرئيسية أولاً.';
      if (!visualConceptPlansApproved()) return 'اعتمد المخططات الثلاثة أولاً.';
      return 'اعتمد الصورة الرئيسية أولاً.';
    }

    function visualConceptSlotLocked(slotId) {
      // The plan diagrams generate in sequence — each is drawn on the previous
      // approved image, so a later plan stays locked until its predecessors
      // are approved.
      if (isVisualConceptPlanSlot(slotId)) {
        const planKind = visualConceptPlanKind(slotId);
        const slots = tenantVisualConceptState?.slots || {};
        const siteApproved = Boolean(durableImageUrl(slots.plan_site?.approvedImageUrl));
        const usesApproved = Boolean(durableImageUrl(slots.plan_uses?.approvedImageUrl));
        if (planKind === 'uses') return !siteApproved;
        if (planKind === 'massing') return !siteApproved || !usesApproved;
        return false;
      }
      if (isVisualConceptInteriorSlot(slotId)) {
        return !tenantVisualConceptState.slots.cover.approvedImageUrl || !visualConceptInteriorComponents().length;
      }
      // Exterior renders are built on the approved plan diagrams, so they stay
      // locked until all three plans are approved; the angles still wait for
      // the hero image on top of that.
      if (!visualConceptPlansApproved()) return true;
      return slotId !== 'cover' && !tenantVisualConceptState.slots.cover.approvedImageUrl;
    }

    function selectedVisualConceptInteriorComponentId() {
      const select = document.getElementById('visualConceptInteriorComponentSelect');
      return String(select?.value || tenantVisualConceptState?.selectedInteriorComponentId || visualConceptInteriorComponents()[0]?.id || '').trim();
    }

    function visualConceptInteriorReferenceIds(slotId) {
      const componentId = visualConceptInteriorComponentIdFromSlot(slotId) || selectedVisualConceptInteriorComponentId();
      const firstId = visualConceptInteriorSlotId(componentId, 1);
      const slot = tenantVisualConceptState.slots[slotId] || {};
      const first = tenantVisualConceptState.slots[firstId] || {};
      const ids = Array.isArray(slot.styleReferenceFileIds) && slot.styleReferenceFileIds.length
        ? slot.styleReferenceFileIds
        : (first.styleReferenceFileIds || []);
      return ids.slice(0, 5);
    }

    function visualConceptInteriorViewIds(componentId) {
      const deleted = new Set(tenantVisualConceptState.deletedInteriorSlots || []);
      const ids = [];
      for (let view = 1; view <= VISUAL_CONCEPT_MAX_INTERIOR_IMAGES; view += 1) {
        const id = visualConceptInteriorSlotId(componentId, view);
        if (tenantVisualConceptState.slots[id] && !deleted.has(id)) ids.push(id);
      }
      return ids;
    }

    function addVisualConceptInteriorView() {
      const componentId = selectedVisualConceptInteriorComponentId();
      if (!componentId) return;
      const existing = visualConceptInteriorViewIds(componentId);
      if (existing.length >= VISUAL_CONCEPT_MAX_INTERIOR_IMAGES) return;
      let nextId = '';
      for (let view = 1; view <= VISUAL_CONCEPT_MAX_INTERIOR_IMAGES; view += 1) {
        const candidate = visualConceptInteriorSlotId(componentId, view);
        if (!tenantVisualConceptState.slots[candidate]) { nextId = candidate; break; }
      }
      if (!nextId) return;
      tenantVisualConceptState.deletedInteriorSlots = (tenantVisualConceptState.deletedInteriorSlots || [])
        .filter(id => id !== nextId);
      tenantVisualConceptState.slots[nextId] = emptyVisualConceptSlot(nextId);
      markVisualConceptDirty();
      renderVisualConceptPage();
    }

    function renderVisualConceptInteriorReferences(slotId) {
      const preview = document.getElementById('visualConceptInteriorReferencePreview');
      if (!preview) return;
      const componentId = visualConceptInteriorComponentIdFromSlot(slotId) || selectedVisualConceptInteriorComponentId();
      const firstId = visualConceptInteriorSlotId(componentId, 1);
      const slot = tenantVisualConceptState.slots[firstId] || tenantVisualConceptState.slots[slotId] || emptyVisualConceptSlot(firstId);
      const ids = Array.isArray(slot.styleReferenceFileIds) ? slot.styleReferenceFileIds : [];
      const names = Array.isArray(slot.styleReferenceNames) ? slot.styleReferenceNames : [];
      if (!ids.length) {
        preview.textContent = 'لم تُرفع صور مرجعية لهذا المكون.';
        return;
      }
      preview.innerHTML = '<div class="visual-concept-reference-list"></div>';
      const list = preview.firstElementChild;
      ids.forEach((fileId, index) => {
        const item = document.createElement('div');
        item.className = 'visual-concept-reference-item';
        item.innerHTML = '<img alt="صورة مرجعية ' + (index + 1) + '"><span>' + escapeHtml(names[index] || ('صورة مرجعية ' + (index + 1))) + '</span>';
        list.appendChild(item);
        attachProjectFileThumbnail(item.querySelector('img'), fileId);
      });
    }

    function renderVisualConceptInteriorWorkspace() {
      const host = document.getElementById('visualConceptInternalWorkspace');
      const select = document.getElementById('visualConceptInteriorComponentSelect');
      const hint = document.getElementById('visualConceptInteriorHint');
      const referenceCard = document.getElementById('visualConceptInteriorReferenceCard');
      if (!host) return;
      const components = visualConceptInteriorComponents();
      const coverApproved = Boolean(tenantVisualConceptState.slots.cover.approvedImageUrl);
      if (select) {
        const current = selectedVisualConceptInteriorComponentId();
        select.innerHTML = components.length
          ? components.map(item => '<option value="' + escapeHtml(item.id) + '"' + (item.id === current ? ' selected' : '') + '>' + escapeHtml(item.name) + '</option>').join('')
          : '<option value="">لا توجد مكونات في الدراسة المالية</option>';
        if (components.some(item => item.id === current)) select.value = current;
        else if (components[0]) select.value = components[0].id;
        tenantVisualConceptState.selectedInteriorComponentId = select.value || '';
      }
      if (hint) {
        if (!components.length) hint.textContent = 'أضف مكونات المشروع في الدراسة المالية أولًا.';
        else hint.textContent = '';
      }
      if (referenceCard) referenceCard.hidden = !components.length;
      const selectedId = selectedVisualConceptInteriorComponentId();
      if (!selectedId) {
        host.innerHTML = '<p class="tenant-hint">لا توجد مكونات لتوليد صور داخلية.</p>';
        return;
      }
      const component = components.find(item => item.id === selectedId);
      const viewIds = visualConceptInteriorViewIds(selectedId);
      viewIds.forEach(id => {
        if (!tenantVisualConceptState.slots[id]) tenantVisualConceptState.slots[id] = emptyVisualConceptSlot(id);
      });
      const cards = viewIds.map((id, index) => renderVisualConceptSlot({
        id,
        label: 'تصور داخلي: ' + (component?.name || 'المكون') + ' — صورة ' + (index + 1),
        group: 'internal'
      }, !coverApproved)).join('');
      const canAdd = viewIds.length < VISUAL_CONCEPT_MAX_INTERIOR_IMAGES;
      host.innerHTML = '<div class="visual-concept-interior-stack">' + cards + '</div>' +
        (canAdd ? '<div class="visual-concept-actions" style="margin-top:12px"><button type="button" class="btn ghost small" data-visual-action="add-interior">إضافة صورة داخلية</button></div>' : '');
      renderVisualConceptInteriorReferences(viewIds[0]);
      const allApproved = viewIds.length > 0 && viewIds.every(id => tenantVisualConceptState.slots[id]?.status === 'approved');
      if (referenceCard) {
        referenceCard.classList.toggle('section-locked', allApproved);
        referenceCard.querySelectorAll('input, button').forEach(control => {
          control.disabled = allApproved;
        });
      }
    }

    function renderVisualConceptSlot(slotDef, locked) {
      const slot = tenantVisualConceptState.slots[slotDef.id];
      const stored = slot.approvedImageUrl || slot.imageUrl;
      const image = isSessionOnlyImageUrl(stored) ? '' : stored;
      const hasImage = Boolean(image || slot.sourceFileId);
      // Approval is one toggle per image and it locks that card, exactly like a section.
      const approved = slot.status === 'approved';
      const frozen = approved;
      const waitCover = locked && !approved;
      const generateDisabled = frozen || waitCover || slot.status === 'generating';
      const mode = slot.mode === 'upload' ? 'upload' : 'ai';
      const disableAiSwitch = frozen || (hasImage && mode === 'upload');
      const disableUploadSwitch = frozen || (hasImage && mode === 'ai');
      const statusLabel = approved ? 'معتمد' : slot.status === 'generating' ? 'قيد التوليد' : slot.status === 'review' ? 'مسودة - جاهزة للاعتماد' : 'مسودة';
      const chat = (slot.chat || []).map(item => (
        '<div class="visual-concept-chat-message"><strong>' + (item.role === 'assistant' ? trDynamicI18n('النظام:') + ' ' : trDynamicI18n('أنت:') + ' ') + '</strong>' + escapeHtml(item.text) + '</div>'
      )).join('') || '<div class="tenant-hint">' + trDynamicI18n('لا توجد تعديلات بعد.') + '</div>';
      const title = visualConceptSlotLabel(slotDef.id);
      const preview = image
        ? '<div class="visual-concept-preview has-image" data-visual-zoom="' + escapeHtml(image) + '" data-visual-title="' + escapeHtml(title) + '">' +
        '<img src="' + escapeHtml(image) + '" alt="' + escapeHtml(title) + '">' +
        '<button type="button" class="visual-concept-zoom-btn" data-visual-zoom="' + escapeHtml(image) + '" data-visual-title="' + escapeHtml(title) + '">تكبير</button>' +
        '</div>'
        : '<div class="visual-concept-preview empty">لم تُرفع أو تُولَّد هذه الصورة بعد.</div>';
      const uploadAccept = 'image/png,image/jpeg,image/jpg,image/webp';
      const heading = visualConceptCanRenameSlot(slotDef.id)
        ? '<input class="visual-concept-title-input" data-visual-title="' + slotDef.id + '" value="' + escapeHtml(title) + '" ' + (frozen ? 'disabled' : '') + '>'
        : '<h3>' + escapeHtml(title) + '</h3>';

      // Plans pick their mode by which tab they live in, not a per-card switch.
      const modeSelector = isVisualConceptPlanSlot(slotDef.id) ? '' : '<div class="visual-concept-mode-selector">' +
        '<button type="button" class="visual-concept-mode-btn' + (mode === 'ai' ? ' active' : '') + '" data-visual-action="set-mode" data-visual-mode="ai" data-visual-slot="' + slotDef.id + '" ' + (disableAiSwitch ? 'disabled title="احذف الصورة الحالية أولاً لتغيير النمط"' : '') + '>توليد بالذكاء الاصطناعي</button>' +
        '<button type="button" class="visual-concept-mode-btn' + (mode === 'upload' ? ' active' : '') + '" data-visual-action="set-mode" data-visual-mode="upload" data-visual-slot="' + slotDef.id + '" ' + (disableUploadSwitch ? 'disabled title="احذف الصورة الحالية أولاً لتغيير النمط"' : '') + '>رفع يدوي</button>' +
        '</div>';

      const deleteBtn = hasImage
        ? '<button type="button" class="btn danger small" data-visual-action="delete-image" data-visual-slot="' + slotDef.id + '" ' + (frozen ? 'disabled' : '') + '>حذف الصورة</button>'
        : '';
      const deleteFieldBtn = isVisualConceptInteriorSlot(slotDef.id)
        ? '<button type="button" class="btn danger small" data-visual-action="delete-interior-field" data-visual-slot="' + slotDef.id + '">حذف الحقل</button>'
        : (isVisualConceptPlanSlot(slotDef.id)
          ? '<button type="button" class="btn danger small" data-visual-action="delete-plan" data-visual-slot="' + slotDef.id + '">حذف المخطط</button>'
          : '');

      let bodyControls = '';
      if (mode === 'upload') {
        bodyControls = '<div class="visual-concept-upload-box">' +
          '<label class="visual-concept-upload-label">اختر ملف الصورة من جهازك</label>' +
          '<input type="file" accept="' + uploadAccept + '" data-visual-upload="' + slotDef.id + '" ' + (frozen ? 'disabled' : '') + '>' +
          (slot.sourceFileName ? '<div class="visual-concept-file-info">الملف الحالي: ' + escapeHtml(slot.sourceFileName) + '</div>' : '') +
          '</div>' +
          (isVisualConceptPlanSlot(slotDef.id) ? '<label>وصف المخطط</label>' : '<label>وصف الصورة</label>') +
          '<textarea data-visual-caption="' + slotDef.id + '" rows="3" ' + (frozen ? 'disabled' : '') + '>' + escapeHtml(slot.caption || '') + '</textarea>' +
          '<div class="visual-concept-actions">' +
          '<button type="button" class="btn ' + (approved ? 'ghost' : 'primary') + ' small" data-visual-action="' + (approved ? 'unapprove' : 'approve') + '" data-visual-slot="' + slotDef.id + '" ' + ((!image && !approved) ? 'disabled' : '') + '>' + (approved ? 'الغاء الاعتماد' : 'اعتماد') + '</button>' +
          deleteBtn + deleteFieldBtn +
          '</div>';
      } else {
        bodyControls = '<label>وصف التوليد</label>' +
          '<textarea class="visual-concept-prompt" data-visual-prompt="' + slotDef.id + '" ' + (frozen ? 'disabled' : '') + ' dir="ltr">' + escapeHtml(slot.prompt || '') + '</textarea>' +
          (isVisualConceptPlanSlot(slotDef.id)
            ? '<label>وصف المخطط</label><textarea data-visual-caption="' + slotDef.id + '" rows="2" ' + (frozen ? 'disabled' : '') + '>' + escapeHtml(slot.caption || '') + '</textarea>'
            : '') +
          '<div class="visual-concept-actions">' +
          '<button type="button" class="btn ghost small" data-visual-action="prompt" data-visual-slot="' + slotDef.id + '" ' + (generateDisabled ? 'disabled' : '') + '>إنشاء / إعادة توليد الوصف</button>' +
          '<button type="button" class="btn primary small" data-visual-action="generate" data-visual-slot="' + slotDef.id + '" ' + (generateDisabled ? 'disabled' : '') + '>توليد الصورة</button>' +
          '<button type="button" class="btn ' + (approved ? 'ghost' : 'primary') + ' small" data-visual-action="' + (approved ? 'unapprove' : 'approve') + '" data-visual-slot="' + slotDef.id + '" ' + ((!image && !approved) ? 'disabled' : '') + '>' + (approved ? 'الغاء الاعتماد' : 'اعتماد') + '</button>' +
          deleteBtn + deleteFieldBtn +
          '</div>' +
          '<div class="visual-concept-chat">' + chat + '</div>' +
          '<div class="visual-concept-chat-row">' +
          '<textarea data-visual-chat="' + slotDef.id + '" rows="2" ' + (generateDisabled ? 'disabled' : '') + '></textarea>' +
          '<button type="button" class="btn primary small" data-visual-action="chat" data-visual-slot="' + slotDef.id + '" ' + (generateDisabled ? 'disabled' : '') + '>إرسال التعديل</button>' +
          '</div>';
      }

      const lockHint = waitCover
        ? '<p class="tenant-hint">' + escapeHtml(visualConceptLockMessage(slotDef.id)) + '</p>'
        : '';
      return '<article class="visual-concept-card' + (waitCover ? ' locked' : '') + (approved ? ' section-locked' : '') + '" data-visual-slot="' + slotDef.id + '">' +
        '<div class="visual-concept-head">' + heading +
        '<span class="visual-concept-status ' + slot.status + '">' + statusLabel + '</span></div>' +
        modeSelector +
        preview +
        lockHint +
        bodyControls +
        '</article>';
    }

    function openVisualConceptLightbox(url, title) {
      if (!url) return;
      let modal = document.getElementById('visualConceptLightbox');
      if (!modal) {
        modal = document.createElement('div');
        modal.id = 'visualConceptLightbox';
        modal.className = 'visual-concept-lightbox';
        modal.innerHTML = `
          <div class="visual-concept-lightbox-backdrop" data-visual-lightbox-close></div>
          <div class="visual-concept-lightbox-content">
            <div class="visual-concept-lightbox-header">
              <h3 id="visualConceptLightboxTitle">معاينة الصورة</h3>
              <button type="button" class="btn ghost small" data-visual-lightbox-close>إغلاق</button>
            </div>
            <div class="visual-concept-lightbox-body">
              <img id="visualConceptLightboxImg" src="" alt="معاينة مكبرة">
            </div>
          </div>
        `;
        document.body.appendChild(modal);
        modal.querySelectorAll('[data-visual-lightbox-close]').forEach(btn => {
          btn.addEventListener('click', closeVisualConceptLightbox);
        });
      }
      const img = modal.querySelector('#visualConceptLightboxImg');
      const titleEl = modal.querySelector('#visualConceptLightboxTitle');
      if (img) img.src = url;
      if (titleEl) titleEl.textContent = title || 'معاينة الصورة';
      modal.hidden = false;
    }

    function closeVisualConceptLightbox() {
      const modal = document.getElementById('visualConceptLightbox');
      if (modal) {
        modal.hidden = true;
        const img = modal.querySelector('#visualConceptLightboxImg');
        if (img) img.src = '';
      }
    }

    if (!window._visualConceptLightboxEscapeBound) {
      window._visualConceptLightboxEscapeBound = true;
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeVisualConceptLightbox();
      });
    }

    function visualConceptImageUrl(url) {
      const value = String(url || '');
      if (!value.startsWith('/uploads/')) return value;
      // The media route needs the expiring ?s= signature from the JSON response —
      // keep it and only append a cache-buster, or a fresh image 404s until reload.
      return value + (value.includes('?') ? '&' : '?') + 't=' + Date.now();
    }

    function renderVisualConceptStyleReference() {
      const preview = document.getElementById('visualConceptStyleReferencePreview');
      if (!preview) return;
      const ids = Array.isArray(tenantVisualConceptState?.styleReferenceFileIds)
        ? tenantVisualConceptState.styleReferenceFileIds : [];
      const names = Array.isArray(tenantVisualConceptState?.styleReferenceNames)
        ? tenantVisualConceptState.styleReferenceNames : [];
      if (!ids.length) {
        preview.textContent = 'لم تُرفع صور مرجعية.';
        return;
      }
      preview.innerHTML = '<div class="visual-concept-reference-list"></div>';
      const list = preview.firstElementChild;
      ids.forEach((fileId, index) => {
        const item = document.createElement('div');
        item.className = 'visual-concept-reference-item';
        item.innerHTML = '<img alt="صورة مرجعية ' + (index + 1) + '"><span>' + escapeHtml(names[index] || ('صورة مرجعية ' + (index + 1))) + '</span>';
        list.appendChild(item);
        attachProjectFileThumbnail(item.querySelector('img'), fileId);
      });
    }

    async function uploadVisualConceptStyleReference(input) {
      const files = Array.from(input?.files || []);
      if (!files.length) return;
      if (files.length > 5) toast('سيتم رفع أول 5 صور فقط.');
      try {
        input.dataset.projectFileType = 'visual_reference';
        const uploaded = await uploadTenantProjectFileInput(input, 'visual_style_reference');
        const incoming = (Array.isArray(uploaded) ? uploaded : [uploaded]).map((file, index) => ({
          id: file?.id || file,
          name: file?.originalName || files[index]?.name || ''
        })).filter(file => file.id);
        if (!incoming.length) throw new Error('تعذر رفع الصور المرجعية');
        tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState);
        const merged = [];
        const existingIds = tenantVisualConceptState.styleReferenceFileIds || [];
        const existingNames = tenantVisualConceptState.styleReferenceNames || [];
        existingIds.forEach((id, index) => merged.push({ id, name: existingNames[index] || '' }));
        incoming.forEach(file => {
          const found = merged.find(item => String(item.id) === String(file.id));
          if (found) found.name = found.name || file.name;
          else merged.push(file);
        });
        const limited = merged.slice(0, 5);
        tenantVisualConceptState.styleReferenceFileIds = limited.map(file => file.id);
        tenantVisualConceptState.styleReferenceNames = limited.map(file => file.name);
        tenantVisualConceptState.styleReferenceFileId = limited[0]?.id || '';
        tenantVisualConceptState.styleReferenceName = limited[0]?.name || '';
        markVisualConceptDirty();
        renderVisualConceptStyleReference();
        toast('تم حفظ ' + limited.length + ' صور مرجعية.');
      } catch (error) {
        toast(error.message || 'تعذر رفع الصور المرجعية');
      } finally {
        if (input) input.value = '';
      }
    }

    async function uploadVisualConceptInteriorReferences(input) {
      const files = Array.from(input?.files || []);
      if (!files.length) return;
      const componentId = selectedVisualConceptInteriorComponentId();
      if (!componentId) {
        toast('اختر مكونًا أولًا');
        return;
      }
      const remaining = Math.max(0, VISUAL_CONCEPT_MAX_INTERIOR_IMAGES - visualConceptInteriorViewIds(componentId).filter(id => {
        const slot = tenantVisualConceptState.slots[id] || {};
        return slot.imageUrl || slot.approvedImageUrl || slot.sourceFileId;
      }).length);
      if (!remaining) {
        toast('تم الوصول إلى الحد الأقصى لصور هذا المكون');
        input.value = '';
        return;
      }
      const slotId = visualConceptInteriorSlotId(componentId, 1);
      if (files.length > 4) toast('سيتم رفع أول 4 صور فقط.');
      try {
        input.dataset.projectFileType = 'visual_reference';
        const uploaded = await uploadTenantProjectFileInput(input, 'visual_style_reference');
        const incoming = (Array.isArray(uploaded) ? uploaded : [uploaded]).map((file, index) => ({
          id: file?.id || file,
          name: file?.originalName || files[index]?.name || ''
        })).filter(file => file.id);
        if (!incoming.length) throw new Error('تعذر رفع الصور المرجعية');
        tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState);
        if (!tenantVisualConceptState.slots[slotId]) tenantVisualConceptState.slots[slotId] = emptyVisualConceptSlot(slotId);
        const slot = tenantVisualConceptState.slots[slotId];
        const merged = [];
        (slot.styleReferenceFileIds || []).forEach((id, index) => merged.push({ id, name: (slot.styleReferenceNames || [])[index] || '' }));
        incoming.forEach(file => {
          const found = merged.find(item => String(item.id) === String(file.id));
          if (found) found.name = found.name || file.name;
          else merged.push(file);
        });
        const limited = merged.slice(0, 4);
        slot.styleReferenceFileIds = limited.map(file => file.id);
        slot.styleReferenceNames = limited.map(file => file.name);
        const revivedViewIds = [];
        for (let index = 0; index < limited.length; index += 1) {
          const file = limited[index];
          const viewId = visualConceptInteriorSlotId(componentId, index + 1);
          revivedViewIds.push(viewId);
          if (!tenantVisualConceptState.slots[viewId]) tenantVisualConceptState.slots[viewId] = emptyVisualConceptSlot(viewId);
          const viewSlot = tenantVisualConceptState.slots[viewId];
          if (!viewSlot.imageUrl && !viewSlot.approvedImageUrl) {
            viewSlot.sourceFileId = file.id;
            viewSlot.sourceFileName = file.name;
            viewSlot.imageUrl = await publishProjectFileImageUrl(file.id);
            viewSlot.status = viewSlot.status === 'approved' ? viewSlot.status : 'review';
          }
        }
        tenantVisualConceptState.deletedInteriorSlots = (tenantVisualConceptState.deletedInteriorSlots || [])
          .filter(id => !revivedViewIds.includes(id));
        markVisualConceptDirty();
        renderVisualConceptPage();
        toast('تم حفظ صور هذا المكون.');
      } catch (error) {
        toast(error.message || 'تعذر رفع الصور المرجعية');
      } finally {
        if (input) input.value = '';
      }
    }

    function clearVisualConceptInteriorReferences() {
      const componentId = selectedVisualConceptInteriorComponentId();
      const slotId = visualConceptInteriorSlotId(componentId, 1);
      tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState);
      if (!tenantVisualConceptState.slots[slotId]) return;
      tenantVisualConceptState.slots[slotId].styleReferenceFileIds = [];
      tenantVisualConceptState.slots[slotId].styleReferenceNames = [];
      markVisualConceptDirty();
      renderVisualConceptInteriorReferences(slotId);
      toast('تم حذف صور هذا المكون.');
    }

    function clearVisualConceptStyleReference() {
      tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState);
      tenantVisualConceptState.styleReferenceFileIds = [];
      tenantVisualConceptState.styleReferenceFileId = '';
      tenantVisualConceptState.styleReferenceNames = [];
      tenantVisualConceptState.styleReferenceName = '';
      markVisualConceptDirty();
      renderVisualConceptStyleReference();
      toast('تم حذف الصور المرجعية. سيولد النظام التصميم من البيانات والخريطة فقط.');
    }

    function visualConceptPlans() {
      if (!Array.isArray(tenantVisualConceptState?.plans2d)) {
        if (tenantVisualConceptState) tenantVisualConceptState.plans2d = [];
        else return [];
      }
      return tenantVisualConceptState.plans2d;
    }

    function visualConceptPlanMode(plan) {
      const slot = tenantVisualConceptState?.slots?.[plan?.id];
      const mode = slot ? slot.mode : plan?.mode;
      return mode === 'upload' ? 'upload' : 'generate';
    }

    function setVisualConceptPlansTab(tab) {
      const active = tab === 'upload' ? 'upload' : 'generate';
      document.querySelectorAll('[data-visual-plans-tab]').forEach(button => {
        button.classList.toggle('active', button.getAttribute('data-visual-plans-tab') === active);
      });
      document.querySelectorAll('[data-visual-plans-panel]').forEach(panel => {
        panel.hidden = panel.getAttribute('data-visual-plans-panel') !== active;
      });
    }

    function renderVisualConceptBoundarySvg(host, points) {
      if (!host) return;
      const rows = visualConceptBoundaryPoints(points);
      if (rows.length < 3) {
        host.innerHTML = '<p class="tenant-hint">لا توجد نقاط حدود مكتملة.</p>';
        return;
      }
      const xs = rows.map(item => item.eastings);
      const ys = rows.map(item => item.northings);
      const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
      const span = Math.max(maxX - minX, maxY - minY) || 1;
      const pad = 100;
      const toPoint = item => {
        const x = pad + ((item.eastings - minX) / span) * (1000 - pad * 2) + ((1000 - pad * 2) - ((maxX - minX) / span) * (1000 - pad * 2)) / 2;
        const y = 700 - (pad + ((item.northings - minY) / span) * (700 - pad * 2) + ((700 - pad * 2) - ((maxY - minY) / span) * (700 - pad * 2)) / 2);
        return [Math.round(x), Math.round(y)];
      };
      const polygon = rows.map(toPoint).map(point => point.join(',')).join(' ');
      const circles = rows.map((item, index) => {
        const [x, y] = toPoint(item);
        return '<circle cx="' + x + '" cy="' + y + '" r="9" fill="#172b4d"><title>' + escapeHtml(item.point || String(index + 1)) + '</title></circle>';
      }).join('');
      host.innerHTML = '<svg viewBox="0 0 1000 700" role="img" aria-label="حدود الأرض" class="plans-boundary-svg">' +
        '<polygon points="' + polygon + '" fill="#e8f0e8" stroke="#172b4d" stroke-width="7"></polygon>' +
        circles +
        '<line x1="90" y1="155" x2="90" y2="70" stroke="#172b4d" stroke-width="7"></line>' +
        '<polygon points="90,50 76,78 104,78" fill="#172b4d"></polygon>' +
        '<text x="82" y="185" fill="#172b4d" font-size="24">N</text>' +
        '</svg>';
    }

    function visualConceptDistributionTotalsRowsHtml(distribution) {
      const totals = Array.isArray(distribution.totals) ? distribution.totals : [];
      if (!totals.length) return '';
      const fmt = value => (value === null || value === undefined || value === '') ? '—'
        : (typeof value === 'number' ? String(Math.round(value * 100) / 100) : String(value));
      const rowsHtml = totals.map(item => {
        const deltas = [];
        if (typeof item.delta_units === 'number' && item.delta_units) deltas.push('وحدات ' + (item.delta_units > 0 ? '+' : '') + item.delta_units);
        if (typeof item.delta_area === 'number' && item.delta_area) deltas.push('م² ' + (item.delta_area > 0 ? '+' : '') + item.delta_area);
        const hasRequired = typeof item.required_units === 'number' || typeof item.required_area === 'number';
        const deltaText = deltas.length ? deltas.join('، ') : (hasRequired ? 'مطابق للدراسة' : '—');
        const impact = deltas.length ? '<div class="plans-conflict-location">يؤثر في الدراسة المالية</div>' : '';
        return '<tr class="plans-distribution-total"><td colspan="3">' + escapeHtml(item.component || '') + '</td>' +
          '<td>' + escapeHtml(fmt(item.units)) + ' / ' + escapeHtml(fmt(item.required_units)) + '</td>' +
          '<td>' + escapeHtml(fmt(item.area)) + ' / ' + escapeHtml(fmt(item.required_area)) + '</td>' +
          '<td colspan="2">' + escapeHtml(deltaText) + impact + '</td></tr>';
      }).join('');
      return '<tr class="plans-distribution-total-head"><td colspan="3">إجمالي المكونات</td>' +
        '<td>الوحدات توزيع/دراسة</td><td>المساحة توزيع/دراسة</td><td colspan="2">الفرق</td></tr>' + rowsHtml;
    }

    function visualConceptDistributionEditorHtml(distribution) {
      const rows = Array.isArray(distribution.rows) ? distribution.rows : [];
      const head = '<thead><tr><th>المبنى</th><th>الدور أو نطاق الأدوار</th><th>الاستخدام / المكون</th>' +
        '<th>عدد الوحدات لكل دور</th><th>مساحة الدور الإجمالية</th><th>الحركة والخدمات ضمن المساحة</th><th></th></tr></thead>';
      const body = rows.length ? rows.map(row =>
        '<tr>' +
        '<td><input data-dist-field="building" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.building) + '"></td>' +
        '<td><input data-dist-field="floor_range" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.floor_range) + '" placeholder="1-4"></td>' +
        '<td><input data-dist-field="component" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.component) + '"></td>' +
        '<td><input data-dist-field="units_per_floor" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.units_per_floor ?? '') + '"></td>' +
        '<td><input data-dist-field="floor_area_sqm" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.floor_area_sqm ?? '') + '"></td>' +
        '<td><input data-dist-field="circulation" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.circulation) + '"></td>' +
        '<td><button type="button" class="btn ghost small" data-dist-remove="' + escapeHtml(row.id) + '">حذف</button></td>' +
        '</tr>').join('')
        : '<tr><td colspan="7" class="plans-workflow-empty">لم يُقترح توزيع بعد.</td></tr>';
      return '<div class="plans-workflow-table-wrap"><table class="plans-workflow-table plans-distribution-table">' +
        head + '<tbody>' + body + '</tbody>' +
        '<tfoot data-plans-distribution-totals>' + visualConceptDistributionTotalsRowsHtml(distribution) + '</tfoot>' +
        '</table></div>' +
        '<div class="visual-concept-actions"><button type="button" class="btn ghost small" data-plans-workflow-action="add-distribution-row">إضافة صف</button></div>';
    }

    function visualConceptDistributionResultsHtml(distribution) {
      const rows = Array.isArray(distribution.rows) ? distribution.rows : [];
      const checks = Array.isArray(distribution.checks) ? distribution.checks : [];
      const issues = Array.isArray(distribution.issues) ? distribution.issues : [];
      const findings = checks.map(item =>
          (item.result && item.result !== 'مطابق' ? item.result + ': ' : '') + (item.detail || item.item || ''))
        .concat(issues.flatMap(item =>
          (Array.isArray(item.points) && item.points.length ? item.points : [item.title || ''])))
        .filter(Boolean);
      const findingsHtml = findings.length
        ? '<div class="plans-workflow-notice"><ul class="plans-issue-list">' +
          findings.map(point => '<li>' + escapeHtml(point) + '</li>').join('') + '</ul></div>'
        : (rows.length ? '<p class="plans-workflow-success">لا توجد تعارضات في التوزيع.</p>' : '');
      const canApprove = rows.length > 0 && !visualConceptDistributionBlocking(distribution).length;
      return findingsHtml +
        '<div class="visual-concept-actions">' +
        '<button type="button" class="btn ghost small" data-plans-workflow-action="check-distribution" ' + (rows.length ? '' : 'disabled') + '>فحص التعارضات</button>' +
        '<button type="button" class="btn ghost small" data-plans-workflow-action="repair-distribution" ' + (findings.length ? '' : 'disabled') + '>إصلاح التعارضات بالذكاء الاصطناعي</button>' +
        '<button type="button" class="btn primary small" data-plans-workflow-action="approve-distribution" ' + (canApprove ? '' : 'disabled') + '>اعتماد التوزيع</button>' +
        (distribution.approved ? '<span class="plans-workflow-success">التوزيع معتمد</span>' : '') +
        '</div>';
    }

    function visualConceptDistributionBlocking(distribution) {
      const checks = Array.isArray(distribution.checks) ? distribution.checks : [];
      const issues = Array.isArray(distribution.issues) ? distribution.issues : [];
      return checks.filter(item => item.result === 'متعارض' || item.severity === 'high')
        .concat(issues.filter(item => item.severity === 'high'));
    }

    function renderVisualConceptPlansWorkflow() {
      const root = document.getElementById('visualConceptPlansWorkflow');
      if (!root) return;
      const workflow = visualConceptPlansWorkflowState();
      const verification = workflow.verification || {};
      const boundary = workflow.boundary || {};
      const distribution = workflow.distribution || {};
      const verified = Boolean(verification.approved);
      const boundaryApproved = Boolean(boundary.approved);
      const distApproved = Boolean(distribution.approved);
      const promptReady = Boolean(workflow.promptReady);
      const defaultStage = !verified ? 'verify' : ((boundaryApproved && distApproved) ? 'generate' : 'boundary');
      const requestedStage = ['verify', 'boundary', 'generate'].includes(workflow.viewStage) ? workflow.viewStage : defaultStage;
      const activeStage = requestedStage === 'generate' && !(boundaryApproved && distApproved)
        ? (verified ? 'boundary' : 'verify')
        : (requestedStage === 'boundary' && !verified ? 'verify' : requestedStage);
      const checks = Array.isArray(verification.checks) ? verification.checks : [];
      const conflicts = checks.filter(item => item.result === 'متعارض');
      const canApprove = !conflicts.length && (checks.length > 0 || verification.canProceed);
      const checkRows = conflicts.length ? conflicts.map(item =>
        '<tr><td>' + escapeHtml(item.item || '') +
        ((item.section || item.field) ? '<div class="plans-conflict-location">' + escapeHtml(item.section || '') + (item.field ? ' — ' + escapeHtml(item.field) : '') + '</div>' : '') +
        '</td><td>' + escapeHtml(item.project || '') + '</td><td>' + escapeHtml(item.regulatory || '') + '</td><td><span class="plans-check-result plans-check-' + escapeHtml(item.result || '') + '">' + escapeHtml(item.result || '') + '</span></td><td>' +
        (Array.isArray(item.issues) && item.issues.length ? '<ul class="plans-issue-list">' + item.issues.map(issue => '<li>' + escapeHtml(issue) + '</li>').join('') + '</ul>' : '') +
        (item.suggestion ? '<div class="plans-conflict-solution"><strong>' + escapeHtml(WFT('plans.proposed_solution', 'الحل المقترح:')) + '</strong> ' + escapeHtml(item.suggestion) + '</div>' : '') +
        escapeHtml(item.action || '') + '</td></tr>'
      ).join('') : '<tr><td colspan="5" class="plans-workflow-empty plans-workflow-success">' + escapeHtml(WFT('plans.no_conflicts', 'لا توجد تعارضات مباشرة.')) + '</td></tr>';
      const conflictPoints = conflicts.flatMap(item => Array.isArray(item.issues) ? item.issues : []).filter(Boolean);
      const issueList = conflictPoints.length
        ? '<ul class="plans-issue-list plans-issue-summary">' + conflictPoints.map(point => '<li>' + escapeHtml(point) + '</li>').join('') + '</ul>'
        : '';
      const promptCards = promptReady
        ? '<div class="visual-concept-stack">' + VISUAL_CONCEPT_PLAN_KINDS.map(definition =>
          renderVisualConceptSlot({ id: definition.id, label: definition.label, group: 'plans' }, visualConceptSlotLocked(definition.id))
        ).join('') + '</div>'
        : '<p class="tenant-hint">لم تُجهز برومبتات المخططات بعد.</p>';
      root.innerHTML =
        '<div class="plans-workflow-card">' +
        '<ol class="plans-workflow-steps">' +
        '<li class="' + (activeStage === 'verify' ? 'is-active' : (verified ? 'is-complete' : '')) + '"><button type="button" data-plans-workflow-tab="verify">التحقق من التضارب</button></li>' +
        '<li class="' + (activeStage === 'boundary' ? 'is-active' : (boundaryApproved && distApproved ? 'is-complete' : '')) + '"><button type="button" data-plans-workflow-tab="boundary" ' + (!verified ? 'disabled' : '') + '>رسم الحدود وتوزيع المكونات</button></li>' +
        '<li class="' + (activeStage === 'generate' ? 'is-active' : '') + '"><button type="button" data-plans-workflow-tab="generate" ' + (!(boundaryApproved && distApproved) ? 'disabled' : '') + '>توليد المخططات</button></li>' +
        '</ol>' +
        '<section class="plans-workflow-panel" data-plans-workflow-stage="verify"' + (activeStage !== 'verify' ? ' hidden' : '') + '>' +
        '<div class="plans-workflow-panel-head"><h4>التحقق من التضارب</h4><button type="button" class="btn primary small" data-plans-workflow-action="verify">تحقق</button></div>' +
        '<p class="' + (conflicts.length ? 'tenant-hint' : 'plans-workflow-success') + '" data-plans-verification-summary>' + escapeHtml(conflicts.length ? WFT('plans.conflicts_count', 'عدد التعارضات المباشرة: ') + conflicts.length : WFT('plans.no_conflicts', 'لا توجد تعارضات مباشرة.')) + '</p>' +
        (issueList ? '<div class="plans-workflow-notice">' + issueList + '</div>' : '') +
        '<div class="plans-workflow-table-wrap"><table class="plans-workflow-table plans-check-table"><thead><tr><th>البند</th><th>بيانات المشروع</th><th>البيانات الموثقة</th><th>النتيجة</th><th>المشاكل والإجراء</th></tr></thead><tbody>' + checkRows + '</tbody></table></div>' +
        '<div class="visual-concept-actions"><button type="button" class="btn primary small" data-plans-workflow-action="approve-verification" ' + (!canApprove ? 'disabled' : '') + '>اعتماد نتيجة التحقق</button></div>' +
        '</section>' +
        '<section class="plans-workflow-panel" data-plans-workflow-stage="boundary"' + (activeStage !== 'boundary' ? ' hidden' : '') + '>' +
        '<div class="plans-workflow-panel-head"><h4>رسم حدود الأرض</h4><div class="visual-concept-actions"><button type="button" class="btn ghost small" data-plans-workflow-action="open-land-data">مراجعة بيانات الأرض والكروكي</button><button type="button" class="btn ghost small" data-plans-workflow-action="refresh-boundary">تحديث الرسم</button></div></div>' +
        '<div class="plans-boundary-editor"><div class="plans-boundary-preview" data-plans-boundary-preview></div><div class="plans-boundary-meta"><p class="tenant-hint">حدود الرسم مأخوذة من جدول الإحداثيات المعتمد في الأرض والكروكي.</p></div></div>' +
        '<div class="visual-concept-actions"><button type="button" class="btn ghost small" data-plans-workflow-action="boundary-ai">تعديل الحدود بالذكاء الاصطناعي</button><button type="button" class="btn primary small" data-plans-workflow-action="approve-boundary" ' + (boundary.points.length < 3 || !boundary.referenceUrl ? 'disabled' : '') + '>اعتماد حدود الأرض</button></div>' +
        '<label>ملاحظات تعديل الحدود</label><textarea rows="3" data-plans-boundary-instruction>' + escapeHtml(boundary.instruction || '') + '</textarea>' +
        '<div class="plans-workflow-panel-head"><h4>توزيع المكونات على الأدوار</h4><button type="button" class="btn primary small" data-plans-workflow-action="propose-distribution">اقتراح التوزيع</button></div>' +
        '<div data-plans-distribution-editor>' + visualConceptDistributionEditorHtml(distribution) + '</div>' +
        '<div data-plans-distribution-results>' + visualConceptDistributionResultsHtml(distribution) + '</div>' +
        '</section>' +
        '<section class="plans-workflow-panel" data-plans-workflow-stage="generate"' + (activeStage !== 'generate' ? ' hidden' : '') + '>' +
        '<div class="plans-workflow-panel-head"><h4>توليد المخططات</h4><button type="button" class="btn primary small" data-plans-workflow-action="prepare-prompts">إعداد برومبتات المخططات</button></div>' +
        '<p class="tenant-hint">' + escapeHtml(promptReady ? 'البرومبتات جاهزة للتعديل والتوليد.' : (workflow.promptsError ? 'تعذر إعداد برومبتات المخططات: ' + workflow.promptsError : 'برومبتات المخططات الثلاثة غير جاهزة.')) + '</p>' +
        '<div data-plans-workflow-prompts>' + promptCards + '</div>' +
        '</section></div>';
      const preview = root.querySelector('[data-plans-boundary-preview]');
      renderVisualConceptBoundarySvg(preview, boundary.points);
      // Delegated binding, once: the distribution results container is re-rendered
      // in place after every re-check, so per-button listeners would die with it.
      if (!root.dataset.plansWorkflowBound) {
        root.dataset.plansWorkflowBound = 'true';
        root.addEventListener('click', event => {
          const tab = event.target.closest('[data-plans-workflow-tab]');
          if (tab && !tab.disabled) {
            const stage = tab.getAttribute('data-plans-workflow-tab');
            const state = visualConceptPlansWorkflowState();
            if (stage === 'boundary' && !state.verification.approved) return;
            if (stage === 'generate' && !(state.boundary.approved && state.distribution.approved)) return;
            state.viewStage = stage;
            persistVisualConceptDraftState();
            renderVisualConceptPage();
            return;
          }
          const removeBtn = event.target.closest('[data-dist-remove]');
          if (removeBtn) {
            const state = visualConceptPlansWorkflowState();
            const id = removeBtn.getAttribute('data-dist-remove');
            state.distribution.rows = (state.distribution.rows || []).filter(item => item.id !== id);
            state.distribution.approved = false;
            state.promptReady = false;
            markVisualConceptDirty();
            renderVisualConceptPage();
            scheduleVisualConceptDistributionCheck();
            return;
          }
          const actionBtn = event.target.closest('[data-plans-workflow-action]');
          if (!actionBtn || actionBtn.disabled) return;
          const action = actionBtn.getAttribute('data-plans-workflow-action');
          const state = visualConceptPlansWorkflowState();
          if (action === 'open-land-data') {
            state.verification.approved = false;
            state.boundary.approved = false;
            state.distribution.approved = false;
            state.promptReady = false;
            state.promptsError = '';
            state.viewStage = 'verify';
            state.status = 'idle';
            markVisualConceptDirty();
            if (typeof showSection === 'function') showSection('land_croquis');
          } else if (action === 'verify') verifyVisualConceptPlans();
          else if (action === 'approve-verification') approveVisualConceptPlansVerification();
          else if (action === 'refresh-boundary') refreshVisualConceptPlansBoundary();
          else if (action === 'boundary-ai') reviseVisualConceptPlansBoundaryWithAi();
          else if (action === 'approve-boundary') approveVisualConceptPlansBoundary();
          else if (action === 'propose-distribution') proposeVisualConceptPlansDistribution();
          else if (action === 'check-distribution') checkVisualConceptPlansDistribution('ai');
          else if (action === 'repair-distribution') repairVisualConceptPlansDistribution();
          else if (action === 'add-distribution-row') addVisualConceptDistributionRow();
          else if (action === 'approve-distribution') approveVisualConceptPlansDistribution();
          else if (action === 'prepare-prompts') prepareVisualConceptPlansPrompts();
        });
        root.addEventListener('change', event => {
          const input = event.target.closest('[data-dist-field]');
          if (!input) return;
          const state = visualConceptPlansWorkflowState();
          const id = input.getAttribute('data-dist-id');
          const field = input.getAttribute('data-dist-field');
          const row = (state.distribution.rows || []).find(item => item.id === id);
          if (!row) return;
          row[field] = input.value;
          state.distribution.approved = false;
          state.promptReady = false;
          state.promptsError = '';
          markVisualConceptDirty();
          scheduleVisualConceptDistributionCheck();
        });
      }
    }

    function renderVisualConceptPlans() {
      renderVisualConceptPlansWorkflow();
      const uploadHost = document.getElementById('visualConceptPlansUploadList');
      const count = document.getElementById('visualConceptPlansCount');
      const input = document.getElementById('visualConceptPlansUploadInput');
      const plans = visualConceptPlans().filter(plan => !isVisualConceptWorkflowPlan(plan.id));
      if (count) count.textContent = plans.length ? plans.length + ' مخطط مرفوع' : 'لا توجد مخططات مرفوعة.';
      if (input) input.disabled = plans.length >= VISUAL_CONCEPT_MAX_PLANS;
      if (!uploadHost) return;
      plans.forEach(plan => {
        if (!tenantVisualConceptState.slots[plan.id]) tenantVisualConceptState.slots[plan.id] = visualConceptPlanSeed(plan) || emptyVisualConceptSlot(plan.id);
      });
      uploadHost.innerHTML = plans.length
        ? '<div class="visual-concept-stack">' + plans.map(plan => renderVisualConceptSlot({ id: plan.id, label: plan.title || 'مخطط', group: 'plans' }, false)).join('') + '</div>'
        : '<p class="tenant-hint">لا توجد مخططات مرفوعة.</p>';
    }

    async function collectVisualConceptPlansWorkflowPayload() {
      const payload = await collectVisualConceptPayload('plan_site');
      payload.plansWorkflow = normalizeVisualConceptPlansWorkflow(tenantVisualConceptState.plansWorkflow);
      // The plans endpoints read plansWorkflow and the project facts only, so the
      // visual_concept state mirror is dead weight here — and oversized bodies are
      // what the hosting edge corrupts, so the request drops it (clone: projectData
      // is tenantProjectData, which must keep its own copy).
      payload.projectData = { ...payload.projectData };
      delete payload.projectData.visual_concept;
      return payload;
    }

    async function verifyVisualConceptPlans() {
      if (!hasPermission('generate_images')) { toast(WFT('plans.permission', 'لا تملك صلاحية توليد المخططات')); return; }
      showLoader(WFT('plans.verify_loading', 'جاري التحقق من التضارب'), WFT('plans.verify_loading_detail', 'يتم فحص بيانات المشروع والبيانات التنظيمية الموثقة...'), 18);
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        const response = await api('POST', '/api/visual-concept/plans-verify', payload);
        hideLoader();
        if (!response?.success) { toast(response?.error || WFT('plans.verify_failed', 'تعذر التحقق من التضارب')); return; }
        const workflow = visualConceptPlansWorkflowState();
        workflow.verification = normalizeVisualConceptPlansWorkflow({ verification: response.verification }).verification;
        workflow.planContext = response.planContext || workflow.planContext || null;
        workflow.status = 'verified';
        workflow.viewStage = 'verify';
        workflow.boundary.approved = false;
        workflow.distribution.approved = false;
        workflow.promptReady = false;
        workflow.promptsError = '';
        markVisualConceptDirty();
        renderVisualConceptPage();
      } catch (error) {
        hideLoader();
        toast(error.message || WFT('plans.verify_failed', 'تعذر التحقق من التضارب'));
      }
    }

    function approveVisualConceptPlansVerification() {
      const workflow = visualConceptPlansWorkflowState();
      const checks = Array.isArray(workflow.verification.checks) ? workflow.verification.checks : [];
      const conflicts = checks.filter(item => item.result === 'متعارض');
      if (conflicts.length || (!checks.length && !workflow.verification.canProceed)) return;
      workflow.verification.approved = true;
      workflow.status = 'verified';
      workflow.viewStage = 'boundary';
      if (!workflow.boundary.points.length) workflow.boundary.points = visualConceptBoundaryPoints(tenantProjectData.survey_coordinates);
      markVisualConceptDirty();
      renderVisualConceptPage();
    }

    async function refreshVisualConceptPlansBoundary() {
      const payload = await collectVisualConceptPlansWorkflowPayload();
      const seedWorkflow = visualConceptPlansWorkflowState();
      const sourcePoints = visualConceptBoundaryPoints(payload.projectData?.survey_coordinates);
      if (sourcePoints.length >= 3) seedWorkflow.boundary.points = sourcePoints;
      payload.points = seedWorkflow.boundary.points;
      payload.mode = 'manual';
      showLoader(WFT('plans.boundary_loading', 'جاري تجهيز رسم حدود الأرض'), WFT('plans.boundary_loading_detail', 'يتم بناء الرسم من الإحداثيات المحفوظة...'), 35);
      try {
        const response = await api('POST', '/api/visual-concept/plans-boundary', payload);
        hideLoader();
        if (!response?.success) { toast(response?.error || WFT('plans.boundary_failed', 'تعذر تجهيز رسم الحدود')); return; }
        const workflow = visualConceptPlansWorkflowState();
        workflow.boundary.points = visualConceptBoundaryPoints(response.points);
        workflow.boundary.referenceUrl = response.referenceUrl || '';
        workflow.boundary.approved = false;
        markVisualConceptDirty();
        renderVisualConceptPage();
      } catch (error) {
        hideLoader();
        toast(error.message || WFT('plans.boundary_failed', 'تعذر تجهيز رسم الحدود'));
      }
    }

    async function reviseVisualConceptPlansBoundaryWithAi() {
      const instruction = String(document.querySelector('[data-plans-boundary-instruction]')?.value || '').trim();
      if (!instruction) { toast(WFT('plans.boundary_instruction_required', 'طلب تعديل الحدود مطلوب')); return; }
      const savedInstruction = instruction.slice(0, 2000);
      const payload = await collectVisualConceptPlansWorkflowPayload();
      const seedWorkflow = visualConceptPlansWorkflowState();
      seedWorkflow.boundary.instruction = savedInstruction;
      payload.points = seedWorkflow.boundary.points;
      payload.instruction = savedInstruction;
      payload.mode = 'ai';
      showLoader(WFT('plans.boundary_ai_loading', 'جاري تعديل حدود الأرض'), WFT('plans.boundary_ai_loading_detail', 'يتم مراجعة التعديل على الإحداثيات...'), 35);
      try {
        const response = await api('POST', '/api/visual-concept/plans-boundary', payload);
        hideLoader();
        if (!response?.success) { toast(response?.error || WFT('plans.boundary_failed', 'تعذر تعديل رسم الحدود')); return; }
        const workflow = visualConceptPlansWorkflowState();
        workflow.boundary.points = visualConceptBoundaryPoints(response.points);
        workflow.boundary.referenceUrl = response.referenceUrl || workflow.boundary.referenceUrl;
        workflow.boundary.instruction = savedInstruction;
        workflow.boundary.approved = false;
        markVisualConceptDirty();
        renderVisualConceptPage();
      } catch (error) {
        hideLoader();
        toast(error.message || WFT('plans.boundary_failed', 'تعذر تعديل رسم الحدود'));
      }
    }

    function approveVisualConceptPlansBoundary() {
      const workflow = visualConceptPlansWorkflowState();
      if (workflow.boundary.points.length < 3 || !workflow.boundary.referenceUrl) return;
      workflow.boundary.approved = true;
      workflow.status = 'boundary';
      workflow.viewStage = workflow.distribution.approved ? 'generate' : 'boundary';
      workflow.promptReady = false;
      markVisualConceptDirty();
      renderVisualConceptPage();
    }

    let visualConceptDistCheckTimer = null;

    function scheduleVisualConceptDistributionCheck() {
      if (visualConceptDistCheckTimer) clearTimeout(visualConceptDistCheckTimer);
      visualConceptDistCheckTimer = setTimeout(() => {
        visualConceptDistCheckTimer = null;
        checkVisualConceptPlansDistribution('local', { silent: true });
      }, 700);
    }

    function addVisualConceptDistributionRow() {
      const workflow = visualConceptPlansWorkflowState();
      workflow.distribution.rows.push({
        id: 'row_' + Date.now().toString(36),
        building: '', floor_range: '', component: '',
        units_per_floor: '', floor_area_sqm: '', circulation: ''
      });
      workflow.distribution.approved = false;
      workflow.promptReady = false;
      markVisualConceptDirty();
      renderVisualConceptPage();
    }

    async function proposeVisualConceptPlansDistribution() {
      if (!hasPermission('generate_images')) { toast(WFT('plans.permission', 'لا تملك صلاحية توليد المخططات')); return; }
      showLoader(WFT('plans.distribution_loading', 'جاري اقتراح التوزيع'),
        WFT('plans.distribution_loading_detail', 'يتم توزيع المكونات على المباني والأدوار...'), 30);
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        const response = await api('POST', '/api/visual-concept/plans-distribution', payload);
        hideLoader();
        if (!response?.success) { toast(response?.error || WFT('plans.distribution_failed', 'تعذر اقتراح التوزيع')); return; }
        const workflow = visualConceptPlansWorkflowState();
        workflow.distribution = normalizeVisualConceptPlansWorkflow({ distribution: response.distribution }).distribution;
        workflow.planContext = response.planContext || workflow.planContext || null;
        workflow.promptReady = false;
        workflow.promptsError = '';
        markVisualConceptDirty();
        renderVisualConceptPage();
      } catch (error) {
        hideLoader();
        toast(error.message || WFT('plans.distribution_failed', 'تعذر اقتراح التوزيع'));
      }
    }

    async function checkVisualConceptPlansDistribution(mode, options) {
      const silent = Boolean(options && options.silent);
      const workflow = visualConceptPlansWorkflowState();
      if (!workflow.verification.approved || !(workflow.distribution.rows || []).length) return;
      if (!silent) showLoader(WFT('plans.distribution_check_loading', 'جاري فحص التوزيع'),
        WFT('plans.distribution_check_loading_detail', 'يتم مراجعة المساحات والقيود...'), 35);
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        payload.mode = mode || 'local';
        payload.distribution = { rows: workflow.distribution.rows };
        const response = await api('POST', '/api/visual-concept/plans-distribution-check', payload);
        if (!silent) hideLoader();
        if (!response?.success) {
          if (!silent) toast(response?.error || WFT('plans.distribution_check_failed', 'تعذر فحص التوزيع'));
          return;
        }
        workflow.distribution.totals = Array.isArray(response.totals) ? response.totals : [];
        workflow.distribution.checks = Array.isArray(response.checks) ? response.checks : [];
        if (Array.isArray(response.issues)) workflow.distribution.issues = response.issues;
        markVisualConceptDirty();
        const totalsHost = document.querySelector('[data-plans-distribution-totals]');
        if (totalsHost) totalsHost.innerHTML = visualConceptDistributionTotalsRowsHtml(workflow.distribution);
        const host = document.querySelector('[data-plans-distribution-results]');
        if (host) host.innerHTML = visualConceptDistributionResultsHtml(workflow.distribution);
        else renderVisualConceptPage();
      } catch (error) {
        if (silent) return;
        hideLoader();
        toast(error.message || WFT('plans.distribution_check_failed', 'تعذر فحص التوزيع'));
      }
    }

    async function repairVisualConceptPlansDistribution() {
      if (!hasPermission('generate_images')) { toast(WFT('plans.permission', 'لا تملك صلاحية توليد المخططات')); return; }
      const workflow = visualConceptPlansWorkflowState();
      if (!(workflow.distribution.rows || []).length) return;
      showLoader(WFT('plans.distribution_repair_loading', 'جاري إصلاح التوزيع'),
        WFT('plans.distribution_repair_loading_detail', 'يعالج الذكاء الصفوف المتعارضة ويحدّث المجاميع...'), 40);
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        payload.distribution = { rows: workflow.distribution.rows, issues: workflow.distribution.issues };
        const response = await api('POST', '/api/visual-concept/plans-distribution-repair', payload);
        hideLoader();
        if (!response?.success) { toast(response?.error || WFT('plans.distribution_repair_failed', 'تعذر إصلاح التوزيع')); return; }
        if (response.repaired === false) toast(WFT('plans.distribution_nothing_to_repair', 'لا توجد ملاحظات تستدعي الإصلاح'));
        workflow.distribution = normalizeVisualConceptPlansWorkflow({ distribution: response.distribution }).distribution;
        workflow.promptReady = false;
        workflow.promptsError = '';
        markVisualConceptDirty();
        renderVisualConceptPage();
      } catch (error) {
        hideLoader();
        toast(error.message || WFT('plans.distribution_repair_failed', 'تعذر إصلاح التوزيع'));
      }
    }

    function approveVisualConceptPlansDistribution() {
      const workflow = visualConceptPlansWorkflowState();
      const rows = workflow.distribution.rows || [];
      if (!rows.length) return;
      if (visualConceptDistributionBlocking(workflow.distribution).length) return;
      workflow.distribution.approved = true;
      workflow.promptReady = false;
      workflow.promptsError = '';
      workflow.viewStage = workflow.boundary.approved ? 'generate' : 'boundary';
      markVisualConceptDirty();
      renderVisualConceptPage();
    }

    let visualConceptPlansPromptsPending = false;

    async function prepareVisualConceptPlansPrompts() {
      const initialWorkflow = visualConceptPlansWorkflowState();
      if (!initialWorkflow.verification.approved || !initialWorkflow.boundary.approved || !initialWorkflow.distribution.approved) return;
      if (visualConceptPlansPromptsPending) return;
      visualConceptPlansPromptsPending = true;
      initialWorkflow.promptsError = '';
      showLoader(WFT('plans.prompts_loading', 'جاري إعداد برومبتات المخططات'), WFT('plans.prompts_loading_detail', 'يتم بناء البرومبتات من البيانات المعتمدة وحدود الأرض...'), 50);
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        const response = await api('POST', '/api/visual-concept/plans-prompts', payload);
        hideLoader();
        const workflow = visualConceptPlansWorkflowState();
        if (!response?.success || !response.prompts) {
          workflow.promptsError = String(response?.error || WFT('plans.prompts_failed', 'تعذر إعداد برومبتات المخططات'));
          markVisualConceptDirty();
          renderVisualConceptPage();
          toast(workflow.promptsError);
          return;
        }
        workflow.prompts = { ...workflow.prompts, ...response.prompts };
        workflow.promptReady = VISUAL_CONCEPT_PLAN_KINDS.every(item => Boolean(workflow.prompts[item.kind]));
        workflow.promptsError = workflow.promptReady ? '' : WFT('plans.prompts_incomplete', 'برومبتات المخططات الثلاثة غير مكتملة');
        workflow.status = workflow.promptReady ? 'ready' : 'boundary';
        VISUAL_CONCEPT_PLAN_KINDS.forEach(definition => {
          const slot = tenantVisualConceptState.slots[definition.id] || (tenantVisualConceptState.slots[definition.id] = emptyVisualConceptSlot(definition.id));
          slot.label = definition.label;
          slot.prompt = workflow.prompts[definition.kind] || slot.prompt;
          slot.caption = definition.label;
          slot.status = slot.imageUrl ? 'review' : 'pending';
        });
        markVisualConceptDirty();
        renderVisualConceptPage();
      } catch (error) {
        hideLoader();
        const workflow = visualConceptPlansWorkflowState();
        workflow.promptsError = String(error.message || WFT('plans.prompts_failed', 'تعذر إعداد برومبتات المخططات'));
        markVisualConceptDirty();
        renderVisualConceptPage();
        toast(workflow.promptsError);
      } finally {
        visualConceptPlansPromptsPending = false;
      }
    }

    function addVisualConceptPlan() {
      if (visualConceptPlans().length >= VISUAL_CONCEPT_MAX_PLANS) {
        toast('تم الوصول إلى الحد الأقصى للمخططات');
        return;
      }
      tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState);
      const id = 'plan_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
      visualConceptPlans().push({ id, mode: 'ai', title: '', description: '', fileId: '', fileName: '', imageUrl: '' });
      tenantVisualConceptState.slots[id] = emptyVisualConceptSlot(id);
      markVisualConceptDirty();
      setVisualConceptPlansTab('generate');
      renderVisualConceptPage();
    }

    async function uploadVisualConceptPlanImages(input) {
      const files = Array.from(input?.files || []);
      if (!files.length) return;
      const plans = visualConceptPlans();
      const uploadedPlans = plans.filter(plan => !isVisualConceptWorkflowPlan(plan.id));
      const remaining = Math.max(0, VISUAL_CONCEPT_MAX_PLANS - uploadedPlans.length);
      if (!remaining) {
        toast('تم الوصول إلى الحد الأقصى للمخططات');
        input.value = '';
        return;
      }
      showLoader('جاري رفع المخططات', 'يتم حفظ ' + Math.min(files.length, remaining) + ' مخطط...');
      input.disabled = true;
      try {
        input.dataset.projectFileType = 'visual_reference';
        const uploaded = await uploadTenantProjectFileInput(input, 'visual_plan_2d');
        const incoming = (Array.isArray(uploaded) ? uploaded : [uploaded]).map((file, index) => ({
          id: file?.id || file,
          name: file?.originalName || files[index]?.name || ''
        })).filter(file => file.id).slice(0, remaining);
        if (!incoming.length) throw new Error('تعذر رفع المخططات');
        for (const file of incoming) {
          if (plans.some(plan => plan.fileId === String(file.id))) continue;
          plans.push({
            id: 'plan_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8),
            mode: 'upload',
            title: '',
            description: '',
            fileId: String(file.id),
            fileName: file.name,
            imageUrl: await publishProjectFileImageUrl(file.id)
          });
        }
        markVisualConceptDirty();
        renderVisualConceptPage();
        toast('تم رفع ' + incoming.length + ' مخطط.');
      } catch (error) {
        toast(error.message || 'تعذر رفع المخططات');
      } finally {
        hideLoader();
        if (input) {
          input.disabled = false;
          input.value = '';
          delete input.dataset.uploadSignatures;
        }
      }
    }

    function deleteVisualConceptPlan(planId) {
      if (isVisualConceptWorkflowPlan(planId)) return;
      const plans = visualConceptPlans();
      const index = plans.findIndex(item => item.id === planId);
      if (index < 0) return;
      plans.splice(index, 1);
      if (tenantVisualConceptState.slots) delete tenantVisualConceptState.slots[planId];
      markVisualConceptDirty();
      renderVisualConceptPage();
      toast('تم حذف المخطط');
    }

    function updateVisualConceptHomeCards() {
      const cover = tenantVisualConceptState?.slots?.cover || {};
      const stored = cover.approvedImageUrl || cover.imageUrl || tenantCreativeImages?.cover || '';
      const image = isSessionOnlyImageUrl(stored) ? '' : stored;
      const preview = document.getElementById('visualConceptHomeCoverPreview');
      const externalStatus = document.getElementById('visualConceptHomeExternalStatus');
      const internalStatus = document.getElementById('visualConceptHomeInternalStatus');
      const externalCard = document.querySelector('.visual-concept-home-card[data-visual-concept-target="external"]');
      if (preview) {
        if (image) {
          preview.src = image;
          preview.hidden = false;
        } else {
          preview.removeAttribute('src');
          preview.hidden = true;
        }
      }
      if (externalCard) externalCard.classList.toggle('has-preview', !!image);
      if (externalStatus) {
        externalStatus.textContent = cover.status === 'approved'
          ? 'معتمدة'
          : (image ? 'تم التوليد — تحتاج اعتماد' : 'جاهز للعمل');
      }
      if (internalStatus) {
        internalStatus.textContent = cover.approvedImageUrl
          ? (visualConceptInteriorComponents().length ? 'جاهز للعمل' : 'أضف مكونات الدراسة المالية')
          : 'مقفل حتى اعتماد الصورة الرئيسية';
      }
      const plansStatus = document.getElementById('visualConceptHomePlansStatus');
      if (plansStatus) {
        const plans = visualConceptPlans();
        plansStatus.textContent = plans.length ? plans.length + ' مخطط' : 'لا توجد مخططات';
      }
    }