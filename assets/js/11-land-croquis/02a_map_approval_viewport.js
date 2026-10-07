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

    const tenantMapApprovalInflight = {};

    function approveTenantMap(mapType) {
      if (tenantMapApprovalInflight[mapType]) return tenantMapApprovalInflight[mapType];
      const run = Promise.resolve().then(() => approveTenantMapOnce(mapType)).catch(error => {
        console.warn('[MAP APPROVAL]', error);
        toast(WFT('map.edit_apply_failed', 'تعذر حفظ التعديلات على الخريطة'));
        return false;
      }).finally(() => {
        delete tenantMapApprovalInflight[mapType];
        renderLocationWorkflowState();
      });
      tenantMapApprovalInflight[mapType] = run;
      renderLocationWorkflowState();
      return run;
    }

    function mapPreviewScopeKey() {
      return String(tenantPresentationId || tenantProjectData.draftId || '');
    }

    function mapPreviewScopeMatches(creative, scope) {
      return tenantCreativeImages === creative && mapPreviewScopeKey() === scope;
    }

    function tenantMapApprovalBusy(mapType) {
      return !!tenantMapApprovalInflight[mapType];
    }

    function tenantMapRasterCurrent(mapType) {
      const version = tenantCreativeImages.map_renderer_version;
      return !!version && tenantCreativeImages.map_render_versions?.[mapType] === version;
    }

    function noteMapRenderVersion(mapType, data) {
      if (!data.mapRenderVersion) return;
      tenantCreativeImages.map_renderer_version = data.mapRenderVersion;
      tenantCreativeImages.map_render_versions = {
        ...(tenantCreativeImages.map_render_versions || {}), [mapType]: data.mapRenderVersion
      };
    }

    function tenantMapHasOpenEdits(mapType) {
      return (mapType === 'overview' && (tenantMapPolygonMode || tenantMapPinMode))
        || (mapType === 'access' && tenantRoadEditMode)
        || (mapType === 'catchment' && tenantCatchmentEditMode)
        || (mapType === 'landmarks' && tenantLandmarksEditMode)
        || LOCATION_TABLE_FIELDS[tenantLandmarkPlacementTarget?.key]?.mapType === mapType;
    }

    async function saveMapPreviewState() {
      tenantProjectData.tenantCreativeImages = tenantCreativeImages;
      let saved = false;
      try {
        if (tenantPresentationId) {
          const resp = await api('PUT', '/api/presentations/' + encodeURIComponent(tenantPresentationId), {
            projectData: tenantProjectData,
            expectedRevision: tenantPresentationRevision
          });
          saved = !!resp && resp.success !== false && !resp.error;
          if (saved && resp.revision) {
            tenantPresentationRevision = Number(resp.revision) || tenantPresentationRevision;
          }
        } else if (tenantProjectData.draftId && typeof saveProjectAsDraftNow === 'function') {
          // Regenerating a map is an explicit user action. Persist the new image URL
          // immediately for drafts; otherwise reload restores the previous placeholder.
          // A failed save keeps the workspace but must be said, or the map looks
          // persisted while a reload quietly drops it.
          saved = !!(await saveProjectAsDraftNow(true));
        } else {
          triggerAutoSaveDraft();
        }
      } catch (error) {
        console.warn('[MAP STATE SAVE]', error);
      }
      if (!saved) toast(WFT('map.save_state_failed', 'تعذر حفظ حالة الخريطة على الخادم'));
      return saved;
    }

    async function approveTenantMapOnce(mapType) {
      // Two-tier model: each generated map approves on its own artifact — the
      // site analysis is a sibling generated-content approval, not a gate, and
      // the section approval is what requires all of them together.
      if (!mapOverlayHasBase(mapType)) return false;
      if (tenantMapApproved(mapType)) return true;
      if (tenantMapHasOpenEdits(mapType)) {
        toast(WFT('map.edit_apply_failed', 'تعذر حفظ التعديلات على الخريطة'));
        return false;
      }
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
      const scope = mapPreviewScopeKey();
      const currentCreative = tenantCreativeImages;
      // A table edit still inside its debounce window must land first — once
      // the approval flag is set the recompose path refuses to touch the
      // raster, so a click that outruns the timer would certify a stale map.
      if (typeof flushMapTableRecompose === 'function' && !(await flushMapTableRecompose(mapType))) {
        toast(WFT('map.edit_apply_failed', 'تعذر حفظ التعديلات على الخريطة'));
        return false;
      }
      // The dirty flag is only as fresh as the last idle — pull the live
      // camera now so a pan followed by an instant click still bakes the
      // frame the client is looking at, not the pre-pan one.
      if (!mapPreviewScopeMatches(currentCreative, scope)) return false;
      if (typeof syncInteractiveLiveFrame === 'function') syncInteractiveLiveFrame();
      if (tenantInteractiveFrameDirty[mapType]) {
        const baked = await regenerateMapPreview(mapType, true);
        if (!baked) return false;
      } else if (!tenantMapRasterCurrent(mapType)) {
        const apply = { overview: applyOverviewMapEdits, access: applyAccessMapEdits,
          catchment: applyCatchmentMapEdits, landmarks: applyLandmarksMapEdits }[mapType];
        if (!apply || !(await enqueueTenantMapWrite(apply))) return false;
      }
      if (typeof flushMapTableRecompose === 'function' && !(await flushMapTableRecompose(mapType))) return false;
      if (!mapPreviewScopeMatches(currentCreative, scope) || !mapOverlayHasBase(mapType)) return false;
      if (typeof syncInteractiveLiveFrame === 'function') syncInteractiveLiveFrame();
      if (tenantInteractiveFrameDirty[mapType] || tenantMapHasOpenEdits(mapType)) return false;
      const creative = tenantCreativeImages;
      const previous = creative.map_approvals?.[mapType];
      creative.map_approvals = { ...(creative.map_approvals || {}), [mapType]: true };
      let saved = false;
      try {
        saved = await saveMapPreviewState();
      } finally {
        if (!saved) {
          const approvals = { ...(creative.map_approvals || {}) };
          if (previous === undefined) delete approvals[mapType];
          else approvals[mapType] = previous;
          creative.map_approvals = approvals;
          if (tenantCreativeImages === creative) renderLocationWorkflowState();
        }
      }
      if (!saved) return false;
      toast('تم اعتماد الخريطة');
      // Re-selecting swaps the mounted live map for the certified raster the
      // approval just froze — nothing on the preview stays interactive.
      if (tenantSelectedMapType === mapType) selectMapPreviewView(mapType);
      renderMapPreviewGallery(true);
      renderLocationWorkflowState();
      return true;
    }

    async function unapproveTenantMap(mapType) {
      if (tenantMapApprovalInflight[mapType]) await tenantMapApprovalInflight[mapType];
      if (!tenantMapApproved(mapType)) return true;
      const previousSectionStatus = tenantProjectSectionStatuses.location;
      tenantCreativeImages.map_approvals = { ...(tenantCreativeImages.map_approvals || {}), [mapType]: false };
      // The section approval required every map's flag — dropping one inside an
      // approved section must drop the section too, same as any other mutation.
      if (typeof releaseLocationSectionApproval === 'function') releaseLocationSectionApproval();
      if (!(await saveMapPreviewState())) {
        tenantCreativeImages.map_approvals = { ...(tenantCreativeImages.map_approvals || {}), [mapType]: true };
        if (previousSectionStatus === 'approved' && typeof applySectionStatuses === 'function') {
          applySectionStatuses({ location: previousSectionStatus });
        }
        renderLocationWorkflowState();
        return false;
      }
      toast('تم إلغاء اعتماد الخريطة');
      // Re-selecting remounts the live map on the released frame so editing
      // can resume right away.
      if (tenantSelectedMapType === mapType) selectMapPreviewView(mapType);
      renderMapPreviewGallery(true);
      renderLocationWorkflowState();
      return true;
    }

    // Shared gate for every path that would alter an approved raster.
    function mapApprovalBlocksEdit(mapType, approving = false) {
      if (tenantMapApprovalBusy(mapType) && !approving) {
        toast(WFT('map.approval_busy', 'الخريطة قيد الاعتماد'));
        return true;
      }
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
      if (tenantMapApproved(tenantSelectedMapType) || tenantMapApprovalBusy(tenantSelectedMapType)) return false;
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
      noteMapRenderVersion(mapType, data);
      if (mapViewportAdjustable(mapType) && (tenantCreativeImages.map_viewport_overrides || {})[mapType]) return;
      if (data.zooms && data.zooms[mapType] !== undefined)
        tenantCreativeImages.map_zooms = { ...(tenantCreativeImages.map_zooms || {}), [mapType]: data.zooms[mapType] };
      if (data.centers && data.centers[mapType] !== undefined)
        tenantCreativeImages.map_centers = { ...(tenantCreativeImages.map_centers || {}), [mapType]: data.centers[mapType] };
    }

