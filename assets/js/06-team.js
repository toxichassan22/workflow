/* 06-team.js - index.html lines 12628-13567, shared global scope, classic scripts in order */

    async function renderProjectTeam() {
      const libraryHost = document.getElementById('projectTeamLibrary');
      const localHost = document.getElementById('projectTeamLocal');
      if (!libraryHost || !localHost) return;
      if (!tenantTeamEntities.length) await loadTenantTeamEntities().catch(() => []);
      const state = getProjectTeamState();

      libraryHost.innerHTML = tenantTeamEntities.length
        ? '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px">' +
        tenantTeamEntities.map(entity => {
          const excluded = state.excluded.includes(String(entity.id));
          const role = state.roles[entity.id] ?? entity.role ?? '';
          const safeId = String(entity.id).replace(/'/g, "\\'");
          return '<div style="border:1px solid var(--line);border-radius:12px;padding:12px;background:' +
            (excluded ? '#f7f7f8' : '#fff') + ';opacity:' + (excluded ? '.6' : '1') + '">' +
            '<div style="display:flex;gap:10px;align-items:center">' +
            (entity.logoFileId
              ? '<img data-team-logo="' + escapeHtml(entity.logoFileId) + '" alt="" style="width:46px;height:46px;object-fit:contain;border-radius:9px;background:#f6f7f9;flex:none">'
              : teamMonogramHtml(entity.name, 46)) +
            '<div style="flex:1;min-width:0"><strong style="word-break:break-word">' + escapeHtml(entity.name) + '</strong>' +
            '</div></div>' +
            '<label style="display:block;font-size:.8rem;margin-top:8px">دور الجهة في هذا المشروع</label>' +
            '<input type="text" value="' + escapeHtml(role) + '" ' + (excluded ? 'disabled ' : '') +
            'placeholder="' + escapeHtml(entity.role || 'دور الجهة') + '" style="width:100%" ' +
            'onchange="setProjectTeamRole(\'' + safeId + '\', this.value)">' +
            '<button type="button" class="btn ghost' + (excluded ? '' : ' danger') +
            '" style="width:100%;margin-top:8px;padding:5px 8px;font-size:.78rem" ' +
            'onclick="toggleTeamEntityInFile(\'' + safeId + '\')">' +
            (excluded ? 'إعادة الجهة إلى هذا الملف' : 'استبعاد من هذا الملف') + '</button></div>';
        }).join('') + '</div>'
        : '<p class="tenant-hint">لا توجد جهات في إعدادات الشركة.</p>';

      const localCards = state.local.map(entity =>
        projectLocalTeamDraft && String(entity.localId) === String(editingProjectLocalTeamId)
          ? renderProjectLocalTeamForm(projectLocalTeamDraft)
          : renderProjectLocalTeamCard(entity));
      if (projectLocalTeamDraft && !state.local.some(entity =>
        String(entity.localId) === String(editingProjectLocalTeamId))) {
        localCards.push(renderProjectLocalTeamForm(projectLocalTeamDraft));
      }
      localHost.innerHTML = localCards.length
        ? '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px">' +
        localCards.join('') + '</div>'
        : '';
      // Without any project-only entity the heading would sit above nothing but the add button.
      const localTitle = document.getElementById('projectTeamLocalTitle');
      if (localTitle) localTitle.hidden = !(state.local.length || projectLocalTeamDraft);

      document.querySelectorAll('#section-team img[data-team-logo]').forEach(image => {
        attachProjectFileThumbnail(image, image.dataset.teamLogo);
      });
    }

    function renderProjectLocalTeamForm(entity) {
      const safeId = String(entity.localId).replace(/'/g, "\\'");
      const field = (key, label, type) =>
        '<label style="display:block;font-size:.78rem;margin-top:7px">' + label + '</label>' +
        (type === 'textarea'
          ? '<textarea rows="2" style="width:100%" onchange="updateLocalTeamEntity(\'' + safeId + '\',\'' + key + '\',this.value)">' + escapeHtml(entity[key] || '') + '</textarea>'
          : '<input type="' + type + '" value="' + escapeHtml(entity[key] || '') + '" style="width:100%" onchange="updateLocalTeamEntity(\'' + safeId + '\',\'' + key + '\',this.value)">');
      return '<div style="border:1px solid var(--line);border-radius:12px;padding:12px;background:#fff">' +
        '<div style="display:flex;gap:10px;align-items:center;margin-bottom:4px">' +
        (entity.logoFileId
          ? '<img data-team-logo="' + escapeHtml(entity.logoFileId) + '" alt="" style="width:46px;height:46px;object-fit:contain;border-radius:9px;background:#f6f7f9;flex:none">'
          : teamMonogramHtml(entity.name, 46)) +
        '<strong style="flex:1;word-break:break-word">' +
        escapeHtml(entity.name || 'جهة جديدة') + '</strong></div>' +
        field('name', 'اسم الجهة', 'text') +
        field('experienceYears', 'سنوات الخبرة', 'number') +
        field('role', 'دور الجهة في المشروع', 'text') +
        field('brief', 'نبذة عن الجهة', 'textarea') +
        field('notableProjects', 'أبرز المشاريع', 'textarea') +
        '<label style="display:block;font-size:.78rem;margin-top:7px">شعار الجهة</label>' +
        '<input type="file" accept="image/*,.jpg,.jpeg,.png,.webp" style="width:100%" ' +
        'onchange="uploadLocalTeamLogo(\'' + safeId + '\', this)">' +
        '<div style="display:flex;gap:8px;margin-top:10px">' +
        '<button type="button" class="btn primary" style="flex:1;padding:5px 8px;font-size:.78rem" ' +
        'onclick="saveLocalTeamEntity(\'' + safeId + '\')">حفظ</button>' +
        '<button type="button" class="btn ghost" style="flex:1;padding:5px 8px;font-size:.78rem" ' +
        'onclick="cancelLocalTeamEntity(\'' + safeId + '\')">إلغاء</button></div></div>';
    }

    function renderProjectLocalTeamCard(entity) {
      const safeId = String(entity.localId).replace(/'/g, "\\'");
      return '<div style="border:1px solid var(--line);border-radius:12px;padding:12px;background:#fff">' +
        '<div style="display:flex;gap:10px;align-items:center">' +
        (entity.logoFileId
          ? '<img data-team-logo="' + escapeHtml(entity.logoFileId) + '" alt="" style="width:46px;height:46px;object-fit:contain;border-radius:9px;background:#f6f7f9;flex:none">'
          : teamMonogramHtml(entity.name, 46)) +
        '<strong style="flex:1;word-break:break-word">' + escapeHtml(entity.name || 'جهة جديدة') + '</strong></div>' +
        '<label style="display:block;font-size:.8rem;margin-top:8px">دور الجهة في المشروع</label>' +
        '<input type="text" value="' + escapeHtml(entity.role || '') + '" placeholder="دور الجهة" style="width:100%" ' +
        'onchange="updateLocalTeamEntity(\'' + safeId + '\',\'role\',this.value)">' +
        '<div style="display:flex;gap:8px;margin-top:8px">' +
        '<button type="button" class="btn ghost" style="flex:1;padding:5px 8px;font-size:.78rem" ' +
        'onclick="editLocalTeamEntity(\'' + safeId + '\')">تعديل</button>' +
        '<button type="button" class="btn ghost danger" style="flex:1;padding:5px 8px;font-size:.78rem" ' +
        'onclick="removeLocalTeamEntity(\'' + safeId + '\')">حذف</button></div></div>';
    }

    function updateLocalTeamEntity(localId, key, value) {
      if (projectLocalTeamDraft && String(projectLocalTeamDraft.localId) === String(localId)) {
        projectLocalTeamDraft[key] = String(value || '').trim();
        return;
      }
      const state = getProjectTeamState();
      const entity = state.local.find(item => String(item.localId) === String(localId));
      if (!entity) return;
      entity[key] = String(value || '').trim();
      setProjectTeamState(state);
    }

    async function uploadLocalTeamLogo(localId, input) {
      const file = input?.files?.[0];
      if (!file) return;
      try {
        const formData = new FormData();
        formData.append('file', file, file.name);
        formData.append('fileType', 'team_logo');
        if (tenantProjectData?.draftId) formData.append('draftId', tenantProjectData.draftId);
        const response = await api('POST', '/api/project-files', formData, true);
        if (!response?.success || !response.file?.id) throw new Error(response?.error || 'تعذر رفع الشعار');
        if (projectLocalTeamDraft && String(projectLocalTeamDraft.localId) === String(localId)) {
          projectLocalTeamDraft.logoFileId = response.file.id;
        } else {
          updateLocalTeamEntity(localId, 'logoFileId', response.file.id);
        }
        renderProjectTeam();
      } catch (error) {
        toast(error.message || 'تعذر رفع شعار الجهة');
      }
    }

    function toggleTeamEntityInFile(entityId) {
      const state = getProjectTeamState();
      const id = String(entityId);
      state.excluded = state.excluded.includes(id)
        ? state.excluded.filter(item => item !== id)
        : state.excluded.concat(id);
      setProjectTeamState(state);
      renderProjectTeam();
    }

    function setProjectTeamRole(entityId, role) {
      const state = getProjectTeamState();
      const value = String(role || '').trim();
      if (value) state.roles[entityId] = value;
      else delete state.roles[entityId];
      setProjectTeamState(state);
    }

    function addLocalTeamEntity() {
      if (projectLocalTeamDraft) {
        toast('احفظ المطور الحالي أولاً');
        return;
      }
      editingProjectLocalTeamId = 'local-' + crypto.randomUUID();
      projectLocalTeamDraft = {
        localId: editingProjectLocalTeamId,
        name: '',
        logoFileId: '',
        brief: '',
        experienceYears: '',
        notableProjects: '',
        role: '',
      };
      renderProjectTeam();
    }

    function saveLocalTeamEntity(localId) {
      if (!projectLocalTeamDraft || String(projectLocalTeamDraft.localId) !== String(localId)) return;
      const draft = { ...projectLocalTeamDraft };
      ['name', 'experienceYears', 'role', 'brief', 'notableProjects'].forEach(key => {
        draft[key] = String(draft[key] || '').trim();
      });
      if (!draft.name) {
        toast('اسم الجهة مطلوب');
        return;
      }
      const state = getProjectTeamState();
      const existingIndex = state.local.findIndex(entity => String(entity.localId) === String(localId));
      if (existingIndex >= 0) state.local[existingIndex] = draft;
      else state.local = state.local.concat(draft);
      setProjectTeamState(state);
      editingProjectLocalTeamId = null;
      projectLocalTeamDraft = null;
      renderProjectTeam();
    }

    function editLocalTeamEntity(localId) {
      if (projectLocalTeamDraft) {
        toast('احفظ المطور الحالي أولاً');
        return;
      }
      const entity = getProjectTeamState().local.find(item => String(item.localId) === String(localId));
      if (!entity) return;
      editingProjectLocalTeamId = String(localId);
      projectLocalTeamDraft = { ...entity };
      renderProjectTeam();
    }

    function cancelLocalTeamEntity(localId) {
      if (!projectLocalTeamDraft || String(projectLocalTeamDraft.localId) !== String(localId)) return;
      editingProjectLocalTeamId = null;
      projectLocalTeamDraft = null;
      renderProjectTeam();
    }

    function removeLocalTeamEntity(localId) {
      const state = getProjectTeamState();
      state.local = state.local.filter(entity => String(entity.localId) !== String(localId));
      setProjectTeamState(state);
      if (projectLocalTeamDraft && String(projectLocalTeamDraft.localId) === String(localId)) {
        editingProjectLocalTeamId = null;
        projectLocalTeamDraft = null;
      }
      renderProjectTeam();
    }

    // ── Project team library (فريق العمل) ─────────────────────────────────────
    let tenantTeamEntities = [];
    let editingTeamEntityId = null;

    async function openTenantTeam() {
      showTenantPage('tenantTeamPage');
      resetTeamEntityForm();
      await loadTenantTeamEntities();
    }

    async function loadTenantTeamEntities() {
      const data = await api('GET', '/api/team-entities');
      tenantTeamEntities = data.success ? (data.entities || []) : [];
      renderTenantTeamList();
      return tenantTeamEntities;
    }

    function resetTeamEntityForm() {
      editingTeamEntityId = null;
      ['teamEntityName', 'teamEntityExperience', 'teamEntityBrief', 'teamEntityProjects'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
      });
      const logo = document.getElementById('teamEntityLogo');
      if (logo) logo.value = '';
      const saveBtn = document.getElementById('teamEntitySaveBtn');
      if (saveBtn) saveBtn.textContent = 'إضافة المطور';
      const cancelBtn = document.getElementById('teamEntityCancelBtn');
      if (cancelBtn) cancelBtn.style.display = 'none';
    }

    async function uploadTeamLogo() {
      const input = document.getElementById('teamEntityLogo');
      const file = input?.files?.[0];
      if (!file) return '';
      const formData = new FormData();
      formData.append('file', file, file.name);
      formData.append('fileType', 'team_logo');
      const response = await api('POST', '/api/project-files', formData, true);
      if (!response?.success || !response.file?.id) {
        throw new Error(response?.error || 'تعذر رفع شعار المطور');
      }
      return response.file.id;
    }

    async function submitTeamEntity() {
      const payload = {
        name: (document.getElementById('teamEntityName')?.value || '').trim(),
        experienceYears: (document.getElementById('teamEntityExperience')?.value || '').trim(),
        role: (tenantTeamEntities.find(item => item.id === editingTeamEntityId)?.role || '').trim(),
        brief: (document.getElementById('teamEntityBrief')?.value || '').trim(),
        notableProjects: (document.getElementById('teamEntityProjects')?.value || '').trim(),
      };
      if (!payload.name) { toast('اسم المطور مطلوب'); return; }

      showLoader('حفظ المطور', 'جاري الحفظ...', 20);
      try {
        const logoId = await uploadTeamLogo();
        if (logoId) payload.logoFileId = logoId;
        // Editing without picking a new logo keeps the stored one.
        if (!logoId && editingTeamEntityId) {
          const current = tenantTeamEntities.find(item => item.id === editingTeamEntityId);
          if (current?.logoFileId) payload.logoFileId = current.logoFileId;
        }
        const response = editingTeamEntityId
          ? await api('PUT', '/api/team-entities/' + encodeURIComponent(editingTeamEntityId), payload)
          : await api('POST', '/api/team-entities', payload);
        if (!response?.success) { toast(response?.error || 'تعذر حفظ المطور'); return; }
        toast(editingTeamEntityId ? 'تم تحديث المطور' : 'تم إضافة المطور');
        resetTeamEntityForm();
        await loadTenantTeamEntities();
      } catch (error) {
        toast(error.message || 'تعذر حفظ المطور');
      } finally {
        hideLoader();
      }
    }

    function editTeamEntity(entityId) {
      const entity = tenantTeamEntities.find(item => item.id === entityId);
      if (!entity) return;
      editingTeamEntityId = entityId;
      document.getElementById('teamEntityName').value = entity.name || '';
      document.getElementById('teamEntityExperience').value = entity.experienceYears || '';
      document.getElementById('teamEntityBrief').value = entity.brief || '';
      document.getElementById('teamEntityProjects').value = entity.notableProjects || '';
      document.getElementById('teamEntityLogo').value = '';
      document.getElementById('teamEntitySaveBtn').textContent = 'حفظ التعديل';
      document.getElementById('teamEntityCancelBtn').style.display = 'inline-block';
      document.getElementById('tenantTeamPage')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    async function deleteTeamEntity(entityId) {
      const entity = tenantTeamEntities.find(item => item.id === entityId);
      if (!confirm('حذف «' + (entity?.name || 'المطور') + '» من كل المشاريع؟')) return;
      const response = await api('DELETE', '/api/team-entities/' + encodeURIComponent(entityId));
      if (!response?.success) { toast(response?.error || 'تعذر حذف المطور'); return; }
      toast('تم حذف المطور');
      if (editingTeamEntityId === entityId) resetTeamEntityForm();
      await loadTenantTeamEntities();
    }

    function renderTenantTeamList() {
      const host = document.getElementById('tenantTeamList');
      if (!host) return;
      if (!tenantTeamEntities.length) {
        host.innerHTML = '<p class="tenant-hint">لا يوجد مطورون مسجّلون بعد.</p>';
        return;
      }
      host.innerHTML = '<h3 style="margin:18px 0 8px;color:var(--p);font-size:15px">المطورون المسجّلون</h3>' +
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px">' +
        tenantTeamEntities.map(entity => teamEntityCardHtml(entity, true, false)).join('') + '</div>';
      host.querySelectorAll('img[data-team-logo]').forEach(image => {
        attachProjectFileThumbnail(image, image.dataset.teamLogo);
      });
    }

    // Shared by the settings library and the in-project section.
    function teamEntityCardHtml(entity, withLibraryActions, showRole = true) {
      const safeId = String(entity.id || entity.localId || '').replace(/'/g, "\\'");
      const logo = entity.logoFileId
        ? '<img data-team-logo="' + escapeHtml(entity.logoFileId) + '" alt="' + escapeHtml(entity.name || '') +
        '" style="width:52px;height:52px;object-fit:contain;border-radius:10px;background:#f6f7f9;flex:none">'
        : teamMonogramHtml(entity.name, 52);
      const detail = (label, value) => value
        ? '<div style="font-size:.82rem;margin-top:5px"><strong>' + label + ':</strong> ' + escapeHtml(value) + '</div>'
        : '';
      return '<div style="border:1px solid var(--line);border-radius:12px;padding:12px;background:#fff">' +
        '<div style="display:flex;gap:10px;align-items:center">' + logo +
        '<div style="flex:1;min-width:0"><strong style="word-break:break-word">' + escapeHtml(entity.name || '') + '</strong>' +
        (showRole && entity.role ? '<div class="tenant-hint" style="margin:2px 0 0">' + escapeHtml(entity.role) + '</div>' : '') +
        '</div></div>' +
        detail('سنوات الخبرة', entity.experienceYears) +
        detail('نبذة', entity.brief) +
        detail('أبرز المشاريع', entity.notableProjects) +
        (withLibraryActions
          ? '<div style="display:flex;gap:6px;margin-top:10px">' +
          '<button type="button" class="btn ghost" style="flex:1;padding:5px 8px;font-size:.78rem" onclick="editTeamEntity(\'' + safeId + '\')">تعديل</button>' +
          '<button type="button" class="btn ghost danger" style="flex:1;padding:5px 8px;font-size:.78rem" onclick="deleteTeamEntity(\'' + safeId + '\')">حذف</button></div>'
          : '') +
        '</div>';
    }

    // Custom fields
    const TENANT_FIELDS_PAGE_WIP = true;

    async function openTenantFields() {
      showTenantPage('tenantFieldsPage');
      if (TENANT_FIELDS_PAGE_WIP) return;
      const sectionsData = await api('GET', '/api/field-sections');
      tenantFieldSections = sectionsData.available || [];
      tenantAllowedFieldSections = sectionsData.allowed || {};
      const sectionSelect = document.getElementById('newFieldSection');
      if (sectionSelect) {
        sectionSelect.innerHTML = tenantFieldSections.map(s => '<option value="' + s.key + '">' + escapeHtml(s.label) + '</option>').join('');
      }
      renderCustomSectionsList();
      await renderTenantFields();
    }

    function renderCustomSectionsList() {
      const container = document.getElementById('customSectionsList');
      if (!container) return;
      container.innerHTML = '';
      tenantFieldSections.forEach(s => {
        const isCustom = s.custom === true;
        const chip = document.createElement('div');
        chip.style.cssText = 'display:flex;align-items:center;gap:6px;background:#fff;border:1px solid var(--line);border-radius:10px;padding:6px 12px;font-size:13px';
        const label = document.createElement('span');
        label.textContent = s.label;
        chip.appendChild(label);
        if (isCustom) {
          const editButton = document.createElement('button');
          editButton.className = 'btn ghost';
          editButton.style.cssText = 'padding:2px 6px;font-size:11px';
          editButton.textContent = 'تعديل';
          editButton.addEventListener('click', () => renameCustomSection(s.key, s.label));
          const deleteButton = document.createElement('button');
          deleteButton.className = 'btn danger';
          deleteButton.style.cssText = 'padding:2px 6px;font-size:11px';
          deleteButton.textContent = 'حذف';
          deleteButton.addEventListener('click', () => deleteCustomSection(s.key, s.label));
          chip.append(editButton, deleteButton);
        } else {
          const fixedLabel = document.createElement('span');
          fixedLabel.style.cssText = 'font-size:10px;color:#999';
          fixedLabel.textContent = 'ثابت';
          chip.appendChild(fixedLabel);
        }
        container.appendChild(chip);
      });
    }

    async function addCustomSection() {
      const label = document.getElementById('newSectionLabel').value.trim();
      if (!label) { toast('اكتب اسم القسم'); return; }
      const data = await api('POST', '/api/field-sections/custom', { label });
      if (data.success) {
        toast('تم إضافة القسم: ' + label);
        document.getElementById('newSectionLabel').value = '';
        await openTenantFields();
      } else {
        toast(data.error || 'فشل إضافة القسم');
      }
    }

    async function renameCustomSection(key, currentLabel) {
      const label = prompt('اسم القسم:', currentLabel);
      if (label === null) return;
      const cleanLabel = label.trim();
      if (!cleanLabel) { toast('اكتب اسم القسم'); return; }
      if (cleanLabel === currentLabel) return;
      const data = await api('PUT', '/api/field-sections/custom/' + encodeURIComponent(key), { label: cleanLabel });
      if (data.success) {
        toast('تم تعديل اسم القسم');
        await openTenantFields();
      } else {
        toast(data.error || 'فشل تعديل القسم');
      }
    }

    async function deleteCustomSection(key, label) {
      if (!confirm('حذف قسم "' + label + '"؟ الحقول داخله ستنقل لقسم "عام".')) return;
      const data = await api('DELETE', '/api/field-sections/custom/' + encodeURIComponent(key));
      if (data.success) {
        toast('تم حذف القسم');
        await openTenantFields();
      } else {
        toast(data.error || 'فشل حذف القسم');
      }
    }

    async function renderTenantFields() {
      const data = await api('GET', '/api/fields?all=1');
      if (!data.success) { toast('تعذر تحميل الحقول'); return; }
      tenantFields = data.fields || [];
      const list = document.getElementById('tenantFieldsList');
      if (!list) return;
      if (!tenantFields.length) { list.innerHTML = '<p class="tenant-hint">لا توجد حقول</p>'; return; }
      const typeMap = { text: 'نص', textarea: 'نص طويل', number: 'رقم', select: 'قائمة', date: 'تاريخ', image: 'صورة' };
      const sectionMap = {};
      tenantFieldSections.forEach(s => { sectionMap[s.key] = s.label; });

      const groups = {};
      tenantFields.forEach(f => {
        const sec = sectionMap[f.sectionKey] || f.sectionKey || 'عام';
        if (!groups[sec]) groups[sec] = [];
        groups[sec].push(f);
      });

      list.innerHTML = Object.entries(groups).map(([section, fields]) => {
        return '<div style="margin-bottom: 24px;">' +
          '<h3 style="font-size: 15px; color: var(--p); margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid var(--line);">' + escapeHtml(section) + '</h3>' +
          '<div style="display: flex; flex-direction: column; gap: 8px;">' +
          fields.map(f => {
            const idx = tenantFields.findIndex(ff => ff.id === f.id);
            const statusBadge = f.isActive ? '<span style="color:#2e7d32;">مفعّل</span>' : '<span style="color:#999;">معطّل</span>';
            const fieldId = "'" + String(f.id).replace(/\\/g, '\\\\').replace(/'/g, "\\\\'") + "'";
            const controls = f.isCustom
              ? '<button class="btn small ghost" onclick="moveTenantField(' + idx + ', -1)">أعلى</button>' +
              '<button class="btn small ghost" onclick="moveTenantField(' + idx + ', 1)">أسفل</button>' +
              '<button class="btn small ghost" onclick="beginEditTenantField(' + fieldId + ')">تعديل</button>' +
              '<button class="btn small ' + (f.isActive ? 'green' : 'ghost') + '" onclick="toggleTenantField(' + fieldId + ')">' + (f.isActive ? 'تعطيل' : 'تفعيل') + '</button>' +
              '<button class="btn small danger" onclick="deleteTenantField(' + fieldId + ')">حذف</button>'
              : '<span class="tenant-hint" style="white-space:nowrap">حقل ثابت</span>';
            return '<div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px; background: #fafafa; border: 1px solid var(--line); border-radius: 10px;">' +
              '<div style="flex: 1; min-width: 0;">' +
              '<div style="font-weight: 600; margin-bottom: 2px;">' + escapeHtml(f.fieldLabel) + '</div>' +
              '<div class="meta" style="font-size: 12px;">' + escapeHtml(f.fieldKey) + ' | <span>' + (typeMap[f.fieldType] || f.fieldType) + '</span> | <span>' + (f.isCustom ? 'مخصص' : 'جاهز') + '</span> | ' + statusBadge + '</div>' +
              '</div>' +
              '<div style="display: flex; gap: 4px; align-items: center;">' +
              controls +
              '</div>' +
              '</div>';
          }).join('') +
          '</div>' +
          '</div>';
      }).join('');
    }



    function onNewFieldTypeChange() {
      const type = document.getElementById('newFieldType').value;
      const wrap = document.getElementById('newFieldOptionsWrap');
      if (wrap) wrap.style.display = (type === 'select') ? 'block' : 'none';
    }

    function toggleNewFieldAdvanced() {
      const adv = document.getElementById('newFieldAdvanced');
      if (!adv) return;
      adv.style.display = adv.style.display === 'none' ? 'grid' : 'none';
    }

    function clearNewFieldForm() {
      editingTenantFieldId = null;
      document.getElementById('newFieldKey').value = '';
      document.getElementById('newFieldLabel').value = '';
      document.getElementById('newFieldType').value = 'text';
      document.getElementById('newFieldOptions').value = '';
      const sectionSelect = document.getElementById('newFieldSection');
      if (sectionSelect && sectionSelect.options.length) sectionSelect.selectedIndex = 0;
      document.getElementById('newFieldPlaceholder').value = '';
      document.getElementById('newFieldDefault').value = '';
      document.getElementById('newFieldRequired').checked = false;
      onNewFieldTypeChange();
      document.getElementById('newFieldAdvanced').style.display = 'none';
      document.getElementById('tenantFieldFormTitle').textContent = 'إضافة حقل جديد يدوياً';
      document.getElementById('tenantFieldFormHint').textContent = 'أنشئ قسماً مخصصاً أولاً عند الحاجة، ثم أضف داخله الحقول التي تريدها.';
      document.getElementById('tenantFieldFormSubmit').textContent = 'إضافة الحقل';
      document.getElementById('tenantFieldEditCancel').style.display = 'none';
    }

    function beginEditTenantField(fieldId) {
      const field = tenantFields.find(f => String(f.id) === String(fieldId));
      if (!field || !field.isCustom) {
        toast('يمكن تعديل الحقول المخصصة فقط');
        return;
      }
      editingTenantFieldId = field.id;
      document.getElementById('newFieldKey').value = field.fieldKey || '';
      document.getElementById('newFieldLabel').value = field.fieldLabel || '';
      document.getElementById('newFieldType').value = field.fieldType || 'text';
      document.getElementById('newFieldOptions').value = Array.isArray(field.fieldOptions) ? field.fieldOptions.join('، ') : '';
      const sectionSelect = document.getElementById('newFieldSection');
      if (sectionSelect && Array.from(sectionSelect.options).some(option => option.value === field.sectionKey)) {
        sectionSelect.value = field.sectionKey;
      }
      document.getElementById('newFieldPlaceholder').value = field.placeholder || '';
      document.getElementById('newFieldDefault').value = field.defaultValue || '';
      document.getElementById('newFieldRequired').checked = Boolean(field.isRequired);
      onNewFieldTypeChange();
      document.getElementById('newFieldAdvanced').style.display = 'grid';
      document.getElementById('tenantFieldFormTitle').textContent = 'تعديل حقل مخصص';
      document.getElementById('tenantFieldFormHint').textContent = 'عدّل بيانات الحقل المخصص ثم احفظ التغييرات.';
      document.getElementById('tenantFieldFormSubmit').textContent = 'حفظ التعديل';
      document.getElementById('tenantFieldEditCancel').style.display = '';
      document.getElementById('tenantFieldEditor').scrollIntoView({ behavior: 'smooth', block: 'start' });
      document.getElementById('newFieldLabel').focus();
    }

    async function addTenantField() {
      const key = document.getElementById('newFieldKey').value.trim();
      const label = document.getElementById('newFieldLabel').value.trim();
      const type = document.getElementById('newFieldType').value;
      const sectionKey = document.getElementById('newFieldSection').value;
      const options = document.getElementById('newFieldOptions').value.split(/[,،]/).map(s => s.trim()).filter(Boolean);
      const placeholder = document.getElementById('newFieldPlaceholder').value.trim();
      const defaultValue = document.getElementById('newFieldDefault').value.trim();
      const isRequired = document.getElementById('newFieldRequired').checked;
      if (!label) { toast('اسم الحقل مطلوب'); return; }
      if (type === 'select' && !options.length) { toast('أضف خيار واحد على الأقل للقائمة المنسدلة'); return; }
      const isEditing = Boolean(editingTenantFieldId);
      const payload = {
        fieldKey: key,
        fieldLabel: label,
        fieldType: type,
        fieldOptions: type === 'select' ? options : null,
        sectionKey,
        placeholder,
        defaultValue,
        isRequired
      };
      const data = await api(isEditing ? 'PUT' : 'POST', isEditing ? '/api/fields/' + encodeURIComponent(editingTenantFieldId) : '/api/fields', payload);
      if (data.success) {
        toast(isEditing ? 'تم تعديل الحقل' : 'تم إضافة الحقل');
        clearNewFieldForm();
        await renderTenantFields();
      } else {
        toast(data.error || (isEditing ? 'فشل تعديل الحقل' : 'فشل إضافة الحقل'));
      }
    }

    async function moveTenantField(index, direction) {
      const movingField = tenantFields[index];
      if (!movingField || !movingField.isCustom) {
        toast('يمكن ترتيب الحقول المخصصة فقط');
        return;
      }
      let newIndex = index + direction;
      while (newIndex >= 0 && newIndex < tenantFields.length && !tenantFields[newIndex].isCustom) {
        newIndex += direction;
      }
      if (newIndex < 0 || newIndex >= tenantFields.length) return;
      const reordered = tenantFields.slice();
      const temp = reordered[index];
      reordered[index] = reordered[newIndex];
      reordered[newIndex] = temp;
      tenantFields = reordered;
      const fieldIds = reordered.map(f => f.id);
      const data = await api('PUT', '/api/fields/reorder', { fieldIds });
      if (!data.success) { toast(data.error || 'فشل ترتيب الحقول'); return; }
      await renderTenantFields();
    }

    async function toggleTenantField(fieldId) {
      const field = tenantFields.find(f => String(f.id) === String(fieldId));
      if (!field || !field.isCustom) {
        toast('يمكن تغيير حالة الحقول المخصصة فقط');
        return;
      }
      const data = await api('POST', '/api/fields/' + fieldId + '/toggle');
      if (data.success) {
        toast('تم تغيير الحالة');
        await renderTenantFields();
      } else {
        toast(data.error || 'فشل');
      }
    }

    async function deleteTenantField(fieldId) {
      const field = tenantFields.find(f => String(f.id) === String(fieldId));
      if (!field || !field.isCustom) {
        toast('لا يمكن حذف حقل ثابت');
        return;
      }
      if (!confirm('حذف هذا الحقل؟')) return;
      const data = await api('DELETE', '/api/fields/' + fieldId);
      if (data.success) {
        toast('تم الحذف');
        await renderTenantFields();
      } else {
        toast(data.error || 'فشل الحذف');
      }
    }

    // ── AI Input Builder ──
    let aiFieldSuggestions = [];

    function clearAiFieldBuilder() {
      document.getElementById('aiFieldDescription').value = '';
      document.getElementById('aiFieldSuggestions').style.display = 'none';
      document.getElementById('aiFieldSuggestionsList').innerHTML = '';
      aiFieldSuggestions = [];
    }

    async function aiAutoBuildFields() {
      const description = document.getElementById('aiFieldDescription').value.trim();
      if (!description) { toast('اكتب وصف المشروع أولاً'); return; }
      if (!confirm('سيقوم AI بإنشاء الحقول والأقسام مباشرة في قاعدة البيانات. متابعة؟')) return;

      const btn = document.getElementById('btnAiBuildFields');
      btn.disabled = true;
      btn.textContent = 'جاري البناء...';
      showLoader('AI يبني حقول المدخلات', 'قد يستغرق لحظات');

      const data = await api('POST', '/api/ai-build-fields', { description });
      hideLoader();
      btn.disabled = false;
      btn.textContent = 'بناء حقول تلقائياً (AI)';

      if (!data.success) {
        toast(data.error || 'فشل البناء التلقائي');
        return;
      }
      toast(`تم إنشاء ${data.count || 0} حقل تلقائياً`);
      await renderTenantFields();
      const sectionsData = await api('GET', '/api/field-sections');
      tenantFieldSections = sectionsData.available || [];
      clearAiFieldBuilder();
    }

    async function suggestAiFields() {
      const description = document.getElementById('aiFieldDescription').value.trim();
      if (!description) { toast('اكتب وصف المشروع أولاً'); return; }

      const existingKeys = (tenantFields || []).map(f => f.fieldKey);
      const btn = document.getElementById('btnAiSuggestFields');
      btn.disabled = true;
      btn.textContent = 'جاري التحليل...';
      showLoader('AI يحلل وصف المشروع', 'جاري اقتراح الحقول المناسبة');

      const data = await api('POST', '/api/ai-input-builder', { description, existingKeys });
      hideLoader();
      btn.disabled = false;
      btn.textContent = 'اقتراح حقول بالذكاء الاصطناعي';

      if (!data.success || !data.suggestions) {
        toast(data.error || 'فشل الاقتراح');
        return;
      }
      aiFieldSuggestions = (data.suggestions || []).map(s => ({ ...s, _approved: true }));
      renderAiFieldSuggestions();
      document.getElementById('aiFieldSuggestions').style.display = 'block';
    }

    function renderAiFieldSuggestions() {
      const list = document.getElementById('aiFieldSuggestionsList');
      if (!list) return;
      if (!aiFieldSuggestions.length) { list.innerHTML = '<p class="tenant-hint">لا توجد اقتراحات</p>'; return; }

      const typeMap = { text: 'نص', textarea: 'نص طويل', number: 'رقم', select: 'قائمة', date: 'تاريخ', image: 'صورة' };
      const sectionMap = {};
      tenantFieldSections.forEach(s => { sectionMap[s.key] = s.label; });

      list.innerHTML = aiFieldSuggestions.map((s, i) => {
        const optionsStr = s.fieldOptions ? s.fieldOptions.join('، ') : '';
        return '<div class="tenant-presentation-card" style="margin-bottom:8px;background:' + (s._approved ? '#e8f5e9' : '#ffebee') + '">' +
          '<div style="flex:1;min-width:220px">' +
          '<h4>' + escapeHtml(s.fieldLabel) + ' <code style="font-size:11px;color:#666">' + escapeHtml(s.fieldKey) + '</code></h4>' +
          '<div class="meta"><span>' + (typeMap[s.fieldType] || s.fieldType) + '</span> | <span>' + escapeHtml(sectionMap[s.sectionKey] || s.sectionKey) + '</span>' + (s.isRequired ? ' | <span>مطلوب</span>' : '') + '</div>' +
          (optionsStr ? '<div class="meta" style="margin-top:4px"><span>خيارات:</span> ' + escapeHtml(optionsStr) + '</div>' : '') +
          (s.reason ? '<div class="tenant-hint" style="margin-top:6px">' + escapeHtml(s.reason) + '</div>' : '') +
          '</div>' +
          '<div class="tenant-actions" style="gap:6px;align-items:center">' +
          '<button class="btn small ' + (s._approved ? 'green' : 'ghost') + '" onclick="toggleAiFieldApprove(' + i + ')">' + (s._approved ? 'مقبول' : 'مرفوض') + '</button>' +
          '<button class="btn small ghost" onclick="editAiField(' + i + ')">تعديل</button>' +
          '</div></div>';
      }).join('');
    }

    function toggleAiFieldApprove(index) {
      aiFieldSuggestions[index]._approved = !aiFieldSuggestions[index]._approved;
      renderAiFieldSuggestions();
    }

    function editAiField(index) {
      const s = aiFieldSuggestions[index];
      if (!s) return;
      const newLabel = prompt('اسم الحقل:', s.fieldLabel);
      if (newLabel === null) return;
      const newType = prompt('نوع الحقل (text/textarea/number/select/date/image):', s.fieldType);
      if (newType === null) return;
      if (newLabel) s.fieldLabel = newLabel.trim();
      if (newType) s.fieldType = newType.trim();
      if (s.fieldType === 'select' && !s.fieldOptions) s.fieldOptions = ['خيار 1', 'خيار 2'];
      renderAiFieldSuggestions();
    }

    async function approveAllAiFields() {
      const approved = aiFieldSuggestions.filter(s => s._approved);
      if (!approved.length) { toast('لا توجد حقول مقبولة للإضافة'); return; }

      showLoader('جاري إضافة الحقول', `عدد الحقول: ${approved.length}`);
      let added = 0;
      for (const s of approved) {
        const payload = {
          fieldKey: s.fieldKey,
          fieldLabel: s.fieldLabel,
          fieldType: s.fieldType,
          fieldOptions: s.fieldOptions,
          sectionKey: s.sectionKey || 'general',
          placeholder: s.placeholder,
          defaultValue: s.defaultValue,
          isRequired: s.isRequired,
          aiHint: s.aiHint
        };
        const res = await api('POST', '/api/fields', payload);
        if (res.success) added++;
      }
      hideLoader();
      toast(`تم إضافة ${added} من ${approved.length} حقل`);
      await renderTenantFields();
      clearAiFieldBuilder();
    }

    function rejectAllAiFields() {
      aiFieldSuggestions.forEach(s => s._approved = false);
      renderAiFieldSuggestions();
      document.getElementById('aiFieldSuggestions').style.display = 'none';
      toast('تم رفض الاقتراحات');
    }

    function isGoogleMapsUrl(value) {
      if (!value || typeof value !== 'string') return false;
      try {
        const url = new URL(value.trim());
        if (!/^https?:$/.test(url.protocol)) return false;
        const host = url.hostname.toLowerCase();
        const shortMapsHost = host === 'maps.app.goo.gl' || host === 'goo.gl';
        const mapsHost = host === 'maps.google.com';
        const googleMapsPath = (host === 'google.com' || host.endsWith('.google.com')) && url.pathname.toLowerCase().startsWith('/maps');
        return shortMapsHost || mapsHost || googleMapsPath;
      } catch (e) {
        return false;
      }
    }

    // Dynamic Project Form
    // `prefetched` lets callers that already await a bigger request (draft open)
    // fire these two cheap GETs alongside it instead of adding a second serial wait.
    async function loadTenantProjectForm(prefetched) {
      const [fieldsData, sectionsData] = await (prefetched || Promise.all([
        api('GET', '/api/fields'),
        api('GET', '/api/field-sections')
      ]));
      if (!fieldsData.success) {
        toast(fieldsData.error || 'تعذر تحميل الحقول');
        return false;
      }
      tenantFields = fieldsData.fields || [];
      if (!tenantFields.some(field => field.fieldKey === 'location_detail')) {
        tenantFields.push({
          fieldKey: 'location_detail',
          fieldLabel: 'بيانات الموقع / العنوان التفصيلي',
          fieldType: 'textarea',
          sectionKey: 'location',
          sortOrder: 98,
          placeholder: 'يتم تعبئته تلقائيًا من Google Maps ويمكن تعديله.'
        });
      }
      if (!tenantFields.some(field => field.fieldKey === 'site_analysis')) {
        tenantFields.push({
          fieldKey: 'site_analysis',
          fieldLabel: 'تحليل AI للموقع',
          fieldType: 'textarea',
          sectionKey: 'location',
          sortOrder: 99,
          placeholder: 'اضغط «تحليل الموقع» لتشغيل GLM، ثم راجع النص واعتمده أو عدّله.'
        });
      }
      tenantFieldSections = (sectionsData && sectionsData.available) || [];
      tenantAllowedFieldSections = (sectionsData && sectionsData.allowed) || {};
      renderTenantProjectForm(tenantFields);
      if (typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en') {
        const formEl = document.getElementById('tenantProjectForm');
        if (formEl) window.WFI18n.autoTranslate(formEl);
      }
      return true;
    }

    function parseStoredProjectTable(value) {
      if (Array.isArray(value)) return value;
      if (typeof value !== 'string' || !value.trim()) return [];
      try {
        const parsed = JSON.parse(value);
        return Array.isArray(parsed) ? parsed : [];
      } catch (e) {
        return [];
      }
    }

    // Land tables (survey coordinates / directions) are persisted as JSON strings inside
    // hidden inputs, but the AI hands them over as arrays/objects. Returns null when the
    // value cannot be understood so callers can skip rendering instead of wiping stored rows.
    function parseStoredLandTable(value) {
      if (Array.isArray(value) || (value && typeof value === 'object')) return value;
      if (typeof value !== 'string' || !value.trim()) return null;
      try {
        const parsed = JSON.parse(value);
        return (Array.isArray(parsed) || (parsed && typeof parsed === 'object')) ? parsed : null;
      } catch (e) {
        console.warn('[LAND TABLE] could not parse stored value; keeping existing rows', e);
        return null;
      }
    }

    function parseFinancialStudySnapshot(raw) {
      if (!raw) return null;
      if (typeof raw === 'object') return raw;
      try {
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === 'object' ? parsed : null;
      } catch (error) {
        return null;
      }
    }

    function setFinancialSnapshotInput(id, value) {
      const input = document.getElementById(id);
      if (!input || value === undefined || value === null) return;
      if (input.type === 'checkbox') {
        input.checked = value === true || value === 'true' || value === 'yes' || value === 'نعم';
        return;
      }
      if (input.tagName === 'SELECT') {
        const option = [...input.options].find(item => item.value === String(value) || item.textContent.trim() === String(value).trim());
        if (option) input.value = option.value;
        return;
      }
      if (isFinancialNumericControl(input)) {
        const raw = String(value ?? '').trim();
        input.value = raw === '' ? '' : String(parseNumber(raw));
        return;
      }
      input.value = String(value);
    }

    function hydrateFinancialTableRows(tableId, rows, addRow) {
      const body = document.querySelector('#' + tableId + ' tbody');
      if (!body || !Array.isArray(rows) || typeof addRow !== 'function') return;
      body.innerHTML = '';
      rows.forEach(row => addRow(row));
    }

    function hydrateFinancialStudyModel(raw, fallbackComponents = []) {
      const snapshot = parseFinancialStudySnapshot(raw) || (Array.isArray(fallbackComponents) && fallbackComponents.length ? { dynamicRows: { components: fallbackComponents } } : null);
      if (!snapshot) return;
      const financialRoot = document.getElementById('section-financial-calc');
      if (typeof enhanceNumericInputs === 'function' && financialRoot) enhanceNumericInputs(financialRoot);
      Object.entries(snapshot.inputs || {}).forEach(([id, value]) => setFinancialSnapshotInput(id, value));
      const rows = { ...(snapshot.dynamicRows || {}) };
      if (!Array.isArray(rows.components) && Array.isArray(fallbackComponents) && fallbackComponents.length) rows.components = fallbackComponents;
      const developerPaymentsInput = document.getElementById('developerPaymentsEnabled');
      if (developerPaymentsInput && !Object.prototype.hasOwnProperty.call(snapshot.inputs || {}, 'developerPaymentsEnabled')) {
        developerPaymentsInput.value = Array.isArray(rows.schedule) && rows.schedule.length ? 'yes' : 'no';
      }
      window.__batchLoading = true;
      try {
        hydrateFinancialTableRows('componentsTable', rows.components, addComponent);
        hydrateFinancialTableRows('revenueTable', rows.revenue, addRevenue);
        hydrateFinancialTableRows('scheduleTable', rows.schedule, addScheduleStage);
        hydrateFinancialTableRows('financeDrawTable', rows.financeDraw, addFinanceDrawYear);
        hydrateFinancialTableRows('financeRepaymentTable', rows.financeRepayment, addFinanceRepaymentYear);
        hydrateFinancialTableRows('fundAdditionalFeesTable', rows.fundAdditionalFees, addFundAdditionalFee);
        hydrateFinancialTableRows('occupancyRampTable', rows.occupancyRamp, addOccupancyRampYear);
        hydrateFinancialTableRows('costTable', rows.costs, addCost);
        hydrateFinancialTableRows('opexTable', rows.opex, addOpex);
        hydrateFinancialTableRows('externalTable', rows.external, addExternal);
        hydrateFinancialTableRows('graceScheduleTable', rows.graceSchedule, addGraceScheduleRow);
        const sensitivityBody = document.querySelector('#sensitivityAssumptionsTable tbody');
        if (sensitivityBody && Array.isArray(rows.sensitivity) && typeof addSensitivityVariable === 'function') {
          sensitivityBody.innerHTML = '';
          rows.sensitivity.forEach(row => addSensitivityVariable({ ...row, silent: true }));
        }
      } finally {
        window.__batchLoading = false;
      }
      updateRevenueComponentOptions();
      updateDynamicFields();
      calculateAll();
      const graceRevenueSelect = document.getElementById('graceRevenueId');
      const savedGraceRevenue = snapshot.inputs && snapshot.inputs.graceRevenueId;
      if (graceRevenueSelect && savedGraceRevenue && graceRevenueSelect.value !== savedGraceRevenue && [...graceRevenueSelect.options].some(o => o.value === savedGraceRevenue)) {
        graceRevenueSelect.value = savedGraceRevenue;
        calculateAll();
      }
      if (typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en' && financialRoot) {
        window.WFI18n.autoTranslate(financialRoot);
      }
    }