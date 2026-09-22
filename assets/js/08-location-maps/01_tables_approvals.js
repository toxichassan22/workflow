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

