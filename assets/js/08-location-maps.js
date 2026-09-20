/* 08-location-maps.js - index.html lines 14086-15732, shared global scope, classic scripts in order */

    function addLocationTableRow(key, row) {
      row = row || {};
      const table = document.querySelector('#tenantProjectForm table.location-table[data-location-table="' + key + '"]');
      if (!table) return;
      const cfg = LOCATION_TABLE_FIELDS[key] || {};
      const tbody = table.querySelector('tbody');
      const tr = document.createElement('tr');
      tr.dataset.rowSource = row.row_source || row.rowSource || (row.name ? 'ai' : 'manual');
      tr.dataset.lat = row.lat ?? row.latitude ?? '';
      tr.dataset.lng = row.lng ?? row.longitude ?? '';

      const nameTd = document.createElement('td');
      const nameInput = document.createElement(cfg.road ? 'textarea' : 'input');
      if (!cfg.road) nameInput.type = 'text';
      if (cfg.road) nameInput.rows = 1;
      nameInput.className = 'lt-name-input';
      nameInput.placeholder = cfg.nameHint || 'الاسم';
      nameInput.value = row.name || '';
      nameTd.appendChild(nameInput);

      let categoryTd = null;
      let categoryInput = null;
      if (cfg.categoryLabel) {
        categoryTd = document.createElement('td');
        categoryInput = document.createElement('input');
        categoryInput.type = 'text';
        categoryInput.className = 'lt-category-input';
        categoryInput.placeholder = cfg.categoryLabel;
        categoryInput.value = row.category || '';
        categoryTd.appendChild(categoryInput);
      }

      const distTd = document.createElement('td');
      const distInput = document.createElement('input');
      distInput.type = 'number';
      distInput.className = 'lt-dist-input';
      distInput.min = '0';
      distInput.step = '0.1';
      distInput.placeholder = '—';
      if (row.distance_km !== undefined && row.distance_km !== null && row.distance_km !== '') distInput.value = row.distance_km;
      if (cfg.nameOnly) distTd.style.display = 'none';
      distTd.appendChild(distInput);

      const durTd = document.createElement('td');
      const durInput = document.createElement('input');
      durInput.type = 'number';
      durInput.className = 'lt-dur-input';
      durInput.min = '0';
      durInput.step = '1';
      durInput.placeholder = '—';
      if (row.duration_minutes !== undefined && row.duration_minutes !== null && row.duration_minutes !== '') durInput.value = row.duration_minutes;
      if (cfg.nameOnly) durTd.style.display = 'none';
      durTd.appendChild(durInput);

      let selectTd = null;
      let selectInput = null;
      if (cfg.mapSelectable) {
        selectTd = document.createElement('td');
        selectTd.className = 'lt-map-toggle';
        selectInput = document.createElement('input');
        selectInput.type = 'checkbox';
        selectInput.className = 'lt-map-select';
        selectInput.checked = !!(row.show_on_map || row.selected);
        selectInput.addEventListener('change', () => {
          const selected = table.querySelectorAll('.lt-map-select:checked');
          if (selected.length > 7) {
            selectInput.checked = false;
            toast('الحد الأقصى 7 معالم لكل خريطة');
          }
          serializeLocationTable(key);
          if (key === 'city_landmarks') invalidateCatchmentMapApproval();
          if (key === 'nearby_landmarks') invalidateLandmarksMapApproval();
          invalidateLocationAnalysisApproval();
        });
        selectTd.appendChild(selectInput);
      }

      const delTd = document.createElement('td');
      delTd.className = 'lt-actions';
      const actionGroup = document.createElement('div');
      actionGroup.className = 'lt-action-group';
      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.dataset.sectionLockIgnore = '1';
      delBtn.className = 'btn small danger lt-del';
      delBtn.title = 'حذف الصف';
      delBtn.textContent = 'حذف';
      delBtn.addEventListener('click', () => {
        const roadName = nameInput.value.trim();
        tr.remove();
        if (cfg.road && roadName) {
          tenantProjectData.manual_road_paths = (tenantProjectData.manual_road_paths || [])
            .filter(item => String(item?.name || '').trim() !== roadName);
        }
        serializeLocationTable(key);
        if (cfg.road) invalidateAccessMapApproval();
        if (key === 'city_landmarks') invalidateCatchmentMapApproval();
        if (key === 'nearby_landmarks') invalidateLandmarksMapApproval();
        invalidateLocationAnalysisApproval();
      });
      if (cfg.road) {
        const drawBtn = document.createElement('button');
        drawBtn.type = 'button';
        drawBtn.dataset.sectionLockIgnore = '1';
        drawBtn.className = 'btn small ghost';
        drawBtn.textContent = 'تحديد المسار';
        drawBtn.addEventListener('click', () => startManualRoadDrawingFromTable(nameInput.value));
        actionGroup.appendChild(drawBtn);
      }
      if (cfg.mapSelectable) {
        const placeBtn = document.createElement('button');
        placeBtn.type = 'button';
        placeBtn.dataset.sectionLockIgnore = '1';
        placeBtn.className = 'btn small ghost';
        placeBtn.textContent = 'تحديد الموقع';
        placeBtn.addEventListener('click', () => startLandmarkPlacement(key, tr));
        actionGroup.appendChild(placeBtn);
      }
      actionGroup.appendChild(delBtn);
      delTd.appendChild(actionGroup);

      [nameInput, categoryInput, distInput, durInput].filter(Boolean).forEach(inp => inp.addEventListener('input', () => {
        serializeLocationTable(key);
        if (cfg.road) invalidateAccessMapApproval();
        if (key === 'city_landmarks') invalidateCatchmentMapApproval();
        if (key === 'nearby_landmarks') invalidateLandmarksMapApproval();
        invalidateLocationAnalysisApproval();
      }));

      tr.appendChild(nameTd);
      if (categoryTd) tr.appendChild(categoryTd);
      tr.appendChild(distTd);
      tr.appendChild(durTd);
      if (selectTd) tr.appendChild(selectTd);
      tr.appendChild(delTd);
      tbody.appendChild(tr);
    }

    function setLocationTableValue(key, value) {
      const table = document.querySelector('#tenantProjectForm table.location-table[data-location-table="' + key + '"]');
      if (!table) return;
      const tbody = table.querySelector('tbody');
      tbody.innerHTML = '';
      let rows = parseLocationFieldText(key, value);
      if (key === 'main_roads') {
        const seen = new Set();
        rows = rows.flatMap(row => normalizeAccessRoadNames([row.name]).map(name => ({ ...row, name })))
          .filter(row => {
            const normalized = row.name.replace(/^(طريق|شارع|جادة|ممر)\s+/, '').replace(/[\sـ]+/g, ' ').trim().toLowerCase();
            if (!normalized || seen.has(normalized)) return false;
            seen.add(normalized);
            return true;
          });
      }
      (rows.length ? rows : [{}]).forEach(r => addLocationTableRow(key, r));
      serializeLocationTable(key);
    }

    function refreshLocationTables() {
      Object.keys(LOCATION_TABLE_FIELDS).forEach(key => {
        const hidden = document.querySelector('#tenantProjectForm [data-key="' + key + '"].location-table-value');
        if (!hidden) return;
        const structured = key === 'main_roads'
          ? tenantProjectData.main_roads_data
          : key === 'nearby_landmarks' ? tenantProjectData.nearby_landmarks_data
            : key === 'city_landmarks' ? tenantProjectData.city_landmarks_data : null;
        setLocationTableValue(key, Array.isArray(structured) && structured.length ? structured : hidden.value);
      });
    }

    function createLocationTableField(key, labelText, currentValue) {
      const cfg = LOCATION_TABLE_FIELDS[key];
      const wrap = document.createElement('div');
      wrap.className = 'tenant-field full location-table-field';

      const label = document.createElement('label');
      label.textContent = labelText;
      wrap.appendChild(label);

      const tableWrap = document.createElement('div');
      tableWrap.className = 'fin-table-wrap';
      const table = document.createElement('table');
      table.className = 'fin-table location-table' + (cfg.road ? ' location-road-table' : '');
      table.dataset.locationTable = key;
      const categoryHeader = cfg.categoryLabel ? '<th>' + cfg.categoryLabel + '</th>' : '';
      const metricHeaders = cfg.nameOnly ? '' : '<th class="lt-dist">المسافة (كم)</th><th class="lt-dur">المدة (دقائق)</th>';
      const mapHeaders = cfg.mapSelectable ? '<th class="lt-map-toggle">إظهار في الخريطة</th>' : '';
      table.innerHTML = '<thead><tr>' +
        '<th>' + cfg.nameLabel + '</th>' + categoryHeader + metricHeaders + mapHeaders +
        '<th class="lt-actions">الإجراءات</th>' +
        '</tr></thead><tbody></tbody>';
      tableWrap.appendChild(table);
      wrap.appendChild(tableWrap);

      const addBtn = document.createElement('button');
      addBtn.type = 'button';
      addBtn.dataset.sectionLockIgnore = '1';
      addBtn.className = 'btn ghost small location-table-add';
      addBtn.textContent = '+ إضافة صف';
      addBtn.addEventListener('click', () => {
        addLocationTableRow(key, {});
        if (key === 'main_roads') invalidateAccessMapApproval();
        if (key === 'city_landmarks') invalidateCatchmentMapApproval();
        if (key === 'nearby_landmarks') invalidateLandmarksMapApproval();
        invalidateLocationAnalysisApproval();
        const tbody = table.querySelector('tbody');
        const last = tbody.lastElementChild;
        if (last) last.querySelector('.lt-name-input').focus();
      });
      wrap.appendChild(addBtn);
      if (key === 'nearby_landmarks') {
        const fetchedAt = tenantProjectData.location_data_fetched_at || '';
        const display = document.createElement('div');
        display.id = 'locationDataFetchedAtDisplay';
        display.className = 'location-table-hint';
        display.textContent = fetchedAt ? 'آخر تحديث للبيانات: ' + formatLocationDataFetchedAt(fetchedAt) : '';
        wrap.appendChild(display);
        const fetchedInput = document.createElement('input');
        fetchedInput.type = 'hidden';
        fetchedInput.id = 'locationDataFetchedAt';
        fetchedInput.dataset.key = 'location_data_fetched_at';
        fetchedInput.dataset.type = 'text';
        fetchedInput.value = fetchedAt;
        wrap.appendChild(fetchedInput);
      }
      const hint = document.createElement('div');
      hint.className = 'location-table-hint';
      hint.textContent = 'مصدر البيانات: تحليل الموقع';
      wrap.appendChild(hint);

      const hidden = document.createElement('input');
      hidden.type = 'hidden';
      hidden.dataset.key = key;
      hidden.dataset.type = 'textarea';
      hidden.className = 'location-table-value';
      hidden.value = currentValue || '';
      wrap.appendChild(hidden);

      setTimeout(() => setLocationTableValue(key, hidden.value), 0);
      return wrap;
    }

    const LOCATION_ANALYSIS_KEYS = [
      'location_address', 'location_lat', 'location_lng', 'city', 'district',
      'main_roads', 'nearby_landmarks', 'city_landmarks', 'location_detail'
    ];

    function locationTableRows(key) {
      const table = document.querySelector('#tenantProjectForm table.location-table[data-location-table="' + key + '"]');
      if (!table) return [];
      return Array.from(table.querySelectorAll('tbody tr')).map(tr => ({
        tr,
        name: tr.querySelector('.lt-name-input')?.value?.trim() || '',
        category: tr.querySelector('.lt-category-input')?.value?.trim() || '',
        distance: tr.querySelector('.lt-dist-input')?.value?.trim() || '',
        duration: tr.querySelector('.lt-dur-input')?.value?.trim() || '',
        lat: tr.dataset.lat || '', lng: tr.dataset.lng || '',
        rowSource: tr.dataset.rowSource || 'manual'
      })).filter(row => row.name);
    }

    function validateLocationAnalysisApproval() {
      Object.keys(LOCATION_TABLE_FIELDS).forEach(serializeLocationTable);
      const missing = LOCATION_ANALYSIS_KEYS.filter(key => {
        const input = document.querySelector('#tenantProjectForm [data-key="' + key + '"]');
        return !String(input?.value || tenantProjectData[key] || '').trim();
      });
      for (const key of ('nearby_landmarks city_landmarks').split(' ')) {
        const invalid = locationTableRows(key).find(row => row.rowSource === 'manual' && (
          !row.category || !row.distance || !row.duration));
        if (invalid) return { valid: false, message: 'بيانات المعلم اليدوي غير مكتملة: الاسم والنوع والمسافة والمدة مطلوبة.' };
      }
      return missing.length
        ? { valid: false, message: 'بيانات تحليل الموقع غير مكتملة: ' + missing.join('، ') }
        : { valid: true, message: '' };
    }

    function releaseLocationSectionApproval() {
      if (tenantProjectSectionStatuses.location !== 'approved') return false;
      applySectionStatuses({ location: 'draft' });
      return true;
    }

    function invalidateAccessMapApproval() {
      if (!tenantCreativeImages.map_approvals?.access) return;
      tenantCreativeImages.map_approvals = { ...(tenantCreativeImages.map_approvals || {}), access: false };
      releaseLocationSectionApproval();
      renderLocationWorkflowState();
      triggerAutoSaveDraft();
    }

    function invalidateCatchmentMapApproval() {
      if (!tenantCreativeImages.map_approvals?.catchment) return;
      tenantCreativeImages.map_approvals = { ...(tenantCreativeImages.map_approvals || {}), catchment: false };
      releaseLocationSectionApproval();
      renderLocationWorkflowState();
      triggerAutoSaveDraft();
    }

    function invalidateLandmarksMapApproval() {
      if (!tenantCreativeImages.map_approvals?.landmarks) return;
      tenantCreativeImages.map_approvals = { ...(tenantCreativeImages.map_approvals || {}), landmarks: false };
      releaseLocationSectionApproval();
      renderLocationWorkflowState();
      triggerAutoSaveDraft();
    }

    function invalidateLocationAnalysisApproval() {
      const changed = !!tenantProjectData.location_analysis_approved;
      tenantProjectData.location_analysis_approved = false;
      const sectionChanged = releaseLocationSectionApproval();
      const input = document.getElementById('locationAnalysisApproved');
      if (input) input.value = '';
      if (!changed && !sectionChanged) return;
      renderLocationWorkflowState();
      triggerAutoSaveDraft();
    }

    async function toggleLocationAnalysisApproval() {
      if (tenantProjectData.location_analysis_approved) {
        tenantProjectData.location_analysis_approved = false;
        releaseLocationSectionApproval();
      } else {
        const validation = validateLocationAnalysisApproval();
        if (!validation.valid) { toast(validation.message); return; }
        tenantProjectData.location_analysis_approved = true;
        tenantProjectData.location_analysis_approved_at = new Date().toISOString();
      }
      const input = document.getElementById('locationAnalysisApproved');
      if (input) input.value = tenantProjectData.location_analysis_approved ? 'true' : '';
      await saveMapPreviewState();
      renderLocationWorkflowState();
    }

    function renderLocationWorkflowState() {
      const approved = !!tenantProjectData.location_analysis_approved;
      const approvalInput = document.getElementById('locationAnalysisApproved');
      if (approvalInput) approvalInput.value = approved ? 'true' : '';
      const button = document.getElementById('locationAnalysisApprovalButton');
      if (button) button.textContent = approved ? 'إلغاء اعتماد تحليل الموقع' : 'اعتماد تحليل الموقع';
      const status = document.getElementById('locationAnalysisApprovalStatus');
      if (status) status.textContent = approved ? 'تحليل الموقع معتمد' : 'تحليل الموقع يحتاج اعتمادًا قبل توليد الخرائط';
      const overview = typeof MAP_PREVIEW_VIEW_DEFS !== 'undefined' ? MAP_PREVIEW_VIEW_DEFS[0] : null;
      const overviewGenerated = mapPreviewIsGenerated(overview);
      const generateOverviewButton = document.getElementById('generateOverviewMapButton');
      if (generateOverviewButton) generateOverviewButton.disabled = !approved || overviewGenerated;
      LOCATION_ANALYSIS_KEYS.forEach(key => {
        const input = document.querySelector('#tenantProjectForm [data-key="' + key + '"]');
        if (input && input.type !== 'hidden') input.disabled = approved;
      });
      Object.keys(LOCATION_TABLE_FIELDS).forEach(key => {
        const roadModeLocked = key === 'main_roads' && (tenantRoadEditMode || !!tenantRoadDrawingTarget);
        const catchmentModeLocked = key === 'city_landmarks' && tenantCatchmentEditMode;
        const landmarksModeLocked = key === 'nearby_landmarks' && tenantLandmarksEditMode;
        document.querySelectorAll('#tenantProjectForm table[data-location-table="' + key + '"] input, #tenantProjectForm table[data-location-table="' + key + '"] textarea')
          .forEach(control => { control.disabled = approved || roadModeLocked || catchmentModeLocked || landmarksModeLocked; });
        document.querySelectorAll('#tenantProjectForm table[data-location-table="' + key + '"] button')
          .forEach(control => { control.disabled = roadModeLocked || catchmentModeLocked || landmarksModeLocked; });
        const add = document.querySelector('#tenantProjectForm table[data-location-table="' + key + '"]')?.closest('.location-table-field')?.querySelector('.location-table-add');
        if (add) add.disabled = roadModeLocked || catchmentModeLocked || landmarksModeLocked;
      });
      const controls = document.getElementById('locationMapGenerationControls');
      if (controls && typeof MAP_PREVIEW_VIEW_DEFS !== 'undefined') {
        const approvals = tenantCreativeImages.map_approvals || {};
        const view = MAP_PREVIEW_VIEW_DEFS.find(item => item.mapType === tenantSelectedMapType) || MAP_PREVIEW_VIEW_DEFS[0];
        tenantSelectedMapType = view.mapType;
        const generated = mapPreviewIsGenerated(view);
        const mapApproved = !!approvals[view.mapType];
        const generationLocked = !approved || (view.mapType !== 'overview' && !approvals.overview) || mapApproved;
        const approvalLocked = !approved || (view.mapType !== 'overview' && !approvals.overview);
        const approvalButton = generated || mapApproved
          ? '<button type="button" class="btn small ' + (mapApproved ? 'ghost' : 'primary') + '" data-section-lock-ignore="1" onclick="' + (mapApproved ? 'unapproveMapPreview' : 'approveMapPreview') + '(\'' + view.mapType + '\')" ' + (!mapApproved && approvalLocked ? 'disabled' : '') + '>' + (mapApproved ? 'إلغاء اعتماد الخريطة' : 'اعتماد الخريطة') + '</button>'
          : '';
        let actions = '';
        if (view.mapType === 'overview' && tenantMapPolygonMode) {
          actions = '<button type="button" class="btn ghost small" data-section-lock-ignore="1" id="removeLastTenantPolygonPointButton" onclick="removeLastTenantPolygonPoint()">تراجع عن آخر نقطة</button>' +
            '<button type="button" class="btn ghost danger small" data-section-lock-ignore="1" id="clearTenantPolygonSelectionButton" onclick="clearTenantPolygonSelection()">مسح التحديد</button>' +
            '<button type="button" class="btn primary small" data-section-lock-ignore="1" id="confirmTenantPolygonButton" onclick="confirmTenantPolygon()">اعتماد الحدود</button>' +
            '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="cancelTenantPolygonMode()">إلغاء</button>';
        } else if (view.mapType === 'overview' && tenantMapPinMode) {
          actions = '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="cancelTenantMapPin()">إلغاء</button>' +
            '<button type="button" class="btn primary small" data-section-lock-ignore="1" id="confirmTenantMapPinButton" onclick="confirmTenantMapPin()">اعتماد التعيين</button>' +
            '<button type="button" class="btn ghost small" data-section-lock-ignore="1" id="undoTenantMapPinButton" onclick="undoTenantMapPin()">تراجع</button>';
        } else if (view.mapType === 'overview' && generated) {
          actions = approvalButton +
            '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="regenerateMapPreview(\'overview\')" ' + (generationLocked ? 'disabled' : '') + '>إعادة توليد الخريطة</button>' +
            '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="toggleTenantPolygonMode()" ' + (mapApproved ? 'disabled' : '') + '>رسم حدود الموقع</button>' +
            '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="startTenantMapPinMode()" ' + (mapApproved ? 'disabled' : '') + '>تعيين الموقع</button>';
        } else if (mapApproved) {
          // Keep an inconsistent legacy state recoverable: approval can survive while its image
          // reference is missing, and the user must be able to release it before regenerating.
          actions = approvalButton;
        } else if (view.mapType === 'access' && tenantRoadEditMode) {
          actions = accessRoadEditControlsHtml();
        } else if (view.mapType === 'access' && tenantRoadDrawingTarget) {
          actions = manualRoadDrawingControlsHtml();
        } else if (view.mapType === 'access' && generated) {
          actions = '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="regenerateMapPreview(\'access\')" ' + (generationLocked ? 'disabled' : '') + '>إعادة توليد الخريطة</button>' +
            approvalButton +
            '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="startAccessRoadEditMode()" ' + (mapApproved ? 'disabled' : '') + '>إضافة / تعديل الطرق</button>' +
            '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="startManualRoadDrawing(\'\')" ' + (mapApproved ? 'disabled' : '') + '>رسم مسار الطرق</button>';
        } else if (view.mapType === 'catchment' && tenantCatchmentEditMode) {
          actions = '<button type="button" class="btn primary small" data-section-lock-ignore="1" onclick="confirmCatchmentEdits()">اعتماد</button>' +
            '<button type="button" class="btn ghost small" data-section-lock-ignore="1" id="undoCatchmentEditsButton" onclick="undoCatchmentEdits()">تراجع</button>' +
            '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="cancelCatchmentEdits()">إلغاء</button>';
        } else if (view.mapType === 'catchment' && generated) {
          actions = '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="regenerateMapPreview(\'catchment\')" ' + (generationLocked ? 'disabled' : '') + '>إعادة توليد الخريطة</button>' +
            approvalButton +
            '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="startCatchmentEditMode()" ' + (mapApproved ? 'disabled' : '') + '>تعديل</button>';
        } else if (view.mapType === 'landmarks' && tenantLandmarksEditMode) {
          actions = '<button type="button" class="btn primary small" data-section-lock-ignore="1" onclick="confirmLandmarksEdits()">اعتماد</button>' +
            '<button type="button" class="btn ghost small" data-section-lock-ignore="1" id="undoLandmarksEditsButton" onclick="undoLandmarksEdits()">تراجع</button>' +
            '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="cancelLandmarksEdits()">إلغاء</button>';
        } else if (view.mapType === 'landmarks' && generated) {
          actions = '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="regenerateMapPreview(\'landmarks\')" ' + (generationLocked ? 'disabled' : '') + '>إعادة توليد الخريطة</button>' +
            approvalButton +
            '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="startLandmarksEditMode()" ' + (mapApproved ? 'disabled' : '') + '>تعديل</button>';
        } else if (view.mapType !== 'overview') {
          actions = '<button type="button" class="btn small primary" data-section-lock-ignore="1" onclick="regenerateMapPreview(\'' + view.mapType + '\')" ' + (generationLocked ? 'disabled' : '') + '>' + (generated ? 'إعادة توليد ' : 'توليد ') + view.title + '</button>' + approvalButton;
        }
        controls.innerHTML = actions
          ? '<div class="map-active-controls"><div class="map-active-controls-title">' + escapeHtml(view.title) + '</div><div class="map-active-controls-actions">' + actions + '</div></div>'
          : '';
        updateTenantPolygonControls();
        updateTenantRoadControls();
        updateTenantCatchmentControls();
        updateTenantLandmarksControls();
        updateTenantMapInteractionState();
      }
      renderMapPreviewGallery();
      if (typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en') {
        const panel = document.getElementById('locationAnalysisApprovalPanel');
        const controlsEl = document.getElementById('locationMapGenerationControls');
        const galleryEl = document.getElementById('mapPreviewGallery');
        if (panel) window.WFI18n.autoTranslate(panel);
        if (controlsEl) window.WFI18n.autoTranslate(controlsEl);
        if (galleryEl) window.WFI18n.autoTranslate(galleryEl);
      }
    }

    function openLocationTableMap(mapType) {
      const view = MAP_PREVIEW_VIEW_DEFS.find(item => item.mapType === mapType);
      if (!view) return false;
      tenantSelectedMapType = mapType;
      renderLocationWorkflowState();
      if (!mapPreviewIsGenerated(view)) {
        document.getElementById('tenantMapPreview')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        toast(view.title + ' غير مولدة');
        return false;
      }
      selectMapPreviewView(mapType);
      return true;
    }

    function startLandmarkPlacement(key, tr) {
      const mapType = LOCATION_TABLE_FIELDS[key]?.mapType;
      if (!openLocationTableMap(mapType)) return;
      tenantRoadDrawingTarget = null;
      tenantMapPolygonMode = false;
      tenantLandmarkPlacementTarget = { key, tr };
      renderLocationWorkflowState();
      toast('تم تفعيل تحديد موقع المعلم على ' + (mapType === 'landmarks' ? 'خريطة المعالم' : 'خريطة المنطقة'));
    }

    function accessRoadNameKey(name) {
      return String(name || '').replace(/^(طريق|شارع|جادة|ممر)\s+/, '').replace(/[\sـ]+/g, ' ').trim().toLowerCase();
    }

    function accessRoadRows() {
      serializeLocationTable('main_roads');
      const rows = Array.isArray(tenantProjectData.main_roads_data)
        ? tenantProjectData.main_roads_data
        : parseLocationFieldText('main_roads', tenantProjectData.main_roads || '');
      return rows.filter(row => String(row?.name || '').trim()).map(row => ({
        ...row,
        name: String(row.name).trim(),
        original_name: row.original_name || String(row.name).trim()
      }));
    }

    function accessRoadGeometry() {
      const byName = new Map();
      const add = road => {
        const key = accessRoadNameKey(road?.name);
        if (!key || !Array.isArray(road?.points) || road.points.length < 2) return;
        byName.set(key, { ...road, points: road.points.map(point => [Number(point[0]), Number(point[1])]) });
      };
      const storedRoads = Array.isArray(tenantProjectData.access_roads_data)
        ? tenantProjectData.access_roads_data
        : (Array.isArray(tenantCreativeImages.map_access_roads) ? tenantCreativeImages.map_access_roads : []);
      storedRoads.forEach(add);
      (Array.isArray(tenantProjectData.manual_road_paths) ? tenantProjectData.manual_road_paths : []).forEach(add);
      const positions = tenantRoadEditMode
        ? tenantRoadEditDraft?.labelPositions || {}
        : tenantProjectData.access_road_label_positions || {};
      const sizes = tenantRoadEditMode
        ? tenantRoadEditDraft?.labelSizes || {}
        : tenantProjectData.access_road_label_sizes || {};
      const rows = tenantRoadEditMode ? tenantRoadEditDraft?.rows || [] : accessRoadRows();
      const roads = rows.map(row => {
        const geometry = byName.get(accessRoadNameKey(row.original_name)) || byName.get(accessRoadNameKey(row.name));
        if (!geometry) return null;
        return {
          ...geometry,
          name: row.name,
          label_point: positions[row.name] || positions[row.original_name] || geometry.label_point || null,
          label_scale: sizes[row.name] || sizes[row.original_name] || geometry.label_scale || 1
        };
      }).filter(Boolean);
      if (tenantRoadDrawingTarget?.points?.length) {
        const index = roads.findIndex(road => accessRoadNameKey(road.name) === accessRoadNameKey(tenantRoadDrawingTarget.name));
        const draft = { name: tenantRoadDrawingTarget.name, points: tenantRoadDrawingTarget.points, label_point: positions[tenantRoadDrawingTarget.name] || null, label_scale: sizes[tenantRoadDrawingTarget.name] || 1 };
        if (index >= 0) roads[index] = draft;
        else roads.push(draft);
      }
      return roads;
    }

    function roadEditSnapshot() {
      return JSON.stringify({ draft: tenantRoadEditDraft, selectedIndex: tenantRoadEditSelectedIndex });
    }

    function pushRoadEditHistory() {
      const snapshot = roadEditSnapshot();
      if (tenantRoadEditHistory[tenantRoadEditHistory.length - 1] !== snapshot) tenantRoadEditHistory.push(snapshot);
      if (tenantRoadEditHistory.length > 60) tenantRoadEditHistory.shift();
    }

    function accessRoadEditControlsHtml() {
      const rows = tenantRoadEditDraft?.rows || [];
      const options = rows.map((row, index) => '<option value="' + index + '" ' + (tenantRoadEditSelectedIndex === index ? 'selected' : '') + '>' + escapeHtml(row.name) + '</option>').join('');
      const selectedName = tenantRoadEditSelectedIndex >= 0 ? rows[tenantRoadEditSelectedIndex]?.name || '' : tenantRoadEditDraft?.newName || '';
      return '<label class="map-control-field">اختيار الطريق<select id="accessRoadEditSelect" onchange="selectAccessRoadEdit(this.value)">' + options + '<option value="-1" ' + (tenantRoadEditSelectedIndex < 0 ? 'selected' : '') + '>طريق جديد</option></select></label>' +
        '<label class="map-control-field">اسم الطريق<input id="accessRoadEditName" type="text" value="' + escapeHtml(selectedName) + '" oninput="updateAccessRoadDraftName(this.value)"></label>' +
        '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="adjustAccessRoadLabelSize(-0.1)">تصغير الاسم</button>' +
        '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="adjustAccessRoadLabelSize(0.1)">تكبير الاسم</button>' +
        '<button type="button" class="btn ghost small" data-section-lock-ignore="1" id="undoAccessRoadEditsButton" onclick="undoAccessRoadEdits()">تراجع</button>' +
        '<button type="button" class="btn primary small" data-section-lock-ignore="1" onclick="confirmAccessRoadEdits()">اعتماد</button>' +
        '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="cancelAccessRoadEdits()">إلغاء</button>';
    }

    function manualRoadDrawingControlsHtml() {
      const names = accessRoadRows().map(row => row.name);
      const options = names.map(name => '<option value="' + escapeHtml(name) + '" ' + (name === tenantRoadDrawingTarget?.name ? 'selected' : '') + '>' + escapeHtml(name) + '</option>').join('');
      return '<label class="map-control-field">اختيار الطريق<select id="manualRoadDrawingSelect" onchange="selectManualRoadDrawingRoad(this.value)">' + options + '</select></label>' +
        '<button type="button" class="btn primary small" data-section-lock-ignore="1" id="confirmManualRoadDrawingButton" onclick="finishManualRoadDrawing()">اعتماد المسارات</button>' +
        '<button type="button" class="btn ghost small" data-section-lock-ignore="1" id="undoManualRoadDrawingButton" onclick="undoManualRoadDrawing()">تراجع</button>' +
        '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="cancelManualRoadDrawing()">إلغاء</button>';
    }

    async function startAccessRoadEditMode() {
      if (tenantCreativeImages.map_approvals?.access) { toast('خريطة الطرق معتمدة'); return; }
      if (!openLocationTableMap('access')) return;
      tenantRoadDrawingTarget = null;
      tenantRoadEditMode = true;
      tenantRoadEditDraft = {
        rows: accessRoadRows(),
        labelPositions: JSON.parse(JSON.stringify(tenantProjectData.access_road_label_positions || {})),
        labelSizes: JSON.parse(JSON.stringify(tenantProjectData.access_road_label_sizes || {})),
        newName: ''
      };
      tenantRoadEditHistory = [];
      tenantRoadEditSelectedIndex = tenantRoadEditDraft.rows.length ? 0 : -1;
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
      await ensureAccessEditablePreview();
    }

    function selectAccessRoadEdit(value) {
      tenantRoadEditSelectedIndex = Number(value);
      const input = document.getElementById('accessRoadEditName');
      if (input) input.value = tenantRoadEditSelectedIndex >= 0
        ? tenantRoadEditDraft?.rows?.[tenantRoadEditSelectedIndex]?.name || ''
        : tenantRoadEditDraft?.newName || '';
      renderTenantMapPolygonOverlay();
    }

    function updateAccessRoadDraftName(value) {
      if (!tenantRoadEditMode || !tenantRoadEditDraft) return;
      pushRoadEditHistory();
      if (tenantRoadEditSelectedIndex < 0) {
        tenantRoadEditDraft.newName = value;
      } else if (tenantRoadEditDraft.rows[tenantRoadEditSelectedIndex]) {
        tenantRoadEditDraft.rows[tenantRoadEditSelectedIndex].name = value;
      }
      renderTenantMapPolygonOverlay();
      updateTenantRoadControls();
    }

    function commitAccessRoadDraftName() {
      if (!tenantRoadEditDraft || tenantRoadEditSelectedIndex >= 0) return tenantRoadEditDraft?.rows?.[tenantRoadEditSelectedIndex] || null;
      const input = document.getElementById('accessRoadEditName');
      const name = String(input?.value || tenantRoadEditDraft.newName || '').trim();
      if (!name) return null;
      const existing = tenantRoadEditDraft.rows.findIndex(row => accessRoadNameKey(row.name) === accessRoadNameKey(name));
      if (existing >= 0) {
        tenantRoadEditSelectedIndex = existing;
        return tenantRoadEditDraft.rows[existing];
      }
      tenantRoadEditDraft.rows.push({ name, original_name: name, row_source: 'manual' });
      tenantRoadEditSelectedIndex = tenantRoadEditDraft.rows.length - 1;
      tenantRoadEditDraft.newName = '';
      return tenantRoadEditDraft.rows[tenantRoadEditSelectedIndex];
    }

    function setAccessRoadLabelFromMap(lat, lng) {
      if (!tenantRoadEditMode || !tenantRoadEditDraft) return;
      pushRoadEditHistory();
      const row = commitAccessRoadDraftName();
      if (!row || !String(row.name || '').trim()) return;
      tenantRoadEditDraft.labelPositions[row.name.trim()] = [lat, lng];
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
    }

    function startAccessRoadLabelDrag(event, name) {
      if (!tenantRoadEditMode || !tenantRoadEditDraft) return;
      const index = tenantRoadEditDraft.rows.findIndex(row => accessRoadNameKey(row.name) === accessRoadNameKey(name));
      if (index < 0) return;
      tenantRoadEditSelectedIndex = index;
      const select = document.getElementById('accessRoadEditSelect');
      const input = document.getElementById('accessRoadEditName');
      if (select) select.value = String(index);
      if (input) input.value = tenantRoadEditDraft.rows[index].name;
      pushRoadEditHistory();
      highlightMapPlacePair('road', name, true, true);
      const image = document.querySelector('#mapPreviewImage img');
      const move = moveEvent => {
        const coordinates = tenantMapCoordinatesFromClient(moveEvent.clientX, moveEvent.clientY, image);
        if (!coordinates) return;
        tenantRoadEditDraft.labelPositions[tenantRoadEditDraft.rows[index].name] = coordinates;
        renderTenantMapPolygonOverlay();
      };
      const stop = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', stop);
        window.removeEventListener('pointercancel', stop);
        highlightMapPlacePair('road', name, false, true);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', stop);
      window.addEventListener('pointercancel', stop);
      event.preventDefault();
      event.stopPropagation();
    }

    function deleteAccessRoadFromDraft(event, name) {
      if (!tenantRoadEditMode || !tenantRoadEditDraft) return;
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }
      const index = tenantRoadEditDraft.rows.findIndex(row => accessRoadNameKey(row.name) === accessRoadNameKey(name));
      if (index < 0) return;
      pushRoadEditHistory();
      const [removed] = tenantRoadEditDraft.rows.splice(index, 1);
      for (const key of [removed.name, removed.original_name]) {
        delete tenantRoadEditDraft.labelPositions[key];
        delete tenantRoadEditDraft.labelSizes[key];
      }
      tenantRoadEditSelectedIndex = tenantRoadEditDraft.rows.length
        ? Math.min(index, tenantRoadEditDraft.rows.length - 1)
        : -1;
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
    }

    function adjustAccessRoadLabelSize(delta) {
      if (!tenantRoadEditMode || !tenantRoadEditDraft) return;
      pushRoadEditHistory();
      const row = commitAccessRoadDraftName();
      if (!row || !String(row.name || '').trim()) return;
      const current = Number(tenantRoadEditDraft.labelSizes[row.name] || tenantRoadEditDraft.labelSizes[row.original_name] || 1);
      tenantRoadEditDraft.labelSizes[row.name] = Math.max(0.6, Math.min(1.8, Math.round((current + Number(delta || 0)) * 10) / 10));
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
    }

    function undoAccessRoadEdits() {
      const snapshot = tenantRoadEditHistory.pop();
      if (!snapshot) return;
      const state = JSON.parse(snapshot);
      tenantRoadEditDraft = state.draft;
      tenantRoadEditSelectedIndex = state.selectedIndex;
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
    }

    async function confirmAccessRoadEdits() {
      if (!tenantRoadEditMode || !tenantRoadEditDraft) return;
      commitAccessRoadDraftName();
      const unique = new Set();
      const rows = tenantRoadEditDraft.rows.filter(row => {
        row.name = String(row.name || '').trim();
        const key = accessRoadNameKey(row.name);
        if (!key || unique.has(key)) return false;
        unique.add(key);
        return true;
      });
      const renamed = new Map(rows.map(row => [accessRoadNameKey(row.original_name), row.name]));
      const renameGeometry = road => ({ ...road, name: renamed.get(accessRoadNameKey(road?.name)) || road?.name });
      const allowedRoadKeys = new Set(rows.map(row => accessRoadNameKey(row.name)));
      tenantProjectData.access_roads_data = (Array.isArray(tenantProjectData.access_roads_data) ? tenantProjectData.access_roads_data : [])
        .map(renameGeometry).filter(road => allowedRoadKeys.has(accessRoadNameKey(road?.name)));
      tenantProjectData.manual_road_paths = (Array.isArray(tenantProjectData.manual_road_paths) ? tenantProjectData.manual_road_paths : [])
        .map(renameGeometry).filter(road => allowedRoadKeys.has(accessRoadNameKey(road?.name)));
      tenantProjectData.access_road_label_positions = Object.fromEntries(rows.map(row => {
        const point = tenantRoadEditDraft.labelPositions[row.name] || tenantRoadEditDraft.labelPositions[row.original_name];
        return point ? [row.name, point] : null;
      }).filter(Boolean));
      tenantProjectData.access_road_label_sizes = Object.fromEntries(rows.map(row => {
        const size = tenantRoadEditDraft.labelSizes[row.name] || tenantRoadEditDraft.labelSizes[row.original_name];
        return size ? [row.name, size] : null;
      }).filter(Boolean));
      tenantProjectData.main_roads = rows.map(row => row.name).join('\n');
      tenantProjectData.main_roads_data = rows.map(({ original_name, ...row }) => row);
      setLocationTableValue('main_roads', tenantProjectData.main_roads_data);
      tenantRoadEditMode = false;
      tenantRoadEditDraft = null;
      tenantRoadEditHistory = [];
      tenantRoadEditSelectedIndex = -1;
      tenantCreativeImages.map_approvals = { ...(tenantCreativeImages.map_approvals || {}), access: false };
      releaseLocationSectionApproval();
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
      triggerAutoSaveDraft();
      await applyAccessMapEdits();
      toast('تم اعتماد تعديلات الطرق');
    }

    function cancelAccessRoadEdits() {
      tenantRoadEditMode = false;
      tenantRoadEditDraft = null;
      tenantRoadEditHistory = [];
      tenantRoadEditSelectedIndex = -1;
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
    }

    function startManualRoadDrawingFromTable(name) {
      const roadName = String(name || '').trim();
      if (!roadName) { toast('اسم الطريق مطلوب'); return; }
      return startManualRoadDrawing(roadName);
    }

    async function startManualRoadDrawing(name) {
      if (tenantCreativeImages.map_approvals?.access) { toast('خريطة الطرق معتمدة'); return; }
      if (!openLocationTableMap('access')) return;
      const names = accessRoadRows().map(row => row.name);
      const requestedName = String(name || '').trim();
      const roadName = requestedName
        ? names.find(item => accessRoadNameKey(item) === accessRoadNameKey(requestedName))
        : names[0];
      if (!roadName) { toast(requestedName ? 'اسم الطريق غير موجود في الجدول' : 'لا توجد طرق رئيسية'); return; }
      tenantLandmarkPlacementTarget = null;
      tenantRoadEditMode = false;
      tenantRoadEditDraft = null;
      tenantRoadDrawingTarget = { name: roadName, points: [] };
      tenantMapPolygonMode = false;
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
      await ensureAccessEditablePreview();
    }

    function selectManualRoadDrawingRoad(name) {
      if (!tenantRoadDrawingTarget) return;
      tenantRoadDrawingTarget = { name: String(name || '').trim(), points: [] };
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
    }

    function undoManualRoadDrawing() {
      if (!tenantRoadDrawingTarget?.points?.length) return;
      tenantRoadDrawingTarget.points.pop();
      renderTenantMapPolygonOverlay();
      updateTenantRoadControls();
    }

    async function finishManualRoadDrawing() {
      if (!tenantRoadDrawingTarget || tenantRoadDrawingTarget.points.length < 2) return;
      const paths = Array.isArray(tenantProjectData.manual_road_paths) ? tenantProjectData.manual_road_paths : [];
      tenantProjectData.manual_road_paths = paths.filter(item => accessRoadNameKey(item?.name) !== accessRoadNameKey(tenantRoadDrawingTarget.name))
        .concat([{ name: tenantRoadDrawingTarget.name, points: tenantRoadDrawingTarget.points }]);
      tenantCreativeImages.map_approvals = { ...(tenantCreativeImages.map_approvals || {}), access: false };
      tenantRoadDrawingTarget = null;
      releaseLocationSectionApproval();
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
      triggerAutoSaveDraft();
      await applyAccessMapEdits();
      toast('تم اعتماد مسار الطريق');
    }

    function cancelManualRoadDrawing() {
      tenantRoadDrawingTarget = null;
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
    }

    function isUsableMapCoordinate(value, latitude) {
      if (value === '' || value === null || value === undefined) return false;
      const number = Number(value);
      return Number.isFinite(number) && (latitude ? number >= -90 && number <= 90 : number >= -180 && number <= 180);
    }

    function mergeResolvedMapLandmark(row, resolved) {
      const source = resolved || {};
      return {
        ...source,
        ...row,
        lat: isUsableMapCoordinate(row?.lat, true) ? Number(row.lat) : source.lat,
        lng: isUsableMapCoordinate(row?.lng, false) ? Number(row.lng) : source.lng
      };
    }

    function catchmentMapLandmarks() {
      const stored = Array.isArray(tenantProjectData.catchment_map_landmarks)
        ? tenantProjectData.catchment_map_landmarks
        : (Array.isArray(tenantCreativeImages.map_catchment_landmarks) ? tenantCreativeImages.map_catchment_landmarks : []);
      const cityRows = Array.isArray(tenantProjectData.city_landmarks_data) ? tenantProjectData.city_landmarks_data : [];
      const selectedRows = cityRows.filter(item => item?.show_on_map === true || item?.selected === true);
      const desiredRows = (selectedRows.length ? selectedRows : cityRows).slice(0, 7);
      const storedByName = new Map(stored.map(item => [String(item?.name || '').trim(), item]));
      const source = tenantCatchmentEditMode && Array.isArray(tenantCatchmentEditDraft?.landmarks)
        ? tenantCatchmentEditDraft.landmarks
        : desiredRows.length
          ? desiredRows.map(item => mergeResolvedMapLandmark(item, storedByName.get(String(item?.name || '').trim())))
          : stored.slice(0, 7);
      const positions = tenantCatchmentEditMode
        ? tenantCatchmentEditDraft?.labelPositions || {}
        : tenantProjectData.catchment_label_positions || {};
      return source.filter(item => isUsableMapCoordinate(item?.lat, true) && isUsableMapCoordinate(item?.lng, false)).map(item => ({
        ...item,
        lat: Number(item.lat),
        lng: Number(item.lng),
        label_point: positions[item.name] || item.label_point || null
      }));
    }

    function pushCatchmentEditHistory() {
      const snapshot = JSON.stringify(tenantCatchmentEditDraft);
      if (tenantCatchmentEditHistory[tenantCatchmentEditHistory.length - 1] !== snapshot) tenantCatchmentEditHistory.push(snapshot);
      if (tenantCatchmentEditHistory.length > 60) tenantCatchmentEditHistory.shift();
    }

    async function startCatchmentEditMode() {
      if (tenantCreativeImages.map_approvals?.catchment) { toast('خريطة المنطقة معتمدة'); return; }
      if (!openLocationTableMap('catchment')) return;
      tenantProjectData.catchment_map_landmarks = catchmentMapLandmarks();
      tenantCatchmentEditMode = true;
      tenantCatchmentEditDraft = {
        landmarks: JSON.parse(JSON.stringify(tenantProjectData.catchment_map_landmarks || [])),
        labelPositions: JSON.parse(JSON.stringify(tenantProjectData.catchment_label_positions || {}))
      };
      tenantCatchmentEditHistory = [];
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
      await ensureCatchmentEditablePreview();
    }

    function startCatchmentLabelDrag(event, name) {
      if (!tenantCatchmentEditMode || !tenantCatchmentEditDraft) return;
      pushCatchmentEditHistory();
      updateTenantCatchmentControls();
      highlightMapPlacePair('catchment', name, true, true);
      const image = document.querySelector('#mapPreviewImage img');
      const move = moveEvent => {
        const coordinates = tenantMapCoordinatesFromClient(moveEvent.clientX, moveEvent.clientY, image);
        if (!coordinates) return;
        tenantCatchmentEditDraft.labelPositions[name] = coordinates;
        renderTenantMapPolygonOverlay();
      };
      const stop = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', stop);
        window.removeEventListener('pointercancel', stop);
        highlightMapPlacePair('catchment', name, false, true);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', stop);
      window.addEventListener('pointercancel', stop);
      event.preventDefault();
      event.stopPropagation();
    }

    function startCatchmentMarkerDrag(event, name) {
      if (!tenantCatchmentEditMode || !tenantCatchmentEditDraft) return;
      const item = tenantCatchmentEditDraft.landmarks.find(value => value?.name === name);
      if (!item) return;
      pushCatchmentEditHistory();
      updateTenantCatchmentControls();
      highlightMapPlacePair('catchment', name, true, true);
      const image = document.querySelector('#mapPreviewImage img');
      const startLat = Number(item.lat);
      const startLng = Number(item.lng);
      const initialLabel = tenantCatchmentEditDraft.labelPositions[name] || item.label_point;
      const move = moveEvent => {
        const coordinates = tenantMapCoordinatesFromClient(moveEvent.clientX, moveEvent.clientY, image);
        if (!coordinates) return;
        item.lat = coordinates[0];
        item.lng = coordinates[1];
        if (Array.isArray(initialLabel)) {
          tenantCatchmentEditDraft.labelPositions[name] = [
            Number(initialLabel[0]) + coordinates[0] - startLat,
            Number(initialLabel[1]) + coordinates[1] - startLng
          ];
        }
        renderTenantMapPolygonOverlay();
      };
      const stop = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', stop);
        window.removeEventListener('pointercancel', stop);
        highlightMapPlacePair('catchment', name, false, true);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', stop);
      window.addEventListener('pointercancel', stop);
      event.preventDefault();
      event.stopPropagation();
    }

    function undoCatchmentEdits() {
      const snapshot = tenantCatchmentEditHistory.pop();
      if (!snapshot) return;
      tenantCatchmentEditDraft = JSON.parse(snapshot);
      renderTenantMapPolygonOverlay();
      updateTenantCatchmentControls();
    }

    async function confirmCatchmentEdits() {
      if (!tenantCatchmentEditMode || !tenantCatchmentEditDraft) return;
      tenantProjectData.catchment_label_positions = { ...tenantCatchmentEditDraft.labelPositions };
      tenantProjectData.catchment_map_landmarks = catchmentMapLandmarks();
      const updatedByName = new Map(tenantProjectData.catchment_map_landmarks.map(item => [item.name, item]));
      tenantProjectData.city_landmarks_data = (Array.isArray(tenantProjectData.city_landmarks_data) ? tenantProjectData.city_landmarks_data : []).map(item => {
        const updated = updatedByName.get(item?.name);
        return updated ? { ...item, lat: updated.lat, lng: updated.lng } : item;
      });
      tenantCatchmentEditMode = false;
      tenantCatchmentEditDraft = null;
      tenantCatchmentEditHistory = [];
      tenantCreativeImages.map_approvals = { ...(tenantCreativeImages.map_approvals || {}), catchment: false };
      releaseLocationSectionApproval();
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
      triggerAutoSaveDraft();
      await applyCatchmentMapEdits();
      toast('تم اعتماد تعديلات خريطة المنطقة');
    }

    function cancelCatchmentEdits() {
      resetTenantCatchmentMode();
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
    }

    function nearbyMapLandmarks() {
      const stored = Array.isArray(tenantProjectData.landmark_map_items)
        ? tenantProjectData.landmark_map_items
        : (Array.isArray(tenantCreativeImages.map_landmark_items) ? tenantCreativeImages.map_landmark_items : []);
      const nearbyRows = Array.isArray(tenantProjectData.nearby_landmarks_data) ? tenantProjectData.nearby_landmarks_data : [];
      const selectedRows = nearbyRows.filter(item => item?.show_on_map === true || item?.selected === true);
      const desiredRows = (selectedRows.length ? selectedRows : nearbyRows).slice(0, 7);
      const storedByName = new Map(stored.map(item => [String(item?.name || '').trim(), item]));
      const source = tenantLandmarksEditMode && Array.isArray(tenantLandmarksEditDraft?.landmarks)
        ? tenantLandmarksEditDraft.landmarks
        : desiredRows.length
          ? desiredRows.map(item => mergeResolvedMapLandmark(item, storedByName.get(String(item?.name || '').trim())))
          : stored.slice(0, 7);
      const positions = tenantLandmarksEditMode
        ? tenantLandmarksEditDraft?.labelPositions || {}
        : tenantProjectData.landmark_label_positions || {};
      return source.filter(item => isUsableMapCoordinate(item?.lat, true) && isUsableMapCoordinate(item?.lng, false)).map(item => ({
        ...item,
        lat: Number(item.lat),
        lng: Number(item.lng),
        label_point: positions[item.name] || item.label_point || null
      }));
    }

    function pushLandmarksEditHistory() {
      const snapshot = JSON.stringify(tenantLandmarksEditDraft);
      if (tenantLandmarksEditHistory[tenantLandmarksEditHistory.length - 1] !== snapshot) tenantLandmarksEditHistory.push(snapshot);
      if (tenantLandmarksEditHistory.length > 60) tenantLandmarksEditHistory.shift();
    }

    async function startLandmarksEditMode() {
      if (tenantCreativeImages.map_approvals?.landmarks) { toast('خريطة المعالم معتمدة'); return; }
      if (!openLocationTableMap('landmarks')) return;
      tenantProjectData.landmark_map_items = nearbyMapLandmarks();
      tenantLandmarksEditMode = true;
      tenantLandmarksEditDraft = {
        landmarks: JSON.parse(JSON.stringify(tenantProjectData.landmark_map_items || [])),
        labelPositions: JSON.parse(JSON.stringify(tenantProjectData.landmark_label_positions || {}))
      };
      tenantLandmarksEditHistory = [];
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
      await ensureLandmarksEditablePreview();
    }

    function startLandmarksLabelDrag(event, name) {
      if (!tenantLandmarksEditMode || !tenantLandmarksEditDraft) return;
      pushLandmarksEditHistory();
      updateTenantLandmarksControls();
      highlightMapPlacePair('landmark', name, true, true);
      const image = document.querySelector('#mapPreviewImage img');
      const move = moveEvent => {
        const coordinates = tenantMapCoordinatesFromClient(moveEvent.clientX, moveEvent.clientY, image);
        if (!coordinates) return;
        tenantLandmarksEditDraft.labelPositions[name] = coordinates;
        renderTenantMapPolygonOverlay();
      };
      const stop = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', stop);
        window.removeEventListener('pointercancel', stop);
        highlightMapPlacePair('landmark', name, false, true);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', stop);
      window.addEventListener('pointercancel', stop);
      event.preventDefault();
      event.stopPropagation();
    }

    function startLandmarksMarkerDrag(event, name) {
      if (!tenantLandmarksEditMode || !tenantLandmarksEditDraft) return;
      const item = tenantLandmarksEditDraft.landmarks.find(value => value?.name === name);
      if (!item) return;
      pushLandmarksEditHistory();
      updateTenantLandmarksControls();
      highlightMapPlacePair('landmark', name, true, true);
      const image = document.querySelector('#mapPreviewImage img');
      const startLat = Number(item.lat);
      const startLng = Number(item.lng);
      const initialLabel = tenantLandmarksEditDraft.labelPositions[name] || item.label_point;
      const move = moveEvent => {
        const coordinates = tenantMapCoordinatesFromClient(moveEvent.clientX, moveEvent.clientY, image);
        if (!coordinates) return;
        item.lat = coordinates[0];
        item.lng = coordinates[1];
        if (Array.isArray(initialLabel)) {
          tenantLandmarksEditDraft.labelPositions[name] = [
            Number(initialLabel[0]) + coordinates[0] - startLat,
            Number(initialLabel[1]) + coordinates[1] - startLng
          ];
        }
        renderTenantMapPolygonOverlay();
      };
      const stop = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', stop);
        window.removeEventListener('pointercancel', stop);
        highlightMapPlacePair('landmark', name, false, true);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', stop);
      window.addEventListener('pointercancel', stop);
      event.preventDefault();
      event.stopPropagation();
    }

    function undoLandmarksEdits() {
      const snapshot = tenantLandmarksEditHistory.pop();
      if (!snapshot) return;
      tenantLandmarksEditDraft = JSON.parse(snapshot);
      renderTenantMapPolygonOverlay();
      updateTenantLandmarksControls();
    }

    async function confirmLandmarksEdits() {
      if (!tenantLandmarksEditMode || !tenantLandmarksEditDraft) return;
      tenantProjectData.landmark_label_positions = { ...tenantLandmarksEditDraft.labelPositions };
      tenantProjectData.landmark_map_items = nearbyMapLandmarks();
      const updatedByName = new Map(tenantProjectData.landmark_map_items.map(item => [item.name, item]));
      tenantProjectData.nearby_landmarks_data = (Array.isArray(tenantProjectData.nearby_landmarks_data) ? tenantProjectData.nearby_landmarks_data : []).map(item => {
        const updated = updatedByName.get(item?.name);
        return updated ? { ...item, lat: updated.lat, lng: updated.lng } : item;
      });
      tenantNearbyLandmarks = tenantProjectData.nearby_landmarks_data;
      refreshLocationTables();
      tenantLandmarksEditMode = false;
      tenantLandmarksEditDraft = null;
      tenantLandmarksEditHistory = [];
      tenantCreativeImages.map_approvals = { ...(tenantCreativeImages.map_approvals || {}), landmarks: false };
      releaseLocationSectionApproval();
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
      triggerAutoSaveDraft();
      await applyLandmarksMapEdits();
      toast('تم اعتماد تعديلات خريطة المعالم');
    }

    function cancelLandmarksEdits() {
      resetTenantLandmarksEditMode();
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
    }

    const TENANT_PROJECT_HIDDEN_FIELDS = new Set(['plot_number', 'land_area', 'built_area', 'building_system', 'infrastructure', 'population_density', 'secondary_roads', 'catchment_areas', 'location_data_fetched_at']);
    const TENANT_CLIENT_ENTERED_LAND_FIELDS = new Set(['approved_financial_area', 'approved_floor_count', 'approved_coverage_ratio']);

    function updateClientEnteredLandFieldState(input) {
      if (!input || !TENANT_CLIENT_ENTERED_LAND_FIELDS.has(input.dataset.key)) return;
      const field = input.closest('.tenant-field');
      if (!field) return;
      const entered = String(input.value ?? '').trim() !== '';
      field.classList.toggle('tenant-client-required-field', !entered);
      field.classList.toggle('tenant-client-complete-field', entered);
    }

    function refreshClientEnteredLandFieldStates() {
      document.querySelectorAll('#tenantProjectForm [data-key]').forEach(updateClientEnteredLandFieldState);
    }

    function validateLandCroquisClientFields() {
      const fieldSpecs = [
        { key: 'approved_floor_count', label: 'الأدوار المعتمدة', message: 'يرجى إدخال عدد الأدوار المعتمدة للمشروع وفقًا للاشتراطات التنظيمية.' },
        { key: 'approved_coverage_ratio', label: 'التغطية المعتمدة (%)', message: 'يرجى إدخال نسبة التغطية المعتمدة للأرض وفقًا للاشتراطات التنظيمية.' },
        { key: 'approved_financial_area', label: 'المساحة المعتمدة للدراسة المالية (م²)', message: 'يرجى إدخال إجمالي المساحة البنائية المعتمدة التي ستُبنى عليها حسابات الدراسة المالية.' }
      ];
      const errors = [];
      for (const spec of fieldSpecs) {
        const input = document.querySelector('#tenantProjectForm [data-key="' + spec.key + '"]');
        const val = input ? String(input.value ?? '').trim() : '';
        const numVal = parseFloat(val.replace(/,/g, ''));
        if (!val || isNaN(numVal) || numVal <= 0) {
          errors.push(spec);
        }
      }
      return errors;
    }

    function tenantProjectFieldLabel(field) {
      let lbl = field.fieldLabel;
      if (field.fieldKey === 'main_roads') lbl = 'الطرق الرئيسية المحيطة';
      else if (field.fieldKey === 'city_landmarks') lbl = 'أهم المعالم الرئيسية في المدينة';
      else if (field.fieldKey === 'project_mixed_components') lbl = 'أنواع المشروع متعدد الاستخدامات';
      const isEn = typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en';
      const dict = (typeof window.WFI18n !== 'undefined' && window.WFI18n.autoDict) || (typeof WFI18N_EN_AUTO !== 'undefined' ? WFI18N_EN_AUTO : (window.WFI18N_EN_AUTO || null));
      if (isEn && dict) {
        if (dict[lbl]) return dict[lbl];
        const alt2 = lbl.indexOf('²') !== -1 ? lbl.replace(/²/g, '2') : null;
        if (alt2 && dict[alt2]) return dict[alt2];
        const altSup = lbl.indexOf('2') !== -1 ? lbl.replace(/2/g, '²') : null;
        if (altSup && dict[altSup]) return dict[altSup];
      }
      return lbl;
    }

    async function geocodeTenantLocationLink(input, latInput, lngInput, force = false) {
      const value = String(input?.value || '').trim();
      tenantProjectData.location_address = value;
      if (!value) return false;
      if (!isGoogleMapsUrl(value)) {
        toast('أدخل رابط Google Maps صحيحًا في قسم الموقع والخرائط');
        return false;
      }
      if (tenantLocationGeocodeRequest) return tenantLocationGeocodeRequest;
      tenantLocationGeocodeRequest = geocodeProjectAddress(input, latInput, lngInput, force)
        .finally(() => { tenantLocationGeocodeRequest = null; });
      return tenantLocationGeocodeRequest;
    }

    function renderTenantProjectForm(fields) {
      const form = document.getElementById('tenantProjectForm');
      if (!form) return;
      fields = (fields || []).filter(field => !TENANT_PROJECT_HIDDEN_FIELDS.has(field.fieldKey));
      form.innerHTML = '';
      form.dataset.projectFormFilled = '';
      if (!fields.length) {
        form.innerHTML = '<p class="tenant-hint">لا توجد حقول مفعّلة</p>';
        const sidebar = document.getElementById('tenantProjectSidebar');
        if (sidebar) sidebar.innerHTML = '';
        return;
      }
      fields.sort((a, b) => (a.sortOrder || 0) - (b.sortOrder || 0));

      // Group fields by section; hide sections not allowed for current user
      const sectionMap = {};
      tenantFieldSections.forEach(s => { sectionMap[s.key] = s.label; });
      const grouped = {};
      fields.forEach(f => {
        const section = f.sectionKey || 'general';
        if (!grouped[section]) grouped[section] = [];
        grouped[section].push(f);
      });

      // Keep references to location inputs for geocoding/preview
      let addressInput = null;
      let latInput = null;
      let lngInput = null;
      let locationSection = null;

      function renderFormSection(sectionKey) {
        const sectionFields = grouped[sectionKey];
        if (!sectionFields || !sectionFields.length) return null;
        if (sectionKey !== 'general' && !tenantAllowedFieldSections[sectionKey]) return null; // hide unauthorized section

        const sectionDiv = document.createElement('div');
        sectionDiv.className = 'tenant-form-section';
        sectionDiv.dataset.section = sectionKey;
        sectionDiv.id = 'project-section-' + sectionKey;
        sectionDiv.appendChild(createProjectSectionHeader(sectionKey, sectionMap[sectionKey] || 'عام'));

        sectionFields.forEach(f => {
          if (LOCATION_TABLE_FIELDS[f.fieldKey]) {
            const currentTableValue = (tenantProjectData && tenantProjectData[f.fieldKey]) || f.defaultValue || '';
            sectionDiv.appendChild(createLocationTableField(f.fieldKey, tenantProjectFieldLabel(f) + (f.isRequired ? ' *' : ''), currentTableValue));
            return;
          }
          const div = document.createElement('div');
          div.className = 'tenant-field' + (f.fieldType === 'textarea' || f.fieldKey === 'location_address' || f.fieldKey === 'project_type' ? ' full' : '');
          const isClientEnteredLandField = sectionKey === 'land_croquis' && TENANT_CLIENT_ENTERED_LAND_FIELDS.has(f.fieldKey);
          if (isClientEnteredLandField) div.classList.add('tenant-client-required-field');
          const rawLabel = (f.fieldKey === 'main_roads') ? 'الطرق الرئيسية المحيطة' :
            (f.fieldKey === 'city_landmarks') ? 'أهم المعالم الرئيسية في المدينة' :
            (f.fieldKey === 'project_mixed_components') ? 'أنواع المشروع متعدد الاستخدامات' : f.fieldLabel;
          const label = document.createElement('label');
          label.dataset.arLabel = rawLabel;
          label.dataset.isRequired = f.isRequired ? '1' : '';
          label.textContent = tenantProjectFieldLabel(f) + (f.isRequired ? ' *' : '');
          if (isClientEnteredLandField) {
            const badge = document.createElement('span');
            badge.className = 'tenant-client-required-badge';
            const isEn = typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en';
            badge.textContent = 'إدخال العميل';
            if (isEn) badge.textContent = 'Client-Entered Only';
            badge.dataset.arText = 'إدخال العميل';
            label.appendChild(badge);
          }
          let input;
          let uploadStatus = null;
          if (f.fieldKey === 'project_subtype' || f.fieldKey === 'target_audience') {
            input = document.createElement('textarea');
            input.style.display = 'none';
          } else if (f.fieldType === 'textarea') {
            input = document.createElement('textarea');
          } else if (f.fieldKey === 'project_type' || f.fieldKey === 'project_mixed_components' || f.fieldKey === 'activity_class') {
            input = document.createElement('input');
            input.type = 'hidden';
          } else if (f.fieldType === 'select') {
            input = document.createElement('select');
            let opts = f.fieldOptions || f.options || [];
            if (typeof opts === 'string') {
              try {
                opts = JSON.parse(opts);
              } catch (e) {
                opts = opts.split(/[,،;\n]/).map(s => s.trim()).filter(Boolean);
              }
            }
            if (!Array.isArray(opts)) opts = [];

            const isEn = typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en';
            const trVal = (val) => (isEn && typeof WFI18N_EN_AUTO !== 'undefined' && WFI18N_EN_AUTO[val]) ? WFI18N_EN_AUTO[val] : val;

            const placeholderOpt = document.createElement('option');
            placeholderOpt.value = '';
            placeholderOpt.textContent = trVal('-- اختر القيمة --');
            placeholderOpt.dataset.arText = '-- اختر القيمة --';
            input.appendChild(placeholderOpt);

            opts.forEach(opt => {
              if (typeof opt === 'string') {
                const subOpts = opt.split(/[,،;\n]/).map(s => s.trim()).filter(Boolean);
                subOpts.forEach(o => {
                  const option = document.createElement('option');
                  option.value = o;
                  option.textContent = trVal(o);
                  option.dataset.arText = o;
                  input.appendChild(option);
                });
              } else if (opt !== null && opt !== undefined) {
                const option = document.createElement('option');
                option.value = String(opt);
                option.textContent = trVal(String(opt));
                option.dataset.arText = String(opt);
                input.appendChild(option);
              }
            });
          } else if (f.fieldKey === 'land_photos') {
            // Client-supplied photos of the plot: up to 4, images only, each with a caption.
            input = document.createElement('input');
            input.type = 'file';
            input.multiple = true;
            input.accept = 'image/*,.jpg,.jpeg,.png,.webp';
            input.dataset.filetype = 'file';
            input.dataset.projectFileType = 'land_image';
            uploadStatus = document.createElement('div');
            uploadStatus.id = 'landPhotosUploadStatus';
            uploadStatus.style.cssText = 'margin-top:8px;';
            input.addEventListener('change', () => {
              if (input.files.length > LAND_PHOTOS_MAX) {
                const transfer = new DataTransfer();
                Array.from(input.files).slice(0, LAND_PHOTOS_MAX).forEach(file => transfer.items.add(file));
                input.files = transfer.files;
                toast('يمكن رفع ' + LAND_PHOTOS_MAX + ' صور كحد أقصى للأرض');
              }
              uploadLandPhotos(input);
            });
          } else if (f.fieldType === 'pdf' || f.fieldType === 'file' || f.fieldKey === 'land_documents_files') {
            input = document.createElement('input');
            input.type = 'file';
            input.multiple = f.fieldKey === 'land_documents_files';
            input.maxLength = LAND_DOCUMENTS_MAX;
            input.accept = 'image/*,application/pdf,.pdf,.jpg,.jpeg,.png,.webp';
            input.dataset.filetype = 'pdf';
            input.dataset.projectFileType = 'land_document';
            if (f.fieldKey === 'land_documents_files') {
              uploadStatus = document.createElement('div');
              uploadStatus.id = 'landDocumentsUploadStatus';
              uploadStatus.style.cssText = 'margin-top:8px;';
              input.addEventListener('change', () => {
                if (input.files.length > LAND_DOCUMENTS_MAX) {
                  const transfer = new DataTransfer();
                  Array.from(input.files).slice(0, LAND_DOCUMENTS_MAX).forEach(file => transfer.items.add(file));
                  input.files = transfer.files;
                  toast(WFT('land.docs.max_files', 'يمكن رفع {n} ملفات كحد أقصى: الكروكي والرخصة وأي مستندات مساندة', { n: LAND_DOCUMENTS_MAX }));
                }
                uploadLandDocuments(input);
              });
              renderLandDocumentsUploadState(tenantProjectData.land_documents_files_file_meta || []);
            }
          } else if (f.fieldType === 'image') {
            input = document.createElement('input');
            input.type = 'file';
            input.accept = 'image/*';
            input.dataset.filetype = 'image';
            input.dataset.projectFileType = f.fieldKey === 'project_logo' ? 'project_logo' : 'visual_reference';
            if (f.fieldKey === 'project_logo') {
              uploadStatus = document.createElement('div');
              uploadStatus.id = 'projectLogoUploadStatus';
              uploadStatus.style.cssText = 'margin-top:4px;';
              input.addEventListener('change', () => {
                uploadProjectLogo(input);
              });
            }
          } else if (f.fieldType === 'number') {
            input = document.createElement('input');
            input.type = 'number';
          } else if (f.fieldType === 'date') {
            input = document.createElement('input');
            input.type = 'date';
          } else {
            input = document.createElement('input');
            input.type = 'text';
          }
          if ((f.fieldKey === 'max_floors_height' || f.fieldKey === 'allowed_uses') && input.tagName === 'TEXTAREA') input.rows = 4;
          input.dataset.key = f.fieldKey;
          input.dataset.type = f.fieldType;
          if (f.fieldType === 'number') {
            input.addEventListener('blur', () => {
              if (input.value !== '' && !projectNumberKeepsPrecision(f.fieldKey)) {
                input.value = String(roundSystemNumber(Number(input.value)));
              }
            });
          }
          input.placeholder = f.placeholder || '';
          if (f.fieldKey === 'approved_floor_count' && !input.placeholder) {
            input.placeholder = 'يرجى إدخال عدد الأدوار المعتمدة للمشروع وفقًا للاشتراطات التنظيمية.';
          } else if (f.fieldKey === 'approved_coverage_ratio' && !input.placeholder) {
            input.placeholder = 'يرجى إدخال نسبة التغطية المعتمدة للأرض وفقًا للاشتراطات التنظيمية.';
          } else if (f.fieldKey === 'approved_financial_area' && !input.placeholder) {
            input.placeholder = 'يرجى إدخال إجمالي المساحة البنائية المعتمدة التي ستُبنى عليها حسابات الدراسة المالية.';
          }
          // City and district stay editable: the map fill is a starting value, and
          // this section is the single edit point the market mirrors follow.
          if (f.fieldKey === 'project_type' || f.fieldKey === 'project_mixed_components' || f.fieldKey === 'project_subtype' || f.fieldKey === 'target_audience' || f.fieldKey === 'activity_class') {
            input.type = 'hidden';
            input.dataset.type = 'text';
            const stored = tenantProjectData[f.fieldKey];
            if (Array.isArray(stored) || (stored && typeof stored === 'object')) {
              input.value = JSON.stringify(stored);
            } else if (stored) {
              input.value = String(stored);
            }
            if (f.fieldKey === 'project_mixed_components') div.style.display = 'none';
          }
          if (f.defaultValue) input.value = f.defaultValue;
          if (f.isRequired) input.required = true;
          if (f.fieldKey !== 'project_type' && input.tagName === 'SELECT' && tenantProjectData && tenantProjectData[f.fieldKey]) {
            const stored = String(tenantProjectData[f.fieldKey]);
            if (stored && !Array.from(input.options).some(option => option.value === stored)) {
              const extra = document.createElement('option');
              extra.value = stored;
              extra.textContent = stored;
              input.appendChild(extra);
            }
            if (stored) input.value = stored;
          }

          // The land/croquis section owns the approved build inputs; mirror them into the
          // financial study as soon as they change so the two can never disagree.
          if (f.fieldKey === 'approved_financial_area' || f.fieldKey === 'approved_floor_count' || f.fieldKey === 'approved_coverage_ratio') {
            input.addEventListener('input', syncFinancialFromLand);
          }
          if (isClientEnteredLandField) {
            input.addEventListener('input', () => updateClientEnteredLandFieldState(input));
            input.addEventListener('change', () => updateClientEnteredLandFieldState(input));
            updateClientEnteredLandFieldState(input);
          }

          if (f.fieldKey === 'site_analysis') {
            input.readOnly = !(tenantProjectData && tenantProjectData.site_analysis);
            input.classList.add('site-analysis-input');
          }

          if (f.fieldKey === 'location_address') {
            addressInput = input;
            locationSection = sectionDiv;
            input.type = 'url';
            input.inputMode = 'url';
            input.required = true;
            label.textContent = 'رابط موقع الأرض في Google Maps *';
            input.placeholder = 'https://maps.google.com/...';
            input.addEventListener('input', () => {
              const value = input.value.trim();
              const previous = String(tenantProjectData.location_address || '').trim();
              tenantProjectData.location_address = value;
              if (previous && previous !== value) {
                tenantProjectData.location_lat = '';
                tenantProjectData.location_lng = '';
                tenantProjectData.location_coordinates_confirmed = false;
                if (latInput) latInput.value = '';
                if (lngInput) lngInput.value = '';
                tenantProjectData.location_analysis_approved = false;
                renderLocationWorkflowState();
              }
            });
          }
          if (f.fieldKey === 'location_lat') { latInput = input; locationSection = sectionDiv; }
          if (f.fieldKey === 'location_lng') { lngInput = input; locationSection = sectionDiv; }

          div.appendChild(label);
          if (f.fieldKey === 'site_analysis') {
            const analysisActions = document.createElement('div');
            analysisActions.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap;margin:8px 0;';
            const analyzeButton = document.createElement('button');
            analyzeButton.type = 'button';
            analyzeButton.className = 'btn primary small';
            analyzeButton.textContent = 'تحليل الموقع';
            analyzeButton.onclick = () => generateTenantSiteAnalysis();
            const approveButton = document.createElement('button');
            approveButton.type = 'button';
            approveButton.className = 'btn ghost small';
            approveButton.textContent = 'اعتماد التحليل';
            approveButton.onclick = () => approveTenantSiteAnalysis();
            analysisActions.appendChild(analyzeButton);
            analysisActions.appendChild(approveButton);
            div.appendChild(analysisActions);
            input.addEventListener('input', () => {
              tenantProjectData.site_analysis = input.value;
              tenantProjectData.site_analysis_approved = false;
            });
          }
          div.appendChild(input);
          if (f.fieldKey === 'allowed_uses') {
            const statusNote = document.createElement('div');
            statusNote.id = 'allowedUsesStatusNote';
            statusNote.hidden = true;
            statusNote.style.cssText = 'margin-top:8px;font-size:13px;font-weight:700;line-height:1.6';
            div.appendChild(statusNote);
            input.addEventListener('input', refreshAllowedUsesStatusNote);
          }
          if (f.fieldKey === 'land_documents_files') {
            if (uploadStatus) {
              div.appendChild(uploadStatus);
              renderLandDocumentsUploadState(tenantProjectData.land_documents_files_file_meta || []);
            }
            const analyzeButton = document.createElement('button');
            analyzeButton.type = 'button';
            analyzeButton.className = 'btn primary small land-documents-action-btn';
            analyzeButton.textContent = 'تحليل الكروكي والمستندات معًا';
            analyzeButton.style.cssText = 'margin-top:10px;width:100%;';
            analyzeButton.onclick = () => extractTenantCroquisData('land_documents_files');
            div.appendChild(analyzeButton);
          }
          if (f.fieldKey === 'land_photos' && uploadStatus) {
            div.appendChild(uploadStatus);
            renderLandPhotos(tenantProjectData.land_photos_file_meta || []);
          }
          if (f.fieldKey === 'project_logo' && uploadStatus) {
            div.appendChild(uploadStatus);
            renderProjectLogoState(tenantProjectData.project_logo_file_meta || (tenantProjectData.project_logo ? { path: tenantProjectData.project_logo, id: tenantProjectData.project_logo_file_id } : null));
          }
          if (f.fieldType === 'select' && f.fieldKey !== 'activity_class' && f.fieldKey !== 'project_level' && f.fieldKey !== 'project_type') {
            const otherInput = document.createElement('input');
            otherInput.type = 'text';
            otherInput.placeholder = 'اكتب التحديد المخصص بالتفصيل...';
            otherInput.style.cssText = 'margin-top:10px;display:none;width:100%;padding:10px 14px;border:1px solid var(--p);border-radius:10px;background:#f8fafc;font-family:inherit;font-size:13px;box-shadow:0 1px 3px rgba(0,0,0,0.05);';
            otherInput.dataset.key = f.fieldKey + '_other';
            otherInput.dataset.type = 'text';
            if (tenantProjectData && tenantProjectData[f.fieldKey + '_other']) {
              otherInput.value = tenantProjectData[f.fieldKey + '_other'];
            }
            const checkOther = () => {
              const val = (input.value || '').trim();
              const isOther = val === 'أخرى' || val.startsWith('أخرى');
              otherInput.style.display = isOther ? 'block' : 'none';
              if (isOther && f.isRequired) otherInput.required = true;
              else otherInput.required = false;
            };
            input.addEventListener('change', () => {
              checkOther();
              if (f.fieldKey === 'project_type') {
                refreshAllowedUsesStatusNote();
                if (typeof syncProjectClassificationFields === 'function') syncProjectClassificationFields();
              }
            });
            input.addEventListener('input', checkOther);
            otherInput.addEventListener('input', () => {
              if (tenantProjectData) tenantProjectData[f.fieldKey + '_other'] = otherInput.value;
              if (typeof triggerAutoSaveDraft === 'function') triggerAutoSaveDraft();
            });
            div.appendChild(otherInput);
            checkOther();
          }

          // Geocoding stays explicit: the button is the only trigger for the pasted link.
          if (f.fieldKey === 'location_address' && addressInput && sectionKey === 'location') {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn ghost';
            btn.textContent = 'تحليل رابط الموقع';
            btn.style.marginTop = '8px';
            btn.onclick = () => analyzeTenantSite();
            div.appendChild(btn);

          }

          sectionDiv.appendChild(div);
        });

        if (sectionKey === 'land_croquis') {
          const analysisResultsField = document.createElement('div');
          analysisResultsField.className = 'tenant-field full';
          analysisResultsField.style.display = 'none';
          analysisResultsField.innerHTML = '<input type="hidden" data-key="land_documents_analysis" data-type="text" id="landDocumentsAnalysisData"><div id="landDocumentsAnalysisPreview" style="display:none;margin-top:10px"></div>';

          const coordinatesField = document.createElement('div');
          coordinatesField.className = 'tenant-field full';
          coordinatesField.innerHTML = '<input type="hidden" data-key="survey_coordinates" data-type="text" id="surveyCoordinatesData"><div id="surveyCoordinatesPanel"></div>';

          const directionsField = document.createElement('div');
          directionsField.className = 'tenant-field full';
          directionsField.innerHTML = '<input type="hidden" data-key="directions_table" data-type="text" id="directionsTableData"><div id="surveyDirectionsPanel" class="survey-directions-panel"></div>';

          sectionDiv.appendChild(analysisResultsField);
          sectionDiv.appendChild(coordinatesField);
          sectionDiv.appendChild(directionsField);
        }

        return sectionDiv;
      }

      const sectionOrder = ['basic', 'location', 'land_croquis'];
      sectionOrder.forEach(sectionKey => {
        const sectionDiv = renderFormSection(sectionKey);
        if (sectionDiv) form.appendChild(sectionDiv);
      });

      // Add map preview section
      if (addressInput || latInput || lngInput) {
        const previewDiv = document.createElement('div');
        previewDiv.className = 'tenant-field full';
        previewDiv.id = 'tenantMapPreview';
        previewDiv.innerHTML = `
          <label>تحليل الموقع والخرائط</label>
          <div id="locationAnalysisApprovalPanel" style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;align-items:center;">
            <button type="button" class="btn primary" id="locationAnalysisApprovalButton" data-section-lock-ignore="1" onclick="toggleLocationAnalysisApproval()">اعتماد تحليل الموقع</button>
            <button type="button" class="btn ghost" id="generateOverviewMapButton" data-section-lock-ignore="1" onclick="generateOverviewMap()">توليد خريطة الأرض / المبنى</button>
            <span id="locationAnalysisApprovalStatus" class="tenant-hint">تحليل الموقع يحتاج اعتمادًا قبل توليد الخرائط</span>
          </div>
          <input type="hidden" id="locationAnalysisApproved" data-key="location_analysis_approved" data-type="text" value="">
          <div id="locationMapGenerationControls"></div>
          <input type="hidden" id="tenantCoordinatesConfirmed" data-key="location_coordinates_confirmed" data-type="text" value="">
          <div id="mapPreviewImage" style="display:none;max-width:100%;border-radius:8px;overflow:hidden;border:1px solid #ddd;position:relative;">
            <img src="" alt="Map preview" style="width:100%;display:block;cursor:crosshair;" onclick="setTenantMapPointFromClick(event)" />
            <svg id="mapPolygonOverlay" viewBox="0 0 100 100" preserveAspectRatio="none" style="position:absolute;inset:0;width:100%;height:100%;pointer-events:none"></svg>
            <div id="mapLabelOverlay" style="position:absolute;inset:0;pointer-events:none"></div>
          </div>
          <div id="mapPreviewGallery" class="tenant-map-preview-gallery" style="display:none;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-top:12px;"></div>
          <p id="mapPreviewHint" class="tenant-hint" style="margin:8px 0 0;display:none"></p>
          <input id="tenantLocationPolygon" type="hidden" data-key="location_polygon" data-type="text" value="">
          <div id="siteAnalysisWarnings" hidden style="margin-top:10px;padding:11px 13px;border-radius:12px;background:#fff0f0;border:1px solid #efb3b3;color:#9c1d1d;font-weight:700;font-size:13px;line-height:1.6"></div>
          <div id="landmarksPreview" style="margin-top:10px;display:none;"></div>
        `;
        (locationSection || form).appendChild(previewDiv);
        (locationSection || form).querySelectorAll('[data-key]').forEach(control => {
          if (LOCATION_ANALYSIS_KEYS.includes(control.dataset.key)) {
            control.addEventListener('input', invalidateLocationAnalysisApproval);
            control.addEventListener('change', invalidateLocationAnalysisApproval);
          }
        });
        setTimeout(renderLocationWorkflowState, 0);
      }

      // Append order defines the sidebar order: basic, location, land/croquis, timeline,
      // financial, team, market study, visual concept, executive content, and contact. The timeline
      // comes before the financial study because it feeds it. Executive content writes
      // from earlier sections and never invents facts. Contact information is at the end.
      // Widget sections are governed like field sections: a revoked key must not render.
      if (tenantAllowedFieldSections['section-timeline']) addTimelineTable(form);
      if (tenantAllowedFieldSections['section-financial-calc']) addFinancialCalculations(form);
      if (tenantAllowedFieldSections['section-team']) addTeamSection(form);
      if (tenantAllowedFieldSections['section-market-study']) addMarketStudySection(form);
      if (tenantAllowedFieldSections['section-visual-concept']) addVisualConceptSection(form);
      if (tenantAllowedFieldSections['section-executive-content']) addExecutiveContentSection(form);

      const contactSectionDiv = renderFormSection('contact');
      if (contactSectionDiv) form.appendChild(contactSectionDiv);

      tenantVisualConceptState = normalizeVisualConceptState(tenantProjectData.visual_concept || tenantVisualConceptState);
      persistVisualConceptDraftState();

      const projectSections = Array.from(form.querySelectorAll('.tenant-form-section[data-section]'));
      populateProjectSidebar(projectSections);
      const initialStatuses = {};
      projectSections.forEach(section => {
        if (section.dataset.underConstruction === '1') return;
        initialStatuses[section.dataset.section] = tenantProjectSectionStatuses[section.dataset.section] || 'draft';
      });
      // Every section must carry an explicit status. This was computed and then dropped, so a
      // section nobody opened had no entry at all and the server's approval gate — which only
      // walks the stored statuses — let the file through as if that section were approved.
      applySectionStatuses(initialStatuses);
      form.removeEventListener('input', triggerAutoSaveDraft);
      form.removeEventListener('change', triggerAutoSaveDraft);
      form.addEventListener('input', triggerAutoSaveDraft);
      form.addEventListener('change', triggerAutoSaveDraft);

      const initialSection = projectSections.find(section => section.dataset.section === tenantActiveProjectSection) || projectSections[0];
      if (initialSection) showSection(initialSection.dataset.section, true);
      updateTenantPolygonControls();
      renderSurveyCoordinates(tenantProjectData.survey_coordinates || []);
      renderSurveyDirections(tenantProjectData.directions_table || {});
      renderLandDocumentsUploadState(tenantProjectData.land_documents_files_file_meta || []);
      renderLandPhotos(tenantProjectData.land_photos_file_meta || []);
      renderProjectLogoState(tenantProjectData.project_logo_file_meta || (tenantProjectData.project_logo ? { path: tenantProjectData.project_logo, id: tenantProjectData.project_logo_file_id } : null));
      renderProjectTeam();
      enhanceProjectClassificationFields();
      refreshAllowedUsesStatusNote();
      applyMarketStudyState(getMarketStudyState());
      renderVisualConceptPage();
      applyExecutiveContentState(getExecutiveContentState());
      persistVisualConceptDraftState();
    }