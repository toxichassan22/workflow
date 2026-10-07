    /* ── Tenant map-edit state: polygon/road/catchment/landmark drafts,
       edit-mode flags and the asset invalidation used by every map panel. ── */


    let tenantMapPreviewState = null;
    let tenantMapPolygonPoints = [];
    let tenantMapDraftPolygonPoints = [];
    let tenantMapPolygonMode = false;
    let tenantMapPinMode = false;
    let tenantMapDraftPinHistory = [];
    let tenantRoadEditMode = false;
    let tenantRoadEditDraft = null;
    let tenantRoadEditHistory = [];
    let tenantRoadEditSelectedIndex = -1;
    let tenantCatchmentEditMode = false;
    let tenantCatchmentEditDraft = null;
    let tenantCatchmentEditHistory = [];
    let tenantLandmarksEditMode = false;
    let tenantLandmarksEditDraft = null;
    let tenantLandmarksEditHistory = [];
    let tenantLandmarkPlacementTarget = null;
    let mapPlaceLinked = null;
    let tenantNearbyLandmarks = [];
    let tenantSelectedMapType = 'overview';

    function parseTenantPolygonPoints(value) {
      if (Array.isArray(value)) {
        return value.map(point => Array.isArray(point) ? point.map(Number) : [])
          .filter(point => point.length >= 2 && Number.isFinite(point[0]) && Number.isFinite(point[1]))
          .map(point => [point[0], point[1]]);
      }
      if (typeof value !== 'string') return [];
      return value.split(';').map(point => point.split(',').map(Number))
        .filter(point => point.length === 2 && point.every(Number.isFinite));
    }

    function resetTenantRoadModes() {
      tenantRoadEditMode = false;
      tenantRoadEditDraft = null;
      tenantRoadEditHistory = [];
      tenantRoadEditSelectedIndex = -1;
      mapPlaceLinked = null;
    }

    function resetTenantCatchmentMode() {
      tenantCatchmentEditMode = false;
      tenantCatchmentEditDraft = null;
      tenantCatchmentEditHistory = [];
      mapPlaceLinked = null;
    }

    function resetTenantLandmarksEditMode() {
      tenantLandmarksEditMode = false;
      tenantLandmarksEditDraft = null;
      tenantLandmarksEditHistory = [];
      mapPlaceLinked = null;
    }

    function invalidateTenantMapAssets() {
      tenantCreativeImages = {
        ...(tenantCreativeImages || {}),
        map_placeholders: {},
        map_zooms: {},
        map_centers: {},
        map_viewport_overrides: {},
        map_landmarks: [],
        map_access_roads: [],
        map_catchment_landmarks: [],
        map_landmark_items: [],
        map_baked_frames: {},
        map_approvals: {},
        map_lat: null,
        map_lng: null,
        maps_signature: null,
        maps_persisted: false
      };
      if (typeof resetInteractiveMapState === 'function') resetInteractiveMapState();
      // Rendered roads, resolved marker items, label placements and a manually
      // drawn boundary are all pinned to the old site's coordinates — carrying
      // them over draws them off-frame or blocks the next render with stale
      // geometry.
      tenantProjectData.location_polygon_source = 'auto';
      tenantProjectData.access_roads_data = [];
      tenantProjectData.manual_road_paths = [];
      tenantProjectData.catchment_map_landmarks = [];
      tenantProjectData.landmark_map_items = [];
      tenantProjectData.landmarks_matrix = [];
      tenantProjectData.landmark_label_positions = {};
      tenantProjectData.access_road_label_positions = {};
      tenantProjectData.access_road_label_sizes = {};
      tenantProjectData.catchment_label_positions = {};
      tenantMapPreviewState = null;
      tenantMapPolygonPoints = [];
      tenantMapDraftPolygonPoints = [];
      tenantMapPolygonMode = false;
      tenantMapPinMode = false;
      tenantMapDraftPinHistory = [];
      resetTenantRoadModes();
      resetTenantCatchmentMode();
      resetTenantLandmarksEditMode();
      tenantProjectData.location_polygon = '';
      syncTenantLocationPolygon();
      renderTenantMapPolygonOverlay();
      renderMapPreviewGallery();
      triggerAutoSaveDraft();
    }


    function tenantMapCoordinatesFromClient(clientX, clientY, img) {
      // The live map converts through its own projection — always frame-accurate.
      if (interactiveMapActive()) return interactiveMapClientToLatLng(clientX, clientY);
      // Without the zoom the server rendered at, click-to-coordinates math lands the
      // point at a completely wrong place — refuse instead of storing corrupt data.
      if (!tenantMapPreviewState || tenantMapPreviewState.frameAccurate === false || !img) return null;
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
      if (!coordinates) {
        if (tenantMapPolygonMode || tenantMapPinMode || tenantRoadEditMode || tenantLandmarkPlacementTarget) {
          toast('تعذر تحديد الإحداثيات على هذه الخريطة');
        }
        return;
      }
      dispatchTenantMapPoint(coordinates[0], coordinates[1]);
    }

    // Shared by the static image click and the live map's click listener —
    // both hand in resolved coordinates.
    function dispatchTenantMapPoint(nextLat, nextLng) {
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
        addAccessRoadPathPoint(nextLat, nextLng);
        return;
      }
      const landmarkMapType = LOCATION_TABLE_FIELDS[tenantLandmarkPlacementTarget?.key]?.mapType;
      if (tenantLandmarkPlacementTarget && tenantSelectedMapType === landmarkMapType) {
        tenantLandmarkPlacementTarget.tr.dataset.lat = nextLat.toFixed(6);
        tenantLandmarkPlacementTarget.tr.dataset.lng = nextLng.toFixed(6);
        tenantLandmarkPlacementTarget.tr.dataset.manualPosition = '1';
        serializeLocationTable(tenantLandmarkPlacementTarget.key);
        scheduleMapTableRecompose(tenantLandmarkPlacementTarget.key);
        tenantLandmarkPlacementTarget = null;
        releaseLocationSectionApproval();
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
      const locked = !overviewGenerated;
      if (undoButton) undoButton.disabled = locked || !tenantMapDraftPolygonPoints.length;
      if (confirmButton) confirmButton.disabled = locked || tenantMapDraftPolygonPoints.length < 3;
      if (clearButton) clearButton.disabled = locked || !tenantMapDraftPolygonPoints.length;
      if (pinUndoButton) pinUndoButton.disabled = locked || tenantMapDraftPinHistory.length <= 1;
      if (pinConfirmButton) pinConfirmButton.disabled = locked || tenantMapDraftPinHistory.length <= 1;
    }

    function updateTenantRoadControls() {
      const editUndo = document.getElementById('undoAccessRoadEditsButton');
      const pathClear = document.getElementById('clearAccessRoadPathButton');
      if (editUndo) editUndo.disabled = !tenantRoadEditHistory.length;
      if (pathClear) pathClear.disabled = !(
        tenantRoadEditSelectedIndex >= 0
        && (tenantRoadEditDraft?.rows?.[tenantRoadEditSelectedIndex]?.points || []).length
      );
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
      const modeActive = tenantMapPolygonMode || tenantMapPinMode || tenantRoadEditMode || tenantCatchmentEditMode || tenantLandmarksEditMode || tenantLandmarkPlacementTarget;
      if (interactiveMapActive()) {
        try { tenantInteractiveMap.setOptions({ draggableCursor: modeActive ? 'crosshair' : 'grab' }); } catch (e) { /* map gone */ }
        return;
      }
      const image = document.querySelector('#mapPreviewImage img');
      if (!image) return;
      image.style.cursor = modeActive ? 'crosshair' : (mapViewportPanAllowed() ? 'grab' : 'default');
    }

    // Only the land and roads maps take a manual viewport: the live preview
    // mounts for them and the recorded frame is what the next bake (and the
    // approval) freezes. Catchment and landmarks are fixed auto-framed
    // rasters — their edit sessions move labels and markers on the stored
    // image, never the frame itself.
    function mapViewportAdjustable(mapType) {
      return mapType === 'overview' || mapType === 'access';
    }

    // Per-map approval: the flag certifies the stored raster exactly as the
    // client framed it — approving while the live view is dirty bakes that
    // frame first, and any later frame/content change drops the flag again.
    function tenantMapApproved(mapType) {
      return !!(tenantCreativeImages.map_approvals && tenantCreativeImages.map_approvals[mapType]);
    }

    async function approveTenantMap(mapType) {
      // Two-tier model: each generated map approves on its own artifact — the
      // site analysis is a sibling generated-content approval, not a gate, and
      // the section approval is what requires all of them together.
      if (!mapOverlayHasBase(mapType)) return false;
      // Two-tier order: the section certifies everything inside it, so a map
      // cannot (re)approve inside an already-approved section — its live frame
      // is also frozen there, and approving would freeze the stale raster
      // instead of what is on screen. Unapprove the section first.
      if (tenantProjectSectionStatuses && tenantProjectSectionStatuses.location === 'approved') {
        toast(typeof WFT === 'function'
          ? WFT('location.section_unapprove_first_map', 'ألغ اعتماد قسم الموقع قبل اعتماد خريطة بداخله')
          : 'ألغ اعتماد قسم الموقع قبل اعتماد خريطة بداخله');
        return false;
      }
      // A table edit still inside its debounce window must land first — once
      // the approval flag is set the recompose path refuses to touch the
      // raster, so a click that outruns the timer would certify a stale map.
      if (typeof flushMapTableRecompose === 'function') await flushMapTableRecompose();
      // The dirty flag is only as fresh as the last idle — pull the live
      // camera now so a pan followed by an instant click still bakes the
      // frame the client is looking at, not the pre-pan one.
      if (typeof syncInteractiveLiveFrame === 'function') syncInteractiveLiveFrame();
      if (tenantInteractiveFrameDirty[mapType]) {
        const baked = await regenerateMapPreview(mapType);
        if (!baked) return false;
      }
      tenantCreativeImages.map_approvals = { ...(tenantCreativeImages.map_approvals || {}), [mapType]: true };
      await saveMapPreviewState();
      toast('تم اعتماد الخريطة');
      // Re-selecting swaps the mounted live map for the certified raster the
      // approval just froze — nothing on the preview stays interactive.
      if (tenantSelectedMapType === mapType) selectMapPreviewView(mapType);
      renderMapPreviewGallery(true);
      renderLocationWorkflowState();
      return true;
    }

    async function unapproveTenantMap(mapType) {
      if (!tenantMapApproved(mapType)) return;
      tenantCreativeImages.map_approvals = { ...(tenantCreativeImages.map_approvals || {}), [mapType]: false };
      // The section approval required every map's flag — dropping one inside an
      // approved section must drop the section too, same as any other mutation.
      if (typeof releaseLocationSectionApproval === 'function') releaseLocationSectionApproval();
      await saveMapPreviewState();
      toast('تم إلغاء اعتماد الخريطة');
      // Re-selecting remounts the live map on the released frame so editing
      // can resume right away.
      if (tenantSelectedMapType === mapType) selectMapPreviewView(mapType);
      renderMapPreviewGallery(true);
      renderLocationWorkflowState();
    }

    // Shared gate for every path that would alter an approved raster.
    function mapApprovalBlocksEdit(mapType) {
      if (!tenantMapApproved(mapType)) return false;
      toast(typeof WFT === 'function'
        ? WFT('location.map_unapprove_first', 'ألغ اعتماد الخريطة قبل تعديلها أو إعادة توليدها')
        : 'ألغ اعتماد الخريطة قبل تعديلها أو إعادة توليدها');
      return true;
    }

    // Drag-to-pan is only safe on a frame we can convert clicks against: a known
    // zoom and centre. Every drawing/editing mode keeps priority.
    function mapViewportPanAllowed() {
      if (!mapViewportAdjustable(tenantSelectedMapType)) return false;
      if (tenantMapApproved(tenantSelectedMapType)) return false;
      if (tenantMapPolygonMode || tenantMapPinMode || tenantRoadEditMode || tenantCatchmentEditMode || tenantLandmarksEditMode || tenantLandmarkPlacementTarget) return false;
      return !!(tenantMapPreviewState && tenantMapPreviewState.frameAccurate);
    }

    let tenantMapViewportBusy = false;

    // Clears a hand-picked zoom/center so the next render frames this map
    // automatically again — without it a stray pan would pin the frame forever.
    // Fixed maps keep this escape hatch: a viewport pinned while they were
    // still adjustable must stay releasable or the frame is stuck forever.
    function resetMapViewport(mapType) {
      if (tenantMapViewportBusy) return;
      if (mapApprovalBlocksEdit(mapType)) return;
      if (!(tenantCreativeImages.map_viewport_overrides || {})[mapType]) return;
      const overrides = { ...(tenantCreativeImages.map_viewport_overrides || {}) };
      delete overrides[mapType];
      tenantCreativeImages.map_viewport_overrides = overrides;
      const zooms = { ...(tenantCreativeImages.map_zooms || {}) };
      delete zooms[mapType];
      tenantCreativeImages.map_zooms = zooms;
      const centers = { ...(tenantCreativeImages.map_centers || {}) };
      delete centers[mapType];
      tenantCreativeImages.map_centers = centers;
      regenerateMapPreview(mapType);
    }

    function startMapViewportPan(event) {
      if (event.button !== 0 || tenantMapViewportBusy || !mapViewportPanAllowed()) return;
      if (tenantMapApproved(tenantSelectedMapType)) return;
      const box = document.getElementById('mapPreviewImage');
      const img = box?.querySelector('img');
      if (!box || !img || !img.src) return;
      const pan = { startX: event.clientX, startY: event.clientY, dx: 0, dy: 0 };
      const parts = [img, box.querySelector('#mapPolygonOverlay'), box.querySelector('#mapLabelOverlay')].filter(Boolean);
      const move = moveEvent => {
        pan.dx = moveEvent.clientX - pan.startX;
        pan.dy = moveEvent.clientY - pan.startY;
        if (Math.abs(pan.dx) + Math.abs(pan.dy) > 3) {
          parts.forEach(el => { el.style.transform = 'translate(' + pan.dx + 'px,' + pan.dy + 'px)'; });
          img.style.cursor = 'grabbing';
        }
      };
      const stop = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', stop);
        window.removeEventListener('pointercancel', stop);
        parts.forEach(el => { el.style.transform = ''; });
        img.style.cursor = '';
        const dx = pan.dx;
        const dy = pan.dy;
        if (Math.abs(dx) + Math.abs(dy) < 12) return;
        const rect = img.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        // The image point that lands under the centre becomes the new map centre.
        const coords = tenantMapCoordinatesFromClient(rect.left + rect.width / 2 - dx, rect.top + rect.height / 2 - dy, img);
        if (!coords) return;
        tenantCreativeImages.map_centers = { ...(tenantCreativeImages.map_centers || {}), [tenantSelectedMapType]: { lat: coords[0], lng: coords[1] } };
        tenantCreativeImages.map_viewport_overrides = { ...(tenantCreativeImages.map_viewport_overrides || {}), [tenantSelectedMapType]: true };
        tenantMapViewportBusy = true;
        regenerateMapPreview(tenantSelectedMapType).finally(() => { tenantMapViewportBusy = false; });
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', stop);
      window.addEventListener('pointercancel', stop);
    }

    // An overlay composes onto the raster that already exists for this map; after
    // a location invalidation there is none, and posting anyway would stamp the
    // old site's image with the new site's metadata.
    function mapOverlayHasBase(mapType) {
      const view = (typeof MAP_PREVIEW_VIEW_DEFS !== 'undefined' ? MAP_PREVIEW_VIEW_DEFS : [])
        .find(v => v.mapType === mapType);
      return !!(view && mapPreviewStoredUrl(view));
    }

    // A recompose answers with the raster's stored frame. Under a viewport
    // override that frame is stale next to the live camera — merging it would
    // overwrite map_centers/map_zooms, and the user's unsaved pan would then
    // compare clean against the baked frame and never reach the bake.
    function mergeRecomposeMapFrame(mapType, data) {
      // Fixed maps take the refit frame even with a stale override flag —
      // a leftover flag from the adjustable era must not pin them wide.
      if (mapViewportAdjustable(mapType) && (tenantCreativeImages.map_viewport_overrides || {})[mapType]) return;
      if (data.zooms && data.zooms[mapType] !== undefined)
        tenantCreativeImages.map_zooms = { ...(tenantCreativeImages.map_zooms || {}), [mapType]: data.zooms[mapType] };
      if (data.centers && data.centers[mapType] !== undefined)
        tenantCreativeImages.map_centers = { ...(tenantCreativeImages.map_centers || {}), [mapType]: data.centers[mapType] };
    }

    async function applyOverviewMapEdits() {
      if (!mapOverlayHasBase('overview') || tenantMapApproved('overview')) return false;
      try {
        const payload = slimMapProjectData(tenantProjectData);
        payload.draftId = tenantProjectData.draftId;
        const data = await api('POST', '/api/generate-map-image', {
          projectData: payload,
          mapType: 'overview',
          presentationId: tenantPresentationId,
          highlightSite: shouldHighlightTenantSite(),
          overlayOnly: true
        });
        if (!data.success) return false;
        if (data.revision) tenantPresentationRevision = Number(data.revision) || tenantPresentationRevision;
        tenantCreativeImages.map_placeholders = { ...(tenantCreativeImages.map_placeholders || {}), ...(data.placeholders || {}) };
        mergeRecomposeMapFrame('overview', data);
        if (typeof noteInteractiveBakedFrame === 'function') noteInteractiveBakedFrame('overview', data.zooms?.overview, data.centers?.overview);
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
      if (!mapOverlayHasBase('access') || tenantMapApproved('access')) return false;
      try {
          const payload = slimMapProjectData(tenantProjectData);
          payload.draftId = tenantProjectData.draftId;
          const data = await api('POST', '/api/generate-map-image', {
            projectData: payload,
            mapType: 'access',
            presentationId: tenantPresentationId,
            overlayOnly: true
          });
          if (!data.success) return false;
          if (data.revision) tenantPresentationRevision = Number(data.revision) || tenantPresentationRevision;
          tenantCreativeImages.map_placeholders = { ...(tenantCreativeImages.map_placeholders || {}), ...(data.placeholders || {}) };
          mergeRecomposeMapFrame('access', data);
          if (typeof noteInteractiveBakedFrame === 'function') noteInteractiveBakedFrame('access', data.zooms?.access, data.centers?.access);
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
      // On the live map the editable base is always there — no raster swap needed.
      if (await ensureInteractivePreview('access')) return true;
      if (tenantMapPreviewState?.usesEditableBase) return true;
      selectMapPreviewView('access');
      if (tenantMapPreviewState?.usesEditableBase) return true;
      if (!(await applyAccessMapEdits())) return false;
      return selectMapPreviewView('access');
    }

    function applyCatchmentMapEdits() {
      if (!mapOverlayHasBase('catchment') || tenantMapApproved('catchment')) return Promise.resolve(false);
      return (async () => {
        try {
          const payload = slimMapProjectData(tenantProjectData);
          payload.draftId = tenantProjectData.draftId;
          const data = await api('POST', '/api/generate-map-image', {
            projectData: payload,
            mapType: 'catchment',
            presentationId: tenantPresentationId,
            overlayOnly: true
          });
          if (!data.success) return false;
          if (data.revision) tenantPresentationRevision = Number(data.revision) || tenantPresentationRevision;
          tenantCreativeImages.map_placeholders = { ...(tenantCreativeImages.map_placeholders || {}), ...(data.placeholders || {}) };
          mergeRecomposeMapFrame('catchment', data);
          if (typeof noteInteractiveBakedFrame === 'function') noteInteractiveBakedFrame('catchment', data.zooms?.catchment, data.centers?.catchment);
          tenantProjectData.catchment_map_landmarks = Array.isArray(data.catchmentLandmarks) ? data.catchmentLandmarks : tenantProjectData.catchment_map_landmarks || [];
          tenantCreativeImages.map_catchment_landmarks = tenantProjectData.catchment_map_landmarks;
          // The server may have re-anchored a marker (e.g. a road snapped onto
          // its drawn path) — the table rows must carry the same coordinates or
          // the next merge would resurrect the stale ones.
          const returnedCatchmentByName = new Map(tenantProjectData.catchment_map_landmarks.map(item => [item?.name, item]));
          tenantProjectData.city_landmarks_data = (Array.isArray(tenantProjectData.city_landmarks_data) ? tenantProjectData.city_landmarks_data : []).map(item => {
            const updated = returnedCatchmentByName.get(item?.name);
            if (!updated) return item;
            const next = { ...item, lat: updated.lat, lng: updated.lng };
            if (updated.manual_position) next.manual_position = true;
            return next;
          });
          document.querySelectorAll('table.location-table[data-location-table="city_landmarks"] tbody tr').forEach(tr => {
            const updated = returnedCatchmentByName.get(tr.querySelector('.lt-name-input')?.value?.trim());
            if (!updated) return;
            tr.dataset.lat = String(updated.lat);
            tr.dataset.lng = String(updated.lng);
            if (updated.manual_position) tr.dataset.manualPosition = '1';
          });
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
      if (await ensureInteractivePreview('catchment')) return true;
      if (tenantMapPreviewState?.usesEditableBase) return true;
      selectMapPreviewView('catchment');
      if (tenantMapPreviewState?.usesEditableBase) return true;
      if (!(await applyCatchmentMapEdits())) return false;
      return selectMapPreviewView('catchment');
    }

    function applyLandmarksMapEdits() {
      if (!mapOverlayHasBase('landmarks') || tenantMapApproved('landmarks')) return Promise.resolve(false);
      return (async () => {
        try {
          const payload = slimMapProjectData(tenantProjectData);
          payload.draftId = tenantProjectData.draftId;
          const data = await api('POST', '/api/generate-map-image', {
            projectData: payload,
            mapType: 'landmarks',
            presentationId: tenantPresentationId,
            overlayOnly: true
          });
          if (!data.success) return false;
          if (data.revision) tenantPresentationRevision = Number(data.revision) || tenantPresentationRevision;
          tenantCreativeImages.map_placeholders = { ...(tenantCreativeImages.map_placeholders || {}), ...(data.placeholders || {}) };
          mergeRecomposeMapFrame('landmarks', data);
          if (typeof noteInteractiveBakedFrame === 'function') noteInteractiveBakedFrame('landmarks', data.zooms?.landmarks, data.centers?.landmarks);
          tenantProjectData.landmark_map_items = Array.isArray(data.landmarkMapItems) ? data.landmarkMapItems : tenantProjectData.landmark_map_items || [];
          tenantCreativeImages.map_landmark_items = tenantProjectData.landmark_map_items;
          // Same write-back as the catchment map: server-side re-anchored
          // coordinates must reach the nearby-landmark rows too.
          const returnedLandmarksByName = new Map(tenantProjectData.landmark_map_items.map(item => [item?.name, item]));
          tenantProjectData.nearby_landmarks_data = (Array.isArray(tenantProjectData.nearby_landmarks_data) ? tenantProjectData.nearby_landmarks_data : []).map(item => {
            const updated = returnedLandmarksByName.get(item?.name);
            if (!updated) return item;
            const next = { ...item, lat: updated.lat, lng: updated.lng };
            if (updated.manual_position) next.manual_position = true;
            return next;
          });
          document.querySelectorAll('table.location-table[data-location-table="nearby_landmarks"] tbody tr').forEach(tr => {
            const updated = returnedLandmarksByName.get(tr.querySelector('.lt-name-input')?.value?.trim());
            if (!updated) return;
            tr.dataset.lat = String(updated.lat);
            tr.dataset.lng = String(updated.lng);
            if (updated.manual_position) tr.dataset.manualPosition = '1';
          });
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
      if (await ensureInteractivePreview('landmarks')) return true;
      if (tenantMapPreviewState?.usesEditableBase) return true;
      selectMapPreviewView('landmarks');
      if (tenantMapPreviewState?.usesEditableBase) return true;
      if (!(await applyLandmarksMapEdits())) return false;
      return selectMapPreviewView('landmarks');
    }

    async function toggleTenantPolygonMode() {
      if (tenantSelectedMapType !== 'overview') selectMapPreviewView('overview');
      if (!tenantMapPreviewState) { toast('خريطة الأرض غير مولدة'); return; }
      if (mapApprovalBlocksEdit('overview')) return;
      tenantMapPinMode = false;
      tenantMapDraftPinHistory = [];
      tenantMapDraftPolygonPoints = [];
      tenantMapPolygonMode = true;
      selectMapPreviewView('overview');
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
      releaseLocationSectionApproval();
      renderLocationWorkflowState();
      renderTenantMapPolygonOverlay();
      triggerAutoSaveDraft();
      await applyOverviewMapEdits();
      toast('تم اعتماد حدود الموقع');
    }

    async function startTenantMapPinMode() {
      if (tenantSelectedMapType !== 'overview') selectMapPreviewView('overview');
      if (!tenantMapPreviewState) { toast('خريطة الأرض غير مولدة'); return; }
      if (mapApprovalBlocksEdit('overview')) return;
      const lat = Number(tenantProjectData.location_lat);
      const lng = Number(tenantProjectData.location_lng);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) { toast('موقع المبنى غير محدد'); return; }
      tenantMapPolygonMode = false;
      tenantMapDraftPolygonPoints = [];
      tenantMapPinMode = true;
      tenantMapDraftPinHistory = [[lat, lng]];
      selectMapPreviewView('overview');
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
      tenantMapPinMode = false;
      tenantMapDraftPinHistory = [];
      releaseLocationSectionApproval();
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
        return '<div class="map-road-label' + mapPlaceLinkClass('road', path.name) + (tenantRoadEditMode ? ' editable' : '') + '" data-road-label="' + escapeHtml(path.name) + '" style="left:' + x.toFixed(3) + '%;top:' + y.toFixed(3) + '%;font-size:' + (13 * scale).toFixed(1) + 'px;font-size:' + (1.3 * scale).toFixed(3) + 'cqw;padding:' + (4 * scale).toFixed(1) + 'px ' + (8 * scale).toFixed(1) + 'px;padding:' + (0.4 * scale).toFixed(3) + 'cqw ' + (0.8 * scale).toFixed(3) + 'cqw"' +
          (tenantRoadEditMode ? ' onpointerdown="startAccessRoadLabelDrag(event,decodeURIComponent(\'' + encodedName + '\'))"' + hoverAttrs : '') + '>' + escapeHtml(path.name) + deleteAction + '</div>';
      }).join('');
    }

    function renderCatchmentLabels(items, toPoint) {
      const layer = document.getElementById('mapLabelOverlay');
      if (!layer) return;
      // The layer stays click-through: only .editable labels/markers opt into
      // pointer events, so a live map keeps panning during edit mode too.
      layer.style.pointerEvents = 'none';
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
        const label = '<div class="map-place-label' + linked + (tenantCatchmentEditMode ? ' editable' : '') + '" data-catchment-label="' + escapeHtml(item.name) + '" style="left:' + x.toFixed(3) + '%;top:' + y.toFixed(3) + '%;font-size:12px;font-size:1.2cqw;padding:3px 7px;padding:.3cqw .7cqw"' +
          (tenantCatchmentEditMode ? ' onpointerdown="startCatchmentLabelDrag(event,decodeURIComponent(\'' + encodedName + '\'))"' + hoverAttrs : '') + '>' + numChip + escapeHtml(item.name) + '</div>';
        return marker + label;
      }).join('');
    }

    function renderLandmarksLabels(items, toPoint) {
      const layer = document.getElementById('mapLabelOverlay');
      if (!layer) return;
      layer.style.pointerEvents = 'none';
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
        const label = '<div class="map-place-label' + linked + (tenantLandmarksEditMode ? ' editable' : '') + '" data-landmark-label="' + escapeHtml(item.name) + '" style="left:' + x.toFixed(3) + '%;top:' + y.toFixed(3) + '%;font-size:12px;font-size:1.2cqw;padding:3px 7px;padding:.3cqw .7cqw"' +
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
      const liveActive = interactiveMapActive();
      if (!overlay || !state || (!liveActive && (!img || !img.naturalWidth || !img.naturalHeight)) || (!showBoundary && !showPin && !showAccessPin && !showCatchment && !showLandmarks && (!showRoads || !roadPaths.length))) {
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
      const toPoint = liveActive
        ? (point => interactiveMapLatLngToPercent(point[0], point[1]) || '-1000,-1000')
        : (point => {
          const lngOffset = (point[1] - state.lng) * world / 360;
          const pointLatRad = point[0] * Math.PI / 180;
          const pointY = (1 - Math.log(Math.tan(pointLatRad) + 1 / Math.cos(pointLatRad)) / Math.PI) / 2;
          const yOffset = (pointY - centerY) * world;
          return ((0.5 + lngOffset / img.naturalWidth) * 100).toFixed(3) + ',' + ((0.5 + yOffset / img.naturalHeight) * 100).toFixed(3);
        });
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
        : '';
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
      // Vertex dots mark the path being sketched for the selected road —
      // clicks append to it until اعتماد commits the session.
      const sketchPoints = tenantRoadEditMode && tenantRoadEditSelectedIndex >= 0
        ? (tenantRoadEditDraft?.rows?.[tenantRoadEditSelectedIndex]?.points || [])
        : [];
      const roadPointMarkup = sketchPoints.map(point => {
        const [x, y] = toPoint(point).split(',');
        return '<circle cx="' + x + '%" cy="' + y + '%" r="1.15" fill="#fff" stroke="#6B1C23" stroke-width="0.45"></circle>';
      }).join('');
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

    // Object URLs for previewed documents, keyed by file id so repeat opens stay cheap.
    const projectFileObjectUrls = new Map();