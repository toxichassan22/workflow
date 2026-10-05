    /* ── Interactive Google Maps preview: mounts a live google.maps.Map inside
       #mapPreviewImage so pan/zoom is free and instant, while the generated
       raster stays the stored artifact — re-baked on demand (إعادة توليد) or
       automatically before the location section is approved. Falls back to
       the static image whenever the browser key or the JS API is missing. ── */

    let tenantInteractiveMap = null;
    let tenantInteractiveMapType = null;
    let tenantInteractiveProjection = null;
    let tenantInteractiveReadyPromise = null;
    let tenantInteractiveMountPromise = null;
    let tenantInteractiveMounted = false;
    let tenantInteractiveScriptLoaded = false;
    let tenantInteractiveSuppressIdle = false;
    let interactiveMountSeq = 0;
    let interactiveOverlayRaf = 0;
    // mapType: the live frame diverges from the raster stored on the server.
    const tenantInteractiveFrameDirty = {};

    // Ported from maps_service SATELLITE_*_STYLES / ACCESS_ROADMAP_STYLES so the
    // live basemap matches the generated raster closely enough for editing.
    const INTERACTIVE_STYLE_SATELLITE_LABELS = [
      { featureType: 'all', stylers: [{ saturation: -80 }, { lightness: -10 }] },
      { featureType: 'poi', stylers: [{ visibility: 'off' }] },
      { featureType: 'poi.business', stylers: [{ visibility: 'off' }] },
      { featureType: 'transit', stylers: [{ visibility: 'off' }] },
      { featureType: 'administrative', stylers: [{ visibility: 'off' }] },
      { featureType: 'road', elementType: 'geometry', stylers: [{ visibility: 'simplified' }] },
      { featureType: 'road.highway', elementType: 'labels', stylers: [{ visibility: 'on' }] },
      { featureType: 'road.highway', elementType: 'labels.text.fill', stylers: [{ color: '#ffffff' }] },
      { featureType: 'road.highway', elementType: 'labels.text.stroke', stylers: [{ color: '#333333' }, { weight: 3 }] },
      { featureType: 'road.arterial', elementType: 'labels', stylers: [{ visibility: 'on' }] },
      { featureType: 'road.arterial', elementType: 'labels.text.fill', stylers: [{ color: '#e0e0e0' }] },
      { featureType: 'road.arterial', elementType: 'labels.text.stroke', stylers: [{ color: '#333333' }, { weight: 2 }] },
      { featureType: 'road.local', elementType: 'labels', stylers: [{ visibility: 'off' }] }
    ];
    const INTERACTIVE_STYLE_SATELLITE_WIDE = [
      { featureType: 'all', stylers: [{ saturation: -70 }, { lightness: -5 }] },
      { featureType: 'poi', stylers: [{ visibility: 'off' }] },
      { featureType: 'poi.business', stylers: [{ visibility: 'off' }] },
      { featureType: 'transit', stylers: [{ visibility: 'off' }] },
      { featureType: 'administrative.land_parcel', stylers: [{ visibility: 'off' }] },
      { featureType: 'road.highway', elementType: 'labels', stylers: [{ visibility: 'on' }] },
      { featureType: 'road.highway', elementType: 'labels.text.fill', stylers: [{ color: '#ffffff' }] },
      { featureType: 'road.highway', elementType: 'labels.text.stroke', stylers: [{ color: '#444444' }, { weight: 3 }] },
      { featureType: 'road.arterial', elementType: 'labels', stylers: [{ visibility: 'on' }] },
      { featureType: 'road.arterial', elementType: 'labels.text.fill', stylers: [{ color: '#dddddd' }] },
      { featureType: 'road.arterial', elementType: 'labels.text.stroke', stylers: [{ color: '#444444' }, { weight: 2 }] },
      { featureType: 'road.local', elementType: 'labels', stylers: [{ visibility: 'off' }] }
    ];
    const INTERACTIVE_STYLE_ACCESS_ROADMAP = [
      { featureType: 'poi', stylers: [{ visibility: 'off' }] },
      { featureType: 'poi.business', stylers: [{ visibility: 'off' }] },
      { featureType: 'transit', stylers: [{ visibility: 'off' }] },
      { featureType: 'administrative.land_parcel', stylers: [{ visibility: 'off' }] },
      { featureType: 'road', elementType: 'labels', stylers: [{ visibility: 'off' }] },
      { featureType: 'road.highway', elementType: 'labels', stylers: [{ visibility: 'off' }] },
      { featureType: 'road.arterial', elementType: 'labels', stylers: [{ visibility: 'off' }] },
      { featureType: 'road.local', elementType: 'labels', stylers: [{ visibility: 'off' }] }
    ];

    function interactiveMapStylesFor(mapType) {
      if (mapType === 'access') return INTERACTIVE_STYLE_ACCESS_ROADMAP;
      if (mapType === 'catchment' || mapType === 'landmarks') return INTERACTIVE_STYLE_SATELLITE_WIDE;
      return INTERACTIVE_STYLE_SATELLITE_LABELS;
    }

    function interactiveMapActive() {
      return !!(tenantInteractiveMounted && tenantInteractiveMap && tenantInteractiveProjection);
    }

    // The frame the last raster bake actually rendered, persisted in creative
    // state so a reload can still tell a stored-but-unbaked override apart
    // from a baked one.
    function interactiveBakedFrame(mapType) {
      const frames = (tenantCreativeImages && tenantCreativeImages.map_baked_frames) || {};
      const frame = frames[mapType];
      return (frame && Number.isFinite(Number(frame.zoom))) ? frame : null;
    }

    function interactiveViewportSize(mapType) {
      if (!tenantInteractiveMounted || tenantInteractiveMapType !== mapType) return null;
      const holder = document.getElementById('mapLiveView');
      const width = Math.round(Number(holder?.clientWidth));
      const height = Math.round(Number(holder?.clientHeight));
      return width >= 64 && height >= 64 && width <= 2048 && height <= 2048 ? { width, height } : null;
    }

    function interactiveFrameSizeChanged(frame, size) {
      return !!size && (!frame || Number(frame.width) !== Number(size.width) || Number(frame.height) !== Number(size.height));
    }

    // Loads the Maps JS API once. Resolves false (and keeps the static-image
    // path) when no browser key is configured or the loader script fails. Only
    // success is memoized — a transient miss must not kill interactive mode
    // for the whole session, so failures clear the cached promise and the
    // next mount retries.
    function ensureInteractiveMapsApi() {
      if (tenantInteractiveReadyPromise) return tenantInteractiveReadyPromise;
      tenantInteractiveReadyPromise = (async () => {
        try {
          const cfg = await api('GET', '/api/maps/interactive-config');
          if (!cfg || !cfg.success || !cfg.key) {
            console.warn('[INTERACTIVE MAP] static fallback —', (cfg && (cfg.error || cfg.error_code)) || 'no config');
            tenantInteractiveReadyPromise = null;
            return false;
          }
          if (!(window.google && window.google.maps && window.google.maps.Map) && !tenantInteractiveScriptLoaded) {
            const lang = (typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang && window.WFI18n.getLang()) || 'ar';
            await new Promise((resolve, reject) => {
              const script = document.createElement('script');
              script.src = 'https://maps.googleapis.com/maps/api/js?key=' + encodeURIComponent(cfg.key)
                + '&loading=async&language=' + encodeURIComponent(lang) + '&region=SA';
              script.async = true;
              script.onload = () => { tenantInteractiveScriptLoaded = true; resolve(); };
              script.onerror = () => reject(new Error('maps js load failed'));
              document.head.appendChild(script);
            });
          }
          // loading=async fires onload long before the google.maps namespace
          // is populated (the api/js bootstrap still has to fetch its own
          // modules) — wait for it, then pull Map through importLibrary.
          for (let i = 0; i < 300 && !(window.google && window.google.maps); i++) {
            await new Promise(resolve => setTimeout(resolve, 50));
          }
          if (window.google && window.google.maps && window.google.maps.importLibrary) {
            try { await window.google.maps.importLibrary('maps'); } catch (e) { /* Map may already be there */ }
          }
          const ok = !!(window.google && window.google.maps && window.google.maps.Map);
          if (!ok) {
            console.warn('[INTERACTIVE MAP] static fallback — maps namespace unavailable');
            tenantInteractiveReadyPromise = null;
          }
          return ok;
        } catch (error) {
          console.warn('[INTERACTIVE MAP]', error);
          tenantInteractiveReadyPromise = null;
          return false;
        }
      })();
      return tenantInteractiveReadyPromise;
    }

    function meterInteractiveMapLoad(mapType) {
      // One Dynamic Maps load bills per map instance; pans and zooms after that
      // are free. Best-effort metering — a failed post must not break the map.
      try {
        api('POST', '/api/maps/interactive-load', {
          mapType,
          draftId: tenantProjectData && tenantProjectData.draftId,
          presentationId: tenantPresentationId || null
        }).catch(() => undefined);
      } catch (e) { /* metering is best-effort */ }
    }

    function mountInteractiveMap(mapType, lat, lng, zoom) {
      const box = document.getElementById('mapPreviewImage');
      const holder = document.getElementById('mapLiveView');
      if (!box || !holder || !(window.google && window.google.maps && window.google.maps.Map)) return false;
      // An approved map is a fixed raster — the live view never mounts over it.
      if (tenantMapApproved(mapType)) return false;
      const clampedZoom = Math.max(8, Math.min(20, Number(zoom) || 17));
      const options = {
        center: { lat: Number(lat), lng: Number(lng) },
        zoom: clampedZoom,
        minZoom: 8,
        maxZoom: 20,
        mapTypeId: mapType === 'access' ? 'roadmap' : 'satellite',
        styles: interactiveMapStylesFor(mapType),
        disableDefaultUI: true,
        zoomControl: true,
        fullscreenControl: false,
        // cooperative: a stray wheel pass scrolls the page instead of zooming;
        // zoom needs Ctrl+wheel and panning needs a real drag (two fingers on
        // touch) — the map only catches deliberate gestures.
        gestureHandling: 'cooperative',
        // Whole-number zooms only: the Static Maps API bakes integer zooms, so a
        // fractional live frame could never be reproduced exactly at bake time.
        isFractionalZoomEnabled: false,
        tilt: 0,
        clickableIcons: false,
        keyboardShortcuts: false,
        backgroundColor: '#f4f6f8'
      };
      if (!Number.isFinite(options.center.lat) || !Number.isFinite(options.center.lng)) return false;
      tenantInteractiveSuppressIdle = { lat: options.center.lat, lng: options.center.lng, zoom: clampedZoom };
      if (!tenantInteractiveMap) {
        holder.style.display = 'block';
        tenantInteractiveMap = new google.maps.Map(holder, options);
        // A transparent OverlayView exposes the container-pixel projection the
        // DOM overlays (boundary, roads, labels) already position themselves with.
        tenantInteractiveProjection = new google.maps.OverlayView();
        tenantInteractiveProjection.onAdd = function () {};
        tenantInteractiveProjection.draw = function () {};
        tenantInteractiveProjection.setMap(tenantInteractiveMap);
        tenantInteractiveMap.addListener('click', event => {
          if (event && event.latLng) dispatchTenantMapPoint(event.latLng.lat(), event.latLng.lng());
        });
        tenantInteractiveMap.addListener('idle', interactiveMapFrameChanged);
        tenantInteractiveMap.addListener('bounds_changed', positionInteractiveOverlaySoon);
        meterInteractiveMapLoad(mapType);
      } else {
        tenantInteractiveMap.setOptions(options);
        tenantInteractiveMap.setCenter(options.center);
        tenantInteractiveMap.setZoom(clampedZoom);
      }
      tenantInteractiveMapType = mapType;
      tenantInteractiveMounted = true;
      // The stored raster is exactly 16:9, so pinning the box ratio keeps the
      // live map measurable even before the backdrop image loads.
      box.style.aspectRatio = '16 / 9';
      holder.style.display = 'block';
      google.maps.event.trigger(tenantInteractiveMap, 'resize');
      evaluateInteractiveDirtyAtMount(mapType, options.center.lat, options.center.lng, clampedZoom);
      return true;
    }

    // Restored drafts carry overrides without saying whether they were ever
    // baked; a missing baked record is treated as dirty so the next approval
    // re-bakes once and self-heals. Truly legacy drafts (no baked record for
    // any map and no stored override) predate the divergence entirely — there
    // map_centers still is the raster's frame, so it seeds the record instead
    // of forcing a bake. An override with no baked record is the opposite
    // case: the raster was never rendered at the stored frame, and seeding it
    // as "baked" would let an approval freeze the stale auto-fitted image.
    function evaluateInteractiveDirtyAtMount(mapType, lat, lng, zoom) {
      const allBaked = (tenantCreativeImages && tenantCreativeImages.map_baked_frames) || {};
      const overrides = (tenantCreativeImages && tenantCreativeImages.map_viewport_overrides) || {};
      if (!Object.keys(allBaked).length && !overrides[mapType]) {
        tenantCreativeImages.map_baked_frames = {
          ...allBaked,
          [mapType]: { zoom, lat, lng }
        };
      }
      if (!overrides[mapType]) {
        tenantInteractiveFrameDirty[mapType] = false;
      } else {
        const baked = interactiveBakedFrame(mapType);
        tenantInteractiveFrameDirty[mapType] = !baked
          || Math.abs(Number(baked.lat) - lat) > 1e-6
          || Math.abs(Number(baked.lng) - lng) > 1e-6
          || Number(baked.zoom) !== Math.round(Number(zoom));
      }
      if (interactiveFrameSizeChanged(interactiveBakedFrame(mapType), interactiveViewportSize(mapType))) {
        tenantInteractiveFrameDirty[mapType] = true;
      }
      syncInteractiveFrameDirtyHint();
    }

    function unmountInteractiveMap() {
      const holder = document.getElementById('mapLiveView');
      if (holder) holder.style.display = 'none';
      tenantInteractiveMounted = false;
      tenantInteractiveMapType = null;
    }

    // Full reset for a new project/draft or a re-analyzed location: pending
    // mounts are voided and every dirty record belongs to the old site.
    function resetInteractiveMapState() {
      interactiveMountSeq += 1;
      unmountInteractiveMap();
      Object.keys(tenantInteractiveFrameDirty).forEach(key => delete tenantInteractiveFrameDirty[key]);
      syncInteractiveFrameDirtyHint();
    }

    // Called by selectMapPreviewView once the preview state is known. Mounts
    // (or re-frames) the live map when the API is usable; resolves whether the
    // live map ended up driving the preview. A failed mount retries itself a
    // few times — the Maps loader races slow networks, and without the retry
    // the preview would sit on the static image (whose pans cost a regen)
    // until the user happened to reselect the map.
    function mountInteractivePreview(mapType, lat, lng, zoom, retryAttempt) {
      // Approved maps render only the certified raster — skip the API load and
      // the retry loop entirely.
      if (tenantMapApproved(mapType)) return Promise.resolve(false);
      const attempt = Number(retryAttempt) || 0;
      const seq = ++interactiveMountSeq;
      const finish = mounted => {
        if (!mounted
          && seq === interactiveMountSeq
          && tenantSelectedMapType === mapType
          && !interactiveMapActive()
          && !tenantMapApproved(mapType)
          && attempt < 4) {
          setTimeout(() => {
            if (interactiveMapActive() || tenantSelectedMapType !== mapType || tenantMapApproved(mapType)) return;
            mountInteractivePreview(mapType, lat, lng, zoom, attempt + 1);
          }, 1200 + attempt * 800);
        }
        return mounted;
      };
      tenantInteractiveMountPromise = ensureInteractiveMapsApi().then(ok => {
        if (!ok || seq !== interactiveMountSeq) return finish(false);
        if (tenantSelectedMapType !== mapType || !tenantMapPreviewState || tenantMapApproved(mapType)) return false;
        const mounted = mountInteractiveMap(mapType, lat, lng, zoom);
        if (!mounted) return finish(false);
        // The live map is always a clean editable base: every drawable item is
        // repainted by the DOM overlay, so the flags never depend on which
        // raster variant the preview fell back to.
        tenantMapPreviewState.usesEditableBase = true;
        tenantMapPreviewState.live = true;
        renderTenantMapPolygonOverlay();
        updateTenantMapInteractionState();
        return true;
      });
      return tenantInteractiveMountPromise;
    }

    // Edit modes call this instead of the raster path: it waits for the live
    // map to mount on the wanted type, or returns false so the caller keeps
    // the static-image fallback.
    async function ensureInteractivePreview(mapType) {
      if (interactiveMapActive() && tenantInteractiveMapType === mapType) return true;
      if (!(await ensureInteractiveMapsApi())) return false;
      if (tenantSelectedMapType !== mapType) selectMapPreviewView(mapType);
      try { await (tenantInteractiveMountPromise || Promise.resolve(false)); } catch (e) { /* fall through */ }
      return interactiveMapActive() && tenantInteractiveMapType === mapType;
    }

    function interactiveMapClientToLatLng(clientX, clientY) {
      const projection = tenantInteractiveProjection && tenantInteractiveProjection.getProjection
        ? tenantInteractiveProjection.getProjection() : null;
      const holder = document.getElementById('mapLiveView');
      if (!projection || !holder || !(window.google && window.google.maps)) return null;
      const rect = holder.getBoundingClientRect();
      if (!rect.width || !rect.height) return null;
      const point = new google.maps.Point(clientX - rect.left, clientY - rect.top);
      const ll = projection.fromContainerPixelToLatLng(point);
      return ll ? [ll.lat(), ll.lng()] : null;
    }

    function interactiveMapLatLngToPercent(lat, lng) {
      const projection = tenantInteractiveProjection && tenantInteractiveProjection.getProjection
        ? tenantInteractiveProjection.getProjection() : null;
      const holder = document.getElementById('mapLiveView');
      if (!projection || !holder || !(window.google && window.google.maps)) return null;
      const px = projection.fromLatLngToContainerPixel(new google.maps.LatLng(Number(lat), Number(lng)));
      if (!px) return null;
      const w = holder.clientWidth;
      const h = holder.clientHeight;
      if (!w || !h) return null;
      return (px.x / w * 100).toFixed(3) + ',' + (px.y / h * 100).toFixed(3);
    }

    // The overlay must track the live map while it pans/zooms. bounds_changed
    // fires per animation frame, so the re-render is coalesced through rAF.
    function positionInteractiveOverlaySoon() {
      if (interactiveOverlayRaf) return;
      interactiveOverlayRaf = requestAnimationFrame(() => {
        interactiveOverlayRaf = 0;
        renderTenantMapPolygonOverlay();
      });
    }

    // Settle handler: mirror the live frame into the stored viewport state so
    // the next raster bake renders exactly what is on screen. Every generated
    // map honours a manual viewport, so a real divergence records the override
    // and the approval then freezes the frame the client actually framed.
    function interactiveMapFrameChanged() {
      const map = tenantInteractiveMap;
      if (!map || !tenantInteractiveMounted || !tenantMapPreviewState) return;
      // An approved map never mounts live — an idle queued before the
      // approval-time unmount must not touch its frame or its flag.
      if (tenantMapApproved(tenantInteractiveMapType)) return;
      const center = map.getCenter();
      if (!center) return;
      const lat = center.lat();
      const lng = center.lng();
      const zoom = Number(map.getZoom());
      tenantMapPreviewState.lat = lat;
      tenantMapPreviewState.lng = lng;
      if (Number.isFinite(zoom)) tenantMapPreviewState.zoom = zoom;
      renderTenantMapPolygonOverlay();
      const mapType = tenantInteractiveMapType;
      if (!mapViewportAdjustable(mapType)) return;
      // An approved section is frozen: exploring never mutates its frame.
      if (tenantProjectSectionStatuses && tenantProjectSectionStatuses.location === 'approved') return;
      // The first idle after a programmatic mount/reframe is not a user pan —
      // but a gesture that landed before that settle already moved the frame,
      // so only a frame matching the mount target counts as the mount echo.
      if (tenantInteractiveSuppressIdle) {
        const expected = tenantInteractiveSuppressIdle;
        tenantInteractiveSuppressIdle = null;
        if (Math.abs(Number(expected.lat) - lat) < 1e-6
            && Math.abs(Number(expected.lng) - lng) < 1e-6
            && Math.round(Number(expected.zoom)) === Math.round(zoom)) return;
      }
      recordInteractiveFrame(mapType, lat, lng, zoom);
    }

    // Writes one observed frame (idle settle or an explicit sync before an
    // approval click) into the stored viewport state. Kept separate so the
    // approve path can pull the live camera synchronously — idle is debounced
    // by Google, and a click landing first would read stale map_centers.
    function recordInteractiveFrame(mapType, lat, lng, zoom) {
      const roundedZoom = Math.round(Number.isFinite(zoom) ? zoom : 0);
      if (!roundedZoom) return;
      // Idle also fires on tile loads and viewport fits with no gesture at all —
      // a frame identical to what is already recorded is not user intent, so it
      // must not mint a viewport override or flip the dirty flag.
      const recordedCenter = (tenantCreativeImages.map_centers || {})[mapType];
      const recordedZoom = (tenantCreativeImages.map_zooms || {})[mapType];
      const size = interactiveViewportSize(mapType);
      if (recordedCenter && recordedZoom === roundedZoom
          && Math.abs(Number(recordedCenter.lat) - lat) < 1e-6
          && Math.abs(Number(recordedCenter.lng) - lng) < 1e-6
          && !interactiveFrameSizeChanged(recordedCenter, size)
          && !interactiveFrameSizeChanged(interactiveBakedFrame(mapType), size)) return;
      tenantCreativeImages.map_zooms = { ...(tenantCreativeImages.map_zooms || {}), [mapType]: roundedZoom };
      tenantCreativeImages.map_centers = { ...(tenantCreativeImages.map_centers || {}), [mapType]: { lat, lng, ...(size || {}) } };
      const baked = interactiveBakedFrame(mapType);
      const mapView = (typeof MAP_PREVIEW_VIEW_DEFS !== 'undefined' ? MAP_PREVIEW_VIEW_DEFS : [])
        .find(item => item.mapType === mapType);
      const mapGenerated = !!(mapView && typeof mapPreviewIsGenerated === 'function' && mapPreviewIsGenerated(mapView));
      // With a baked frame the divergence is exact. Without one the mount-time
      // evaluation already decided (a generated raster with an override but no
      // baked record mounts dirty so its next approval re-bakes) — that verdict
      // stands, while a never-generated map has nothing to diverge from.
      const diverged = interactiveFrameSizeChanged(baked, size) || (baked
        ? (baked.zoom !== roundedZoom
          || Math.abs(Number(baked.lat) - lat) > 1e-6
          || Math.abs(Number(baked.lng) - lng) > 1e-6)
        : (mapGenerated && tenantInteractiveFrameDirty[mapType] === true));
      tenantInteractiveFrameDirty[mapType] = diverged;
      // The override flag means "the user picked this frame": mint it on real
      // divergence, on a map with no baked frame yet, or keep one already set —
      // but never on a stray idle that re-landed on the baked frame.
      if (diverged || !baked || (tenantCreativeImages.map_viewport_overrides || {})[mapType]) {
        tenantCreativeImages.map_viewport_overrides = {
          ...(tenantCreativeImages.map_viewport_overrides || {}),
          [mapType]: true
        };
      }
      // Approval certifies the baked raster frame — a live camera that has
      // drifted off it is no longer what was approved.
      if (diverged
          && tenantCreativeImages.map_approvals && tenantCreativeImages.map_approvals[mapType]) {
        tenantCreativeImages.map_approvals = { ...tenantCreativeImages.map_approvals, [mapType]: false };
      }
      syncInteractiveFrameDirtyHint();
      renderLocationWorkflowState();
      // The framed view (and any approval a divergence just released) must
      // survive a reload — mark the draft dirty so the next save carries it.
      tenantProjectData.tenantCreativeImages = tenantCreativeImages;
      triggerAutoSaveDraft();
    }

    // Synchronous pull of the live camera into the recorded frame state.
    // Approval paths call this first: the idle listener only runs once Google
    // settles, so a click fired right after the last pan would otherwise bake
    // (or skip baking against) the pre-pan frame.
    function syncInteractiveLiveFrame() {
      const map = tenantInteractiveMap;
      if (!map || !tenantInteractiveMounted || !tenantInteractiveMapType) return;
      const mapType = tenantInteractiveMapType;
      if (tenantMapApproved(mapType)) return;
      const center = map.getCenter && map.getCenter();
      const zoom = map.getZoom && map.getZoom();
      if (!center) return;
      const lat = center.lat();
      const lng = center.lng();
      if (tenantMapPreviewState) {
        tenantMapPreviewState.lat = lat;
        tenantMapPreviewState.lng = lng;
        if (Number.isFinite(Number(zoom))) tenantMapPreviewState.zoom = zoom;
      }
      if (!mapViewportAdjustable(mapType)) return;
      if (tenantProjectSectionStatuses && tenantProjectSectionStatuses.location === 'approved') return;
      recordInteractiveFrame(mapType, lat, lng, zoom);
    }

    // The raster bake result for ONE map type: updates the persisted
    // rendered-frame record and clears the dirty flag when the live view
    // already matches what was just rendered. Recompose responses can carry
    // frames for maps they did not re-render, so callers scope this to the
    // map type the request actually baked — no sibling's record is touched.
    function noteInteractiveBakedFrame(mapType, zoom, center) {
      if (zoom === undefined && !center) return;
      const prev = interactiveBakedFrame(mapType) || {};
      const frame = {
        zoom: Number.isFinite(Number(zoom)) ? Number(zoom) : prev.zoom,
        lat: center && Number.isFinite(Number(center.lat)) ? Number(center.lat) : prev.lat,
        lng: center && Number.isFinite(Number(center.lng)) ? Number(center.lng) : prev.lng,
        width: center && Number.isFinite(Number(center.width)) ? Number(center.width) : prev.width,
        height: center && Number.isFinite(Number(center.height)) ? Number(center.height) : prev.height
      };
      tenantCreativeImages.map_baked_frames = {
        ...(tenantCreativeImages.map_baked_frames || {}),
        [mapType]: frame
      };
      // A fresh bake replaces the artifact the approval certified — the
      // approve flow re-sets the flag itself after its bake lands.
      if (tenantCreativeImages.map_approvals && tenantCreativeImages.map_approvals[mapType]) {
        tenantCreativeImages.map_approvals = { ...tenantCreativeImages.map_approvals, [mapType]: false };
      }
      // Dirty is live-camera-vs-baked: compare against the recorded live frame
      // (map_centers/map_zooms — what the interactive map would remount at),
      // not tenantMapPreviewState, which is the *static* raster's frame and is
      // equal to the just-baked value by definition. The old comparison wiped a
      // real dirty flag whenever a recompose response landed after a pan, and
      // flagged a false one right after the approval bake itself.
      const liveCenter = (tenantCreativeImages.map_centers || {})[mapType];
      const liveZoom = (tenantCreativeImages.map_zooms || {})[mapType];
      const liveKnown = liveCenter
        && Number.isFinite(Number(liveCenter.lat)) && Number.isFinite(Number(liveCenter.lng))
        && Number.isFinite(Number(liveZoom));
      if (liveKnown && Number.isFinite(Number(frame.zoom))) {
        tenantInteractiveFrameDirty[mapType] =
          Math.abs(Number(frame.lat) - Number(liveCenter.lat)) > 1e-6
          || Math.abs(Number(frame.lng) - Number(liveCenter.lng)) > 1e-6
          || Number(frame.zoom) !== Math.round(Number(liveZoom))
          || interactiveFrameSizeChanged(frame, liveCenter.width && liveCenter.height ? liveCenter : null);
      } else {
        tenantInteractiveFrameDirty[mapType] = false;
      }
      syncInteractiveFrameDirtyHint();
    }

    function syncInteractiveFrameDirtyHint() {
      const hint = document.getElementById('mapFrameDirtyHint');
      if (!hint) return;
      const dirty = Object.keys(tenantInteractiveFrameDirty).some(key => tenantInteractiveFrameDirty[key]);
      hint.style.display = dirty ? 'block' : 'none';
      if (dirty) {
        hint.textContent = (typeof WFT === 'function')
          ? WFT('location.map_frame_unsaved', 'إطار المعاينة المعروض لم يُحفظ في صورة الخريطة المخزنة')
          : 'إطار المعاينة المعروض لم يُحفظ في صورة الخريطة المخزنة';
      }
    }

    // Bakes every dirty live frame into its stored raster before the location
    // section is approved: what the client saw on the map is what the approval
    // freezes. Called from approveSectionWithVersion — a failed bake leaves the
    // flag set and never blocks the approval itself.
    async function settleInteractiveMapFrames() {
      // Same idle-race fix as approveTenantMap: section approval must settle
      // against the camera on screen right now, not the last idle's record.
      if (typeof syncInteractiveLiveFrame === 'function') syncInteractiveLiveFrame();
      const dirty = Object.keys(tenantInteractiveFrameDirty).filter(key => tenantInteractiveFrameDirty[key]);
      for (const mapType of dirty) {
        await regenerateMapPreview(mapType);
      }
    }
