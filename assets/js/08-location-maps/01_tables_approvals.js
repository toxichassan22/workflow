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
      tr.dataset.manualPosition = row.manual_position ? '1' : '';

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
        selectInput.dataset.sectionLockIgnore = '1';
        selectInput.checked = !!(row.show_on_map || row.selected);
        selectInput.addEventListener('change', () => {
          serializeLocationTable(key);
          scheduleMapTableRecompose(key);
          if (typeof triggerAutoSaveDraft === 'function') triggerAutoSaveDraft();
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
        updateLocationTableOrderControls(key);
        if (cfg.road && roadName) {
          const roadKey = accessRoadNameKey(roadName);
          tenantProjectData.manual_road_paths = (Array.isArray(tenantProjectData.manual_road_paths) ? tenantProjectData.manual_road_paths : [])
            .filter(item => accessRoadNameKey(item?.name) !== roadKey);
          tenantProjectData.access_roads_data = (Array.isArray(tenantProjectData.access_roads_data) ? tenantProjectData.access_roads_data : [])
            .filter(item => accessRoadNameKey(item?.name) !== roadKey);
          if (tenantCreativeImages) {
            tenantCreativeImages.map_access_roads = (Array.isArray(tenantCreativeImages.map_access_roads) ? tenantCreativeImages.map_access_roads : [])
              .filter(item => accessRoadNameKey(item?.name) !== roadKey);
          }
        }
        serializeLocationTable(key);
        scheduleMapTableRecompose(key);
        releaseLocationSectionApproval();
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

        const moveUpBtn = document.createElement('button');
        moveUpBtn.type = 'button';
        moveUpBtn.dataset.sectionLockIgnore = '1';
        moveUpBtn.className = 'btn small ghost lt-move-up';
        moveUpBtn.textContent = 'أعلى';
        moveUpBtn.addEventListener('click', () => moveLocationTableRow(key, tr, -1));
        actionGroup.appendChild(moveUpBtn);

        const moveDownBtn = document.createElement('button');
        moveDownBtn.type = 'button';
        moveDownBtn.dataset.sectionLockIgnore = '1';
        moveDownBtn.className = 'btn small ghost lt-move-down';
        moveDownBtn.textContent = 'أسفل';
        moveDownBtn.addEventListener('click', () => moveLocationTableRow(key, tr, 1));
        actionGroup.appendChild(moveDownBtn);
      }
      actionGroup.appendChild(delBtn);
      delTd.appendChild(actionGroup);

      [nameInput, categoryInput, distInput, durInput].filter(Boolean).forEach(inp => inp.addEventListener('input', () => {
        serializeLocationTable(key);
        scheduleMapTableRecompose(key);
        releaseLocationSectionApproval();
      }));

      tr.appendChild(nameTd);
      if (categoryTd) tr.appendChild(categoryTd);
      tr.appendChild(distTd);
      tr.appendChild(durTd);
      if (selectTd) tr.appendChild(selectTd);
      tr.appendChild(delTd);
      tbody.appendChild(tr);
      updateLocationTableOrderControls(key);
    }

    function updateLocationTableOrderControls(key) {
      const table = document.querySelector('#tenantProjectForm table.location-table[data-location-table="' + key + '"]');
      if (!table) return;
      const rows = Array.from(table.querySelectorAll('tbody tr'));
      rows.forEach((row, index) => {
        const moveUp = row.querySelector('.lt-move-up');
        const moveDown = row.querySelector('.lt-move-down');
        if (moveUp) moveUp.disabled = index === 0;
        if (moveDown) moveDown.disabled = index === rows.length - 1;
      });
    }

    function moveLocationTableRow(key, row, direction) {
      const tbody = row?.parentElement;
      if (!tbody) return false;
      const rows = Array.from(tbody.children);
      const index = rows.indexOf(row);
      const target = index + Number(direction || 0);
      if (index < 0 || target < 0 || target >= rows.length) return false;
      if (target < index) tbody.insertBefore(row, rows[target]);
      else tbody.insertBefore(rows[target], row);
      updateLocationTableOrderControls(key);
      serializeLocationTable(key);
      scheduleMapTableRecompose(key);
      releaseLocationSectionApproval();
      if (typeof triggerAutoSaveDraft === 'function') triggerAutoSaveDraft();
      return true;
    }

    function locationDistanceKmOrBlank(item) {
      const direct = parseFloat(item && (item.distance_km ?? item.distance));
      if (Number.isFinite(direct)) return direct;
      const textMatch = String((item && item.distance_text) || '').replace(/,/g, '').match(/(\d+(?:\.\d+)?)/);
      return textMatch ? parseFloat(textMatch[1]) : '';
    }

    function setLocationTableValue(key, value) {
      const table = document.querySelector('#tenantProjectForm table.location-table[data-location-table="' + key + '"]');
      if (!table) return;
      const tbody = table.querySelector('tbody');
      tbody.innerHTML = '';
      if (!Array.isArray(value)) {
        // Text lines carry no show_on_map/lat/lng — the structured mirror does. Hydration and
        // the deferred createLocationTableField fill both hand us text, so prefer the mirror or
        // the trailing serializeLocationTable would write the stripped copy over the stored one.
        const structured = key === 'main_roads'
          ? tenantProjectData.main_roads_data
          : key === 'nearby_landmarks' ? tenantProjectData.nearby_landmarks_data
            : key === 'city_landmarks' ? tenantProjectData.city_landmarks_data : null;
        if (Array.isArray(structured) && structured.length) value = structured;
      }
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
        releaseLocationSectionApproval();
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
        display.textContent = fetchedAt ? WFT('sectionver.data_updated', 'آخر تحديث للبيانات: {time}', { time: formatLocationDataFetchedAt(fetchedAt) }) : '';
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

    function releaseLocationSectionApproval() {
      if (tenantProjectSectionStatuses.location !== 'approved') return false;
      applySectionStatuses({ location: 'draft' });
      return true;
    }

    // A table edit must reach the persisted raster on its own: the designer
    // chat refreshes a slide from the latest stored map file, so a change that
    // only edits project data keeps serving the pre-edit image. Each mutation
    // schedules a debounced overlay recompose — the same local redraw the
    // confirm buttons run — so the stored raster tracks the tables without
    // extra steps or warnings.
    const tenantMapRecomposeTimers = {};
    const tenantMapRecomposeInflight = {};
    const tenantMapRecomposeFailures = {};
    // mapType -> promise that resolves once a recompose's server request ends.
    // Set inside the enqueued task, so a recompose merely queued on the shared
    // map-write chain is not "applying" yet — and a running regen must never
    // wait on it (it waits on the regen's own chain slot).
    const tenantMapRecomposeApplying = {};
    const MAP_RECOMPOSE_TOKENS = {
      access: '##MAP_ACCESS##', catchment: '##MAP_CATCHMENT##', landmarks: '##MAP_LANDMARKS##'
    };

    function scheduleMapRecomposeType(mapType) {
      const token = MAP_RECOMPOSE_TOKENS[mapType];
      if (!token) return;
      // Nothing to refresh until this map has actually been generated.
      const base = token.slice(0, -2);
      const placeholders = (tenantCreativeImages && tenantCreativeImages.map_placeholders) || {};
      if (![token, base + '_SATELLITE##', base + '_ROADMAP##'].some(t => placeholders[t])) return;
      clearTimeout(tenantMapRecomposeTimers[mapType]);
      tenantMapRecomposeTimers[mapType] = setTimeout(() => {
        void runMapTableRecompose(mapType).catch(e => console.warn('[MAP RECOMPOSE]', e));
      }, 1500);
    }

    function scheduleMapTableRecompose(key) {
      scheduleMapRecomposeType((LOCATION_TABLE_FIELDS[key] || {}).mapType);
    }

    function runMapTableRecompose(mapType) {
      if (tenantMapRecomposeInflight[mapType]) {
        scheduleMapRecomposeType(mapType);
        return tenantMapRecomposeInflight[mapType];
      }
      clearTimeout(tenantMapRecomposeTimers[mapType]);
      delete tenantMapRecomposeTimers[mapType];
      // A timer queued before a location invalidation must not fire after it —
      // that overlay would stamp the stale raster with the new site's metadata.
      const recomposeBase = MAP_RECOMPOSE_TOKENS[mapType];
      if (!recomposeBase) return Promise.resolve(false);
      const recomposePlaceholders = (tenantCreativeImages && tenantCreativeImages.map_placeholders) || {};
      const recomposeStem = recomposeBase.slice(0, -2);
      if (![recomposeBase, recomposeStem + '_SATELLITE##', recomposeStem + '_ROADMAP##']
          .some(t => recomposePlaceholders[t])) return Promise.resolve(false);
      // An open edit session owns this raster — its confirm path applies it.
      if ((mapType === 'landmarks' && tenantLandmarksEditMode)
          || (mapType === 'catchment' && tenantCatchmentEditMode)
          || (mapType === 'access' && tenantRoadEditMode)) return Promise.resolve(false);
      const apply = { landmarks: applyLandmarksMapEdits, catchment: applyCatchmentMapEdits, access: applyAccessMapEdits }[mapType];
      if (typeof apply !== 'function') return Promise.resolve(false);
      const scope = String(tenantPresentationId || tenantProjectData.draftId || '');
      const run = (async () => {
        let success = false;
        try {
          if (typeof saveMapPreviewState === 'function' && (await saveMapPreviewState()) === false) return false;
          // Run on the shared map-write chain — a recompose posting while a
          // full regen is in flight can land after it and overwrite the fresh
          // map state with the pre-regen one.
          const applyTask = () => {
            let done;
            tenantMapRecomposeApplying[mapType] = new Promise(resolve => { done = resolve; });
            return Promise.resolve().then(apply).finally(() => {
              delete tenantMapRecomposeApplying[mapType];
              done();
            });
          };
          success = (typeof enqueueTenantMapWrite === 'function'
            ? await enqueueTenantMapWrite(applyTask) : await applyTask()) === true;
          return success;
        } finally {
          if (success) delete tenantMapRecomposeFailures[mapType];
          else tenantMapRecomposeFailures[mapType] = scope;
          delete tenantMapRecomposeInflight[mapType];
        }
      })();
      tenantMapRecomposeInflight[mapType] = run;
      return run;
    }

    async function flushMapTableRecompose(mapType) {
      const keys = state => Object.keys(state).filter(type => !mapType || type === mapType);
      let success = true;
      while (true) {
        const inflight = keys(tenantMapRecomposeInflight).map(type => tenantMapRecomposeInflight[type]);
        if (inflight.length) {
          if ((await Promise.all(inflight)).some(result => result === false)) success = false;
          continue;
        }
        const pending = keys(tenantMapRecomposeTimers);
        if (!pending.length) return success && !keys(tenantMapRecomposeFailures)
          .some(type => tenantMapRecomposeFailures[type] === String(tenantPresentationId || tenantProjectData.draftId || ''));
        pending.forEach(type => clearTimeout(tenantMapRecomposeTimers[type]));
        const runs = pending.map(type => runMapTableRecompose(type));
        // An apply already in flight still leaves the outgoing payload one
        // raster behind — wait for those alongside the freshly scheduled runs.
        if ((await Promise.all(runs)).some(result => result === false)) success = false;
      }
    }

    // A full regen of mapType supersedes that map's queued table recompose: the
    // regen serializes the same rows and redraws the raster from scratch, so a
    // pending debounce would only repeat work — and landing after the regen
    // response it would overwrite the fresh map state with the pre-regen one.
    // Applies already running still get to finish: they may hold the
    // server-side map lock and have started writing state. Recomposes only
    // queued on the map-write chain stay queued — they run after this regen
    // and overlay the fresh raster, which is the order the edits happened in.
    async function settleMapRecomposeBeforeRegen(mapType) {
      if (tenantMapRecomposeTimers[mapType]) {
        clearTimeout(tenantMapRecomposeTimers[mapType]);
        delete tenantMapRecomposeTimers[mapType];
      }
      const applying = Object.values(tenantMapRecomposeApplying);
      if (applying.length) await Promise.allSettled(applying);
    }

    // Re-entrancy guard for the pending-placeholder reselect inside
    // renderLocationWorkflowState (selectMapPreviewView renders before it can
    // populate the preview state).
    let locationMapReselectPending = false;

    function renderLocationWorkflowState() {
      const overview = typeof MAP_PREVIEW_VIEW_DEFS !== 'undefined' ? MAP_PREVIEW_VIEW_DEFS[0] : null;
      const overviewGenerated = mapPreviewIsGenerated(overview);
      const generateOverviewButton = document.getElementById('generateOverviewMapButton');
      const toolsPanel = document.getElementById('locationMapToolsPanel');
      const hasCoords = isUsableMapCoordinate(tenantProjectData.location_lat, true)
        && isUsableMapCoordinate(tenantProjectData.location_lng, false);
      // The overview generate button belongs to its own map: it only shows
      // while overview is selected and still ungenerated — a permanently
      // disabled button floating above every map was noise.
      const showOverviewGenerate = tenantSelectedMapType === 'overview' && !overviewGenerated;
      if (generateOverviewButton) {
        generateOverviewButton.style.display = showOverviewGenerate ? '' : 'none';
        generateOverviewButton.disabled = !hasCoords || overviewGenerated;
      }
      if (toolsPanel) toolsPanel.style.display = showOverviewGenerate ? 'flex' : 'none';
      Object.keys(LOCATION_TABLE_FIELDS).forEach(key => {
        const roadModeLocked = key === 'main_roads' && tenantRoadEditMode;
        const catchmentModeLocked = key === 'city_landmarks' && tenantCatchmentEditMode;
        const landmarksModeLocked = key === 'nearby_landmarks' && tenantLandmarksEditMode;
        const modeLocked = roadModeLocked || catchmentModeLocked || landmarksModeLocked
          || tenantMapApprovalBusy(LOCATION_TABLE_FIELDS[key]?.mapType);
        document.querySelectorAll('#tenantProjectForm table[data-location-table="' + key + '"] input, #tenantProjectForm table[data-location-table="' + key + '"] textarea')
          .forEach(control => { control.disabled = modeLocked; });
        document.querySelectorAll('#tenantProjectForm table[data-location-table="' + key + '"] button')
          .forEach(control => { control.disabled = modeLocked; });
        const add = document.querySelector('#tenantProjectForm table[data-location-table="' + key + '"]')?.closest('.location-table-field')?.querySelector('.location-table-add');
        if (add) add.disabled = modeLocked;
      });
      const controls = document.getElementById('locationMapGenerationControls');
      if (controls && typeof MAP_PREVIEW_VIEW_DEFS !== 'undefined') {
        const view = MAP_PREVIEW_VIEW_DEFS.find(item => item.mapType === tenantSelectedMapType) || MAP_PREVIEW_VIEW_DEFS[0];
        tenantSelectedMapType = view.mapType;
        const generated = mapPreviewIsGenerated(view);
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
          actions = tenantMapApproved('overview')
            ? '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="unapproveTenantMap(\'overview\')">إلغاء اعتماد الخريطة</button>'
            : '<button type="button" class="btn primary small" data-section-lock-ignore="1" onclick="approveTenantMap(\'overview\')">اعتماد الخريطة</button>' +
              '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="regenerateMapPreview(\'overview\')">إعادة توليد الخريطة</button>' +
              ((tenantCreativeImages.map_viewport_overrides || {}).overview
                ? '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="resetMapViewport(\'overview\')">الإطار التلقائي</button>' : '') +
              '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="toggleTenantPolygonMode()">رسم حدود الموقع</button>' +
              '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="startTenantMapPinMode()">تعيين الموقع</button>';
        } else if (view.mapType === 'catchment' && tenantCatchmentEditMode) {
          actions = '<button type="button" class="btn primary small" data-section-lock-ignore="1" onclick="confirmCatchmentEdits()">اعتماد</button>' +
            '<button type="button" class="btn ghost small" data-section-lock-ignore="1" id="undoCatchmentEditsButton" onclick="undoCatchmentEdits()">تراجع</button>' +
            '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="cancelCatchmentEdits()">إلغاء</button>';
        } else if (view.mapType === 'catchment' && generated) {
          actions = tenantMapApproved('catchment')
            ? '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="unapproveTenantMap(\'catchment\')">إلغاء اعتماد الخريطة</button>'
            : '<button type="button" class="btn primary small" data-section-lock-ignore="1" onclick="approveTenantMap(\'catchment\')">اعتماد الخريطة</button>' +
              '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="regenerateMapPreview(\'catchment\')">إعادة توليد الخريطة</button>' +
              ((tenantCreativeImages.map_viewport_overrides || {}).catchment
                ? '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="resetMapViewport(\'catchment\')">الإطار التلقائي</button>' : '') +
              '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="startCatchmentEditMode()">تعديل</button>';
        } else if (view.mapType === 'landmarks' && tenantLandmarksEditMode) {
          actions = '<button type="button" class="btn primary small" data-section-lock-ignore="1" onclick="confirmLandmarksEdits()">اعتماد</button>' +
            '<button type="button" class="btn ghost small" data-section-lock-ignore="1" id="undoLandmarksEditsButton" onclick="undoLandmarksEdits()">تراجع</button>' +
            '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="cancelLandmarksEdits()">إلغاء</button>';
        } else if (view.mapType === 'landmarks' && generated) {
          actions = tenantMapApproved('landmarks')
            ? '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="unapproveTenantMap(\'landmarks\')">إلغاء اعتماد الخريطة</button>'
            : '<button type="button" class="btn primary small" data-section-lock-ignore="1" onclick="approveTenantMap(\'landmarks\')">اعتماد الخريطة</button>' +
              '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="regenerateMapPreview(\'landmarks\')">إعادة توليد الخريطة</button>' +
              ((tenantCreativeImages.map_viewport_overrides || {}).landmarks
                ? '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="resetMapViewport(\'landmarks\')">الإطار التلقائي</button>' : '') +
              '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="startLandmarksEditMode()">تعديل</button>';
        } else if (view.mapType === 'access' && tenantRoadEditMode) {
          actions = accessRoadEditControlsHtml();
        } else if (view.mapType === 'access' && generated) {
          actions = tenantMapApproved('access')
            ? '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="unapproveTenantMap(\'access\')">إلغاء اعتماد الخريطة</button>'
            : '<button type="button" class="btn primary small" data-section-lock-ignore="1" onclick="approveTenantMap(\'access\')">اعتماد الخريطة</button>' +
              '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="regenerateMapPreview(\'access\')">إعادة توليد الخريطة</button>' +
              ((tenantCreativeImages.map_viewport_overrides || {}).access
                ? '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="resetMapViewport(\'access\')">الإطار التلقائي</button>' : '') +
              '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="startAccessRoadEditMode()">إضافة / تعديل الطرق</button>';
        } else if (view.mapType !== 'overview') {
          actions = '<button type="button" class="btn small primary" data-section-lock-ignore="1" onclick="regenerateMapPreview(\'' + view.mapType + '\')" ' + (hasCoords ? '' : 'disabled') + '>' + (generated ? 'إعادة توليد ' : 'توليد ') + view.title + '</button>';
        }
        controls.innerHTML = actions
          ? '<div class="map-active-controls"><div class="map-active-controls-title">' + escapeHtml(view.title) + '</div><div class="map-active-controls-actions">' + actions + '</div></div>'
          : '';
        updateTenantPolygonControls();
        updateTenantRoadControls();
        updateTenantCatchmentControls();
        updateTenantLandmarksControls();
        updateTenantMapInteractionState();
        if (tenantMapApprovalBusy(view.mapType)) {
          controls.querySelectorAll('button').forEach(button => { button.disabled = true; });
        }
      }
      renderMapPreviewGallery();
      // The selected map can be picked while map_placeholders is still empty
      // (the section renders before the draft payload lands) — the select then
      // bails with no preview state and the box stays blank until the user
      // clicks the card again. Once the data catches up, re-select it here.
      if (!tenantMapPreviewState && tenantSelectedMapType && !locationMapReselectPending
        && typeof MAP_PREVIEW_VIEW_DEFS !== 'undefined') {
        const selView = MAP_PREVIEW_VIEW_DEFS.find(item => item.mapType === tenantSelectedMapType);
        const selPlaceholders = tenantCreativeImages.map_placeholders || {};
        const selHasUrl = selView
          && ((selView.keys || []).some(key => selPlaceholders[key])
            || (selView.editableKeys || []).some(key => selPlaceholders[key]));
        const selCenter = (tenantCreativeImages.map_centers || {})[tenantSelectedMapType] || {};
        const selBaked = (tenantCreativeImages.map_baked_frames || {})[tenantSelectedMapType] || {};
        const selLat = selBaked.lat ?? selCenter.lat ?? tenantCreativeImages.map_lat ?? tenantProjectData.location_lat;
        const selLng = selBaked.lng ?? selCenter.lng ?? tenantCreativeImages.map_lng ?? tenantProjectData.location_lng;
        if (selHasUrl && Number.isFinite(Number(selLat)) && Number.isFinite(Number(selLng))) {
          locationMapReselectPending = true;
          try { selectMapPreviewView(tenantSelectedMapType); }
          finally { locationMapReselectPending = false; }
        }
      }
      if (typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en') {
        const panel = document.getElementById('locationMapToolsPanel');
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
      if (typeof mapApprovalBlocksEdit === 'function' && mapApprovalBlocksEdit(mapType)) return;
      if (!openLocationTableMap(mapType)) return;
      tenantMapPolygonMode = false;
      tenantLandmarkPlacementTarget = { key, tr };
      renderLocationWorkflowState();
      toast(WFT('maps.landmark_pick_on', 'تم تفعيل تحديد موقع المعلم على {map}', { map: wfTr(mapType === 'landmarks' ? 'خريطة المعالم' : 'خريطة المنطقة') }));
    }

