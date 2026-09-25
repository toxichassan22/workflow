    async function addTenantUser() {
      const name = document.getElementById('newUserName').value.trim();
      const email = document.getElementById('newUserEmail').value.trim();
      const password = document.getElementById('newUserPassword').value;
      if (!name || !email || !password) { toast('كل الحقول مطلوبة'); return; }
      const pwError = passwordPolicyError(password);
      if (pwError) { toast(pwError); return; }
      const data = await api('POST', '/api/users', { name, email, password });
      if (data.success) {
        toast('تم إضافة الموظف' + (data.emailSent === false ? ' — تعذر إرسال البريد' : ''));
        document.getElementById('newUserName').value = '';
        document.getElementById('newUserEmail').value = '';
        document.getElementById('newUserPassword').value = '';
        openTenantUsers();
      } else {
        toast(data.error || 'فشل إضافة الموظف');
      }
    }

    async function toggleUserActive(userId, isActive) {
      const data = await api('PUT', '/api/users/' + userId, { is_active: isActive });
      if (data.success) { toast(isActive ? 'تم التفعيل' : 'تم التعطيل'); openTenantUsers(); }
      else { toast(data.error || 'فشل'); }
    }

    async function deleteTenantUser(userId, userName) {
      if (!confirm('حذف الموظف: ' + userName + '؟')) return;
      const data = await api('DELETE', '/api/users/' + userId);
      if (data.success) { toast('تم الحذف'); openTenantUsers(); }
      else { toast(data.error || 'فشل الحذف'); }
    }

    async function showSodMatrixModal() {
      let matrix = null;
      try {
        const resp = await api('GET', '/api/approvals/sod-matrix');
        if (resp && resp.success) matrix = resp.matrix;
      } catch (err) {
        console.warn('SoD matrix error:', err);
      }

      const modal = document.createElement('div');
      modal.id = 'sodMatrixModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10000;display:flex;align-items:center;justify-content:center;padding:16px;';
      const selfCount = matrix?.self_approvals_count || 0;
      const selfApprovals = matrix?.self_approvals || [];
      const violationsRows = selfApprovals.length
        ? selfApprovals.map(item => {
            const date = (item.decided_at || '').slice(0, 16).replace('T', ' ');
            return '<tr style="border-bottom:1px solid #e2e8f0;">' +
              '<td style="padding:8px;font-weight:600;">' + escapeHtml(item.section_key || item.kind || '') + '</td>' +
              '<td style="padding:8px;">إصدار ' + (item.version_number || 1) + '</td>' +
              '<td style="padding:8px;">' + escapeHtml(item.decided_by_name || item.decided_by || '') + '</td>' +
              '<td style="padding:8px;color:#64748b;font-size:12px;">' + escapeHtml(date) + '</td>' +
              '<td style="padding:8px;"><span style="font-size:11px;padding:3px 8px;border-radius:10px;background:#fff3bf;color:#8a6d00;">تنبيه: تعميد ذاتي للمحرر</span></td>' +
              '</tr>';
          }).join('')
        : '<tr><td colspan="5" style="padding:16px;text-align:center;color:#1c7a2e;">لا توجد مخالفات في الفصل بين المهام</td></tr>';

      const extraSections = [
        { key: 'cross_gate_approvals', count: 'cross_gate_count', label: 'اعتماد التوليد والملف لنفس المعتمد', name: i => i.decided_by_name || i.decided_by },
        { key: 'last_editor_conflicts', count: 'last_editor_conflicts_count', label: 'معتمد الملف هو آخر محرر له', name: i => i.decided_by_name || i.decided_by },
        { key: 'post_approval_edits', count: 'post_approval_edits_count', label: 'تعديل بعد الاعتماد النهائي بدون صلاحية', name: i => i.user_name || i.user_id },
        { key: 'client_side_topups', count: 'client_side_topups_count', label: 'شحن محفظة من جهة العميل', name: i => i.actor || '' },
        { key: 'missing_reason_decisions', count: 'missing_reason_count', label: 'قرار رفض أو إرجاع بدون سبب', name: i => i.decided_by || '' },
      ];
      const extraRows = extraSections.map(sec => {
        const items = matrix?.[sec.key] || [];
        const count = matrix?.[sec.count] ?? items.length;
        const itemsHtml = items.length
          ? items.map(i => '<div style="font-size:12px;color:#475569;padding:2px 0">' + escapeHtml(sec.name(i) || '') +
              ' — ' + escapeHtml((i.decided_at || i.created_at || '').slice(0, 16).replace('T', ' ')) + '</div>').join('')
          : '';
        return '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px;">' +
          '<strong style="font-size:13px">' + escapeHtml(sec.label) + '</strong>' +
          '<div style="margin-top:6px">العدد: <strong style="color:' + (count > 0 ? '#a67c00' : '#1c7a2e') + '">' + count + '</strong></div>' +
          itemsHtml + '</div>';
      }).join('');

      const policies = matrix?.policies || {};
      const currentPolicy = policies.section_self_approval || 'allow';
      const policyLabels = { allow: 'سماح مع توثيق', warn: 'سماح مع تنبيه', block: 'منع' };
      const genPolicy = policies.generation_self_approval || 'block';
      const genPolicyLabels = { allow: 'سماح', block: 'منع' };
      const policySelect = hasPermission('company_settings')
        ? '<select id="sodPolicySelect" style="margin-top:8px;font-size:12px">' +
          Object.keys(policyLabels).map(v =>
            '<option value="' + v + '" ' + (v === currentPolicy ? 'selected' : '') + '>' + policyLabels[v] + '</option>'
          ).join('') + '</select>' +
          '<button type="button" class="btn small ghost" style="margin-top:6px" onclick="saveSodPolicy()">' + escapeHtml(WFT('common.save', 'حفظ')) + '</button>'
        : '<div style="margin-top:8px;font-size:12px;color:#64748b">' + escapeHtml(policyLabels[currentPolicy] || currentPolicy) + '</div>';
      const genPolicySelect = hasPermission('company_settings')
        ? '<select id="sodGenPolicySelect" style="margin-top:8px;font-size:12px">' +
          Object.keys(genPolicyLabels).map(v =>
            '<option value="' + v + '" ' + (v === genPolicy ? 'selected' : '') + '>' + genPolicyLabels[v] + '</option>'
          ).join('') + '</select>'
        : '<div style="margin-top:8px;font-size:12px;color:#64748b">' + escapeHtml(genPolicyLabels[genPolicy] || genPolicy) + '</div>';

      modal.innerHTML =
        '<div style="background:#fff;border-radius:16px;max-width:680px;width:100%;max-height:85vh;display:flex;flex-direction:column;padding:24px;box-shadow:0 12px 32px rgba(0,0,0,.2);direction:rtl;text-align:right;">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">' +
        '<h3 style="margin:0;color:#1a3a52;font-size:18px;">مصفوفة الفصل بين المهام</h3>' +
        '<button type="button" id="closeSodModalBtn" class="btn ghost small" style="padding:4px 12px;">إغلاق</button>' +
        '</div>' +
        '<p style="margin:0 0 16px;color:#64748b;font-size:13px;">حوكمة الاعتمادات وفصل المسؤوليات وفق القرارين d01 و d02</p>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;font-size:13px;">' +
        '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px;">' +
        '<strong>اعتماد المحرر لقسمه (d01):</strong>' +
        '<div style="margin-top:8px;">إجمالي التعميد الذاتي: <strong style="color:' + (selfCount > 0 ? '#a67c00' : '#1c7a2e') + ';">' + selfCount + '</strong></div>' +
        policySelect +
        '</div>' +
        '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px;">' +
        '<strong>اعتماد مقدم طلب التوليد لطلبه (d02):</strong>' +
        '<p style="margin:4px 0 0;color:#64748b;font-size:12px;">فصل إلزامي في مصفوفة الأدوار ما لم تسمح الشركة بالاعتماد الذاتي</p>' +
        genPolicySelect +
        '</div></div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;font-size:13px;">' + extraRows + '</div>' +
        '<div style="flex:1;overflow-y:auto;border:1px solid #e2e8f0;border-radius:8px;">' +
        '<table style="width:100%;border-collapse:collapse;font-size:13px;text-align:right;">' +
        '<thead><tr style="background:#f8fafc;border-bottom:1px solid #e2e8f0;color:#475569;">' +
        '<th style="padding:8px;">القسم</th>' +
        '<th style="padding:8px;">الإصدار</th>' +
        '<th style="padding:8px;">المعتمد</th>' +
        '<th style="padding:8px;">التاريخ</th>' +
        '<th style="padding:8px;">الحالة الرقابية</th>' +
        '</tr></thead><tbody>' + violationsRows + '</tbody></table>' +
        '</div></div>';

      document.body.appendChild(modal);
      const closeBtn = modal.querySelector('#closeSodModalBtn');
      if (closeBtn) closeBtn.onclick = () => { if (modal.parentNode) modal.parentNode.removeChild(modal); };
    }

    async function saveSodPolicy() {
      const sel = document.getElementById('sodPolicySelect');
      const genSel = document.getElementById('sodGenPolicySelect');
      const updates = {};
      if (sel) updates.section_self_approval = sel.value;
      if (genSel) updates.generation_self_approval = genSel.value;
      if (!Object.keys(updates).length) return;
      const data = await api('PUT', '/api/policies', updates);
      if (data && data.success) {
        toast(WFT('common.saved', 'حفظ'));
      } else {
        toast((data && data.error) || WFT('common.error', 'حدث خطأ'));
      }
    }

    let editingUserPermissions = null;
    const PERMISSION_LABELS = {
      dashboard: 'الرئيسية',
      create_presentation: 'إنشاء عرض جديد',
      view_presentations: 'عرض العروض السابقة',
      generate_images: 'توليد الصور',
      generate_maps: 'توليد الخرائط',
      company_settings: 'إعدادات الشركة',
      custom_fields: 'الحقول المخصصة',
      manage_users: 'إدارة الموظفين',
      ai_rules: 'قواعد AI',
      training_data: 'تدريب GLM',
      approvals: 'تعميد العروض',
      approve_generation: 'اعتماد بدء التوليد',
      approve_final_file: 'اعتماد الملف النهائي',
      export_files: 'تصدير الملفات',
      copy_presentation: 'نسخ العروض',
      post_approval_edit: 'التعديل بعد الاعتماد',
      billing: 'الفوترة والمحفظة',
      audit_log: 'سجل المراجعة',
      support_tickets: 'تذاكر الدعم',
      sag_admin_panel: 'لوحة المدير العام',
    };

    const USER_ROLE_LABELS = {
      employee: 'موظف',
    };

    const ASSIGNMENT_ROLES = [
      { key: 'editor', label: 'محرر' },
      { key: 'approver', label: 'معتمد' },
    ];
    let editingAssignments = [];
    let tenantAssignments = [];

    async function openUserPermissionsModal(userId, userName) {
      const [permData, sectionData, scopeData, assignData, tenantAssignData] = await Promise.all([
        api('GET', '/api/users/' + userId + '/permissions'),
        api('GET', '/api/users/' + userId + '/field-sections'),
        api('GET', '/api/users/' + userId + '/project-scope').catch(() => null),
        api('GET', '/api/users/' + userId + '/assignments').catch(() => null),
        api('GET', '/api/assignments').catch(() => null)
      ]);
      if (!permData.success || !sectionData.success) { toast('تعذر تحميل الصلاحيات'); return; }
      const perms = permData.permissions || {};
      const keys = permData.availableKeys || [];
      const sections = sectionData.sections || {};
      const availableSections = sectionData.available || [];
      const scopeDrafts = (scopeData && scopeData.drafts) || [];
      const scopeSet = new Set((scopeData && scopeData.scope) || []);
      editingAssignments = ((assignData && assignData.assignments) || []).map(a => ({
        draft_id: a.draft_id || '*', role: a.role,
      }));
      tenantAssignments = (tenantAssignData && tenantAssignData.assignments) || [];
      editingUserPermissions = { userId, userName, availableSections, scopeDrafts };

      const permRows = keys.map(key => {
        const label = PERMISSION_LABELS[key] || key;
        return '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--line)">' +
          '<label>' + label + '</label>' +
          '<input type="checkbox" id="perm_' + key + '" ' + (perms[key] ? 'checked' : '') + '>' +
          '</div>';
      }).join('');

      const sectionRows = availableSections.map(s => {
        return '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--line)">' +
          '<label>' + escapeHtml(s.label) + '</label>' +
          '<input type="checkbox" id="section_' + s.key + '" ' + (sections[s.key] ? 'checked' : '') + '>' +
          '</div>';
      }).join('');

      const scopeRows = scopeDrafts.length ? scopeDrafts.map(d =>
        '<div style="display:flex;align-items:center;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--line)">' +
        '<label>' + escapeHtml(d.title || d.id) + '</label>' +
        '<input type="checkbox" class="scopeDraftCb" value="' + escapeHtml(d.id) + '" ' + (scopeSet.has(d.id) ? 'checked' : '') + '></div>'
      ).join('') : '<p class="tenant-hint">' + escapeHtml(WFT('common.none', 'لا يوجد')) + '</p>';

      const modal = document.createElement('div');
      modal.id = 'userPermissionsModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
      modal.innerHTML = '<div style="background:#fff;border-radius:20px;padding:24px;max-width:520px;width:100%;max-height:85vh;overflow:auto">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">' +
        '<h3><span>صلاحيات:</span> ' + escapeHtml(userName) + '</h3>' +
        '<button class="btn ghost" onclick="document.getElementById(\'userPermissionsModal\').remove()">إغلاق</button></div>' +
        '<h4 style="margin:12px 0 8px;color:var(--p)">صلاحيات التطبيق</h4>' +
        '' +
        permRows +
        '<h4 style="margin:20px 0 8px;color:var(--p)">أقسام فورم المشروع</h4>' +
        '' +
        sectionRows +
        '<h4 style="margin:20px 0 8px;color:var(--p)">' + escapeHtml(WFT('users.project_scope', 'ملفات المشاريع المسموحة')) + '</h4>' +
        scopeRows +
        '<h4 style="margin:20px 0 8px;color:var(--p)">' + escapeHtml(WFT('users.assignments_title', 'المسؤوليات على المشاريع')) + '</h4>' +
        '<div id="permAssignmentsList"></div>' +
        '<div class="tenant-btns" style="margin-top:8px">' +
        '<button type="button" class="btn small ghost" onclick="addAssignmentRow()">' + escapeHtml(WFT('users.assignment_add', 'إضافة تعيين')) + '</button>' +
        '</div>' +
        '<div class="tenant-btns" style="margin-top:16px">' +
        '<button class="btn primary" onclick="saveUserPermissions()">حفظ الصلاحيات</button>' +
        '</div></div>';
      document.body.appendChild(modal);
      renderAssignmentRows();
    }

    function assignmentDraftOptions(selected) {
      const drafts = (editingUserPermissions && editingUserPermissions.scopeDrafts) || [];
      return '<option value="*">كل المشاريع</option>' + drafts.map(d =>
        '<option value="' + escapeHtml(d.id) + '"' + (d.id === selected ? ' selected' : '') + '>' + escapeHtml(d.title || d.id) + '</option>'
      ).join('');
    }

    function assignmentHolder(draftId, role) {
      if (role !== 'approver') return '';
      const me = editingUserPermissions && editingUserPermissions.userId;
      const hit = tenantAssignments.find(a =>
        a.user_id !== me && a.role === 'approver' &&
        (a.draft_id === '*' || draftId === '*' || a.draft_id === draftId));
      return hit ? (hit.user_name || hit.user_id) : '';
    }

    function renderAssignmentRows() {
      const box = document.getElementById('permAssignmentsList');
      if (!box) return;
      if (!editingAssignments.length) {
        box.innerHTML = '<p class="tenant-hint">' + escapeHtml(WFT('common.none', 'لا يوجد')) + '</p>';
        return;
      }
      box.innerHTML = editingAssignments.map((a, i) => {
        const holder = assignmentHolder(a.draft_id, a.role);
        const roleOptions = ASSIGNMENT_ROLES.map(r =>
          '<option value="' + r.key + '"' + (r.key === a.role ? ' selected' : '') + '>' + r.label + '</option>'
        ).join('');
        return '<div style="display:flex;gap:6px;align-items:center;margin-bottom:6px;flex-wrap:wrap">' +
          '<select class="assignDraftSel" data-i="' + i + '" onchange="updateAssignmentRow(' + i + ')" style="flex:2;min-width:140px">' + assignmentDraftOptions(a.draft_id) + '</select>' +
          '<select class="assignRespSel" data-i="' + i + '" onchange="updateAssignmentRow(' + i + ')" style="flex:1;min-width:110px">' + roleOptions + '</select>' +
          '<button type="button" class="btn small danger" onclick="removeAssignmentRow(' + i + ')">' + escapeHtml(WFT('common.delete', 'حذف')) + '</button>' +
          (holder ? '<div class="tenant-hint" style="width:100%">' + escapeHtml(WFT('users.assignment_holder', 'المعتمد الحالي: ')) + escapeHtml(holder) + '</div>' : '') +
          '</div>';
      }).join('');
    }

    function addAssignmentRow() {
      editingAssignments.push({ draft_id: '*', role: 'editor' });
      renderAssignmentRows();
    }

    function removeAssignmentRow(i) {
      editingAssignments.splice(i, 1);
      renderAssignmentRows();
    }

    function updateAssignmentRow(i) {
      const draftSel = document.querySelector('.assignDraftSel[data-i="' + i + '"]');
      const respSel = document.querySelector('.assignRespSel[data-i="' + i + '"]');
      if (!editingAssignments[i]) return;
      if (draftSel) editingAssignments[i].draft_id = draftSel.value;
      if (respSel) editingAssignments[i].role = respSel.value;
      renderAssignmentRows();
    }

    async function saveUserPermissions() {
      if (!editingUserPermissions) return;
      const keys = Object.keys(PERMISSION_LABELS);
      const permissions = {};
      keys.forEach(key => {
        const cb = document.getElementById('perm_' + key);
        permissions[key] = cb ? cb.checked : false;
      });
      const sections = {};
      (editingUserPermissions.availableSections || []).forEach(s => {
        const cb = document.getElementById('section_' + s.key);
        sections[s.key] = cb ? cb.checked : false;
      });
      const draftIds = Array.from(document.querySelectorAll('.scopeDraftCb:checked')).map(cb => cb.value);
      const assignments = editingAssignments.map(a => ({
        draft_id: a.draft_id || '*', role: a.role,
      }));
      showLoader('جاري حفظ الصلاحيات', '');
      const [permRes, sectionRes, scopeRes] = await Promise.all([
        api('PUT', '/api/users/' + editingUserPermissions.userId + '/permissions', { permissions }),
        api('PUT', '/api/users/' + editingUserPermissions.userId + '/field-sections', { sections }),
        api('PUT', '/api/users/' + editingUserPermissions.userId + '/project-scope', { draftIds }).catch(() => ({ success: true }))
      ]);
      const assignRes = await api('PUT', '/api/users/' + editingUserPermissions.userId + '/assignments', { assignments }).catch(() => ({ success: true }));
      hideLoader();
      const conflicted = assignRes && assignRes.error_code === 'approver_exists';
      const editorCap = assignRes && assignRes.error_code === 'too_many_editors';
      const failed = conflicted || editorCap;
      if (!failed) {
        const modal = document.getElementById('userPermissionsModal');
        if (modal) modal.remove();
      }
      if (conflicted) {
        toast(WFT('users.assignment_conflict', 'المشروع له معتمد آخر بالفعل') + (assignRes.holder ? ': ' + assignRes.holder : ''));
        const tenantData = await api('GET', '/api/assignments').catch(() => null);
        tenantAssignments = (tenantData && tenantData.assignments) || tenantAssignments;
        renderAssignmentRows();
      }
      else if (editorCap) {
        toast(WFT('users.assignment_editor_cap', 'المشروع يقبل خمسة محررين كحد أقصى'));
        renderAssignmentRows();
      }
      else if (permRes.success && sectionRes.success && (!scopeRes || scopeRes.success) && (!assignRes || assignRes.success)) { toast('تم حفظ الصلاحيات'); }
      else { toast(permRes.error || sectionRes.error || (scopeRes && scopeRes.error) || (assignRes && assignRes.error) || 'فشل الحفظ'); }
    }

    async function sendTenantInvite() {
      const email = document.getElementById('inviteEmail').value.trim();
      if (!email) { toast(WFT('users.invite_email_required', 'أدخل بريد الموظف')); return; }
      const result = document.getElementById('inviteResult');
      showInlineLoader(result, WFT('common.sending', 'جاري الإرسال...'));
      const sections = Array.from(document.querySelectorAll('.inviteSectionCb:checked')).map(cb => cb.value);
      const projects = Array.from(document.querySelectorAll('.inviteProjectCb:checked')).map(cb => cb.value);
      const data = await api('POST', '/api/invites', {
        email,
        name: ((document.getElementById('inviteName') || {}).value || '').trim() || null,
        phone: ((document.getElementById('invitePhone') || {}).value || '').trim() || null,
        sections,
        projects,
      });
      if (data.success) {
        const fullUrl = window.location.origin + data.inviteUrl;
        result.innerHTML = '<div style="background:var(--soft);border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:8px">' +
          '<p style="margin:0 0 8px"><strong>' + escapeHtml(WFT('users.invite_created', 'تم إنشاء الدعوة')) + '</strong>' +
          (data.emailSent ? '' : ' — <span style="color:#a67c00">' + escapeHtml(WFT('users.invite_email_queued', 'تعذر إرسال البريد')) + '</span>') + '</p>' +
          '<input type="text" readonly value="' + fullUrl + '" style="width:100%;font-size:13px" onclick="this.select()">' +
          '</div>';
        document.getElementById('inviteEmail').value = '';
        const nameEl = document.getElementById('inviteName');
        if (nameEl) nameEl.value = '';
        const phoneEl = document.getElementById('invitePhone');
        if (phoneEl) phoneEl.value = '';
        openTenantUsers();
      } else {
        result.innerHTML = '<p style="color:#c33">' + escapeHtml(data.error || WFT('common.error', 'فشل')) + '</p>';
      }
    }

    // ── Presentation Versions & Edit Log ──
    async function showPresentationVersions(presId) {
      if (!presId) { toast('لا توجد نسخة محفوظة لهذا العرض'); return; }
      document.getElementById('versionsModal')?.remove();
      const modal = document.createElement('div');
      modal.id = 'versionsModal';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-modal', 'true');
      modal.setAttribute('aria-label', 'سجل التعديلات والنسخ');
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(15,23,42,.65);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px;direction:rtl';
      modal.innerHTML = '<div style="background:#fff;border-radius:18px;padding:24px;width:min(1180px,100%);max-height:92vh;overflow:auto">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;gap:16px"><h3 style="margin:0">سجل التعديلات والنسخ</h3>' +
        '<div style="display:flex;gap:8px">' +
        '<button class="btn ghost" id="presentationHistoryDownloads">مكتبة التنزيلات</button>' +
        '<button class="btn ghost" id="closePresentationHistory">إغلاق</button></div></div>' +
        '<div id="presentationHistoryContent" aria-live="polite" style="margin-top:18px">جاري تحميل النسخ والسجل...</div></div>';
      document.body.appendChild(modal);
      modal.querySelector('#closePresentationHistory').onclick = () => { modal.remove(); tenantPresentationHistory = null; };
      const historyDownloadsBtn = modal.querySelector('#presentationHistoryDownloads');
      if (historyDownloadsBtn) historyDownloadsBtn.onclick = () => showDownloadsLibraryModal(presId);
      const host = modal.querySelector('#presentationHistoryContent');
      try {
        const [versions, log] = await Promise.all([
          api('GET', '/api/presentations/' + encodeURIComponent(presId) + '/versions'),
          api('GET', '/api/presentations/' + encodeURIComponent(presId) + '/edit-log')
        ]);
        if (!versions?.success || !log?.success) throw new Error(versions?.error || log?.error || 'تعذر تحميل سجل العرض');
        if (!modal.isConnected) return;
        tenantPresentationHistory = { presId, revision: Number(versions.currentRevision) || 0,
          versions: versions.versions || [], log: log.log || [], previewRequest: 0 };
        const entries = tenantPresentationHistory.versions;
        host.innerHTML = '<div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:16px">' +
          '<strong>النسخة الحالية: ' + tenantPresentationHistory.revision + '</strong>' +
          '<span class="tenant-hint">' + entries.length + ' نسخة محفوظة</span></div>' +
          '<div id="presentationRevisionPreview" hidden style="margin-bottom:24px;padding:16px;border:1px solid #cbd5e1;border-radius:12px"></div>' +
          (entries.length ? '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:12px">' + entries.map((v, index) => {
            const linked = tenantPresentationHistory.log.find(entry => entry.revision_id === v.id && entry.id === v.change_log_id);
            const source = v.source === 'ai' ? 'بمساعدة الذكاء الاصطناعي' : v.source === 'system' ? 'النظام' : 'يدوي';
            const title = v.snapshotKind === 'legacy-slides' || v.legacy ? 'نسخة قديمة للشرائح فقط' : 'النسخة ' + v.revision;
            return '<article style="padding:16px;border:1px solid #dbe2ea;border-radius:12px;background:#f8fafc">' +
              '<div style="display:flex;justify-content:space-between;gap:8px"><strong>' + escapeHtml(title) + '</strong>' +
              (Number(v.revision) === tenantPresentationHistory.revision && !v.legacy ? '<span>الحالية</span>' : '') + '</div>' +
              '<div style="margin-top:8px">' + escapeHtml(v.user_name || 'غير مسجل') + ' | ' + source + '</div>' +
              '<div class="meta" style="margin-top:4px">' + escapeHtml(String(v.created_at || '').replace('T', ' ').slice(0,19)) +
              ' | ' + (v.slide_count || 0) + ' شريحة</div>' +
              '<div style="margin-top:10px;line-height:1.8">' + escapeHtml(v.summary || linked?.summary || revisionActionLabel(v.action)) + '</div>' +
              ((v.details || linked?.details || []).slice(0, 5).map(line => '<div style="font-size:13px;line-height:1.8">' + escapeHtml(changeDetailText(line)) + '</div>').join('')) +
              '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">' +
              '<button class="btn small ghost" data-version-preview="' + index + '">معاينة ومقارنة</button>' +
              (hasPermission('create_presentation') ? '<button class="btn small ghost" data-version-restore="' + index + '">استعادة</button>' : '') + '</div></article>';
          }).join('') + '</div>' : '<p class="tenant-hint">لا توجد نسخ سابقة محفوظة.</p>') +
          '<h3 style="margin-top:28px">كل الأحداث</h3>' +
          (tenantPresentationHistory.log.length ? tenantPresentationHistory.log.map(renderChangeLogEntry).join('') : '<p class="tenant-hint">لا توجد أحداث مسجلة.</p>');
        host.querySelectorAll('[data-version-preview]').forEach(button => {
          button.onclick = () => previewPresentationVersion(presId, entries[Number(button.dataset.versionPreview)].id, button);
        });
        host.querySelectorAll('[data-version-restore]').forEach(button => {
          button.onclick = () => restoreVersion(presId, entries[Number(button.dataset.versionRestore)].id, button);
        });
      } catch (error) {
        host.textContent = error.message || 'تعذر تحميل سجل العرض';
      }
    }

    function revisionActionLabel(action) {
      return ({ create: 'إنشاء العرض', edit: 'تعديل العرض', restore: 'استعادة نسخة سابقة',
        baseline: 'الحالة السابقة قبل تفعيل سجل النسخ', generation: 'توليد العرض' })[action] || action || 'حفظ العرض';
    }

    function revisionPreviewFrame(host, slide, projectData) {
      host.replaceChildren();
      if (!slide) { host.textContent = 'لا توجد شريحة في هذه النسخة'; return; }
      const frame = document.createElement('iframe');
      frame.title = slide.title || 'معاينة شريحة محفوظة';
      frame.setAttribute('sandbox', '');
      frame.style.cssText = 'width:1280px;height:720px;border:0;transform-origin:top left;position:absolute;left:0;top:0;pointer-events:none;background:white';
      const fontCss = projectData?._presentation_font_css || document.getElementById('tenantFontCss')?.textContent || '';
      frame.srcdoc = '<!doctype html><html dir="rtl"><head><meta charset="utf-8">' +
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src https: http: data:; font-src https: http: data:; style-src \'unsafe-inline\' https:; script-src \'none\'; form-action \'none\'; base-uri ' + window.location.origin + '">' +
        '<base href="' + escapeHtml(window.location.origin + '/') + '"><style>html,body{margin:0;width:1280px;height:720px;overflow:hidden}*{box-sizing:border-box}' +
        fontCss.replace(/<\/style/gi, '') + '</style></head><body>' + String(slide.html || '') + '</body></html>';
      host.style.cssText = 'position:relative;width:100%;aspect-ratio:16/9;overflow:hidden;background:#e2e8f0;border:1px solid #cbd5e1;border-radius:8px';
      host.appendChild(frame);
      const resize = () => { frame.style.transform = 'scale(' + host.clientWidth / 1280 + ')'; };
      resize();
      const observer = new ResizeObserver(() => {
        if (!host.isConnected) observer.disconnect();
        else resize();
      });
      observer.observe(host);
    }

    async function previewPresentationVersion(presId, versionId, button) {
      const context = tenantPresentationHistory;
      const host = document.getElementById('presentationRevisionPreview');
      if (!context || context.presId !== presId || !host) return;
      const request = ++context.previewRequest;
      host.hidden = false;
      host.textContent = 'جاري تحميل المعاينة والمقارنة...';
      if (button) button.disabled = true;
      try {
        const prefix = '/api/presentations/' + encodeURIComponent(presId);
        const [detail, current, comparison] = await Promise.all([
          api('GET', prefix + '/versions/' + encodeURIComponent(versionId)),
          api('GET', prefix),
          api('GET', prefix + '/versions/compare?from=' + encodeURIComponent(versionId) + '&to=current')
        ]);
        if (!detail?.success || !current?.success || !comparison?.success) throw new Error('تعذر تحميل المعاينة');
        if (tenantPresentationHistory !== context || context.previewRequest !== request) return;
        const snapshot = detail.version.snapshot;
        const latest = current.presentation;
        const count = Math.max(snapshot.slidesData?.length || 0, latest.slidesData?.length || 0);
        host.innerHTML = '<div style="display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap"><h3>مقارنة النسخ</h3>' +
          '<label>الشريحة <select id="revisionPreviewSlide">' + Array.from({ length: count }, (_, i) => '<option value="' + i + '">' + (i + 1) + '</option>').join('') + '</select></label></div>' +
          '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));gap:16px;margin-top:12px">' +
          '<div><h4>النسخة المحددة</h4><div id="revisionBeforeFrame"></div></div>' +
          '<div><h4>النسخة الحالية المحفوظة</h4><div id="revisionAfterFrame"></div></div></div>' +
          '<div style="margin-top:16px;line-height:1.9">' + (comparison.changes?.length
            ? comparison.changes.map(line => '<div>' + escapeHtml(line) + '</div>').join('') : 'لا توجد اختلافات في المحتوى') + '</div>';
        const render = () => {
          const index = Number(host.querySelector('#revisionPreviewSlide').value) || 0;
          revisionPreviewFrame(host.querySelector('#revisionBeforeFrame'), snapshot.slidesData?.[index], snapshot.projectData);
          revisionPreviewFrame(host.querySelector('#revisionAfterFrame'), latest.slidesData?.[index], latest.projectData);
        };
        host.querySelector('#revisionPreviewSlide').onchange = render;
        render();
        host.scrollIntoView({ block: 'nearest' });
      } catch (error) { if (context.previewRequest === request) host.textContent = error.message; }
      finally { if (button) button.disabled = false; }
    }

    async function restoreVersion(presId, versionId, button) {
      if (tenantPresentationSavePromise || isGeneratingTenantSlides) { toast('العرض قيد الحفظ أو التوليد'); return; }
      if (!confirm('استعادة هذه النسخة كنسخة جديدة؟ النسخ المحفوظة الحالية ستبقى في السجل.')) return;
      const context = tenantPresentationHistory;
      if (!context || context.presId !== presId) return;
      if (button) { button.disabled = true; button.textContent = 'جاري الاستعادة...'; }
      try {
        let expectedRevision = context.revision;
        if (tenantPresentationId === presId && tenantSlidesData.length) {
          const saved = await saveTenantPresentation();
          if (!saved) return;
          expectedRevision = tenantPresentationRevision;
        }
        const data = await api('POST', '/api/presentations/' + encodeURIComponent(presId) + '/versions/' + encodeURIComponent(versionId) + '/restore', { expectedRevision });
        if (!data?.success) throw new Error(data?.error_code === 'PRESENTATION_REVISION_CONFLICT'
          ? 'ظهرت نسخة أحدث للعرض. لم يتم استبدالها.' : data?.error || 'تعذر الاستعادة');
        tenantArchiveCache = null;
        if (tenantPresentationId === presId) await openExistingPresentation(presId);
        toast('تمت استعادة العرض كنسخة جديدة، وبقيت بيانات المشروع دون تغيير');
        await showPresentationVersions(presId);
      } catch (error) { toast(error.message || 'تعذر الاستعادة'); }
      finally { if (button) { button.disabled = false; button.textContent = 'استعادة'; } }
    }

    // ── Change log: who changed what, rendered as a real audit page ──────────
    // Entries carry structured detail items {group, path, field, old, new, kind}
    // alongside legacy plain strings; the page groups them by section and shows
    // the old value next to the new one instead of «تم تحديث البيانات».
    function parseChangeLogDate(value) {
      const raw = String(value || '').trim();
      if (!raw) return null;
      let parsed = new Date(raw);
      if (!/(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(raw)) parsed = new Date(raw.replace(' ', 'T') + 'Z');
      return isNaN(parsed.getTime()) ? null : parsed;
    }

    function formatChangeLogStamp(value) {
      const parsed = parseChangeLogDate(value);
      if (!parsed) return String(value || '').slice(0, 19).replace('T', ' ');
      const pad = number => String(number).padStart(2, '0');
      let hours = parsed.getHours();
      const suffix = hours < 12 ? 'ص' : 'م';
      hours = hours % 12 || 12;
      return parsed.getFullYear() + '-' + pad(parsed.getMonth() + 1) + '-' + pad(parsed.getDate()) +
        ' — ' + hours + ':' + pad(parsed.getMinutes()) + ' ' + suffix;
    }

    function formatChangeLogDay(value) {
      const parsed = parseChangeLogDate(value);
      if (!parsed) return '';
      const pad = number => String(number).padStart(2, '0');
      return parsed.getFullYear() + '-' + pad(parsed.getMonth() + 1) + '-' + pad(parsed.getDate());
    }

    function changeDetailText(item) {
      if (!item || typeof item !== 'object') return String(item || '');
      const head = [item.group, item.path].filter(Boolean).join(' › ');
      if (item.field) {
        const oldValue = String(item.old || '');
        const newValue = String(item.new || '');
        const phrase = oldValue && newValue
          ? 'من «' + oldValue + '» إلى «' + newValue + '»'
          : newValue ? 'أُضيف «' + newValue + '»' : 'أُفرغ (كان «' + oldValue + '»)';
        return (head ? head + ': ' : '') + item.field + ': ' + phrase;
      }
      const text = String(item.text || '');
      return head ? head + ': ' + text : text;
    }

    // The same token-level marking the section-version diff uses: inside a
    // changed value only the words that actually differ get highlighted.
    function changeLogMarkedValue(text, paired) {
      const frags = (typeof diffWordMarks === 'function')
        ? diffWordMarks(String(text || ''), String(paired || '')) : null;
      if (!frags) return escapeHtml(String(text || ''));
      return frags.map(frag => frag.changed
        ? '<span class="diff-word">' + escapeHtml(frag.text) + '</span>'
        : escapeHtml(frag.text)).join('');
    }

    function renderChangeLogDetails(details) {
      const items = Array.isArray(details) ? details : [];
      // Structured items cluster under their section name even when the source
      // order interleaves groups; plain strings keep their own order at the end.
      const groups = [];
      const loose = [];
      items.forEach(item => {
        if (item && typeof item === 'object') {
          const name = item.group || 'تغييرات';
          let bucket = groups.find(g => g.name === name);
          if (!bucket) { bucket = { name: name, items: [] }; groups.push(bucket); }
          bucket.items.push(item);
        } else if (String(item || '').trim()) {
          loose.push(item);
        }
      });
      const rowHtml = item => {
        const path = item.path
          ? '<span class="change-log-path">' + escapeHtml(item.path) + '</span>' : '';
        if (item.field) {
          const oldValue = String(item.old || '');
          const newValue = String(item.new || '');
          let valueHtml;
          if (oldValue && newValue) {
            valueHtml = '<span class="change-log-old">' + changeLogMarkedValue(oldValue, newValue) + '</span>' +
              '<span class="change-log-to">إلى</span>' +
              '<span class="change-log-new">' + changeLogMarkedValue(newValue, oldValue) + '</span>';
          } else if (newValue) {
            valueHtml = '<span class="change-log-text">أُضيف</span>' +
              '<span class="change-log-new">' + escapeHtml(newValue) + '</span>';
          } else {
            valueHtml = '<span class="change-log-text">أُزيلت (كانت</span>' +
              '<span class="change-log-old">' + escapeHtml(oldValue) + '</span>' +
              '<span class="change-log-text">)</span>';
          }
          return '<div class="change-log-row">' + path +
            '<span class="change-log-field">' + escapeHtml(item.field) + '</span>' +
            valueHtml + '</div>';
        }
        const kindClass = item.kind === 'added' ? ' kind-added'
          : item.kind === 'removed' ? ' kind-removed' : '';
        return '<div class="change-log-row' + kindClass + '">' + path +
          '<span class="change-log-text">' + escapeHtml(item.text || '') + '</span></div>';
      };
      let html = groups.map(group =>
        '<div class="change-log-group"><div class="change-log-group-title">' +
        escapeHtml(group.name) + '</div>' +
        group.items.map(rowHtml).join('') + '</div>').join('');
      html += loose.map(item =>
        '<div class="change-log-plain">' + escapeHtml(String(item)) + '</div>').join('');
      return html;
    }

    // Every entry names its author, whether it was done by hand or by the AI, and the individual
    // differences it produced. It used to read «تعديل نصي» with nothing behind it.
    function renderChangeLogEntry(entry) {
      const source = entry.source === 'ai' ? 'الذكاء الاصطناعي'
        : entry.source === 'system' ? 'النظام' : 'يدوي';
      const badgeClass = entry.source === 'ai' ? 'badge-ai'
        : entry.source === 'system' ? 'badge-system' : 'badge-manual';
      const stamp = formatChangeLogStamp(entry.created_at);
      return '<div class="change-log-entry">' +
        '<div class="change-log-head">' +
        '<strong class="change-log-user">' + escapeHtml(entry.user_name || 'نظام') + '</strong>' +
        '<span class="change-log-action">' + escapeHtml(entry.action || '') + '</span>' +
        '<span class="change-log-badge ' + badgeClass + '">' + source + '</span>' +
        '<span class="change-log-stamp">' + escapeHtml(stamp) + '</span></div>' +
        (entry.summary
          ? '<div class="change-log-summary">' + escapeHtml(entry.summary) + '</div>' : '') +
        renderChangeLogDetails(entry.details) + '</div>';
    }

    function renderChangeLogList(entries) {
      let html = '';
      let lastDay = null;
      const today = formatChangeLogDay(new Date().toISOString());
      const yesterday = formatChangeLogDay(new Date(Date.now() - 86400000).toISOString());
      entries.forEach(entry => {
        const day = formatChangeLogDay(entry.created_at);
        if (day !== lastDay) {
          lastDay = day;
          const label = day === today ? 'اليوم' : day === yesterday ? 'أمس' : (day || 'بدون تاريخ');
          html += '<div class="change-log-day">' + escapeHtml(label) + '</div>';
        }
        html += renderChangeLogEntry(entry);
      });
      return html;
    }

    async function showEditLog(presId) {
      return showPresentationVersions(presId);
    }

    let changeLogEntries = [];

    function ensureChangeLogPage() {
      let overlay = document.getElementById('changeLogPage');
      if (overlay) return overlay;
      overlay = document.createElement('div');
      overlay.id = 'changeLogPage';
      overlay.className = 'll-modal-overlay change-log-overlay';
      overlay.setAttribute('data-a11y-modal', '');
      overlay.addEventListener('click', event => {
        if (event.target === overlay) closeChangeLogPage();
      });
      overlay.innerHTML = '<div class="ll-modal-card change-log-card" role="dialog" aria-modal="true">' +
        '<div class="sag-modal-head"><h2 id="changeLogPageTitle">سجل التعديلات</h2>' +
        '<button type="button" class="btn ghost small" id="changeLogPageClose">إغلاق</button></div>' +
        '<input type="search" id="changeLogSearch" class="change-log-search" placeholder="بحث في السجل">' +
        '<div id="changeLogPageBody"></div></div>';
      document.body.appendChild(overlay);
      overlay.querySelector('#changeLogPageClose').addEventListener('click', closeChangeLogPage);
      overlay.querySelector('#changeLogSearch').addEventListener('input', renderChangeLogPageBody);
      return overlay;
    }

    function closeChangeLogPage() {
      const overlay = document.getElementById('changeLogPage');
      if (overlay) overlay.style.display = 'none';
      if (typeof a11yModalDidClose === 'function') a11yModalDidClose();
    }

    function changeLogEntryMatches(entry, query) {
      const lines = Array.isArray(entry.details) ? entry.details.map(changeDetailText) : [];
      return [entry.user_name, entry.action, entry.summary].concat(lines)
        .join(' ').includes(query);
    }

    function renderChangeLogPageBody() {
      const overlay = document.getElementById('changeLogPage');
      if (!overlay) return;
      const query = (overlay.querySelector('#changeLogSearch').value || '').trim();
      const entries = query
        ? changeLogEntries.filter(entry => changeLogEntryMatches(entry, query))
        : changeLogEntries;
      overlay.querySelector('#changeLogPageBody').innerHTML = entries.length
        ? renderChangeLogList(entries)
        : '<p class="tenant-hint">لا توجد تعديلات مسجلة</p>';
    }

    async function showDraftEditLog(draftId) {
      const overlay = ensureChangeLogPage();
      const body = overlay.querySelector('#changeLogPageBody');
      overlay.querySelector('#changeLogPageTitle').textContent = 'سجل تعديلات المشروع';
      overlay.querySelector('#changeLogSearch').value = '';
      body.innerHTML = '<p class="tenant-hint">جاري تحميل السجل...</p>';
      overlay.style.display = 'flex';
      if (typeof a11yModalDidOpen === 'function') a11yModalDidOpen(overlay);
      try {
        const data = await api('GET', '/api/project-draft/' + encodeURIComponent(draftId) + '/edit-log');
        if (!data || !data.success) {
          body.innerHTML = '<p class="tenant-hint">' + escapeHtml((data && data.error) || 'فشل تحميل السجل') + '</p>';
          return;
        }
        if (data.title) {
          overlay.querySelector('#changeLogPageTitle').textContent = 'سجل تعديلات المشروع — ' + data.title;
        }
        changeLogEntries = data.log || [];
        renderChangeLogPageBody();
      } catch (error) {
        body.innerHTML = '<p class="tenant-hint">تعذر تحميل السجل</p>';
      }
    }

    function initTenant() {
      initScrollSpy();
      const path = window.location.pathname;
      const passwordSetupMatch = path.match(/^\/set-password\/(.+)$/);
      if (passwordSetupMatch) {
        showPasswordSetupPage(passwordSetupMatch[1]);
        initGlobalRail();
        return;
      }
      const token = getTenantToken();
      if (token) {
        bootstrapTenant();
      } else {
        const inviteMatch = path.match(/^\/invite\/(.+)$/);
        if (inviteMatch) {
          showInvitePage(inviteMatch[1]);
        } else {
          showAuthPage();
        }
      }
      initGlobalRail();
    }

    async function showPasswordSetupPage(rawToken) {
      const data = await api('GET', '/api/auth/password-setup/' + encodeURIComponent(rawToken));
      const authPage = document.getElementById('tenantAuthPage');
      document.getElementById('tenantAppPage').classList.remove('active');
      authPage.classList.add('active');
      if (!data.success) {
        authPage.innerHTML = '<div class="auth-card"><h2>رابط كلمة المرور غير صالح</h2>' +
          '<p>انتهت صلاحية الرابط أو تم استخدامه.</p>' +
          '<button class="auth-btn" onclick="window.location.href=\'/\'">العودة لتسجيل الدخول</button></div>';
        return;
      }
      authPage.innerHTML = '<div class="auth-card">' +
        '<h2>تعيين كلمة المرور</h2>' +
        '<p>' + escapeHtml(data.companyName || '') + '</p>' +
        '<div class="tenant-grid full" style="margin-bottom:16px;text-align:right">' +
        '<div class="tenant-field"><label>البريد الإلكتروني</label><p style="margin:0">' +
        escapeHtml(data.email || '') + '</p></div></div>' +
        '<div id="passwordSetupError" class="auth-error"></div>' +
        '<form class="auth-form active" onsubmit="handlePasswordSetup(event, \'' +
        rawToken.replace(/'/g, '') + '\')">' +
        '<label>كلمة المرور الجديدة</label>' +
        '<div style="position:relative;margin-bottom:12px">' +
        '<input type="password" id="passwordSetupValue" minlength="10" autocomplete="new-password" required style="padding-left:70px;margin-bottom:0">' +
        '<button type="button" onclick="togglePasswordSetupVisibility(\'passwordSetupValue\', this)" style="position:absolute;left:10px;top:50%;transform:translateY(-50%);border:0;background:none;color:var(--p);font-weight:800;font-size:13px;font-family:inherit;cursor:pointer;padding:4px 6px">إظهار</button></div>' +
        '<label>تأكيد كلمة المرور</label>' +
        '<div style="position:relative">' +
        '<input type="password" id="passwordSetupConfirm" minlength="10" autocomplete="new-password" required style="padding-left:70px;margin-bottom:0">' +
        '<button type="button" onclick="togglePasswordSetupVisibility(\'passwordSetupConfirm\', this)" style="position:absolute;left:10px;top:50%;transform:translateY(-50%);border:0;background:none;color:var(--p);font-weight:800;font-size:13px;font-family:inherit;cursor:pointer;padding:4px 6px">إظهار</button></div>' +
        '<button type="submit" class="auth-btn">اعتماد كلمة المرور</button>' +
        '</form></div>';
    }

    function togglePasswordVisibility(inputId, btn) {
      const input = document.getElementById(inputId);
      if (!input) return;
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      if (btn) btn.textContent = show ? 'إخفاء' : 'إظهار';
    }

    function togglePasswordSetupVisibility(inputId, btn) {
      togglePasswordVisibility(inputId, btn);
    }

    async function handlePasswordSetup(event, rawToken) {
      event.preventDefault();
      const password = document.getElementById('passwordSetupValue').value;
      const confirmation = document.getElementById('passwordSetupConfirm').value;
      const errorHost = document.getElementById('passwordSetupError');
      errorHost.textContent = '';
      if (password !== confirmation) {
        errorHost.textContent = 'كلمتا المرور غير متطابقتين';
        return;
      }
      const pwError = passwordPolicyError(password);
      if (pwError) { errorHost.textContent = pwError; return; }
      const data = await api(
        'POST',
        '/api/auth/password-setup/' + encodeURIComponent(rawToken),
        { password }
      );
      if (!data.success || !data.token) {
        errorHost.textContent = data.error || 'تعذر اعتماد كلمة المرور';
        return;
      }
      setTenantToken(data.token);
      setTenantUser(data.tenant);
      try {
        tenantUser = data.tenant;
        const next = (typeof tenantCanonicalRoute === 'function' && tenantCanonicalRoute('tenantDashboardPage')) || '/app/dashboard';
        window.history.replaceState({}, '', next);
      } catch (e) { window.history.replaceState({}, '', '/app/dashboard'); }
      await bootstrapTenant();
    }

    async function showInvitePage(inviteToken) {
      const data = await api('GET', '/api/invite/' + inviteToken);
      const authPage = document.getElementById('tenantAuthPage');
      if (!data.success) {
        authPage.innerHTML = '<div class="auth-card"><h2>الدعوة غير صالحة</h2><p>رابط الدعوة منتهي أو مستخدم بالفعل.</p><button class="auth-btn" onclick="window.location.href=\'/\'">العودة للرئيسية</button></div>';
        authPage.style.display = 'flex';
        return;
      }
      authPage.innerHTML = '<div class="auth-card">' +
        '<h2>دعوة انضمام للشركة</h2>' +
        '<p>تمت دعوتك للانضمام لـ <strong>' + escapeHtml(data.companyName) + '</strong></p>' +
        '<p class="tenant-hint">البريد: ' + escapeHtml(data.email) + '</p>' +
        '<div id="inviteError" class="auth-error"></div>' +
        '<form class="auth-form active" onsubmit="handleInviteRegister(event, \'' + inviteToken + '\')">' +
        '<label>الاسم الكامل *</label>' +
        '<input type="text" id="inviteName" placeholder="اسمك الكامل" required>' +
        '<label>كلمة المرور (10 أحرف على الأقل، حروف وأرقام) *</label>' +
        '<div style="position:relative">' +
        '<input type="password" id="invitePassword" placeholder="كلمة المرور" required minlength="10" style="padding-left:64px">' +
        '<button type="button" onclick="togglePasswordVisibility(\'invitePassword\', this)" style="position:absolute;left:10px;top:50%;transform:translateY(-50%);border:0;background:none;color:var(--p);font-weight:800;font-size:13px;font-family:inherit;cursor:pointer;padding:4px 6px">إظهار</button></div>' +
        '<button type="submit" class="auth-btn">إنشاء حسابي</button>' +
        '</form></div>';
      authPage.style.display = 'flex';
    }

    async function handleInviteRegister(e, inviteToken) {
      e.preventDefault();
      const name = document.getElementById('inviteName').value.trim();
      const password = document.getElementById('invitePassword').value;
      showTenantError('inviteError', '');
      const pwError = passwordPolicyError(password);
      if (pwError) { showTenantError('inviteError', pwError); return; }
      const data = await api('POST', '/api/invite/' + inviteToken + '/register', { name, password });
      if (data.success && data.token) {
        setTenantToken(data.token);
        setTenantUser(data.tenant);
        window.history.replaceState({}, '', '/');
        await bootstrapTenant();
      } else {
        showTenantError('inviteError', data.error || 'فشل إنشاء الحساب');
      }
    }

    initTenant();