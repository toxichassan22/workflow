/* 06a-team-library.js — company team library (فريق التطوير).
   One flat library shared by every project file; each entity states its own role.
   Cards keep an equal height, the brief is always two lines with a fade, and the
   add/edit form lives in one drawer. Reordering is drag or Arrow Up/Down on the
   «ترتيب» control. */

let tenantTeamEntities = [];
let editingTeamEntityId = null;
let teamLogoObjectUrl = null;
let teamLogoRemoved = false;
let draggedTeamEntityId = null;

function teamEntityEsc(value) {
  return escapeHtml(value == null ? '' : String(value));
}

function teamEntityProjects(entity) {
  return String(entity?.notableProjects || '')
    .split(/\n+/)
    .map(item => item.trim())
    .filter(Boolean);
}

function teamEntityMonogramHtml(name) {
  const letter = String(name || '').trim().charAt(0) || '—';
  return '<span class="team-logo-mono">' + teamEntityEsc(letter) + '</span>';
}

function currentTeamEntity() {
  if (!editingTeamEntityId) return null;
  return tenantTeamEntities.find(item => String(item.id) === String(editingTeamEntityId)) || null;
}

function updateTeamEntityLogoState() {
  const label = document.getElementById('teamEntityLogoName');
  const file = document.getElementById('teamEntityLogo')?.files?.[0];
  const entity = currentTeamEntity();
  const hasStored = !teamLogoRemoved && !!entity?.logoFileId;
  if (label) {
    if (file) label.textContent = file.name;
    else if (hasStored) label.textContent = WFT('team.logo_current', 'الشعار المحفوظ');
    else label.textContent = WFT('team.logo_none', 'لا يوجد شعار');
  }
  const hasLogo = !!file || hasStored;
  const pick = document.getElementById('teamEntityLogoPick');
  if (pick) {
    pick.textContent = hasLogo
      ? WFT('team.logo_change', 'تغيير الشعار')
      : WFT('team.logo_add', 'إضافة شعار');
  }
  const clear = document.getElementById('teamEntityLogoClear');
  if (clear) clear.hidden = !hasLogo;
}

function focusTeamOrderButton(entityId) {
  document.querySelectorAll('#tenantTeamList .team-card').forEach(card => {
    if (card.dataset.teamId === String(entityId)) {
      card.querySelector('.team-order')?.focus();
    }
  });
}

async function openTenantTeam() {
  showTenantPage('tenantTeamPage');
  closeTeamEntityDrawer();
  await loadTenantTeamEntities();
}

async function loadTenantTeamEntities() {
  const data = await api('GET', '/api/team-entities');
  tenantTeamEntities = data.success ? (data.entities || []) : [];
  renderTenantTeamList();
  return tenantTeamEntities;
}

function renderTenantTeamList() {
  const host = document.getElementById('tenantTeamList');
  if (!host) return;

  const count = document.getElementById('tenantTeamCount');
  if (count) count.textContent = WFT('team.count', '{n} جهة مسجلة', { n: tenantTeamEntities.length });

  if (!tenantTeamEntities.length) {
    host.innerHTML = '<div class="team-empty">' +
      '<div class="team-empty-mono">—</div>' +
      '<div class="team-empty-title">' + WFT('team.empty_title', 'لا توجد جهات مسجلة') + '</div>' +
      '<div class="team-empty-sub">' + WFT('team.empty_sub', 'مكتبة المنشأة فارغة حالياً') + '</div>' +
      '</div>';
    return;
  }

  host.innerHTML = '<div class="team-grid">' + tenantTeamEntities.map(teamEntityCardHtml).join('') + '</div>';
  host.querySelectorAll('img[data-team-logo]').forEach(image => {
    image.addEventListener('load', () => {
      const tile = image.closest('.team-logo');
      if (tile && typeof adaptTenantLogoChip === 'function') adaptTenantLogoChip(image, tile);
    }, { once: true });
    attachProjectFileThumbnail(image, image.dataset.teamLogo);
  });
  bindTeamDragAndDrop();
}

function teamEntityCardHtml(entity) {
  const projects = teamEntityProjects(entity);
  const safeId = String(entity.id || '').replace(/'/g, "\\'");
  const logo = entity.logoFileId
    ? '<img data-team-logo="' + teamEntityEsc(entity.logoFileId) + '" alt="">'
    : teamEntityMonogramHtml(entity.name);
  const chips = [
    entity.experienceYears
      ? '<span class="team-chip is-teal">' + teamEntityEsc(WFT('team.experience_years', '{n} سنة خبرة', { n: entity.experienceYears })) + '</span>'
      : '',
    projects.length
      ? '<span class="team-chip">' + teamEntityEsc(WFT('team.projects_count', '{n} مشاريع موثقة', { n: projects.length })) + '</span>'
      : '',
  ].join('');

  return '<article class="team-card" draggable="true" data-team-id="' + teamEntityEsc(entity.id) + '">' +
    '<div class="team-card-head">' +
      '<div class="team-logo">' + logo + '</div>' +
      '<div class="team-card-name">' +
        '<strong title="' + teamEntityEsc(entity.name) + '">' + teamEntityEsc(entity.name) + '</strong>' +
        (entity.role ? '<div class="team-card-role">' + teamEntityEsc(entity.role) + '</div>' : '') +
      '</div>' +
    '</div>' +
    '<div class="team-chips">' + chips + '</div>' +
    '<div class="team-brief">' + teamEntityEsc(entity.brief) + '</div>' +
    '<div class="team-card-foot">' +
      '<button type="button" class="team-action is-edit" onclick="editTeamEntity(\'' + safeId + '\')">' +
        WFT('common.edit', 'تعديل') + '</button>' +
      '<button type="button" class="team-action is-delete" onclick="deleteTeamEntity(\'' + safeId + '\')">' +
        WFT('common.delete', 'حذف') + '</button>' +
      '<button type="button" class="team-order" title="' + teamEntityEsc(WFT('team.reorder_title', 'اسحب البطاقة لإعادة الترتيب')) + '" ' +
        'aria-label="' + teamEntityEsc(WFT('team.reorder', 'ترتيب')) + '" ' +
        'onkeydown="handleTeamOrderKey(event, \'' + safeId + '\')">' +
        WFT('team.reorder', 'ترتيب') + '</button>' +
    '</div>' +
  '</article>';
}

function bindTeamDragAndDrop() {
  document.querySelectorAll('#tenantTeamList .team-card').forEach(card => {
    card.addEventListener('dragstart', event => {
      draggedTeamEntityId = card.dataset.teamId;
      card.classList.add('is-dragging');
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', draggedTeamEntityId);
      }
    });
    card.addEventListener('dragend', () => {
      draggedTeamEntityId = null;
      document.querySelectorAll('#tenantTeamList .team-card').forEach(item => {
        item.classList.remove('is-dragging', 'is-drop-target');
      });
    });
    card.addEventListener('dragover', event => {
      if (!draggedTeamEntityId || draggedTeamEntityId === card.dataset.teamId) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
      card.classList.add('is-drop-target');
    });
    card.addEventListener('dragleave', () => card.classList.remove('is-drop-target'));
    card.addEventListener('drop', event => {
      event.preventDefault();
      card.classList.remove('is-drop-target');
      const sourceId = draggedTeamEntityId || (event.dataTransfer && event.dataTransfer.getData('text/plain'));
      if (!sourceId || sourceId === card.dataset.teamId) return;
      const fromIndex = tenantTeamEntities.findIndex(item => String(item.id) === String(sourceId));
      const toIndex = tenantTeamEntities.findIndex(item => String(item.id) === String(card.dataset.teamId));
      if (fromIndex < 0 || toIndex < 0) return;
      moveTeamEntity(fromIndex, toIndex);
    });
  });
}

function handleTeamOrderKey(event, entityId) {
  if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
  event.preventDefault();
  const index = tenantTeamEntities.findIndex(item => String(item.id) === String(entityId));
  if (index < 0) return;
  const target = event.key === 'ArrowUp' ? index - 1 : index + 1;
  if (target < 0 || target >= tenantTeamEntities.length) return;
  moveTeamEntity(index, target);
}

async function moveTeamEntity(fromIndex, toIndex) {
  if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0) return;
  const next = tenantTeamEntities.slice();
  const [moved] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, moved);
  tenantTeamEntities = next;
  draggedTeamEntityId = null;
  renderTenantTeamList();
  await persistTeamOrder(moved.id);
}

async function persistTeamOrder(focusId) {
  try {
    const response = await api('POST', '/api/team-entities/reorder', {
      entityIds: tenantTeamEntities.map(item => item.id),
    });
    if (!response?.success) {
      toast(response?.error || WFT('team.reorder_failed', 'تعذر حفظ الترتيب'));
      await loadTenantTeamEntities();
      return;
    }
    if (Array.isArray(response.entities)) tenantTeamEntities = response.entities;
    renderTenantTeamList();
    if (focusId) focusTeamOrderButton(focusId);
  } catch (error) {
    toast(error.message || WFT('team.reorder_failed', 'تعذر حفظ الترتيب'));
    await loadTenantTeamEntities();
  }
}

function openTeamEntityDrawer(entityId) {
  resetTeamEntityForm();
  editingTeamEntityId = entityId ? String(entityId) : null;
  const entity = currentTeamEntity();
  if (entity) {
    document.getElementById('teamEntityName').value = entity.name || '';
    document.getElementById('teamEntityRole').value = entity.role || '';
    document.getElementById('teamEntityExperience').value = entity.experienceYears || '';
    document.getElementById('teamEntityBrief').value = entity.brief || '';
    document.getElementById('teamEntityProjects').value = entity.notableProjects || '';
  }
  updateTeamEntityDrawerLabels();
  updateTeamEntityLogoState();
  updateTeamEntityPreview();
  const drawer = document.getElementById('teamEntityDrawer');
  if (drawer) {
    drawer.classList.add('is-open');
    document.body.classList.add('team-drawer-open');
    setTimeout(() => document.getElementById('teamEntityName')?.focus(), 40);
  }
}

function closeTeamEntityDrawer() {
  document.getElementById('teamEntityDrawer')?.classList.remove('is-open');
  document.body.classList.remove('team-drawer-open');
  resetTeamEntityForm();
}

function resetTeamEntityForm() {
  editingTeamEntityId = null;
  teamLogoRemoved = false;
  ['teamEntityName', 'teamEntityRole', 'teamEntityExperience', 'teamEntityBrief', 'teamEntityProjects'].forEach(id => {
    const field = document.getElementById(id);
    if (field) field.value = '';
  });
  const logo = document.getElementById('teamEntityLogo');
  if (logo) logo.value = '';
  releaseTeamLogoObjectUrl();
  updateTeamEntityDrawerLabels();
  updateTeamEntityLogoState();
  updateTeamEntityPreview();
}

function updateTeamEntityDrawerLabels() {
  const title = document.getElementById('teamEntityDrawerTitle');
  if (title) {
    title.textContent = editingTeamEntityId
      ? WFT('team.edit_title', 'تعديل بيانات الجهة')
      : WFT('team.add_title', 'إضافة جهة جديدة');
  }
  const save = document.getElementById('teamEntitySaveBtn');
  if (save) {
    save.textContent = editingTeamEntityId
      ? WFT('team.edit_save', 'حفظ التعديل')
      : WFT('team.add_save', 'إضافة الجهة');
  }
}

function updateTeamEntityPreview() {
  const entity = currentTeamEntity();
  const name = (document.getElementById('teamEntityName')?.value || '').trim();
  const role = (document.getElementById('teamEntityRole')?.value || '').trim();
  const nameHost = document.getElementById('teamEntityPreviewName');
  const roleHost = document.getElementById('teamEntityPreviewRole');
  if (nameHost) nameHost.textContent = name || WFT('team.preview_name', 'اسم الجهة');
  if (roleHost) roleHost.textContent = role || WFT('team.preview_role', 'الدور');

  const host = document.getElementById('teamEntityPreviewLogo');
  if (!host) return;
  const logoId = teamLogoRemoved ? '' : (entity?.logoFileId || '');
  const mode = teamLogoObjectUrl
    ? 'local:' + teamLogoObjectUrl
    : (logoId ? 'file:' + logoId : 'mono:' + name);
  if (host.dataset.previewMode === mode) return;
  host.dataset.previewMode = mode;
  delete host.dataset.logoTone;

  const applyTone = image => {
    if (typeof adaptTenantLogoChip === 'function') adaptTenantLogoChip(image, host);
  };
  if (teamLogoObjectUrl) {
    host.innerHTML = '<img src="' + teamLogoObjectUrl + '" alt="">';
    const image = host.querySelector('img');
    if (image.complete) applyTone(image);
    else image.addEventListener('load', () => applyTone(image), { once: true });
  } else if (logoId) {
    host.innerHTML = '<img alt="">';
    const image = host.querySelector('img');
    image.addEventListener('load', () => applyTone(image), { once: true });
    attachProjectFileThumbnail(image, logoId);
  } else {
    host.innerHTML = teamEntityMonogramHtml(name);
  }
}

function handleTeamLogoSelection(input) {
  const file = input?.files?.[0];
  teamLogoRemoved = false;
  releaseTeamLogoObjectUrl();
  if (!file) {
    updateTeamEntityLogoState();
    updateTeamEntityPreview();
    return;
  }
  teamLogoObjectUrl = URL.createObjectURL(file);
  updateTeamEntityLogoState();
  updateTeamEntityPreview();
}

function clearTeamEntityLogo() {
  teamLogoRemoved = true;
  const input = document.getElementById('teamEntityLogo');
  if (input) input.value = '';
  releaseTeamLogoObjectUrl();
  updateTeamEntityLogoState();
  updateTeamEntityPreview();
}

function releaseTeamLogoObjectUrl() {
  if (teamLogoObjectUrl) {
    URL.revokeObjectURL(teamLogoObjectUrl);
    teamLogoObjectUrl = null;
  }
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
    throw new Error(response?.error || WFT('team.logo_failed', 'تعذر رفع شعار الجهة'));
  }
  return response.file.id;
}

async function submitTeamEntity() {
  const payload = {
    name: (document.getElementById('teamEntityName')?.value || '').trim(),
    role: (document.getElementById('teamEntityRole')?.value || '').trim(),
    experienceYears: (document.getElementById('teamEntityExperience')?.value || '').trim(),
    brief: (document.getElementById('teamEntityBrief')?.value || '').trim(),
    notableProjects: (document.getElementById('teamEntityProjects')?.value || '').trim(),
  };
  if (!payload.name) {
    toast(WFT('team.name_required', 'اسم الجهة مطلوب'));
    return;
  }

  showLoader(WFT('team.saving', 'حفظ الجهة'), WFT('team.saving_desc', 'جاري الحفظ...'), 20);
  try {
    const logoId = await uploadTeamLogo();
    if (logoId) payload.logoFileId = logoId;
    else if (teamLogoRemoved) payload.logoFileId = '';
    // Editing without picking a new logo keeps the stored one.
    else if (editingTeamEntityId) {
      const current = currentTeamEntity();
      if (current?.logoFileId) payload.logoFileId = current.logoFileId;
    }
    const response = editingTeamEntityId
      ? await api('PUT', '/api/team-entities/' + encodeURIComponent(editingTeamEntityId), payload)
      : await api('POST', '/api/team-entities', payload);
    if (!response?.success) {
      toast(response?.error || WFT('team.save_failed', 'تعذر حفظ الجهة'));
      return;
    }
    toast(editingTeamEntityId ? WFT('team.updated', 'تم تحديث الجهة') : WFT('team.added', 'تم إضافة الجهة'));
    closeTeamEntityDrawer();
    await loadTenantTeamEntities();
  } catch (error) {
    toast(error.message || WFT('team.save_failed', 'تعذر حفظ الجهة'));
  } finally {
    hideLoader();
  }
}

function editTeamEntity(entityId) {
  openTeamEntityDrawer(entityId);
}

async function deleteTeamEntity(entityId) {
  const entity = tenantTeamEntities.find(item => String(item.id) === String(entityId));
  if (!confirm(WFT('team.entity_delete_confirm', 'حذف «{name}» من كل المشاريع؟', { name: entity?.name || WFT('team.entity', 'الجهة') }))) return;
  const response = await api('DELETE', '/api/team-entities/' + encodeURIComponent(entityId));
  if (!response?.success) {
    toast(response?.error || WFT('team.delete_failed', 'تعذر حذف الجهة'));
    return;
  }
  toast(WFT('team.deleted', 'تم حذف الجهة'));
  if (editingTeamEntityId === String(entityId)) closeTeamEntityDrawer();
  await loadTenantTeamEntities();
}

document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  const drawer = document.getElementById('teamEntityDrawer');
  if (drawer?.classList.contains('is-open')) {
    event.preventDefault();
    closeTeamEntityDrawer();
  }
});

document.addEventListener('wf:lang', () => {
  if (document.getElementById('tenantTeamList')) renderTenantTeamList();
  updateTeamEntityDrawerLabels();
  updateTeamEntityLogoState();
  updateTeamEntityPreview();
});
