/* 11-land-croquis.js - index.html lines 18626-20143, shared global scope, classic scripts in order */

    async function extractTenantCroquisData(targetKey = 'land_documents_files') {
      const input = document.querySelector('#tenantProjectForm [data-key="land_documents_files"]');
      const projectContextKeys = [
        'project_name', 'project_type', 'project_subtype', 'project_stage', 'location_address', 'location_detail',
        'location_lat', 'location_lng', 'location_polygon', 'main_roads',
        'nearby_landmarks', 'nearby_landmarks_data', 'city', 'district', 'city_landmarks', 'catchment_areas',
        'population_density', 'population_density_source', 'zoning_code', 'land_use', 'building_ratio_coverage',
        'setbacks', 'allowed_uses', 'regulatory_constraints'
      ];
      const projectContext = {};
      projectContextKeys.forEach(key => {
        const field = document.querySelector('#tenantProjectForm [data-key="' + key + '"]');
        const raw = field ? field.value : tenantProjectData[key];
        projectContext[key] = raw && typeof raw === 'object' ? raw : String(raw || '').trim();
      });
      tenantProjectData = { ...tenantProjectData, ...projectContext };
      const files = Array.from(input?.files || []).slice(0, LAND_DOCUMENTS_MAX);
      let uploaded = [];
      if (files.length) uploaded = await uploadTenantProjectFileInput(input, targetKey);
      if (!files.length && Array.isArray(tenantProjectData[targetKey + '_file_meta'])) {
        uploaded = tenantProjectData[targetKey + '_file_meta'];
      }
      const documents = (Array.isArray(uploaded) ? uploaded : []).map((file, index) => ({
        key: 'land_document',
        fileId: file.id,
        filename: file.originalName || file.name || files[index]?.name || ('مستند ' + (index + 1)),
        mimeType: file.mimeType || files[index]?.type || ''
      })).filter(document => document.fileId);
      if (!documents.length) {
        toast(WFT('land.docs.required', 'يرجى رفع الكروكي والرخصة وأي مستندات مساندة داخل الخانة أولًا'));
        return;
      }
      const locationInput = document.querySelector('#tenantProjectForm [data-key="location_address"]');
      const locationLatInput = document.querySelector('#tenantProjectForm [data-key="location_lat"]');
      const locationLngInput = document.querySelector('#tenantProjectForm [data-key="location_lng"]');
      const locationLink = String(locationInput?.value || tenantProjectData.location_address || '').trim();
      if (!isGoogleMapsUrl(locationLink)) {
        toast('اكتب رابط Google Maps صحيحًا في قسم الموقع والخرائط قبل بدء التحليل');
        return;
      }
      const locationReady = await geocodeTenantLocationLink(
        locationInput, locationLatInput, locationLngInput, false
      );
      if (!locationReady || !locationLatInput?.value || !locationLngInput?.value) {
        toast('تعذر استخراج إحداثيات الموقع من رابط Google Maps؛ لم يبدأ تحليل الاشتراطات');
        return;
      }
      projectContext.location_address = locationLink;
      projectContext.location_lat = String(locationLatInput.value || '').trim();
      projectContext.location_lng = String(locationLngInput.value || '').trim();
      tenantProjectData = { ...tenantProjectData, ...projectContext };
      clearLandAnalysisFailure();
      clearLandAnalysisDiagnostics();
      showLoader(
        WFT('land.docs.analyzing', 'تحليل الكروكي والمستندات معًا'),
        WFT('land.docs.analyzing_wait', 'جاري تحليل الملفات واستخراج التنظيم والاتجاهات والإحداثيات...'),
        10);
      try {
        updateLoaderProgress(25, 'جاري تجهيز بيانات الموقع والخرائط وملفات الاشتراطات كاملة...');
        let res = await api('POST', '/api/extract-croquis', {
          documents,
          draftId: tenantProjectData.draftId,
          projectName: projectContext.project_name,
          projectType: projectContext.project_type,
          projectStage: projectContext.project_stage,
          city: projectContext.city || '',
          zoningCode: projectContext.zoning_code,
          landUse: projectContext.land_use,
          locationAddress: projectContext.location_address,
          locationLat: projectContext.location_lat,
          locationLng: projectContext.location_lng,
          siteContext: slimLandAnalysisSiteContext(projectContext),
          includeMapContext: true
        });
        if (res && res.jobId && !res.extractedData) {
          const jobId = res.jobId;
          updateLoaderProgress(35, res.message || 'بدأ التحليل في الخلفية...');
          const started = Date.now();
          while (Date.now() - started < 12 * 60 * 1000) {
            await new Promise(resolve => setTimeout(resolve, 2500));
            res = await api('GET', '/api/extract-croquis/' + encodeURIComponent(jobId));
            const jobStatus = String(res && res.status || '');
            updateLoaderProgress(
              jobStatus === 'running' ? 55 : 40,
              (res && res.message) || 'جاري تحليل المستندات والاشتراطات...'
            );
            if (jobStatus === 'completed' || jobStatus === 'failed' || (res && res.extractedData) || (res && res.failureReason)) break;
            if (!res || res.failureReason === 'job_not_found') break;
          }
        }
        updateLoaderProgress(55, 'تم تجهيز الموقع والخرائط؛ جاري قراءة المستندات والاشتراطات...');
        if (res.success && res.extractedData) {
          const data = res.extractedData;
          const documentProcessing = res.documentProcessing || data.document_processing || [];
          tenantProjectData.land_document_processing = documentProcessing;
          const renderedPdfCount = documentProcessing.filter(item => item.mode === 'pdf_rendered').length;
          if (renderedPdfCount) toast('تم تجهيز ' + renderedPdfCount + ' ملف PDF بصريًا وإرساله إلى AI كصور صفحات.');
          const extractedFields = buildExtractedLandFieldData(data);
          Object.entries(extractedFields).forEach(([k, v]) => {
            if (v !== undefined && v !== null && v !== '') {
              tenantProjectData[k] = v;
              const inp = document.querySelector('#tenantProjectForm [data-key="' + k + '"]');
              if (inp && typeof v !== 'object') {
                inp.value = k === 'allowed_uses' ? stripLandUseStatusFromText(v).text : v;
              }
            }
          });
          tenantProjectData.land_documents_analysis = data;
          tenantProjectData.land_documents_analysis_status = 'needs_review';
          if (Array.isArray(data.warnings) && data.warnings.length) {
            toast('اكتمل التحليل مع ملاحظات: ' + data.warnings.join(' | '));
          }
          tenantProjectData.survey_coordinates = data.survey_coordinates || [];
          tenantProjectData.directions_table = extractedFields.directions_table || data.directions_table || data.parcels?.[0]?.directions || {};
          storeLandDocumentAnalysis(data);
          renderSurveyCoordinates(data.survey_coordinates || []);
          renderSurveyDirections(tenantProjectData.directions_table);
          showLandAnalysisDiagnostics(data);
          refreshAllowedUsesStatusNote();
          const appliedCount = Object.values(extractedFields)
            .filter(value => value !== undefined && value !== null && value !== '' && typeof value !== 'object').length;
          updateLoaderProgress(100, 'تم تحليل الملفات وتحديث ' + appliedCount + ' حقلًا. راجع الحقول والاتجاهات ثم اعتمد البيانات.');
          toast('تم التحليل وتحديث ' + appliedCount + ' حقلًا. راجع النتائج قبل الاعتماد.');
          clearLandAnalysisFailure();
          triggerAutoSaveDraft();
        } else {
          // A rejected extraction leaves every field untouched, so say that explicitly —
          // otherwise it is indistinguishable from "re-analysis did nothing". The reason goes on
          // screen and stays there: in a toast it cleared itself before it could be read, which is
          // why these failures were only ever visible in the browser console.
          const reason = res.error || 'تعذر تحليل ملفات الأرض والكروكي والرخصة';
          showLandAnalysisFailure(reason, res.providerError);
          updateLoaderProgress(100, 'لم يتم تحديث أي حقل: ' + reason);
          toast('لم يتم تحديث أي حقل — التفصيل أسفل خانة الملفات');
          console.warn('[LAND ANALYSIS] rejected', res.failureReason || 'unknown', res);
        }
      } catch (err) {
        const reason = 'حدث خطأ أثناء تحليل الملفات: ' + (err.message || err);
        showLandAnalysisFailure(reason);
        updateLoaderProgress(100, 'فشل التحليل ولم يتغير أي حقل.');
        toast(reason);
        console.warn('[LAND ANALYSIS] exception', err);
      } finally {
        hideLoader('اكتمل تحليل ملفات الأرض');
      }
    }

    // The analysis payload stays hidden while its table-read diagnostics remain visible near the upload box.
    function storeLandDocumentAnalysis(analysis = {}) {
      const analysisInput = document.getElementById('landDocumentsAnalysisData');
      if (analysisInput) {
        analysisInput.value = (Array.isArray(analysis.parcels) && analysis.parcels.length)
          ? JSON.stringify({
            parcels: analysis.parcels,
            conflicts: analysis.conflicts || [],
            source_priority: analysis.source_priority || [],
            extraction_diagnostics: analysis.extraction_diagnostics || {},
            document_processing: analysis.document_processing || []
          })
          : '';
      }
      const host = document.getElementById('landDocumentsAnalysisPreview');
      if (host) {
        host.innerHTML = '';
        host.style.display = 'none';
      }
    }

    function collectSurveyCoordinates() {
      return Array.from(document.querySelectorAll('#surveyCoordinatesPanel tbody tr')).map(row => ({
        parcel_id: row.querySelector('[data-coordinate-field="parcel_id"]')?.value?.trim() || '',
        point: row.querySelector('[data-coordinate-field="point"]')?.value?.trim() || '',
        eastings: row.querySelector('[data-coordinate-field="eastings"]')?.value?.trim() || '',
        northings: row.querySelector('[data-coordinate-field="northings"]')?.value?.trim() || '',
        source: row.querySelector('[data-coordinate-field="source"]')?.value?.trim() || 'regulation_table'
      })).filter(row => row.parcel_id || row.point || row.eastings || row.northings);
    }

    function syncSurveyCoordinates() {
      const rows = collectSurveyCoordinates();
      tenantProjectData.survey_coordinates = rows;
      const hidden = document.getElementById('surveyCoordinatesData');
      if (hidden) hidden.value = JSON.stringify(rows);
      triggerAutoSaveDraft();
    }

    function renderSurveyCoordinates(rows) {
      const panel = document.getElementById('surveyCoordinatesPanel');
      if (!panel) return;
      const parsed = parseStoredLandTable(rows);
      const hadValue = rows !== null && rows !== undefined && rows !== '';
      if (hadValue && parsed === null) return;
      const normalized = Array.isArray(parsed) ? parsed : [];
      panel.innerHTML = '<div class="survey-coordinates-head">' +
        '<strong class="survey-coordinates-title">جدول الإحداثيات</strong></div>' +
        '<div class="survey-coordinates-table-wrap"><table class="survey-coordinates-table"><thead><tr><th>رقم القطعة</th><th>رقم النقطة</th><th>الشرقيات</th><th>الشماليات</th></tr></thead><tbody></tbody></table></div>';
      const tbody = panel.querySelector('tbody');
      if (!normalized.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="survey-coordinates-empty">سيظهر جدول الإحداثيات بعد تحليل المستندات.</td></tr>';
      }
      const addRow = row => {
        tbody.querySelector('.survey-coordinates-empty')?.closest('tr')?.remove();
        const tr = document.createElement('tr');
        const cell = (field, value, placeholder) => '<td><input type="text" data-coordinate-field="' + field + '" value="' + escapeHtml(value ?? '') + '" placeholder="' + placeholder + '" style="width:100%;min-width:110px"></td>';
        tr.innerHTML = cell('parcel_id', row?.parcel_id || row?.parcelId || '', 'P-1') +
          cell('point', row?.point || row?.point_number || '', '1') +
          cell('eastings', row?.eastings ?? row?.easting ?? '', '510180.849') +
          cell('northings', row?.northings ?? row?.northing ?? '', '2939234.840');
        tr.querySelectorAll('input').forEach(input => input.addEventListener('input', syncSurveyCoordinates));
        tbody.appendChild(tr);
      };
      normalized.forEach(addRow);
      const hidden = document.getElementById('surveyCoordinatesData');
      if (hidden) hidden.value = JSON.stringify(normalized);
      tenantProjectData.survey_coordinates = normalized;
    }

    function normalizeSurveyDirections(value) {
      const labels = { north: 'شمال', south: 'جنوب', east: 'شرق', west: 'غرب' };
      const aliases = { 'شمال': 'north', 'جنوب': 'south', 'شرق': 'east', 'غرب': 'west' };
      const parsed = parseStoredLandTable(value);
      const rows = Array.isArray(parsed) ? parsed : Object.entries(parsed || {}).map(([direction, data]) => ({ direction, ...(data || {}) }));
      const byDirection = Object.fromEntries(rows.map(row => {
        const key = String(row.direction || row.key || '').toLowerCase();
        return [aliases[key] || key, row];
      }));
      return Object.entries(labels).map(([direction, label]) => {
        const row = byDirection[direction] || {};
        const regulationText = row.regulation_text || row.regulation || row.text || '';
        const fallbackText = [
          row.boundary_length_m ?? row.length_m ? 'بطول ' + (row.boundary_length_m ?? row.length_m) + 'م' : '',
          row.street_name || row.street || row.boundary || '',
          row.uses || row.notes || ''
        ].filter(Boolean).join(' — ');
        return {
          direction,
          label,
          regulation_text: regulationText || fallbackText,
          setback: row.setback ?? row.setback_m ?? ''
        };
      });
    }

    function collectSurveyDirections() {
      return Array.from(document.querySelectorAll('#surveyDirectionsPanel tbody tr')).map(row => ({
        direction: row.dataset.direction || '',
        regulation_text: row.querySelector('[data-direction-field="regulation_text"]')?.value?.trim() || '',
        setback: row.querySelector('[data-direction-field="setback"]')?.value?.trim() || '',
        source: 'regulation_table'
      }));
    }

    function syncSurveyDirections() {
      const rows = collectSurveyDirections();
      tenantProjectData.directions_table = rows;
      const hidden = document.getElementById('directionsTableData');
      if (hidden) hidden.value = JSON.stringify(rows);
      triggerAutoSaveDraft();
    }

    function renderSurveyDirections(value) {
      const panel = document.getElementById('surveyDirectionsPanel');
      if (!panel) return;
      const hadValue = value !== null && value !== undefined && value !== '';
      if (hadValue && parseStoredLandTable(value) === null) return;
      const rows = normalizeSurveyDirections(value);
      panel.innerHTML = '<strong class="survey-directions-title">جدول الاتجاهات</strong>' +
        '<div class="survey-directions-table-wrap"><table class="survey-directions-table"><thead><tr><th>الاتجاه</th><th>بموجب التنظيم</th><th>الارتداد</th></tr></thead><tbody></tbody></table></div>';
      const tbody = panel.querySelector('tbody');
      rows.forEach(row => {
        const tr = document.createElement('tr');
        tr.dataset.direction = row.direction;
        tr.innerHTML = '<td>' + escapeHtml(row.label) + '</td>' +
          '<td><textarea data-direction-field="regulation_text" rows="2" placeholder="بطول ... يحده ...">' + escapeHtml(row.regulation_text || '') + '</textarea></td>' +
          '<td><input type="text" data-direction-field="setback" value="' + escapeHtml(row.setback ?? '') + '" placeholder="5"></td>';
        tr.querySelectorAll('textarea, input').forEach(control => control.addEventListener('input', syncSurveyDirections));
        tbody.appendChild(tr);
      });
      const hidden = document.getElementById('directionsTableData');
      if (hidden) hidden.value = JSON.stringify(rows);
      tenantProjectData.directions_table = rows;
    }

    function toggleApproveCroquisData() {
      const inputs = document.querySelectorAll('#tenantProjectForm [data-section="land_croquis"] input, #tenantProjectForm [data-section="land_croquis"] select, #tenantProjectForm [data-section="land_croquis"] textarea');
      const btn = document.getElementById('approveCroquisBtn');
      if (!btn) return;
      const isApproved = btn.classList.contains('approved');
      if (!isApproved) {
        const errors = validateLandCroquisClientFields();
        if (errors.length > 0) {
          toast(errors[0].message);
          const firstInput = document.querySelector('#tenantProjectForm [data-key="' + errors[0].key + '"]');
          if (firstInput) {
            firstInput.focus();
            firstInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
          return;
        }
        inputs.forEach(inp => {
          if (!['approved_financial_area', 'approved_floor_count', 'approved_coverage_ratio'].includes(inp.dataset.key)) {
            inp.disabled = true;
          }
        });
        btn.classList.add('approved');
        btn.style.background = '#2e7d32';
        btn.textContent = 'تم الاعتماد (اضغط لفتح التعديل)';
        tenantProjectData.croquis_approved = true;
        toast('تم اعتماد بيانات الأرض والكروكي وقفل النسخة المعتمدة');
      } else {
        inputs.forEach(inp => inp.disabled = false);
        btn.classList.remove('approved');
        btn.style.background = '';
        btn.textContent = 'اعتماد وقفل البيانات المعتمدة';
        tenantProjectData.croquis_approved = false;
        toast('تم فتح التعديل على بيانات الأرض والكروكي');
      }
      triggerAutoSaveDraft();
    }

    async function generateTenantSiteAnalysis() {
      const input = document.querySelector('#tenantProjectForm [data-key="site_analysis"]');
      if (!input) return;
      const formData = await collectTenantFormData();
      tenantProjectData = { ...tenantProjectData, ...formData };
      if (!tenantProjectData.location_lat || !tenantProjectData.location_lng) {
        toast('حلل رابط الموقع أولًا قبل تشغيل تحليل AI');
        return;
      }
      const analysisKeys = [
        'project_name', 'project_type', 'project_subtype', 'project_stage', 'location_address', 'location_detail',
        'location_maps_link', 'maps_link', 'location_lat', 'location_lng', 'city', 'district', 'main_roads',
        'nearby_landmarks', 'nearby_landmarks_data', 'city_landmarks',
        'catchment_areas', 'population_density', 'population_density_source', 'location_polygon'
      ];
      const analysisProjectData = {};
      analysisKeys.forEach(key => {
        if (tenantProjectData[key] !== undefined && tenantProjectData[key] !== null && tenantProjectData[key] !== '') {
          analysisProjectData[key] = tenantProjectData[key];
        }
      });
      showLoader('تحليل الموقع بالذكاء الاصطناعي', 'جاري تجهيز بيانات الموقع...', 5);
      try {
        updateLoaderProgress(35, 'جاري إرسال بيانات الموقع إلى GLM...');
        const data = await api('POST', '/api/site-analysis', { projectData: analysisProjectData });
        if (data.success && data.analysis) {
          const filledFields = data.fields && typeof data.fields === 'object' ? data.fields : {};
          const clientOnlyFields = new Set(['approved_financial_area', 'approved_financial_area_sqm', 'approved_floor_count', 'approved_floors', 'approved_coverage_ratio']);
          const safeFilledFields = Object.fromEntries(Object.entries(filledFields).filter(([key]) => !clientOnlyFields.has(key)));
          if (Array.isArray(data.warnings) && data.warnings.length) {
            toast('اكتمل التحليل، لكن تعذر جلب بعض المعالم: ' + data.warnings.join(' | '));
          }
          tenantProjectData = { ...tenantProjectData, ...safeFilledFields };
          Object.entries(safeFilledFields).forEach(([key, value]) => {
            const fieldInput = document.querySelector('#tenantProjectForm [data-key="' + key + '"]');
            if (fieldInput && value !== null && value !== undefined) fieldInput.value = value;
          });
          refreshLocationTables();
          updateLoaderProgress(90, 'تم استلام التحليل والبيانات المكملة...');
          tenantProjectData.site_analysis = data.analysis;
          tenantProjectData.site_analysis_approved = false;
          input.value = data.analysis;
          input.readOnly = false;
          triggerAutoSaveDraft();
          updateLoaderProgress(100, 'اكتمل تحليل الموقع. راجعه ثم اعتمده أو عدّله.');
        } else if (data.error) {
          toast(data.error);
        }
      } catch (error) {
        console.warn('[SITE ANALYSIS AI] unavailable', error);
        toast(error?.message ? 'تعذر تشغيل تحليل AI للموقع: ' + error.message : 'تعذر تشغيل تحليل AI للموقع');
      } finally {
        hideLoader('اكتمل تحليل الموقع');
      }
    }

    async function approveTenantSiteAnalysis() {
      const input = document.querySelector('#tenantProjectForm [data-key="site_analysis"]');
      const value = (input?.value || '').trim();
      if (!value) {
        toast('شغّل تحليل الموقع أولًا');
        return;
      }
      tenantProjectData.site_analysis = value;
      tenantProjectData.site_analysis_approved = true;
      if (input) input.readOnly = false;
      await saveProjectAsDraft(true);
      toast('تم اعتماد تحليل الموقع');
    }

    let tenantSiteAnalysisRequest = null;

    function confirmTenantCoordinates() {
      const lat = Number(tenantProjectData?.location_lat);
      const lng = Number(tenantProjectData?.location_lng);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        toast('حدد الإحداثيات أولًا من رابط Google Maps أو بالإدخال اليدوي');
        return;
      }
      tenantProjectData.location_coordinates_confirmed = true;
      tenantProjectData.location_coordinates_source = tenantProjectData.location_coordinates_source || 'google_maps_link';
      const hidden = document.getElementById('tenantCoordinatesConfirmed');
      if (hidden) hidden.value = 'true';
      const status = document.getElementById('tenantCoordinatesStatus');
      if (status) status.innerHTML = '<span>تم اعتماد الإحداثيات:</span> ' + lat.toFixed(6) + ', ' + lng.toFixed(6);
      const button = document.getElementById('confirmTenantCoordinatesButton');
      if (button) { button.textContent = 'تم اعتماد الإحداثيات'; button.classList.add('success'); }
      triggerAutoSaveDraft();
    }

    async function analyzeTenantSite() {
      if (tenantSiteAnalysisRequest) return tenantSiteAnalysisRequest;
      tenantSiteAnalysisRequest = analyzeTenantSiteOnce().finally(() => {
        tenantSiteAnalysisRequest = null;
      });
      return tenantSiteAnalysisRequest;
    }

    async function analyzeTenantSiteOnce() {
      const formData = await collectTenantFormData();
      tenantProjectData = { ...tenantProjectData, ...formData };
      if (!tenantProjectData.draftId) tenantProjectData.draftId = crypto.randomUUID();
      const currentAddress = (tenantProjectData.location_address || '').trim();
      if (window._lastAnalyzedAddress && window._lastAnalyzedAddress !== currentAddress) {
        tenantProjectData.location_analysis_approved = false;
      }
      const locationLink = [tenantProjectData.location_address, tenantProjectData.location_maps_link, tenantProjectData.maps_link]
        .find(value => isGoogleMapsUrl(value)) || '';
      if (!locationLink) {
        toast('أدخل رابط Google Maps صحيحًا فقط لموقع المشروع');
        return;
      }
      showLoader('جاري تحليل الموقع', 'يتم جلب بيانات الموقع والطرق والمعالم فقط...');
      try {
        const data = await apiWithTimeout('POST', '/api/analyze-site', {
          projectData: tenantProjectData,
          presentationId: tenantPresentationId,
          force: true,
          generateMaps: false
        }, 90000, 'انتهت مهلة تحليل بيانات الموقع؛ لم يتم توليد الخرائط بعد.');
        if (!data || !data.success) {
          toast((data && data.error) || 'تعذر تحليل الموقع');
          return;
        }
        const fields = data.fields || {};
        tenantNearbyLandmarks = (Array.isArray(data.landmarks) ? data.landmarks : [])
          .map(item => ({ ...item, row_source: item.row_source || 'ai' }));
        tenantProjectData.nearby_landmarks_data = tenantNearbyLandmarks;
        tenantProjectData.main_roads_data = (Array.isArray(data.roads) && data.roads.length
          ? data.roads
          : parseLocationFieldText('main_roads', fields.main_roads || ''))
          .map(item => ({ ...item, row_source: 'ai' }));
        tenantProjectData.city_landmarks_data = (Array.isArray(data.cityLandmarks) ? data.cityLandmarks : [])
          .map(item => ({ ...item, row_source: item.row_source || 'ai' }));
        const mapHint = document.getElementById('mapPreviewHint');
        if (mapHint && Number.isFinite(Number(data.lat)) && Number.isFinite(Number(data.lng))) {
          const sourceLabel = data.source === 'maps_link' ? 'رابط Google Maps' : 'بيانات الموقع';
          const boundaryLabel = data.boundary && data.boundary.status === 'verified_building'
            ? 'تم العثور على حدود مبنى مطابقة.'
            : 'حدود المبنى تحتاج مراجعة.';
          mapHint.innerHTML = '<span>تم تحديد النقطة من</span> <span>' + sourceLabel + '</span>: ' + Number(data.lat).toFixed(6) + ', ' + Number(data.lng).toFixed(6) + '. <span>' + boundaryLabel + '</span>';
          mapHint.style.display = 'block';
        }
        tenantProjectData = { ...tenantProjectData, ...fields };
        tenantProjectData.location_coordinates_confirmed = false;
        tenantProjectData.location_coordinates_source = data.source || 'site_analysis';
        tenantProjectData.location_analysis_approved = false;
        releaseLocationSectionApproval();
        tenantProjectData.location_analysis_approved_at = '';
        setLocationDataFetchedAt();
        Object.entries(fields).forEach(([key, value]) => {
          const input = document.querySelector('#tenantProjectForm [data-key="' + key + '"]');
          if (input && value !== null && value !== undefined) input.value = value;
        });
        applyCityDistrictToForm(fields.city || tenantProjectData.city, fields.district || tenantProjectData.district, true);
        refreshLocationTables();
        window._lastAnalyzedAddress = (tenantProjectData.location_address || '').trim();
        if (fields.location_polygon_source !== 'cleared' && fields.location_polygon) {
          tenantMapPolygonPoints = parseTenantPolygonPoints(fields.location_polygon);
          syncTenantLocationPolygon();
        } else {
          tenantMapPolygonPoints = [];
          tenantMapDraftPolygonPoints = [];
          tenantMapPolygonMode = false;
          tenantMapPinMode = false;
          tenantMapDraftPinHistory = [];
          resetTenantRoadModes();
          resetTenantCatchmentMode();
          resetTenantLandmarksEditMode();
          renderTenantMapPolygonOverlay();
        }
        tenantCreativeImages = tenantCreativeImages || {};
        tenantProjectData = { ...tenantProjectData, ...fields };
        renderLocationWorkflowState();
        triggerAutoSaveDraft();
        // The reason used to live only in a toast that vanished in about two seconds, which made
        // the failure impossible to read, let alone report. Keep it on screen instead.
        const reasons = [data.landmarksWarning, data.cityLandmarksWarning].filter(Boolean);
        const warningBox = document.getElementById('siteAnalysisWarnings');
        if (warningBox) {
          warningBox.hidden = !reasons.length;
          warningBox.innerHTML = reasons.length
            ? '<div>تعذر جلب المعالم:</div>' + reasons.map(reason =>
              '<div style="margin-top:4px">• ' + escapeHtml(String(reason)) + '</div>').join('')
            : '';
        }
        toast(reasons.length
          ? 'تم تحليل بيانات الموقع، لكن تعذر جلب بعض المعالم'
          : 'تم تحليل رابط الموقع وتعبئة البيانات دون توليد خرائط');
      } catch (error) {
        console.error('[SITE ANALYSIS]', error);
        toast('حدث خطأ أثناء تحليل الموقع');
      } finally {
        hideLoader();
      }
    }

    const MAP_PREVIEW_VIEW_DEFS = [
      { mapType: 'overview', title: 'خريطة الأرض / المبنى', keys: ['##MAP_OVERVIEW##', '##MAP_OVERVIEW_SATELLITE##', '##MAP_OVERVIEW_ROADMAP##'], editableKeys: ['##MAP_OVERVIEW_EDITABLE##', '##MAP_OVERVIEW_SATELLITE_EDITABLE##', '##MAP_OVERVIEW_ROADMAP_EDITABLE##'] },
      { mapType: 'access', title: 'خريطة الطرق الرئيسية', keys: ['##MAP_ACCESS##', '##MAP_ACCESS_SATELLITE##', '##MAP_ACCESS_ROADMAP##'], editableKeys: ['##MAP_ACCESS_EDITABLE##', '##MAP_ACCESS_SATELLITE_EDITABLE##', '##MAP_ACCESS_ROADMAP_EDITABLE##'] },
      { mapType: 'catchment', title: 'خريطة المنطقة', keys: ['##MAP_CATCHMENT##', '##MAP_CATCHMENT_SATELLITE##', '##MAP_CATCHMENT_ROADMAP##'], editableKeys: ['##MAP_CATCHMENT_EDITABLE##', '##MAP_CATCHMENT_SATELLITE_EDITABLE##', '##MAP_CATCHMENT_ROADMAP_EDITABLE##'] },
      { mapType: 'landmarks', title: 'خريطة المعالم', keys: ['##MAP_LANDMARKS##', '##MAP_LANDMARKS_SATELLITE##', '##MAP_LANDMARKS_ROADMAP##'], editableKeys: ['##MAP_LANDMARKS_EDITABLE##', '##MAP_LANDMARKS_SATELLITE_EDITABLE##', '##MAP_LANDMARKS_ROADMAP_EDITABLE##'] }
    ];

    function renderMapPreviewGallery() {
      const forceFull = arguments[0] === true;
      const gallery = document.getElementById('mapPreviewGallery');
      if (!gallery) return;
      const approvals = tenantCreativeImages.map_approvals || {};
      const views = MAP_PREVIEW_VIEW_DEFS;
      const existingCards = gallery.querySelectorAll('.tenant-map-preview-card');
      if (!forceFull && existingCards.length === views.length) {
        existingCards.forEach(card => {
          card.classList.toggle('active', card.dataset.mapSelect === tenantSelectedMapType);
        });
        return;
      }
      const cards = views.map(view => {
        const url = mapPreviewStoredUrl(view);
        const visible = mapPreviewIsVisible(view, approvals);
        const approvedWithoutFile = !!approvals[view.mapType] && !url;
        const status = !visible
          ? (tenantProjectData?.location_analysis_approved
            ? 'بانتظار اعتماد خريطة الأرض / المبنى'
            : 'بانتظار اعتماد تحليل الموقع')
          : (approvals[view.mapType] ? (approvedWithoutFile ? 'معتمدة بدون ملف' : 'معتمدة') : (url ? 'بانتظار الاعتماد' : 'غير مولدة'));
        const preview = visible && url
          ? '<img src="' + escapeHtml(withCacheBust(url)) + '" alt="' + escapeHtml(view.title) + '" style="display:block;width:100%;aspect-ratio:16/9;object-fit:contain;object-position:center center;background:#f4f6f8;border-radius:8px;">'
          : '<div class="tenant-map-preview-placeholder" style="display:flex;align-items:center;justify-content:center;aspect-ratio:16/9;background:#f4f6f8;border-radius:8px;color:var(--muted);text-align:center;padding:12px;">' + escapeHtml(status === 'غير مولدة' ? 'لم تُولد الخريطة' : status) + '</div>';
        return '<figure class="tenant-map-preview-card' + (tenantSelectedMapType === view.mapType ? ' active' : '') + '" data-map-select="' + escapeHtml(view.mapType) + '" style="margin:0;border:1px solid var(--line);border-radius:12px;padding:8px;background:#fff;">' +
          '<figcaption style="display:flex;justify-content:space-between;gap:8px;font-weight:700;font-size:12px;color:var(--p);margin-bottom:6px;"><span>' + escapeHtml(view.title) + '</span><span style="color:var(--muted);font-weight:600;">' + status + '</span></figcaption>' + preview + '</figure>';
      }).join('');
      gallery.innerHTML = cards;
      if (typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en') {
        window.WFI18n.autoTranslate(gallery);
      }
      gallery.querySelectorAll('[data-map-select]').forEach(card => {
        card.addEventListener('click', () => selectMapPreviewView(card.dataset.mapSelect));
      });
      gallery.style.display = cards ? 'grid' : 'none';
    }

    function withCacheBust(url) {
      if (!url) return url;
      const raw = String(url);
      const hashIndex = raw.indexOf('#');
      const withoutHash = hashIndex >= 0 ? raw.slice(0, hashIndex) : raw;
      const hash = hashIndex >= 0 ? raw.slice(hashIndex) : '';
      const queryIndex = withoutHash.indexOf('?');
      const path = queryIndex >= 0 ? withoutHash.slice(0, queryIndex) : withoutHash;
      const params = queryIndex >= 0
        ? withoutHash.slice(queryIndex + 1).split('&').filter(part => part && !/^t=\d+$/.test(part))
        : [];
      params.push('t=' + Date.now());
      return path + '?' + params.join('&') + hash;
    }

    function selectMapPreviewView(mapType) {
      const view = MAP_PREVIEW_VIEW_DEFS.find(item => item.mapType === mapType);
      if (!view) return false;
      if (mapType !== 'overview') {
        tenantMapPolygonMode = false;
        tenantMapDraftPolygonPoints = [];
        tenantMapPinMode = false;
        tenantMapDraftPinHistory = [];
      }
      if (mapType !== 'access') resetTenantRoadModes();
      if (mapType !== 'catchment') resetTenantCatchmentMode();
      if (mapType !== 'landmarks') resetTenantLandmarksEditMode();
      tenantSelectedMapType = mapType;
      renderLocationWorkflowState();
      const placeholders = tenantCreativeImages.map_placeholders || {};
      const markedUrl = view.keys.map(key => placeholders[key]).find(Boolean);
      const editableUrl = view.editableKeys?.map(key => placeholders[key]).find(Boolean);
      const url = mapPreviewIsVisible(view) ? (editableUrl || markedUrl) : '';
      const previewBox = document.getElementById('mapPreviewImage');
      const image = previewBox?.querySelector('img');
      if (!url || !previewBox || !image) {
        if (previewBox) previewBox.style.display = 'none';
        if (image) image.removeAttribute('src');
        tenantMapPreviewState = null;
        renderTenantMapPolygonOverlay();
        return false;
      }
      image.onload = () => renderTenantMapPolygonOverlay();
      image.src = withCacheBust(url);
      image.alt = view.title;
      previewBox.style.display = 'block';
      // Clicks are converted against this state, so it must be the centre the server actually
      // rendered: the plot view is centred on the boundary, not on the site pin.
      const center = (tenantCreativeImages.map_centers || {})[mapType] || {};
      const lat = Number(center.lat ?? tenantCreativeImages.map_lat ?? tenantProjectData.location_lat);
      const lng = Number(center.lng ?? tenantCreativeImages.map_lng ?? tenantProjectData.location_lng);
      const zoom = Number((tenantCreativeImages.map_zooms || {})[mapType] || (tenantCreativeImages.map_zooms || {}).overview || 17);
      if (Number.isFinite(lat) && Number.isFinite(lng)) tenantMapPreviewState = { lat, lng, zoom, usesEditableBase: !!editableUrl };
      renderTenantMapPolygonOverlay();
      updateTenantMapInteractionState();
      previewBox.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return true;
    }

    async function saveMapPreviewState() {
      tenantProjectData.tenantCreativeImages = tenantCreativeImages;
      if (tenantPresentationId) {
        const resp = await api('PUT', '/api/presentations/' + encodeURIComponent(tenantPresentationId), {
          projectData: tenantProjectData,
          expectedRevision: tenantPresentationRevision
        });
        if (resp && resp.revision) {
          tenantPresentationRevision = Number(resp.revision) || tenantPresentationRevision;
        }
      } else if (tenantProjectData.draftId && typeof saveProjectAsDraftNow === 'function') {
        // Regenerating a map is an explicit user action. Persist the new image URL
        // immediately for drafts; otherwise reload restores the previous placeholder.
        // A failed save keeps the workspace but must be said, or the map looks
        // persisted while a reload quietly drops it.
        if (!(await saveProjectAsDraftNow(true))) toast(WFT('map.save_state_failed', 'تعذر حفظ حالة الخريطة على الخادم'));
      } else {
        triggerAutoSaveDraft();
      }
    }

    async function approveMapPreview(mapType) {
      const approvals = tenantCreativeImages.map_approvals || {};
      if (!tenantProjectData.location_analysis_approved) { toast('اعتماد تحليل الموقع مطلوب قبل اعتماد الخريطة'); return; }
      if (mapType !== 'overview' && !approvals.overview) { toast('اعتماد خريطة الأرض مطلوب أولًا'); return; }
      tenantCreativeImages.map_approvals = { ...approvals, [mapType]: true };
      await saveMapPreviewState();
      renderMapPreviewGallery(true);
      renderLocationWorkflowState();
      toast('تم اعتماد الخريطة');
    }

    async function unapproveMapPreview(mapType) {
      const approvals = tenantCreativeImages.map_approvals || {};
      tenantCreativeImages.map_approvals = { ...approvals, [mapType]: false };
      releaseLocationSectionApproval();
      await saveMapPreviewState();
      renderMapPreviewGallery(true);
      renderLocationWorkflowState();
      toast('تم إلغاء اعتماد الخريطة');
    }

    async function regenerateMapPreview(mapType) {
      if (!hasPermission('generate_maps')) { toast('لا تملك صلاحية توليد الخرائط'); return false; }
      const approvals = tenantCreativeImages.map_approvals || {};
      if (!tenantProjectData.location_analysis_approved) { toast('اعتماد تحليل الموقع مطلوب قبل توليد الخرائط'); return false; }
      if (mapType !== 'overview' && !approvals.overview) { toast('اعتماد خريطة الأرض مطلوب أولًا'); return false; }
      if (approvals[mapType]) { toast('ألغ اعتماد الخريطة قبل إعادة توليدها'); return false; }
      showLoader('جاري توليد الخريطة', '');
      try {
        Object.keys(LOCATION_TABLE_FIELDS).forEach(serializeLocationTable);
        const formData = await collectTenantFormData();
        tenantProjectData = { ...tenantProjectData, ...formData };
        tenantProjectData.location_analysis_approved = tenantProjectData.location_analysis_approved === true || tenantProjectData.location_analysis_approved === 'true';
        if (!tenantProjectData.draftId) tenantProjectData.draftId = crypto.randomUUID();
        const payload = slimMapProjectData(tenantProjectData);
        payload.location_analysis_approved = tenantProjectData.location_analysis_approved;
        payload.enabled_maps = [mapType];
        payload.draftId = tenantProjectData.draftId;
        payload.refresh_maps = true;
        const regenSeed = Date.now();
        payload.regen_seed = regenSeed;
        const data = await api('POST', '/api/generate-map-image', {
          projectData: payload,
          mapType,
          presentationId: tenantPresentationId,
          highlightSite: shouldHighlightTenantSite(),
          overviewApproved: !!approvals.overview,
          mapApproved: !!approvals[mapType],
          regenSeed
        });
        if (!data.success) {
          toast(data.error || 'تعذر إعادة توليد الخريطة');
          return false;
        }
        if (data.revision) {
          tenantPresentationRevision = Number(data.revision) || tenantPresentationRevision;
        }
        const nextPlaceholders = { ...(tenantCreativeImages.map_placeholders || {}) };
        MAP_PREVIEW_VIEW_DEFS.filter(view => view.mapType === mapType).forEach(view => {
          [...view.keys, ...(view.editableKeys || [])].forEach(key => { delete nextPlaceholders[key]; });
        });
        tenantCreativeImages.map_placeholders = { ...nextPlaceholders, ...(data.placeholders || {}) };
        tenantCreativeImages.map_zooms = { ...(tenantCreativeImages.map_zooms || {}), ...(data.zooms || {}) };
        tenantCreativeImages.map_centers = { ...(tenantCreativeImages.map_centers || {}), ...(data.centers || {}) };
        if (mapType === 'overview' && Array.isArray(data.sitePolygon) && data.sitePolygon.length >= 3) {
          tenantMapPolygonPoints = parseTenantPolygonPoints(data.sitePolygon);
          if (!['manual', 'cleared'].includes(tenantProjectData.location_polygon_source)) tenantProjectData.location_polygon_source = 'auto';
          syncTenantLocationPolygon();
        }
        if (mapType === 'landmarks') {
          tenantCreativeImages.map_landmarks = data.landmarks_matrix || data.landmarks || [];
          tenantProjectData.landmarks_matrix = tenantCreativeImages.map_landmarks;
          tenantProjectData.landmark_map_items = Array.isArray(data.landmarkMapItems) ? data.landmarkMapItems : data.landmarks || [];
          tenantCreativeImages.map_landmark_items = tenantProjectData.landmark_map_items;
          const positions = { ...(tenantProjectData.landmark_label_positions || {}) };
          tenantProjectData.landmark_map_items.forEach(item => {
            if (item?.name && Array.isArray(item.label_point) && !positions[item.name]) positions[item.name] = item.label_point;
          });
          tenantProjectData.landmark_label_positions = positions;
        }
        if (mapType === 'access') {
          tenantProjectData.access_roads_data = Array.isArray(data.accessRoads) ? data.accessRoads : [];
          tenantCreativeImages.map_access_roads = tenantProjectData.access_roads_data;
          const positions = { ...(tenantProjectData.access_road_label_positions || {}) };
          const sizes = { ...(tenantProjectData.access_road_label_sizes || {}) };
          tenantProjectData.access_roads_data.forEach(road => {
            if (road?.name && Array.isArray(road.label_point) && !positions[road.name]) positions[road.name] = road.label_point;
            if (road?.name && Number.isFinite(Number(road.label_scale)) && !sizes[road.name]) sizes[road.name] = Number(road.label_scale);
          });
          tenantProjectData.access_road_label_positions = positions;
          tenantProjectData.access_road_label_sizes = sizes;
        }
        if (mapType === 'catchment') {
          tenantProjectData.catchment_map_landmarks = Array.isArray(data.catchmentLandmarks) ? data.catchmentLandmarks : [];
          tenantCreativeImages.map_catchment_landmarks = tenantProjectData.catchment_map_landmarks;
          const positions = { ...(tenantProjectData.catchment_label_positions || {}) };
          tenantProjectData.catchment_map_landmarks.forEach(item => {
            if (item?.name && Array.isArray(item.label_point) && !positions[item.name]) positions[item.name] = item.label_point;
          });
          tenantProjectData.catchment_label_positions = positions;
        }
        tenantCreativeImages.maps_persisted = true;
        tenantCreativeImages.map_highlight_site = shouldHighlightTenantSite();
        tenantCreativeImages.map_approvals = { ...(tenantCreativeImages.map_approvals || {}), [mapType]: false };
        tenantCreativeImages.maps_signature = mapsSignature(tenantProjectData);
        setLocationDataFetchedAt();
        await saveMapPreviewState();
        renderMapPreviewGallery(true);
        renderLocationWorkflowState();
        selectMapPreviewView(mapType);
        toast('تم توليد الخريطة وأصبحت في انتظار الاعتماد');
        return true;
      } finally {
        hideLoader();
      }
    }

    let tenantMapPreviewRequest = null;

    function generateOverviewMap() {
      tenantSelectedMapType = 'overview';
      return previewProjectMap();
    }

    async function previewProjectMap() {
      if (tenantMapPreviewRequest) return tenantMapPreviewRequest;
      tenantMapPreviewRequest = regenerateMapPreview('overview').finally(() => {
        tenantMapPreviewRequest = null;
      });
      return tenantMapPreviewRequest;
    }

    async function previewProjectMapOnce() {
      return regenerateMapPreview('overview');
    }

