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
              jobId: window.currentGenerationJobId || undefined,
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

