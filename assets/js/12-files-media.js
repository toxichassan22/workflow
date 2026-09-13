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
        host.innerHTML = '<div class="tenant-hint">لم يتم حفظ ملفات على السيرفر بعد. اختر ملف الرخصة وملف الكروكي.</div>';
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
      const chosen = Array.from(input?.files || []).slice(0, 2);
      if (!chosen.length) return;
      renderLandDocumentsUploadState(chosen.map(file => ({
        originalName: file.name, fileSize: file.size, status: 'pending'
      })));
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
      toast(meta.length ? 'تم حذف الملف من هذا المشروع' : 'تم حذف الملفات — ارفع الرخصة والكروكي من جديد');
    }

    async function uploadTenantProjectFileInput(input, key) {
      // The client decides how many 2D plans a project has, so that key is not capped at 2.
      const multiLimit = key === 'land_photos' ? LAND_PHOTOS_MAX
        : (key === 'visual_style_reference' ? 5
          : (key === 'visual_plan_2d' ? VISUAL_CONCEPT_MAX_PLANS : 2));
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
      for (const file of files) {
        const signature = [file.name, file.size, file.lastModified, fileType].join(':');
        const cachedId = input.multiple ? multiCache[signature] : input.dataset.projectFileId;
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
      const ids = uploaded.map(file => file.id);
      if (input.multiple) {
        // Re-uploads return fresh metadata, so any caption already typed has to be carried over.
        const previousMeta = Array.isArray(tenantProjectData[key + '_file_meta'])
          ? tenantProjectData[key + '_file_meta'] : [];
        const merged = uploaded.map(file => {
          const previous = previousMeta.find(item => item && item.id === file.id);
          return previous?.description ? { ...file, description: previous.description } : file;
        });
        tenantProjectData[key + '_file_ids'] = ids;
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
      await saveProjectAsDraftNow(true, false);

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

      // Persist the project snapshot used to create this presentation without carrying the
      // conversation from the previous presentation.
      resetDesignerChatForNewPresentation();
      await api('POST', '/api/project-draft', { draftData: tenantProjectData, sectionStatuses: tenantProjectSectionStatuses, status: 'submitted' });

      // Navigate to the presentation page with the stage empty. Rendering the file's saved slides
      // here showed the previous deck for the whole planning wait, so the reader watched an old
      // presentation while a new one was being built.
      showTenantPage('tenantSlidesPage');
      clearTenantSlidesStage('جاري إعداد خطة وهيكل العرض');
      setSlidesEditorInfo(tenantProjectData.project_name || tenantProjectData.projectName || '', 0);

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
        const errorMessage = planResponse.error || 'تعذر إعداد خطة الشرائح';
        setLiveGenBanner(true, 'تعذر إعداد الخطة', errorMessage, 5);
        console.error('[SLIDE PLAN]', planResponse);
        toast(errorMessage);
        renderTenantSlides();
        return;
      }

      await generateTenantSlides();
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
        || (isVisualConceptInteriorSlot(slotId) ? 'التصور الداخلي' : 'الصورة');
    }

    function visualConceptCanRenameSlot(slotId) {
      return VISUAL_CONCEPT_EXTERNAL_SLOTS.slice(1).some(item => item.id === slotId);
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

    // The 2D plans are client uploads only: every plan carries the client's own title and
    // description, and AI generation for them is not built yet.
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
        while (seen.has(id)) id = id + '_' + (index + 1);
        seen.add(id);
        return {
          id,
          title: String(source.title || '').slice(0, 120),
          description: String(source.description || '').slice(0, 2000),
          fileId: String(source.fileId || source.file_id || ''),
          fileName: String(source.fileName || source.file_name || ''),
          imageUrl: durableImageUrl(source.imageUrl || source.image_url)
        };
      }).filter(item => item.fileId || item.imageUrl).slice(0, VISUAL_CONCEPT_MAX_PLANS);
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
      Object.keys(source.slots && typeof source.slots === 'object' ? source.slots : {}).forEach(id => {
        if (isVisualConceptInteriorSlot(id) && !deletedInteriorSlots.has(id)) slotIds.add(id);
      });
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
        const slot = visualConceptSlotSource(source.slots, sourceId) || visualConceptSlotSource(source.slots, id) || emptyVisualConceptSlot(id);
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
          : []
      };
    }

    function visualConceptSlotLocked(slotId) {
      if (isVisualConceptInteriorSlot(slotId)) {
        return !tenantVisualConceptState.slots.cover.approvedImageUrl || !visualConceptInteriorComponents().length;
      }
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

      const modeSelector = '<div class="visual-concept-mode-selector">' +
        '<button type="button" class="visual-concept-mode-btn' + (mode === 'ai' ? ' active' : '') + '" data-visual-action="set-mode" data-visual-mode="ai" data-visual-slot="' + slotDef.id + '" ' + (disableAiSwitch ? 'disabled title="احذف الصورة الحالية أولاً لتغيير النمط"' : '') + '>توليد بالذكاء الاصطناعي</button>' +
        '<button type="button" class="visual-concept-mode-btn' + (mode === 'upload' ? ' active' : '') + '" data-visual-action="set-mode" data-visual-mode="upload" data-visual-slot="' + slotDef.id + '" ' + (disableUploadSwitch ? 'disabled title="احذف الصورة الحالية أولاً لتغيير النمط"' : '') + '>رفع يدوي</button>' +
        '</div>';

      const deleteBtn = hasImage
        ? '<button type="button" class="btn danger small" data-visual-action="delete-image" data-visual-slot="' + slotDef.id + '" ' + (frozen ? 'disabled' : '') + '>حذف الصورة</button>'
        : '';
      const deleteFieldBtn = isVisualConceptInteriorSlot(slotDef.id)
        ? '<button type="button" class="btn danger small" data-visual-action="delete-interior-field" data-visual-slot="' + slotDef.id + '">حذف الحقل</button>'
        : '';

      let bodyControls = '';
      if (mode === 'upload') {
        bodyControls = '<div class="visual-concept-upload-box">' +
          '<label class="visual-concept-upload-label">اختر ملف الصورة من جهازك</label>' +
          '<input type="file" accept="' + uploadAccept + '" data-visual-upload="' + slotDef.id + '" ' + (frozen ? 'disabled' : '') + '>' +
          (slot.sourceFileName ? '<div class="visual-concept-file-info">الملف الحالي: ' + escapeHtml(slot.sourceFileName) + '</div>' : '') +
          '</div>' +
          '<label>وصف الصورة</label>' +
          '<textarea data-visual-caption="' + slotDef.id + '" rows="3" ' + (frozen ? 'disabled' : '') + '>' + escapeHtml(slot.caption || '') + '</textarea>' +
          '<div class="visual-concept-actions">' +
          '<button type="button" class="btn ' + (approved ? 'ghost' : 'primary') + ' small" data-visual-action="' + (approved ? 'unapprove' : 'approve') + '" data-visual-slot="' + slotDef.id + '" ' + ((!image && !approved) ? 'disabled' : '') + '>' + (approved ? 'الغاء الاعتماد' : 'اعتماد') + '</button>' +
          deleteBtn + deleteFieldBtn +
          '</div>';
      } else {
        bodyControls = '<label>وصف التوليد</label>' +
          '<textarea class="visual-concept-prompt" data-visual-prompt="' + slotDef.id + '" ' + (frozen ? 'disabled' : '') + ' dir="ltr">' + escapeHtml(slot.prompt || '') + '</textarea>' +
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

      return '<article class="visual-concept-card' + (waitCover ? ' locked' : '') + (approved ? ' section-locked' : '') + '" data-visual-slot="' + slotDef.id + '">' +
        '<div class="visual-concept-head">' + heading +
        '<span class="visual-concept-status ' + slot.status + '">' + statusLabel + '</span></div>' +
        modeSelector +
        preview +
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
      return value.split('?')[0] + '?t=' + Date.now();
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

    function renderVisualConceptPlans() {
      const host = document.getElementById('visualConceptPlansWorkspace');
      const count = document.getElementById('visualConceptPlansCount');
      const input = document.getElementById('visualConceptPlansUploadInput');
      const plans = visualConceptPlans();
      if (count) count.textContent = plans.length ? plans.length + ' مخطط' : 'لا توجد مخططات مرفوعة';
      if (input) input.disabled = plans.length >= VISUAL_CONCEPT_MAX_PLANS;
      if (!host) return;
      if (!plans.length) {
        host.innerHTML = '<p class="tenant-hint">لا توجد مخططات مرفوعة.</p>';
        return;
      }
      host.innerHTML = '<div class="visual-concept-stack">' + plans.map((plan, index) => {
        const title = plan.title || plan.fileName || ('مخطط ' + (index + 1));
        if (isSessionOnlyImageUrl(plan.imageUrl)) plan.imageUrl = '';
        const image = plan.imageUrl
          ? '<div class="visual-concept-preview has-image" data-visual-zoom="' + escapeHtml(plan.imageUrl) + '" data-visual-title="' + escapeHtml(title) + '">' +
          '<img src="' + escapeHtml(plan.imageUrl) + '" alt="' + escapeHtml(title) + '">' +
          '<button type="button" class="visual-concept-zoom-btn" data-visual-zoom="' + escapeHtml(plan.imageUrl) + '" data-visual-title="' + escapeHtml(title) + '">تكبير</button>' +
          '</div>'
          : '<div class="visual-concept-preview empty" data-visual-plan-thumb="' + escapeHtml(plan.id) + '"></div>';
        return '<article class="visual-concept-card" data-visual-plan="' + escapeHtml(plan.id) + '">' +
          '<div class="visual-concept-head">' +
          '<h3>' + escapeHtml('مخطط ' + (index + 1)) + '</h3>' +
          (plan.fileName ? '<span class="visual-concept-status pending">' + escapeHtml(plan.fileName) + '</span>' : '') +
          '</div>' +
          image +
          '<label>عنوان المخطط</label>' +
          '<input type="text" data-visual-plan-title="' + escapeHtml(plan.id) + '" value="' + escapeHtml(plan.title || '') + '">' +
          '<label>وصف المخطط</label>' +
          '<textarea data-visual-plan-description="' + escapeHtml(plan.id) + '" rows="3">' + escapeHtml(plan.description || '') + '</textarea>' +
          '<div class="visual-concept-actions">' +
          '<button type="button" class="btn danger small" data-visual-plan-action="delete" data-visual-plan-id="' + escapeHtml(plan.id) + '">حذف المخطط</button>' +
          '</div>' +
          '</article>';
      }).join('') + '</div>';
      plans.forEach(plan => {
        if (plan.imageUrl || !plan.fileId) return;
        const box = host.querySelector('[data-visual-plan-thumb="' + plan.id.replace(/"/g, '\\"') + '"]');
        if (!box) return;
        const img = document.createElement('img');
        img.alt = plan.title || plan.fileName || 'مخطط';
        box.textContent = '';
        box.appendChild(img);
        attachProjectFileThumbnail(img, plan.fileId);
      });
      host.querySelectorAll('[data-visual-plan-title]').forEach(field => {
        field.addEventListener('input', () => {
          const plan = visualConceptPlans().find(item => item.id === field.getAttribute('data-visual-plan-title'));
          if (!plan) return;
          plan.title = String(field.value || '').slice(0, 120);
          markVisualConceptDirty();
        });
      });
      host.querySelectorAll('[data-visual-plan-description]').forEach(field => {
        field.addEventListener('input', () => {
          const plan = visualConceptPlans().find(item => item.id === field.getAttribute('data-visual-plan-description'));
          if (!plan) return;
          plan.description = String(field.value || '').slice(0, 2000);
          markVisualConceptDirty();
        });
      });
      host.querySelectorAll('[data-visual-plan-action="delete"]').forEach(button => {
        button.addEventListener('click', () => deleteVisualConceptPlan(button.getAttribute('data-visual-plan-id')));
      });
      host.querySelectorAll('[data-visual-zoom]').forEach(el => {
        el.addEventListener('click', (e) => {
          if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
          const url = el.getAttribute('data-visual-zoom');
          if (url) openVisualConceptLightbox(url, el.getAttribute('data-visual-title'));
        });
      });
    }

    async function uploadVisualConceptPlanImages(input) {
      const files = Array.from(input?.files || []);
      if (!files.length) return;
      const plans = visualConceptPlans();
      const remaining = Math.max(0, VISUAL_CONCEPT_MAX_PLANS - plans.length);
      if (!remaining) {
        toast('تم الوصول إلى الحد الأقصى للمخططات');
        input.value = '';
        return;
      }
      showLoader('جاري رفع المخططات 2D', 'يتم حفظ ' + Math.min(files.length, remaining) + ' مخطط...');
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
            title: '',
            description: '',
            fileId: String(file.id),
            fileName: file.name,
            imageUrl: await publishProjectFileImageUrl(file.id)
          });
        }
        markVisualConceptDirty();
        renderVisualConceptPlans();
        updateVisualConceptHomeCards();
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
      const plans = visualConceptPlans();
      const index = plans.findIndex(item => item.id === planId);
      if (index < 0) return;
      plans.splice(index, 1);
      markVisualConceptDirty();
      renderVisualConceptPlans();
      updateVisualConceptHomeCards();
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
        plansStatus.textContent = plans.length ? plans.length + ' مخطط مرفوع' : 'لا توجد مخططات مرفوعة';
      }
    }