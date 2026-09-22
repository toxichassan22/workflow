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

    const TENANT_PROJECT_HIDDEN_FIELDS = new Set(['plot_number', 'population_density', 'catchment_areas', 'location_data_fetched_at']);
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