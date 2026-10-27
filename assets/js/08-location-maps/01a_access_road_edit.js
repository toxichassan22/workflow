    /* Access-road edit session: rows, drawn/auto geometry, thickness, label
       placement, path clearing/restoring and vertex-level path editing.
       Split out of 01_tables_approvals.js to keep every part file small. */

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
      const projectRoads = Array.isArray(tenantProjectData.access_roads_data) ? tenantProjectData.access_roads_data : [];
      const creativeRoads = Array.isArray(tenantCreativeImages.map_access_roads) ? tenantCreativeImages.map_access_roads : [];
      creativeRoads.forEach(add);
      projectRoads.forEach(add);
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
        // In edit mode a row's drawn points are the path being sketched — they
        // override the stored geometry live, and a road with no stored path
        // still renders once it has two drawn points.
        const drawn = tenantRoadEditMode && Array.isArray(row.points) && row.points.length >= 2 ? row.points : null;
        // A cleared path keeps its geometry in storage so it can be restored,
        // but the map must not draw it.
        if ((tenantRoadEditMode ? row.pathCleared : row.path_cleared) && !drawn) return null;
        if (!geometry && !drawn) return null;
        return {
          ...(geometry || {}),
          points: drawn || geometry.points,
          name: row.name,
          path_width_scale: row.path_width_scale || geometry?.path_width_scale || 0.55,
          label_point: positions[row.name] || positions[row.original_name] || geometry?.label_point || null,
          label_scale: sizes[row.name] || sizes[row.original_name] || geometry?.label_scale || 1
        };
      }).filter(Boolean);
      return roads;
    }

    // A render response only carries the roads it drew. Geometry for a road
    // whose path the client cleared — or one this run could not redraw — stays
    // in storage, so استعادة المسار works without another provider call, and a
    // table edit can never blank the geometry of the roads that remain.
    function mergeAccessRoadsResponse(returnedAccessRoads) {
      const approved = new Set(accessRoadRows().map(row => accessRoadNameKey(row.name)).filter(Boolean));
      const merged = new Map();
      (Array.isArray(tenantProjectData.access_roads_data) ? tenantProjectData.access_roads_data : []).forEach(road => {
        const key = accessRoadNameKey(road?.name);
        if (key && approved.has(key)) merged.set(key, road);
      });
      (Array.isArray(returnedAccessRoads) ? returnedAccessRoads : []).forEach(road => {
        if (!road?.name) return;
        merged.set(accessRoadNameKey(road.name), road);
      });
      tenantProjectData.access_roads_data = [...merged.values()];
      tenantCreativeImages.map_access_roads = tenantProjectData.access_roads_data;
      return tenantProjectData.access_roads_data;
    }

    function roadEditSnapshot() {
      return JSON.stringify({ draft: tenantRoadEditDraft, selectedIndex: tenantRoadEditSelectedIndex });
    }

    function pushRoadEditHistory() {
      const snapshot = roadEditSnapshot();
      if (tenantRoadEditHistory[tenantRoadEditHistory.length - 1] !== snapshot) tenantRoadEditHistory.push(snapshot);
      if (tenantRoadEditHistory.length > 300) tenantRoadEditHistory.shift();
    }

    function accessRoadEditControlsHtml() {
      const rows = tenantRoadEditDraft?.rows || [];
      const options = rows.map((row, index) => '<option value="' + index + '" ' + (tenantRoadEditSelectedIndex === index ? 'selected' : '') + '>' + escapeHtml(row.name) + '</option>').join('');
      const selectedName = tenantRoadEditSelectedIndex >= 0 ? rows[tenantRoadEditSelectedIndex]?.name || '' : tenantRoadEditDraft?.newName || '';
      const selectedCleared = tenantRoadEditSelectedIndex >= 0
        && !!tenantRoadEditDraft?.rows?.[tenantRoadEditSelectedIndex]?.pathCleared;
      return '<label class="map-control-field">اختيار الطريق<select id="accessRoadEditSelect" onchange="selectAccessRoadEdit(this.value)">' + options + '<option value="-1" ' + (tenantRoadEditSelectedIndex < 0 ? 'selected' : '') + '>طريق جديد</option></select></label>' +
        '<label class="map-control-field">اسم الطريق<input id="accessRoadEditName" type="text" value="' + escapeHtml(selectedName) + '" oninput="updateAccessRoadDraftName(this.value)"></label>' +
        '<button type="button" class="btn ghost small" data-section-lock-ignore="1" id="clearAccessRoadPathButton" onclick="clearAccessRoadPath()">مسح المسار</button>' +
        (selectedCleared
          ? '<button type="button" class="btn ghost small" data-section-lock-ignore="1" id="restoreAccessRoadPathButton" onclick="restoreAccessRoadPath()">استعادة المسار</button>'
          : '') +
        '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="adjustAccessRoadLabelSize(-0.1)">تصغير الاسم</button>' +
        '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="adjustAccessRoadLabelSize(0.1)">تكبير الاسم</button>' +
        accessRoadPathWidthSliderHtml() +
        '<button type="button" class="btn ghost small" data-section-lock-ignore="1" id="undoAccessRoadEditsButton" onclick="undoAccessRoadEdits()">تراجع</button>' +
        '<button type="button" class="btn primary small" data-section-lock-ignore="1" onclick="confirmAccessRoadEdits()">اعتماد</button>' +
        '<button type="button" class="btn ghost small" data-section-lock-ignore="1" onclick="cancelAccessRoadEdits()">إلغاء</button>';
    }

    async function startAccessRoadEditMode() {
      if (typeof mapApprovalBlocksEdit === 'function' && mapApprovalBlocksEdit('access')) return;
      if (!openLocationTableMap('access')) return;
      const storedRoadWidths = [
        ...(Array.isArray(tenantProjectData.access_roads_data) ? tenantProjectData.access_roads_data : []),
        ...(Array.isArray(tenantCreativeImages?.map_access_roads) ? tenantCreativeImages.map_access_roads : []),
        ...(Array.isArray(tenantProjectData.manual_road_paths) ? tenantProjectData.manual_road_paths : [])
      ];
      tenantLandmarkPlacementTarget = null;
      tenantRoadEditMode = true;
      tenantRoadEditDraft = {
        rows: accessRoadRows().map(row => {
          const geometry = storedRoadWidths.find(road => accessRoadNameKey(road?.name) === accessRoadNameKey(row.original_name)
            || accessRoadNameKey(road?.name) === accessRoadNameKey(row.name));
          const { path_cleared, ...rest } = row;
          return {
            ...rest,
            pathCleared: !!path_cleared,
            has_stored_path: Array.isArray(geometry?.points) && geometry.points.length >= 2,
            path_width_scale: row.path_width_scale || geometry?.path_width_scale || 0.55
          };
        }),
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
      closeAccessRoadPathWidthGesture();
      tenantRoadEditSelectedIndex = Number(value);
      syncAccessRoadPathWidthSlider();
      const input = document.getElementById('accessRoadEditName');
      if (input) input.value = tenantRoadEditSelectedIndex >= 0
        ? tenantRoadEditDraft?.rows?.[tenantRoadEditSelectedIndex]?.name || ''
        : tenantRoadEditDraft?.newName || '';
      renderTenantMapPolygonOverlay();
      updateTenantRoadControls();
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

    // A map click in the unified edit mode adds a vertex to the selected
    // road's path — drawing stays open across roads (switch in the select)
    // until اعتماد commits everything in one recompose. Label positions move
    // by dragging the label itself, so clicks are free for the path.
    function addAccessRoadPathPoint(lat, lng) {
      if (!tenantRoadEditMode || !tenantRoadEditDraft) return;
      const pendingNew = tenantRoadEditSelectedIndex < 0;
      if (pendingNew && !String(document.getElementById('accessRoadEditName')?.value || tenantRoadEditDraft.newName || '').trim()) {
        toast('اسم الطريق مطلوب');
        return;
      }
      pushRoadEditHistory();
      const row = commitAccessRoadDraftName();
      if (!row || !String(row.name || '').trim()) return;
      row.points = Array.isArray(row.points) ? row.points : [];
      row.points.push([lat, lng]);
      row.pathCleared = false;
      if (pendingNew) renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
      updateTenantRoadControls();
    }

    // Empties the selected road's path so it can be redrawn from scratch. The
    // flag rides on the stored row (path_cleared) so اعتماد, a later save and a
    // full regeneration all keep the path deleted until it is restored.
    function clearAccessRoadPath() {
      if (!tenantRoadEditMode || !tenantRoadEditDraft || tenantRoadEditSelectedIndex < 0) return;
      const row = tenantRoadEditDraft.rows[tenantRoadEditSelectedIndex];
      if (!row || ((Array.isArray(row.points) && row.points.length) || row.pathCleared)) return;
      if (!row.has_stored_path && !accessRoadGeometry().some(road => accessRoadNameKey(road.name) === accessRoadNameKey(row.name))) return;
      pushRoadEditHistory();
      row.points = [];
      row.pathCleared = true;
      row.has_stored_path = false;
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
      updateTenantRoadControls();
    }

    // The cleared geometry stays in storage, so restoring needs no provider
    // call — the overlay and the next recompose draw it again.
    function restoreAccessRoadPath() {
      if (!tenantRoadEditMode || !tenantRoadEditDraft || tenantRoadEditSelectedIndex < 0) return;
      const row = tenantRoadEditDraft.rows[tenantRoadEditSelectedIndex];
      if (!row?.pathCleared) return;
      pushRoadEditHistory();
      row.pathCleared = false;
      row.has_stored_path = accessRoadGeometry().some(
        road => accessRoadNameKey(road.name) === accessRoadNameKey(row.name));
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
      updateTenantRoadControls();
    }

    function accessRoadPathWidthSliderHtml() {
      const row = tenantRoadEditDraft?.rows?.[tenantRoadEditSelectedIndex];
      const current = Math.max(0.3, Math.min(1.5, Number(row?.path_width_scale) || 0.55));
      return '<label class="map-control-field">سمك المسار' +
        '<span class="road-width-control">' +
        '<input type="range" min="0.3" max="1.5" step="0.1" value="' + current.toFixed(1) + '" data-section-lock-ignore="1" oninput="setAccessRoadPathWidth(this.value)" onchange="closeAccessRoadPathWidthGesture()">' +
        '<span class="road-width-value" id="accessRoadPathWidthValue">' + current.toFixed(1) + '</span>' +
        '</span></label>';
    }

    function setAccessRoadPathWidth(value) {
      if (!tenantRoadEditMode || !tenantRoadEditDraft) return;
      const row = tenantRoadEditDraft.rows[tenantRoadEditSelectedIndex];
      if (!row) return;
      // One undo step per drag gesture: the history entry is pushed on the
      // first tick and the gesture closes on change (release).
      if (!tenantRoadEditDraft._widthGestureOpen) {
        pushRoadEditHistory();
        tenantRoadEditDraft._widthGestureOpen = true;
      }
      row.path_width_scale = Math.max(0.3, Math.min(1.5, Math.round(Number(value || 0.55) * 10) / 10));
      const readout = document.getElementById('accessRoadPathWidthValue');
      if (readout) readout.textContent = row.path_width_scale.toFixed(1);
      renderTenantMapPolygonOverlay();
      updateTenantRoadControls();
    }

    function closeAccessRoadPathWidthGesture() {
      if (tenantRoadEditDraft) tenantRoadEditDraft._widthGestureOpen = false;
    }

    // The slider lives in the toolbar, which is only rebuilt by
    // renderLocationWorkflowState — switching roads re-renders the overlay
    // but not the toolbar, so the thumb would keep showing the previous
    // road's width while editing the newly selected one.
    function syncAccessRoadPathWidthSlider() {
      const row = tenantRoadEditDraft?.rows?.[tenantRoadEditSelectedIndex];
      const current = Math.max(0.3, Math.min(1.5, Number(row?.path_width_scale) || 0.55)).toFixed(1);
      const slider = document.querySelector('.road-width-control input[type="range"]');
      if (slider) slider.value = current;
      const readout = document.getElementById('accessRoadPathWidthValue');
      if (readout) readout.textContent = current;
    }

    function adjustAccessRoadPathWidth(delta) {
      if (!tenantRoadEditMode || !tenantRoadEditDraft) return;
      const row = tenantRoadEditDraft.rows[tenantRoadEditSelectedIndex];
      if (!row) return;
      tenantRoadEditDraft._widthGestureOpen = false;
      setAccessRoadPathWidth((Number(row.path_width_scale || 0.55) + Number(delta || 0)).toFixed(1));
      closeAccessRoadPathWidthGesture();
      renderLocationWorkflowState();
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
      syncAccessRoadPathWidthSlider();
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

    // The drawn or discovered path is a starting point, not a fixed answer:
    // dragging one of its vertices edits that point, and اعتماد stores the
    // result as the road's manual path.
    function startAccessRoadVertexDrag(event, index) {
      if (!tenantRoadEditMode || !tenantRoadEditDraft || tenantRoadEditSelectedIndex < 0) return;
      const row = tenantRoadEditDraft.rows[tenantRoadEditSelectedIndex];
      if (!row) return;
      const source = Array.isArray(row.points) && row.points.length >= 2
        ? row.points
        : (accessRoadGeometry().find(road => accessRoadNameKey(road.name) === accessRoadNameKey(row.name))?.points || []);
      if (!source[index]) return;
      pushRoadEditHistory();
      row.points = source.map(point => [Number(point[0]), Number(point[1])]);
      row.pathCleared = false;
      row.has_stored_path = true;
      const image = document.querySelector('#mapPreviewImage img');
      const move = moveEvent => {
        const coordinates = tenantMapCoordinatesFromClient(moveEvent.clientX, moveEvent.clientY, image);
        if (!coordinates) return;
        row.points[index] = coordinates;
        renderTenantMapPolygonOverlay();
      };
      const stop = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', stop);
        window.removeEventListener('pointercancel', stop);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', stop);
      window.addEventListener('pointercancel', stop);
      updateTenantRoadControls();
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
      closeAccessRoadPathWidthGesture();
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
      const widthByKey = new Map(rows.map(row => [accessRoadNameKey(row.name), row.path_width_scale || 0.55]));
      const renameGeometry = road => {
        const next = { ...road, name: renamed.get(accessRoadNameKey(road?.name)) || road?.name };
        // A thickness change with no redraw still commits: the stored geometry
        // carries the row's width so the overlay and the next save keep it.
        const kept = widthByKey.get(accessRoadNameKey(next?.name));
        if (kept !== undefined) next.path_width_scale = kept;
        return next;
      };
      const allowedRoadKeys = new Set(rows.map(row => accessRoadNameKey(row.name)));
      // A cleared path keeps its stored geometry: the server skips it because
      // the row says path_cleared, so استعادة المسار can draw it again without
      // another provider call.
      tenantProjectData.access_roads_data = (Array.isArray(tenantProjectData.access_roads_data) ? tenantProjectData.access_roads_data : [])
        .map(renameGeometry).filter(road => allowedRoadKeys.has(accessRoadNameKey(road?.name)));
      tenantCreativeImages.map_access_roads = tenantProjectData.access_roads_data;
      tenantProjectData.manual_road_paths = (Array.isArray(tenantProjectData.manual_road_paths) ? tenantProjectData.manual_road_paths : [])
        .map(renameGeometry).filter(road => allowedRoadKeys.has(accessRoadNameKey(road?.name)));
      // Paths sketched during the session commit here: a drawn path replaces
      // the stored manual one for its road. Sketches shorter than two points
      // are ignored so a stray map click can never erase a stored path.
      rows.forEach(row => {
        const drawn = Array.isArray(row.points) && row.points.length >= 2 ? row.points : null;
        if (!drawn) return;
        row.pathCleared = false;
        const key = accessRoadNameKey(row.name);
        tenantProjectData.manual_road_paths = tenantProjectData.manual_road_paths
          .filter(road => accessRoadNameKey(road?.name) !== key);
        tenantProjectData.manual_road_paths.push({
          name: row.name, points: drawn, path_width_scale: row.path_width_scale || 0.55
        });
      });
      tenantProjectData.access_road_label_positions = Object.fromEntries(rows.map(row => {
        const point = tenantRoadEditDraft.labelPositions[row.name] || tenantRoadEditDraft.labelPositions[row.original_name];
        return point ? [row.name, point] : null;
      }).filter(Boolean));
      tenantProjectData.access_road_label_sizes = Object.fromEntries(rows.map(row => {
        const size = tenantRoadEditDraft.labelSizes[row.name] || tenantRoadEditDraft.labelSizes[row.original_name];
        return size ? [row.name, size] : null;
      }).filter(Boolean));
      tenantProjectData.main_roads = rows.map(row => row.name).join('\n');
      tenantProjectData.main_roads_data = rows.map(({ original_name, points, pathCleared, has_stored_path, path_cleared, ...row }) => (
        pathCleared ? { ...row, path_cleared: true } : row
      ));
      setLocationTableValue('main_roads', tenantProjectData.main_roads_data);
      tenantRoadEditMode = false;
      tenantRoadEditDraft = null;
      tenantRoadEditHistory = [];
      tenantRoadEditSelectedIndex = -1;
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

    // Path drawing lives inside the unified road-edit mode: this entry opens
    // it with the asked-for road already selected in the dropdown.
    async function startManualRoadDrawing(name) {
      await startAccessRoadEditMode();
      if (!tenantRoadEditMode || !tenantRoadEditDraft) return;
      const roadName = String(name || '').trim();
      if (!roadName) return;
      const index = tenantRoadEditDraft.rows.findIndex(row => accessRoadNameKey(row.name) === accessRoadNameKey(roadName));
      if (index < 0) { toast('اسم الطريق غير موجود في الجدول'); return; }
      tenantRoadEditSelectedIndex = index;
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
