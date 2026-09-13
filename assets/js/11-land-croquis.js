/* 11-land-croquis.js - index.html lines 18626-20143, shared global scope, classic scripts in order */

    async function extractTenantCroquisData(targetKey = 'land_documents_files') {
      const input = document.querySelector('#tenantProjectForm [data-key="land_documents_files"]');
      const projectContextKeys = [
        'project_name', 'project_type', 'project_subtype', 'project_stage', 'location_address', 'location_detail',
        'location_lat', 'location_lng', 'location_polygon', 'main_roads', 'secondary_roads',
        'nearby_landmarks', 'nearby_landmarks_data', 'city', 'district', 'city_landmarks', 'catchment_areas',
        'population_density', 'population_density_source', 'land_area', 'built_area',
        'building_system', 'infrastructure', 'zoning_code', 'land_use', 'building_ratio_coverage',
        'setbacks', 'allowed_uses', 'regulatory_constraints'
      ];
      const projectContext = {};
      projectContextKeys.forEach(key => {
        const field = document.querySelector('#tenantProjectForm [data-key="' + key + '"]');
        const raw = field ? field.value : tenantProjectData[key];
        projectContext[key] = raw && typeof raw === 'object' ? raw : String(raw || '').trim();
      });
      tenantProjectData = { ...tenantProjectData, ...projectContext };
      const files = Array.from(input?.files || []).slice(0, 2);
      let uploaded = [];
      if (files.length) uploaded = await uploadTenantProjectFileInput(input, targetKey);
      if (!files.length && Array.isArray(tenantProjectData[targetKey + '_file_meta'])) {
        uploaded = tenantProjectData[targetKey + '_file_meta'];
      }
      const documents = (Array.isArray(uploaded) ? uploaded : []).map((file, index) => ({
        key: 'land_document',
        fileId: file.id,
        filename: files[index]?.name || file.originalName || ('مستند ' + (index + 1)),
        mimeType: files[index]?.type || file.mimeType || ''
      })).filter(document => document.fileId);
      if (!documents.length) {
        toast('يرجى رفع الكروكي، والرخصة إذا كانت متوفرة، داخل الخانة أولًا');
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
      showLoader('تحليل الرخصة والكروكي معًا', 'جاري تحليل الملفين واستخراج التنظيم والاتجاهات والإحداثيات...', 10);
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
          regulation_text: regulationText || fallbackText
        };
      });
    }

    function collectSurveyDirections() {
      return Array.from(document.querySelectorAll('#surveyDirectionsPanel tbody tr')).map(row => ({
        direction: row.dataset.direction || '',
        regulation_text: row.querySelector('[data-direction-field="regulation_text"]')?.value?.trim() || '',
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
        '<div class="survey-directions-table-wrap"><table class="survey-directions-table"><thead><tr><th>الاتجاه</th><th>بموجب التنظيم</th></tr></thead><tbody></tbody></table></div>';
      const tbody = panel.querySelector('tbody');
      rows.forEach(row => {
        const tr = document.createElement('tr');
        tr.dataset.direction = row.direction;
        tr.innerHTML = '<td>' + escapeHtml(row.label) + '</td>' +
          '<td><textarea data-direction-field="regulation_text" rows="2" placeholder="بطول ... يحده ...">' + escapeHtml(row.regulation_text || '') + '</textarea></td>';
        tr.querySelector('textarea').addEventListener('input', syncSurveyDirections);
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
        'secondary_roads', 'nearby_landmarks', 'nearby_landmarks_data', 'city_landmarks',
        'catchment_areas', 'population_density', 'population_density_source', 'land_area',
        'built_area', 'building_system', 'infrastructure', 'location_polygon'
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
        tenantProjectData = { ...tenantProjectData, ...fields, secondary_roads: '' };
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
        tenantProjectData = { ...tenantProjectData, ...fields, secondary_roads: '' };
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
        await saveProjectAsDraftNow(true);
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
        tenantProjectData = { ...tenantProjectData, ...formData, secondary_roads: '' };
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
        return '<div class="map-road-label' + (tenantRoadEditMode ? ' editable' : '') + '" data-road-label="' + escapeHtml(path.name) + '" style="left:' + x.toFixed(3) + '%;top:' + y.toFixed(3) + '%;font-size:' + (13 * scale).toFixed(1) + 'px;padding:' + (4 * scale).toFixed(1) + 'px ' + (8 * scale).toFixed(1) + 'px"' +
          (tenantRoadEditMode ? ' onpointerdown="startAccessRoadLabelDrag(event,decodeURIComponent(\'' + encodedName + '\'))"' : '') + '>' + escapeHtml(path.name) + deleteAction + '</div>';
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
        const marker = '<div class="map-place-marker' + (tenantCatchmentEditMode ? ' editable' : '') + '" data-catchment-marker="' + escapeHtml(item.name) + '" style="left:' + markerPoint[0].toFixed(3) + '%;top:' + markerPoint[1].toFixed(3) + '%"' +
          (tenantCatchmentEditMode ? ' onpointerdown="startCatchmentMarkerDrag(event,decodeURIComponent(\'' + encodedName + '\'))"' : '') + '>' + index + '</div>';
        const label = '<div class="map-place-label' + (tenantCatchmentEditMode ? ' editable' : '') + '" data-catchment-label="' + escapeHtml(item.name) + '" style="left:' + x.toFixed(3) + '%;top:' + y.toFixed(3) + '%;font-size:12px;padding:3px 7px"' +
          (tenantCatchmentEditMode ? ' onpointerdown="startCatchmentLabelDrag(event,decodeURIComponent(\'' + encodedName + '\'))"' : '') + '>' + escapeHtml(item.name) + '</div>';
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
        const marker = '<div class="map-place-marker' + (tenantLandmarksEditMode ? ' editable' : '') + '" data-landmark-marker="' + escapeHtml(item.name) + '" style="left:' + markerPoint[0].toFixed(3) + '%;top:' + markerPoint[1].toFixed(3) + '%"' +
          (tenantLandmarksEditMode ? ' onpointerdown="startLandmarksMarkerDrag(event,decodeURIComponent(\'' + encodedName + '\'))"' : '') + '>' + (index + 1) + '</div>';
        const label = '<div class="map-place-label' + (tenantLandmarksEditMode ? ' editable' : '') + '" data-landmark-label="' + escapeHtml(item.name) + '" style="left:' + x.toFixed(3) + '%;top:' + y.toFixed(3) + '%;font-size:12px;padding:3px 7px"' +
          (tenantLandmarksEditMode ? ' onpointerdown="startLandmarksLabelDrag(event,decodeURIComponent(\'' + encodedName + '\'))"' : '') + '>' + escapeHtml(item.name) + '</div>';
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
      const roadMarkup = showRoads ? roadPaths.map(path => {
        const roadPoints = (path.points || []).map(toPoint);
        if (roadPoints.length < 2) return '';
        const label = String(path.name || '');
        return '<polyline points="' + roadPoints.join(' ') + '" fill="none" stroke="rgba(105,73,35,.55)" stroke-width="1.8"></polyline>' +
          '<polyline points="' + roadPoints.join(' ') + '" fill="none" stroke="#d4a359" stroke-width="0.9"><title>' + escapeHtml(label) + '</title></polyline>';
      }).join('') : '';
      const roadPointMarkup = tenantRoadDrawingTarget ? tenantRoadDrawingTarget.points.map(point => {
        const [x, y] = toPoint(point).split(',');
        return '<circle cx="' + x + '%" cy="' + y + '%" r="1.15" fill="#fff" stroke="#6B1C23" stroke-width="0.45"></circle>';
      }).join('') : '';
      overlay.innerHTML = boundaryMarkup + roadMarkup + roadPointMarkup + pinMarkup;
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
        secondary_roads: 'شارع النرجس\nشارع الراكة\nطريق وادي الدواسر',
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
        land_area: '85,000 م²',
        built_area: '52,000 م²',
        building_system: 'نظام هيكل إنشائي خرساني مسلح، فيلات منفصلة بارتفاع 2-3 طوابق',
        infrastructure: 'كهرباء 11kV، مياه شرب من شبكة مياه الرياض، شبكة صرف صحي، إنترنت ألياف بصرية، نظام ري بالتنقيط',
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
        timeline_start_year: '2026',
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