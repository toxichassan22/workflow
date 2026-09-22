    function tenantMapCoordinatesFromClient(clientX, clientY, img) {
      if (!tenantMapPreviewState || !img) return null;
      const rect = img.getBoundingClientRect();
      if (!rect.width || !rect.height) return null;
      const x = (clientX - rect.left) / rect.width - 0.5;
      const y = (clientY - rect.top) / rect.height - 0.5;
      const world = 256 * Math.pow(2, tenantMapPreviewState.zoom) * 2;
      const centerLatRad = tenantMapPreviewState.lat * Math.PI / 180;
      const centerY = (1 - Math.log(Math.tan(centerLatRad) + 1 / Math.cos(centerLatRad)) / Math.PI) / 2;
      const nextY = centerY + (y * img.naturalHeight) / world;
      const nextLng = tenantMapPreviewState.lng + (x * img.naturalWidth) * 360 / world;
      const nextLat = Math.atan(Math.sinh(Math.PI * (1 - 2 * nextY))) * 180 / Math.PI;
      return [nextLat, nextLng];
    }

    function setTenantMapPointFromClick(event) {
      const img = event.currentTarget;
      const coordinates = tenantMapCoordinatesFromClient(event.clientX, event.clientY, img);
      if (!coordinates) return;
      const [nextLat, nextLng] = coordinates;
      if (tenantMapPolygonMode && tenantSelectedMapType === 'overview') {
        tenantMapDraftPolygonPoints.push([nextLat, nextLng]);
        renderTenantMapPolygonOverlay();
        updateTenantPolygonControls();
        return;
      }
      if (tenantSelectedMapType === 'overview' && tenantMapPinMode) {
        tenantMapDraftPinHistory.push([nextLat, nextLng]);
        renderTenantMapPolygonOverlay();
        updateTenantPolygonControls();
        return;
      }
      if (tenantRoadEditMode && tenantSelectedMapType === 'access') {
        setAccessRoadLabelFromMap(nextLat, nextLng);
        return;
      }
      if (tenantRoadDrawingTarget && tenantSelectedMapType === 'access') {
        tenantRoadDrawingTarget.points.push([nextLat, nextLng]);
        renderTenantMapPolygonOverlay();
        updateTenantRoadControls();
        const status = document.getElementById('manualRoadDrawingStatus');
        if (status) status.innerHTML = '<span>رسم مسار:</span> ' + escapeHtml(tenantRoadDrawingTarget.name) + ' — <span>' + tenantRoadDrawingTarget.points.length + '</span> <span>نقاط</span>';
        return;
      }
      const landmarkMapType = LOCATION_TABLE_FIELDS[tenantLandmarkPlacementTarget?.key]?.mapType;
      if (tenantLandmarkPlacementTarget && tenantSelectedMapType === landmarkMapType) {
        tenantLandmarkPlacementTarget.tr.dataset.lat = nextLat.toFixed(6);
        tenantLandmarkPlacementTarget.tr.dataset.lng = nextLng.toFixed(6);
        serializeLocationTable(tenantLandmarkPlacementTarget.key);
        tenantLandmarkPlacementTarget = null;
        invalidateLocationAnalysisApproval();
        triggerAutoSaveDraft();
        toast('تم حفظ موقع المعلم');
      }
    }

    function updateTenantPolygonControls() {
      const undoButton = document.getElementById('removeLastTenantPolygonPointButton');
      const confirmButton = document.getElementById('confirmTenantPolygonButton');
      const clearButton = document.getElementById('clearTenantPolygonSelectionButton');
      const pinUndoButton = document.getElementById('undoTenantMapPinButton');
      const pinConfirmButton = document.getElementById('confirmTenantMapPinButton');
      const overview = MAP_PREVIEW_VIEW_DEFS.find(view => view.mapType === 'overview');
      const overviewGenerated = mapPreviewIsGenerated(overview);
      const locked = !overviewGenerated || !!tenantCreativeImages.map_approvals?.overview;
      if (undoButton) undoButton.disabled = locked || !tenantMapDraftPolygonPoints.length;
      if (confirmButton) confirmButton.disabled = locked || tenantMapDraftPolygonPoints.length < 3;
      if (clearButton) clearButton.disabled = locked || !tenantMapDraftPolygonPoints.length;
      if (pinUndoButton) pinUndoButton.disabled = locked || tenantMapDraftPinHistory.length <= 1;
      if (pinConfirmButton) pinConfirmButton.disabled = locked || tenantMapDraftPinHistory.length <= 1;
    }

    function updateTenantRoadControls() {
      const editUndo = document.getElementById('undoAccessRoadEditsButton');
      const pathUndo = document.getElementById('undoManualRoadDrawingButton');
      const pathConfirm = document.getElementById('confirmManualRoadDrawingButton');
      if (editUndo) editUndo.disabled = !tenantRoadEditHistory.length;
      if (pathUndo) pathUndo.disabled = !tenantRoadDrawingTarget?.points?.length;
      if (pathConfirm) pathConfirm.disabled = (tenantRoadDrawingTarget?.points?.length || 0) < 2;
    }

    function updateTenantCatchmentControls() {
      const undoButton = document.getElementById('undoCatchmentEditsButton');
      if (undoButton) undoButton.disabled = !tenantCatchmentEditHistory.length;
    }

    function updateTenantLandmarksControls() {
      const undoButton = document.getElementById('undoLandmarksEditsButton');
      if (undoButton) undoButton.disabled = !tenantLandmarksEditHistory.length;
    }

    function updateTenantMapInteractionState() {
      const image = document.querySelector('#mapPreviewImage img');
      if (image) image.style.cursor = tenantMapPolygonMode || tenantMapPinMode || tenantRoadEditMode || tenantRoadDrawingTarget || tenantCatchmentEditMode || tenantLandmarksEditMode || tenantLandmarkPlacementTarget ? 'crosshair' : 'default';
    }

    async function applyOverviewMapEdits() {
      try {
        const payload = slimMapProjectData(tenantProjectData);
        payload.location_analysis_approved = tenantProjectData.location_analysis_approved === true || tenantProjectData.location_analysis_approved === 'true';
        payload.draftId = tenantProjectData.draftId;
        const data = await api('POST', '/api/generate-map-image', {
          projectData: payload,
          mapType: 'overview',
          presentationId: tenantPresentationId,
          highlightSite: shouldHighlightTenantSite(),
          mapApproved: false,
          overlayOnly: true
        });
        if (!data.success) return false;
        if (data.revision) tenantPresentationRevision = Number(data.revision) || tenantPresentationRevision;
        tenantCreativeImages.map_placeholders = { ...(tenantCreativeImages.map_placeholders || {}), ...(data.placeholders || {}) };
        tenantCreativeImages.map_zooms = { ...(tenantCreativeImages.map_zooms || {}), ...(data.zooms || {}) };
        tenantCreativeImages.map_centers = { ...(tenantCreativeImages.map_centers || {}), ...(data.centers || {}) };
        tenantCreativeImages.map_highlight_site = shouldHighlightTenantSite();
        tenantCreativeImages.maps_signature = mapsSignature(tenantProjectData);
        await saveMapPreviewState();
        renderMapPreviewGallery(true);
        return true;
      } catch (error) {
        console.warn('[OVERVIEW MAP OVERLAY]', error);
        triggerAutoSaveDraft();
        return false;
      }
    }

    async function applyAccessMapEdits() {
      try {
          const payload = slimMapProjectData(tenantProjectData);
          payload.location_analysis_approved = tenantProjectData.location_analysis_approved === true || tenantProjectData.location_analysis_approved === 'true';
          payload.draftId = tenantProjectData.draftId;
          const data = await api('POST', '/api/generate-map-image', {
            projectData: payload,
            mapType: 'access',
            presentationId: tenantPresentationId,
            overviewApproved: true,
            mapApproved: false,
            overlayOnly: true
          });
          if (!data.success) return false;
          if (data.revision) tenantPresentationRevision = Number(data.revision) || tenantPresentationRevision;
          tenantCreativeImages.map_placeholders = { ...(tenantCreativeImages.map_placeholders || {}), ...(data.placeholders || {}) };
          tenantCreativeImages.map_zooms = { ...(tenantCreativeImages.map_zooms || {}), ...(data.zooms || {}) };
          tenantCreativeImages.map_centers = { ...(tenantCreativeImages.map_centers || {}), ...(data.centers || {}) };
          tenantProjectData.access_roads_data = Array.isArray(data.accessRoads) ? data.accessRoads : tenantProjectData.access_roads_data || [];
          tenantCreativeImages.map_access_roads = tenantProjectData.access_roads_data;
          const positions = { ...(tenantProjectData.access_road_label_positions || {}) };
          const sizes = { ...(tenantProjectData.access_road_label_sizes || {}) };
          tenantProjectData.access_roads_data.forEach(road => {
            if (road?.name && Array.isArray(road.label_point)) positions[road.name] = road.label_point;
            if (road?.name && Number.isFinite(Number(road.label_scale))) sizes[road.name] = Number(road.label_scale);
          });
          tenantProjectData.access_road_label_positions = positions;
          tenantProjectData.access_road_label_sizes = sizes;
          tenantCreativeImages.maps_signature = mapsSignature(tenantProjectData);
          await saveMapPreviewState();
          renderMapPreviewGallery(true);
          return true;
        } catch (error) {
          console.warn('[ACCESS MAP OVERLAY]', error);
          triggerAutoSaveDraft();
          return false;
      }
    }

    async function ensureAccessEditablePreview() {
      if (tenantMapPreviewState?.usesEditableBase) return true;
      if (!(await applyAccessMapEdits())) return false;
      return selectMapPreviewView('access');
    }

    function applyCatchmentMapEdits() {
      return (async () => {
        try {
          const payload = slimMapProjectData(tenantProjectData);
          payload.draftId = tenantProjectData.draftId;
          const data = await api('POST', '/api/generate-map-image', {
            projectData: payload,
            mapType: 'catchment',
            presentationId: tenantPresentationId,
            mapApproved: false,
            overlayOnly: true
          });
          if (!data.success) return false;
          if (data.revision) tenantPresentationRevision = Number(data.revision) || tenantPresentationRevision;
          tenantCreativeImages.map_placeholders = { ...(tenantCreativeImages.map_placeholders || {}), ...(data.placeholders || {}) };
          tenantCreativeImages.map_zooms = { ...(tenantCreativeImages.map_zooms || {}), ...(data.zooms || {}) };
          tenantCreativeImages.map_centers = { ...(tenantCreativeImages.map_centers || {}), ...(data.centers || {}) };
          tenantProjectData.catchment_map_landmarks = Array.isArray(data.catchmentLandmarks) ? data.catchmentLandmarks : tenantProjectData.catchment_map_landmarks || [];
          tenantCreativeImages.map_catchment_landmarks = tenantProjectData.catchment_map_landmarks;
          const positions = { ...(tenantProjectData.catchment_label_positions || {}) };
          tenantProjectData.catchment_map_landmarks.forEach(item => {
            if (item?.name && Array.isArray(item.label_point)) positions[item.name] = item.label_point;
          });
          tenantProjectData.catchment_label_positions = positions;
          tenantCreativeImages.maps_signature = mapsSignature(tenantProjectData);
          await saveMapPreviewState();
          renderMapPreviewGallery(true);
          return true;
        } catch (error) {
          console.warn('[CATCHMENT MAP OVERLAY]', error);
          triggerAutoSaveDraft();
          return false;
        }
      })();
    }

    async function ensureCatchmentEditablePreview() {
      if (tenantMapPreviewState?.usesEditableBase) return true;
      if (!(await applyCatchmentMapEdits())) return false;
      return selectMapPreviewView('catchment');
    }

    function applyLandmarksMapEdits() {
      return (async () => {
        try {
          const payload = slimMapProjectData(tenantProjectData);
          payload.draftId = tenantProjectData.draftId;
          const data = await api('POST', '/api/generate-map-image', {
            projectData: payload,
            mapType: 'landmarks',
            presentationId: tenantPresentationId,
            mapApproved: false,
            overlayOnly: true
          });
          if (!data.success) return false;
          if (data.revision) tenantPresentationRevision = Number(data.revision) || tenantPresentationRevision;
          tenantCreativeImages.map_placeholders = { ...(tenantCreativeImages.map_placeholders || {}), ...(data.placeholders || {}) };
          tenantCreativeImages.map_zooms = { ...(tenantCreativeImages.map_zooms || {}), ...(data.zooms || {}) };
          tenantCreativeImages.map_centers = { ...(tenantCreativeImages.map_centers || {}), ...(data.centers || {}) };
          tenantProjectData.landmark_map_items = Array.isArray(data.landmarkMapItems) ? data.landmarkMapItems : tenantProjectData.landmark_map_items || [];
          tenantCreativeImages.map_landmark_items = tenantProjectData.landmark_map_items;
          const positions = { ...(tenantProjectData.landmark_label_positions || {}) };
          tenantProjectData.landmark_map_items.forEach(item => {
            if (item?.name && Array.isArray(item.label_point)) positions[item.name] = item.label_point;
          });
          tenantProjectData.landmark_label_positions = positions;
          tenantCreativeImages.maps_signature = mapsSignature(tenantProjectData);
          await saveMapPreviewState();
          renderMapPreviewGallery(true);
          return true;
        } catch (error) {
          console.warn('[LANDMARKS MAP OVERLAY]', error);
          triggerAutoSaveDraft();
          return false;
        }
      })();
    }

    async function ensureLandmarksEditablePreview() {
      if (tenantMapPreviewState?.usesEditableBase) return true;
      if (!(await applyLandmarksMapEdits())) return false;
      return selectMapPreviewView('landmarks');
    }

    async function toggleTenantPolygonMode() {
      if (tenantCreativeImages.map_approvals?.overview) { toast('خريطة الأرض معتمدة'); return; }
      if (tenantSelectedMapType !== 'overview') selectMapPreviewView('overview');
      if (!tenantMapPreviewState) { toast('خريطة الأرض غير مولدة'); return; }
      tenantMapPinMode = false;
      tenantMapDraftPinHistory = [];
      tenantMapDraftPolygonPoints = [];
      tenantMapPolygonMode = true;
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
    }

    function cancelTenantPolygonMode() {
      tenantMapDraftPolygonPoints = [];
      tenantMapPolygonMode = false;
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
    }

    function clearTenantPolygonSelection() {
      tenantMapDraftPolygonPoints = [];
      renderTenantMapPolygonOverlay();
      updateTenantPolygonControls();
    }

    async function confirmTenantPolygon() {
      if (!tenantMapPolygonMode || tenantMapDraftPolygonPoints.length < 3) return;
      tenantMapPolygonPoints = tenantMapDraftPolygonPoints.map(point => [point[0], point[1]]);
      tenantMapDraftPolygonPoints = [];
      tenantMapPolygonMode = false;
      tenantProjectData.location_polygon_source = 'manual';
      tenantCreativeImages.map_highlight_site = null;
      syncTenantLocationPolygon();
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
      triggerAutoSaveDraft();
      await applyOverviewMapEdits();
      toast('تم اعتماد حدود الموقع');
    }

    async function startTenantMapPinMode() {
      if (tenantCreativeImages.map_approvals?.overview) { toast('خريطة الأرض معتمدة'); return; }
      if (tenantSelectedMapType !== 'overview') selectMapPreviewView('overview');
      if (!tenantMapPreviewState) { toast('خريطة الأرض غير مولدة'); return; }
      const lat = Number(tenantProjectData.location_lat);
      const lng = Number(tenantProjectData.location_lng);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) { toast('موقع المبنى غير محدد'); return; }
      tenantMapPolygonMode = false;
      tenantMapDraftPolygonPoints = [];
      tenantMapPinMode = true;
      tenantMapDraftPinHistory = [[lat, lng]];
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
    }

    function undoTenantMapPin() {
      if (!tenantMapPinMode || tenantMapDraftPinHistory.length <= 1) return;
      tenantMapDraftPinHistory.pop();
      renderTenantMapPolygonOverlay();
      updateTenantPolygonControls();
    }

    function cancelTenantMapPin() {
      tenantMapPinMode = false;
      tenantMapDraftPinHistory = [];
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
    }

    async function confirmTenantMapPin() {
      if (!tenantMapPinMode || tenantMapDraftPinHistory.length <= 1) return;
      const [lat, lng] = tenantMapDraftPinHistory[tenantMapDraftPinHistory.length - 1];
      const latValue = lat.toFixed(6);
      const lngValue = lng.toFixed(6);
      const latInput = document.querySelector('#tenantProjectForm [data-key="location_lat"]');
      const lngInput = document.querySelector('#tenantProjectForm [data-key="location_lng"]');
      if (latInput) latInput.value = latValue;
      if (lngInput) lngInput.value = lngValue;
      const confirmedInput = document.getElementById('tenantCoordinatesConfirmed');
      if (confirmedInput) confirmedInput.value = 'true';
      tenantProjectData.location_lat = latValue;
      tenantProjectData.location_lng = lngValue;
      tenantProjectData.location_coordinates_confirmed = true;
      tenantProjectData.location_coordinates_source = 'manual_map';
      tenantCreativeImages.map_lat = lat;
      tenantCreativeImages.map_lng = lng;
      tenantCreativeImages.map_approvals = { ...(tenantCreativeImages.map_approvals || {}), overview: false };
      tenantMapPinMode = false;
      tenantMapDraftPinHistory = [];
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
      triggerAutoSaveDraft();
      await applyOverviewMapEdits();
      toast('تم اعتماد موقع المبنى');
    }

    function syncTenantLocationPolygon() {
      const input = document.getElementById('tenantLocationPolygon');
      const value = tenantMapPolygonPoints.map(point => point[0].toFixed(6) + ',' + point[1].toFixed(6)).join(';');
      tenantProjectData.location_polygon = value;
      if (input) input.value = value;
    }

    function mapPlaceLinkClass(prefix, name) {
      return mapPlaceLinked && mapPlaceLinked.prefix === prefix && mapPlaceLinked.name === name ? ' map-place-linked' : '';
    }

    function highlightMapPlacePair(prefix, name, on, pinned = false) {
      if (on) {
        if (mapPlaceLinked && mapPlaceLinked.pinned && !pinned) return;
        mapPlaceLinked = { prefix: prefix, name: name, pinned: !!pinned };
      } else if (pinned || (mapPlaceLinked && !mapPlaceLinked.pinned)) {
        mapPlaceLinked = null;
      }
      const roots = [document.getElementById('mapLabelOverlay'), document.getElementById('mapPolygonOverlay')];
      roots.forEach(root => {
        if (!root) return;
        root.querySelectorAll('.map-place-linked').forEach(el => el.classList.remove('map-place-linked'));
        if (!mapPlaceLinked) return;
        const esc = (window.CSS && CSS.escape) ? CSS.escape(mapPlaceLinked.name) : String(mapPlaceLinked.name).replace(/["\\]/g, '\\$&');
        ['label', 'marker', 'link', 'path'].forEach(kind => {
          root.querySelectorAll('[data-' + mapPlaceLinked.prefix + '-' + kind + '="' + esc + '"]')
            .forEach(el => el.classList.add('map-place-linked'));
        });
      });
    }

    function renderAccessRoadLabels(roadPaths, toPoint, visible) {
      const layer = document.getElementById('mapLabelOverlay');
      if (!layer) return;
      layer.style.pointerEvents = 'none';
      if (!visible) {
        layer.innerHTML = '';
        return;
      }
      layer.innerHTML = roadPaths.map(path => {
        const points = Array.isArray(path.points) ? path.points : [];
        if (points.length < 2 || !path.name) return '';
        const labelPoint = Array.isArray(path.label_point) ? path.label_point : points[Math.floor(points.length / 2)];
        const [x, y] = toPoint(labelPoint).split(',').map(Number);
        if (!Number.isFinite(x) || !Number.isFinite(y)) return '';
        const scale = Math.max(0.6, Math.min(1.8, Number(path.label_scale) || 1));
        const encodedName = encodeURIComponent(String(path.name)).replace(/'/g, '%27');
        const deleteAction = tenantRoadEditMode
          ? '<button type="button" class="map-road-label-delete" onpointerdown="event.stopPropagation()" onclick="deleteAccessRoadFromDraft(event,decodeURIComponent(\'' + encodedName + '\'))">حذف</button>'
          : '';
        const hoverAttrs = tenantRoadEditMode
          ? ' onmouseenter="highlightMapPlacePair(\'road\',decodeURIComponent(\'' + encodedName + '\'),true)" onmouseleave="highlightMapPlacePair(\'road\',decodeURIComponent(\'' + encodedName + '\'),false)"'
          : '';
        return '<div class="map-road-label' + mapPlaceLinkClass('road', path.name) + (tenantRoadEditMode ? ' editable' : '') + '" data-road-label="' + escapeHtml(path.name) + '" style="left:' + x.toFixed(3) + '%;top:' + y.toFixed(3) + '%;font-size:' + (13 * scale).toFixed(1) + 'px;padding:' + (4 * scale).toFixed(1) + 'px ' + (8 * scale).toFixed(1) + 'px"' +
          (tenantRoadEditMode ? ' onpointerdown="startAccessRoadLabelDrag(event,decodeURIComponent(\'' + encodedName + '\'))"' + hoverAttrs : '') + '>' + escapeHtml(path.name) + deleteAction + '</div>';
      }).join('');
    }

    function renderCatchmentLabels(items, toPoint) {
      const layer = document.getElementById('mapLabelOverlay');
      if (!layer) return;
      layer.style.pointerEvents = tenantCatchmentEditMode ? 'auto' : 'none';
      layer.innerHTML = items.map(item => {
        if (!item?.name) return '';
        const markerPoint = toPoint([item.lat, item.lng]).split(',').map(Number);
        const customPoint = Array.isArray(item.label_point) ? toPoint(item.label_point).split(',').map(Number) : null;
        const x = customPoint?.[0] ?? markerPoint[0];
        const y = customPoint?.[1] ?? markerPoint[1] + 5;
        if (!Number.isFinite(x) || !Number.isFinite(y)) return '';
        const encodedName = encodeURIComponent(String(item.name)).replace(/'/g, '%27');
        const index = items.indexOf(item) + 1;
        const linked = mapPlaceLinkClass('catchment', item.name);
        const hoverAttrs = tenantCatchmentEditMode
          ? ' onmouseenter="highlightMapPlacePair(\'catchment\',decodeURIComponent(\'' + encodedName + '\'),true)" onmouseleave="highlightMapPlacePair(\'catchment\',decodeURIComponent(\'' + encodedName + '\'),false)"'
          : '';
        const numChip = tenantCatchmentEditMode ? '<span class="map-place-label-num">' + index + '</span>' : '';
        const marker = '<div class="map-place-marker' + linked + (tenantCatchmentEditMode ? ' editable' : '') + '" data-catchment-marker="' + escapeHtml(item.name) + '" style="left:' + markerPoint[0].toFixed(3) + '%;top:' + markerPoint[1].toFixed(3) + '%"' +
          (tenantCatchmentEditMode ? ' onpointerdown="startCatchmentMarkerDrag(event,decodeURIComponent(\'' + encodedName + '\'))"' + hoverAttrs : '') + '>' + index + '</div>';
        const label = '<div class="map-place-label' + linked + (tenantCatchmentEditMode ? ' editable' : '') + '" data-catchment-label="' + escapeHtml(item.name) + '" style="left:' + x.toFixed(3) + '%;top:' + y.toFixed(3) + '%;font-size:12px;padding:3px 7px"' +
          (tenantCatchmentEditMode ? ' onpointerdown="startCatchmentLabelDrag(event,decodeURIComponent(\'' + encodedName + '\'))"' + hoverAttrs : '') + '>' + numChip + escapeHtml(item.name) + '</div>';
        return marker + label;
      }).join('');
    }

    function renderLandmarksLabels(items, toPoint) {
      const layer = document.getElementById('mapLabelOverlay');
      if (!layer) return;
      layer.style.pointerEvents = tenantLandmarksEditMode ? 'auto' : 'none';
      layer.innerHTML = items.map((item, index) => {
        if (!item?.name) return '';
        const markerPoint = toPoint([item.lat, item.lng]).split(',').map(Number);
        const customPoint = Array.isArray(item.label_point) ? toPoint(item.label_point).split(',').map(Number) : null;
        const x = customPoint?.[0] ?? markerPoint[0];
        const y = customPoint?.[1] ?? markerPoint[1] + 5;
        if (!Number.isFinite(x) || !Number.isFinite(y)) return '';
        const encodedName = encodeURIComponent(String(item.name)).replace(/'/g, '%27');
        const linked = mapPlaceLinkClass('landmark', item.name);
        const hoverAttrs = tenantLandmarksEditMode
          ? ' onmouseenter="highlightMapPlacePair(\'landmark\',decodeURIComponent(\'' + encodedName + '\'),true)" onmouseleave="highlightMapPlacePair(\'landmark\',decodeURIComponent(\'' + encodedName + '\'),false)"'
          : '';
        const numChip = tenantLandmarksEditMode ? '<span class="map-place-label-num">' + (index + 1) + '</span>' : '';
        const marker = '<div class="map-place-marker' + linked + (tenantLandmarksEditMode ? ' editable' : '') + '" data-landmark-marker="' + escapeHtml(item.name) + '" style="left:' + markerPoint[0].toFixed(3) + '%;top:' + markerPoint[1].toFixed(3) + '%"' +
          (tenantLandmarksEditMode ? ' onpointerdown="startLandmarksMarkerDrag(event,decodeURIComponent(\'' + encodedName + '\'))"' + hoverAttrs : '') + '>' + (index + 1) + '</div>';
        const label = '<div class="map-place-label' + linked + (tenantLandmarksEditMode ? ' editable' : '') + '" data-landmark-label="' + escapeHtml(item.name) + '" style="left:' + x.toFixed(3) + '%;top:' + y.toFixed(3) + '%;font-size:12px;padding:3px 7px"' +
          (tenantLandmarksEditMode ? ' onpointerdown="startLandmarksLabelDrag(event,decodeURIComponent(\'' + encodedName + '\'))"' + hoverAttrs : '') + '>' + numChip + escapeHtml(item.name) + '</div>';
        return marker + label;
      }).join('');
    }

    function renderTenantMapPolygonOverlay() {
      const overlay = document.getElementById('mapPolygonOverlay');
      const labelLayer = document.getElementById('mapLabelOverlay');
      const img = document.querySelector('#mapPreviewImage img');
      const state = tenantMapPreviewState;
      const polygonPoints = tenantMapPolygonMode ? tenantMapDraftPolygonPoints : tenantMapPolygonPoints;
      const roadPaths = tenantSelectedMapType === 'access' ? accessRoadGeometry() : [];
      const catchmentItems = tenantSelectedMapType === 'catchment' ? catchmentMapLandmarks() : [];
      const landmarkItems = tenantSelectedMapType === 'landmarks' ? nearbyMapLandmarks() : [];
      const showBoundary = tenantSelectedMapType === 'overview' && (!!state?.usesEditableBase || tenantMapPolygonMode) && polygonPoints.length > 0;
      const showPin = tenantSelectedMapType === 'overview' && (!!state?.usesEditableBase || tenantMapPinMode);
      const showRoads = tenantSelectedMapType === 'access' && !!state?.usesEditableBase;
      const showAccessPin = tenantSelectedMapType === 'access' && !!state?.usesEditableBase;
      const showCatchment = tenantSelectedMapType === 'catchment' && !!state?.usesEditableBase;
      const showLandmarks = tenantSelectedMapType === 'landmarks' && !!state?.usesEditableBase;
      if (!overlay || !img || !state || !img.naturalWidth || !img.naturalHeight || (!showBoundary && !showPin && !showAccessPin && !showCatchment && !showLandmarks && (!showRoads || !roadPaths.length))) {
        if (overlay) overlay.innerHTML = '';
        if (labelLayer) {
          labelLayer.innerHTML = '';
          labelLayer.style.pointerEvents = 'none';
        }
        return;
      }
      const world = 256 * Math.pow(2, state.zoom) * 2;
      const centerLatRad = state.lat * Math.PI / 180;
      const centerY = (1 - Math.log(Math.tan(centerLatRad) + 1 / Math.cos(centerLatRad)) / Math.PI) / 2;
      const toPoint = point => {
        const lngOffset = (point[1] - state.lng) * world / 360;
        const pointLatRad = point[0] * Math.PI / 180;
        const pointY = (1 - Math.log(Math.tan(pointLatRad) + 1 / Math.cos(pointLatRad)) / Math.PI) / 2;
        const yOffset = (pointY - centerY) * world;
        return ((0.5 + lngOffset / img.naturalWidth) * 100).toFixed(3) + ',' + ((0.5 + yOffset / img.naturalHeight) * 100).toFixed(3);
      };
      const points = showBoundary ? polygonPoints.map(toPoint) : [];
      const line = points.length > 2 ? points.concat(points[0]).join(' ') : points.join(' ');
      const pointMarkup = tenantMapPolygonMode ? points.map((point, index) => {
        const [x, y] = point.split(',');
        return '<circle cx="' + x + '%" cy="' + y + '%" r="1.5" fill="#fff" stroke="#6B1C23" stroke-width="0.45"><title>النقطة ' + (index + 1) + '</title></circle>' +
          '<text x="' + x + '%" y="' + y + '%" dy="-2.2" text-anchor="middle" font-size="3" font-weight="700" fill="#6B1C23">' + (index + 1) + '</text>';
      }).join('') : '';
      const boundaryMarkup = points.length
        ? '<polyline points="' + line + '" fill="' + (points.length > 2 ? 'rgba(107,28,35,.28)' : 'none') + '" stroke="#6B1C23" stroke-width="0.65"></polyline>' + pointMarkup
        : '';
      const savedPin = [Number(tenantProjectData.location_lat), Number(tenantProjectData.location_lng)];
      const draftPin = tenantMapPinMode && tenantMapDraftPinHistory.length ? tenantMapDraftPinHistory[tenantMapDraftPinHistory.length - 1] : savedPin;
      let pinMarkup = '';
      if ((showPin || showAccessPin || showCatchment || showLandmarks) && draftPin.every(Number.isFinite)) {
        const [pinX, pinY] = toPoint(draftPin).split(',');
        pinMarkup = '<circle cx="' + pinX + '%" cy="' + pinY + '%" r="2.2" fill="rgba(107,28,35,.24)" stroke="#fff" stroke-width="0.7"></circle>' +
          '<circle cx="' + pinX + '%" cy="' + pinY + '%" r="1.25" fill="#6B1C23" stroke="#6B1C23" stroke-width="0.35"><title>موقع المبنى</title></circle>';
      }
      const selectedRoadName = tenantRoadEditMode && tenantRoadEditSelectedIndex >= 0
        ? String(tenantRoadEditDraft?.rows?.[tenantRoadEditSelectedIndex]?.name || '')
        : (tenantRoadDrawingTarget ? String(tenantRoadDrawingTarget.name || '') : '');
      const roadMarkup = showRoads ? roadPaths.map(path => {
        const roadPoints = (path.points || []).map(toPoint);
        if (roadPoints.length < 2) return '';
        const label = String(path.name || '');
        const pathClass = 'map-road-path' +
          (selectedRoadName && accessRoadNameKey(label) === accessRoadNameKey(selectedRoadName) ? ' map-road-path-selected' : '') +
          mapPlaceLinkClass('road', label);
        return '<polyline points="' + roadPoints.join(' ') + '" fill="none" stroke="rgba(105,73,35,.55)" stroke-width="1.8"></polyline>' +
          '<polyline data-road-path="' + escapeHtml(label) + '" class="' + pathClass + '" points="' + roadPoints.join(' ') + '" fill="none" stroke="#d4a359" stroke-width="0.9"><title>' + escapeHtml(label) + '</title></polyline>';
      }).join('') : '';
      const linkLinePairs = (showLandmarks && tenantLandmarksEditMode)
        ? landmarkItems.map(item => ['landmark', item])
        : (showCatchment && tenantCatchmentEditMode)
          ? catchmentItems.map(item => ['catchment', item])
          : [];
      const linkLineMarkup = linkLinePairs.map(pair => {
        const item = pair[1];
        if (!item?.name || !Array.isArray(item.label_point)) return '';
        const [mx, my] = toPoint([item.lat, item.lng]).split(',').map(Number);
        const [lx, ly] = toPoint(item.label_point).split(',').map(Number);
        if (![mx, my, lx, ly].every(Number.isFinite) || Math.abs(lx - mx) + Math.abs(ly - my) < 0.4) return '';
        return '<line class="map-place-link-line' + mapPlaceLinkClass(pair[0], item.name) + '" data-' + pair[0] + '-link="' + escapeHtml(item.name) + '" x1="' + mx.toFixed(3) + '%" y1="' + my.toFixed(3) + '%" x2="' + lx.toFixed(3) + '%" y2="' + ly.toFixed(3) + '%"></line>';
      }).join('');
      const roadPointMarkup = tenantRoadDrawingTarget ? tenantRoadDrawingTarget.points.map(point => {
        const [x, y] = toPoint(point).split(',');
        return '<circle cx="' + x + '%" cy="' + y + '%" r="1.15" fill="#fff" stroke="#6B1C23" stroke-width="0.45"></circle>';
      }).join('') : '';
      overlay.innerHTML = boundaryMarkup + roadMarkup + linkLineMarkup + roadPointMarkup + pinMarkup;
      if (showRoads) renderAccessRoadLabels(roadPaths, toPoint, true);
      else if (showCatchment) renderCatchmentLabels(catchmentItems, toPoint);
      else if (showLandmarks) renderLandmarksLabels(landmarkItems, toPoint);
      else if (labelLayer) {
        labelLayer.innerHTML = '';
        labelLayer.style.pointerEvents = 'none';
      }
    }

    function removeTenantPolygonPoint(index) {
      if (!tenantMapPolygonMode || !Number.isInteger(index) || index < 0 || index >= tenantMapDraftPolygonPoints.length) return;
      tenantMapDraftPolygonPoints.splice(index, 1);
      renderTenantMapPolygonOverlay();
      updateTenantPolygonControls();
    }

    function removeLastTenantPolygonPoint() {
      if (!tenantMapDraftPolygonPoints.length) return;
      removeTenantPolygonPoint(tenantMapDraftPolygonPoints.length - 1);
    }

    async function fetchNearbyLandmarkDetails() {
      const hidden = document.querySelector('#tenantProjectForm [data-key="nearby_landmarks"].location-table-value');
      const rows = hidden ? parseLocationFieldText('nearby_landmarks', hidden.value).filter(row => row.name) : [];
      if (!rows.length) {
        toast('لا توجد معالم مختارة لجلب المعلومات');
        return;
      }
      const selectedLandmarks = rows.map(row => {
        const source = tenantNearbyLandmarks.find(item => item.name === row.name) || {};
        return {
          ...source,
          name: row.name,
          category: row.category || source.category || ''
        };
      });
      showLoader('جاري جلب معلومات المعالم', 'يتم حساب المسافة ومدة القيادة من Google Maps...');
      try {
        const formData = await collectTenantFormData();
        const data = await api('POST', '/api/preview-map-data', {
          projectData: { ...tenantProjectData, ...formData },
          selectedLandmarks,
          calculateDriving: true
        });
        if (!data.success) {
          toast(data.error || 'تعذر جلب معلومات المعالم');
          return;
        }
        tenantNearbyLandmarks = Array.isArray(data.landmarks) && data.landmarks.length
          ? data.landmarks
          : selectedLandmarks;
        const lines = tenantNearbyLandmarks.map(item => {
          const parts = [item.name || 'معلم'];
          if (item.category) parts.push(item.category);
          if (item.distance_km !== undefined && item.distance_km !== null) parts.push(item.distance_km + ' كم');
          if (item.duration_minutes !== undefined && item.duration_minutes !== null) parts.push(item.duration_minutes + ' دقائق');
          return parts.join(' — ');
        }).join('\\n');
        tenantProjectData = {
          ...tenantProjectData,
          ...formData,
          nearby_landmarks: lines,
          nearby_landmarks_data: tenantNearbyLandmarks,
          calculate_landmark_driving: true
        };
        setLocationTableValue('nearby_landmarks', lines);
        setLocationDataFetchedAt();
        await saveProjectAsDraft(true);
        toast('تم جلب المسافات ومدة القيادة للمعالم المختارة وحفظها في المسودة');
      } finally {
        hideLoader();
      }
    }

    async function fetchNearbyLandmarks() {
      const formData = await collectTenantFormData();
      showLoader('جاري معاينة وحساب بيانات الخريطة والمعالم', '');
      const data = await api('POST', '/api/preview-map-data', { projectData: formData });
      hideLoader();

      const box = document.getElementById('landmarksPreview');
      if (!box) return;
      const list = data.landmarks || data.landmarks_matrix || [];
      if (data.success && list && list.length) {
        setLocationDataFetchedAt();
        const itemsHtml = list.map((l, i) => {
          const dist = l.distance_km ? `${l.distance_km} كم` : (l.distance_text || '');
          const dur = l.duration_min ? `${l.duration_min} دقائق` : (l.duration_minutes ? `${l.duration_minutes} دقائق` : '');
          const details = [dist, dur].filter(Boolean).join(' • ');
          return `<div style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.1);">
            <span><strong>${i + 1}. ${l.name}</strong></span>
            <span style="font-size:0.85em;opacity:0.9;color:#e2b85d;">${details}</span>
          </div>`;
        }).join('');

        box.innerHTML = `
          <div style="margin-bottom:8px;"><strong> المعالم والمواقع المحسوبة للقيادة:</strong></div>
          ${itemsHtml}
          <button type="button" class="btn secondary sm" style="margin-top:10px;" onclick="applyPreviewedLandmarksToForm()">اعتماد المعالم للفورم</button>
        `;
        box.style.display = 'block';
        window._lastPreviewedLandmarks = list;
        applyPreviewedLandmarksToForm(false);
      } else {
        toast(data.error || 'لم يُعثر على معالم قريبة');
      }
    }

    function applyPreviewedLandmarksToForm(showToast = true) {
      const list = window._lastPreviewedLandmarks || [];
      if (!list.length) return;
      const text = list.map(l => {
        const parts = [l.name || 'معلم'];
        if (l.category) parts.push(l.category);
        const dist = l.distance_km !== undefined && l.distance_km !== null ? `${l.distance_km} كم` : '';
        const dur = l.duration_min !== undefined && l.duration_min !== null ? `${l.duration_min} دقائق` : (l.duration_minutes !== undefined && l.duration_minutes !== null ? `${l.duration_minutes} دقائق` : '');
        if (dist) parts.push(dist);
        if (dur) parts.push(dur);
        return parts.join(' — ');
      }).join('\n');
      const input = document.getElementById('tenant_nearby_landmarks') || document.querySelector('[name="nearby_landmarks"]') || document.querySelector('#tenantProjectForm [data-key="nearby_landmarks"]');
      if (input) {
        tenantNearbyLandmarks = list;
        tenantProjectData.nearby_landmarks = text;
        tenantProjectData.nearby_landmarks_data = list;
        input.value = text;
        setLocationTableValue('nearby_landmarks', text);
        triggerAutoSaveDraft();
        if (showToast) toast('تم اعتماد وتحديث قائمة المعالم والقيادة في الفورم وحفظها للمسودة');
      }
    }

    async function fileToDataUri(file) {
      return new Promise(resolve => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => resolve(null);
        reader.readAsDataURL(file);
      });
    }

    function fillSampleProjectData() {
      /*  مجمع الواحة السكني — حي النرجس، الرياض
          بيانات حقيقية واقعية لمشروع استثماري سكني فاخر  */
      const sample = {
        /* ── Basic ──────────────────────────────── */
        project_name: 'مجمع الواحة السكني — حي النرجس',
        project_name_en: 'Al Waha Residential Compound – Al Narjis',
        project_type: 'سكني فاخر',
        project_description: 'مجمع سكني فاخر يتكون من 120 فيلا بتصميم معماري حديث في حي النرجس شمال الرياض. يتضمن المجمع مرافق ترفيهية متنوعة منها مسبح أولمبي ونادي صحي ومساحات خضراء واسعة ومسارات للمشي وركوب الدراجات. يتميز الموقع بقربه من طريق الملك فهد وطريق الأمير محمد بن سعد، مع وصول سهل إلى مطار الملك خالد الدولي والخدمات الحيوية.',
        total_area_sqm: '85000',
        total_units: '120',
        development_timeline_months: '30',
        project_start_date: '2026-01-01',
        project_end_date: '2028-06-30',

        /* ── Location ───────────────────────────── */
        location_address: 'حي النرجس، طريق الأمير محمد بن سعد، الرياض، المملكة العربية السعودية',
        location_lat: '24.7833',
        location_lng: '46.6250',
        main_roads: 'طريق الملك فهد\nطريق الأمير محمد بن سعد\nطريق الدمام',
        catchment_areas: '5 دقائق: مجمع الراشد Mall\n10 دقائق: جامعة الملك سعود\n15 دقائق: مطار الملك خالد الدولي\n20 دقائق: مركز المملكة',

        /* ── Financial ──────────────────────────── */
        total_project_cost: '280000000',
        land_cost: '95000000',
        construction_cost: '165000000',
        infrastructure_cost: '20000000',
        unit_price_min: '1800000',
        unit_price_max: '3200000',
        annual_revenue_expected: '42000000',
        annual_operating_expenses: '8400000',
        net_operating_income: '33600000',
        roi_percentage: '14.5',
        payback_period_years: '6.8',
        total_profit_expected: '140000000',
        budget: '280,000,000 ريال سعودي',
        noi: '33,600,000 ريال سنوياً',
        roi: '14.5%',
        payback_period: '6.8 سنة',
        revenue_assumptions: 'متوسط بيع الفيلا: 2,400,000 ريال\nإجمالي الإيرادات المتوقعة: 42,000,000 ريال سنوياً\nنسبة الإشغال المتوقعة: 95%',
        cost_assumptions: 'تكلفة الأرض: 95,000,000 ريال\nتكلفة الإنشاء: 165,000,000 ريال\nالبنية التحتية: 20,000,000 ريال\nالمصروفات التشغيلية: 8,400,000 ريال سنوياً',
        exit_strategy: 'بيع الوحدات سكناً واستثماراً مع خيارات تمويل بنكي. يمكن تقسيم المبيعات على 3 مراحل لضمان أعلى عائد.',

        /* ── Features / Components ──────────────── */
        project_features: '120 فيلا بتصميم معماري حديث\nمسبح أولمبي ونادي صحي\nمساحات خضراء 40% من المساحة الإجمالية\nنظام أمن متكامل 24/7\nالقريب لطريق الملك فهد\nقريب من مطار الملك خالد الدولي\nخدمات صيانة شاملة\nموقف سيارات مغطى لكل فيلا',
        project_components: 'فيلا standalone × 40 — 450 م² — 3,200,000 ريال\nفيلا Townhouse × 50 — 380 م² — 2,400,000 ريال\nفيلا Duplex × 30 — 320 م² — 1,800,000 ريال\nمرافق ترفيهية × 1 — 5,000 م² — 15,000,000 ريال\nمسبح أولمبي × 1 — 2,000 م² — 8,000,000 ريال\nنادي صحي × 1 — 1,500 م² — 5,000,000 ريال',
        components: 'فيلا standalone × 40 — 450 م² — 3,200,000 ريال\nفيلا Townhouse × 50 — 380 م² — 2,400,000 ريال\nفيلا Duplex × 30 — 320 م² — 1,800,000 ريال\nمرافق ترفيهية × 1 — 5,000 م² — 15,000,000 ريال\nمسبح أولمبي × 1 — 2,000 م² — 8,000,000 ريال\nنادي صحي × 1 — 1,500 م² — 5,000,000 ريال',
        target_audience: 'عائلات متوسطة وعالية الدخل الباحثة عن سكن فاخر في شمال الرياض\nالمستثمرون في العقارات السكنية\nالمغتربون العاملون في الرياض',
        key_selling_points: 'أفضل موقع في شمال الرياض\nتصميم معماري عالمي\nمرافق حصرية\nعائد استثماري مرتفع\nقريب من جميع الخدمات',
        risks: 'تأخر محتمل في التصاريح البلدية\nتقلبات أسعار مواد البناء\nزيادة المنافسة من مشاريع مماثلة\nتغيرات في أسعار الفائدة',
        investment_opportunities: 'موقع استراتيجي على طريق الملك فهد\nنمو سكاني متزايد في شمال الرياض\nدعم حكومي للمشاريع السكنية\nطلب عالٍ على الفيلات الفاخرة',
        timeline: 'Q1 2026: الحصول على التراخيص النهائية\nQ2 2026: أعمال البنية التحتية (6 أشهر)\nQ4 2026: بدء بناء المرحلة الأولى (60 فيلا)\nQ2 2027: بناء المرحلة الثانية (60 فيلا)\nQ4 2027: التشطيبات النهائية\nQ2 2028: التسليم',

        /* ── SWOT ───────────────────────────────── */
        swot_strengths: 'موقع استراتيجي على طريق الملك فهد\nتصميم معماري عالي الجودة\nمرافق ترفيهية متكاملة\nقرب من المطار والخدمات الحيوية\nشبكة طرق مميزة',
        swot_weaknesses: 'تطلب استثمار أولي مرتفع (280 مليون ريال)\nمنافسة شديدة في سوق الفيلات الفاخرة\nاعتماد كبير على مؤشرات السوق السكني',
        swot_opportunities: 'نمو سكاني متزايد في الرياض (5% سنوياً)\nزيادة الطلب على الفيلات الفاخرة\nدعم حكومي لمشاريع الإسكان\nبرامج التمويل العقاري المتاحة',
        swot_threats: 'تغيرات اقتصادية محتملة\nزيادة تكاليف البناء والمواد\nمنافسة مشاريع جديدة في المنطقة\nتغيرات في اللوائح والأنظمة البلدية',

        /* ── Other / Legacy keys ────────────────── */
        plot_number: 'قطعة 1234 / مخطط 4050 — حي النرجس',
        nearby_landmarks: 'مجمع الراشد Mall — 5 دقائق\nجامعة الملك سعود — 10 دقائق\nمطار الملك خالد الدولي — 15 دقائق\nمركز المملكة — 20 دقائق',
        description: 'مجمع سكني فاخر يتكون من 120 فيلا بتصميم معماري حديث في حي النرجس شمال الرياض. يتضمن المجمع مرافق ترفيهية متنوعة منها مسبح أولمبي ونادي صحي ومساحات خضراء واسعة.',
        location_maps_link: 'https://maps.app.goo.gl/narjis-riyadh',

        /* ── Financial Calc fields ──────────────── */
        fin_avg_rent: '1200',
        fin_service_fee: '5',
        fin_land_cost: '95000000',
        fin_dev_cost: '185000000',
        fin_opex: '8400000',
        fin_exit_value: '420000000',
        fin_cap_rate: '8',

        /* ── Timeline fields ────────────────────── */
        timeline_start_date: '2026-01',
        timeline_years: '3',
      };
      const inputs = document.querySelectorAll('#tenantProjectForm input, #tenantProjectForm textarea, #tenantProjectForm select');
      let filled = 0;
      inputs.forEach(input => {
        const key = input.dataset.key;
        if (!key || !(key in sample)) return;
        if (input.tagName === 'SELECT') {
          const options = Array.from(input.options).map(o => o.value);
          input.value = options.includes(sample[key]) ? sample[key] : '';
        } else {
          input.value = sample[key];
        }
        filled++;
      });

      // Components now live only inside the financial study, which seeds its own default rows.

      // Trigger financial recalc
      const finCalcDone = typeof recalcFinancials === 'function';
      if (finCalcDone) { recalcFinancials(); filled += 7; }

      // The timeline is client-entered, so sample data only ensures an empty row exists.
      if (typeof recalcTimeline === 'function') recalcTimeline();

      // Sync the location tables (roads / landmarks / catchment) with the sample text
      refreshLocationTables();
      window._lastAnalyzedAddress = (sample.location_address || '').trim();

      // Trigger automatic draft save
      triggerAutoSaveDraft();

      toast(filled > 0 ? 'تم تعبئة ' + filled + ' حقل + جداول تجريبية — بيانات مجمع الواحة السكني، حي النرجس، الرياض' : 'لا توجد حقول مطابقة');
    }

    // Object URLs for previewed documents, keyed by file id so repeat opens stay cheap.
    const projectFileObjectUrls = new Map();