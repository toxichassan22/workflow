    const BEST_USE_EXPLORE_FIELDS = [
      'draftId', 'land_documents_files_file_ids', 'croquis_land_area', 'approved_financial_area',
      'approved_coverage_ratio', 'approved_floor_count', 'approved_floor_area_ratio',
      'building_ratio_coverage', 'setbacks', 'max_floors_height', 'boundary_lengths',
      'surrounding_streets', 'survey_coordinates', 'directions_table', 'location_address',
      'location_lat', 'location_lng', 'city', 'district', 'site_analysis', 'main_roads',
      'nearby_landmarks_data', 'city_landmarks_data', 'catchment_areas',
      'location_polygon', 'location_polygon_source', 'plot_number_croquis', 'plan_number', 'zoning_code'
    ];
    const BEST_USE_EXPLORE_JSON = {
      land_documents_files_file_ids: [], survey_coordinates: [], directions_table: [],
      nearby_landmarks_data: [], city_landmarks_data: [], location_polygon: []
    };
    const BEST_USE_EXPLORE_NUMBERS = new Set([
      'croquis_land_area', 'approved_financial_area', 'approved_coverage_ratio',
      'approved_floor_count', 'approved_floor_area_ratio', 'location_lat', 'location_lng'
    ]);
    const BEST_USE_EXPLORE_ARTIFACTS = ['regulations', 'priceScan', 'concepts', 'landDistribution', 'floorDistribution'];
    const BEST_USE_EXPLORE_DEPENDENCIES = {
      regulations: [], priceScan: ['regulations'], concepts: ['regulations', 'priceScan'],
      landDistribution: ['regulations', 'priceScan', 'concepts'],
      floorDistribution: ['regulations', 'priceScan', 'concepts', 'landDistribution']
    };
    let bestUseExploreBusy = false;
    let bestUseExploreTask = null;
    let bestUseExploreStage = 'concepts';
    let bestUseExploreDraftId = '';

    function bestUseActiveMode() { return tenantProjectData?.best_use_mode || 'guided'; }
    function bestUseExploreState() { return bestUseObject(tenantProjectData?.best_use_explore_data); }
    function bestUseExploreChat() { return bestUseObject(tenantProjectData?.best_use_explore_chat); }
    function bestUseArray(value) { return Array.isArray(value) ? value : []; }

    function bestUseExploreSourceSnapshot() {
      const snapshot = {};
      BEST_USE_EXPLORE_FIELDS.forEach(key => {
        const value = bestUseFieldValue(key);
        snapshot[key] = key in BEST_USE_EXPLORE_JSON ? bestUseDecoded(value, BEST_USE_EXPLORE_JSON[key])
          : BEST_USE_EXPLORE_NUMBERS.has(key) ? bestUseNumber(value) : String(value ?? '').trim().slice(0, 30000);
      });
      const maps = bestUseObject(bestUseObject(tenantProjectData?.tenantCreativeImages).map_placeholders);
      snapshot.maps = Object.fromEntries(['##MAP_OVERVIEW##', '##MAP_ACCESS##', '##MAP_CATCHMENT##', '##MAP_LANDMARKS##']
        .filter(key => maps[key]).map(key => [key, maps[key]]));
      snapshot.mode = bestUseActiveMode();
      return bestUseNormalizeMedia(snapshot);
    }

    function bestUseExploreSectionRequired() {
      const state = bestUseExploreState();
      return BEST_USE_EXPLORE_ARTIFACTS.some(name => state[name]?.id && !state[name].rejected);
    }

    function bestUseExploreCurrent(name, visited = []) {
      const state = bestUseExploreState();
      const artifact = state[name];
      if (visited.includes(name) || !artifact?.id || artifact.inputsChanged || artifact.rejected) return false;
      if (bestUseStable(bestUseExploreSourceSnapshot()) !== bestUseStable(bestUseNormalizeMedia(state.sourceSnapshot || {}))) return false;
      if (!BEST_USE_EXPLORE_DEPENDENCIES[name].every(key => bestUseExploreCurrent(key, [...visited, name]))) return false;
      if (['landDistribution', 'floorDistribution'].includes(name)
          && state.selectedConceptVersion !== state.concepts?.version) return false;
      return true;
    }

    function bestUseExploreApproved(name) {
      const artifact = bestUseExploreState()[name];
      return bestUseExploreCurrent(name) && artifact.approved === true
        && artifact.approvedContentHash === artifact.contentHash && artifact.approvedInputHash === artifact.inputHash;
    }

    function bestUseExploreSectionError() {
      if (!bestUseExploreSectionRequired()) return '';
      const state = bestUseExploreState();
      const required = ['priceScan', 'concepts', 'landDistribution', 'floorDistribution'];
      if (state.regulations?.requiresApproval) required.unshift('regulations');
      if (required.some(name => !state[name]?.id)) return WFT('best_use_explore.incomplete', 'مراحل الاستكشاف غير مكتملة.');
      if (required.some(name => !bestUseExploreCurrent(name))) return WFT('best_use_explore.inputs_changed', 'تغيّرت بيانات الأرض أو الموقع أو أدلة الاستكشاف.');
      return required.every(bestUseExploreApproved) ? '' : WFT('best_use_explore.approval_required', 'محتوى الاستكشاف غير معتمد بالكامل.');
    }

    function bestUseExploreMissing() {
      const source = bestUseExploreSourceSnapshot();
      const missing = [];
      if (!source.land_documents_files_file_ids.length) missing.push('croquis');
      if (!source.location_address || source.location_lat === null || source.location_lng === null
          || Math.abs(source.location_lat) > 90 || Math.abs(source.location_lng) > 180) missing.push('site_location');
      ['land_croquis', 'location'].forEach(key => { if (tenantProjectSectionStatuses?.[key] !== 'approved') missing.push(key); });
      ['croquis_land_area', 'approved_financial_area', 'approved_floor_count', 'approved_floor_area_ratio'].forEach(key => {
        if (!(source[key] > 0) || (key === 'approved_floor_count' && !Number.isInteger(source[key]))) missing.push(key);
      });
      if (!(source.approved_coverage_ratio > 0 && source.approved_coverage_ratio <= 100)) missing.push('approved_coverage_ratio');
      if (!source.setbacks) missing.push('setbacks');
      if (!source.city) missing.push('city');
      return missing;
    }

    function renderBestUseModeControls() {
      const select = document.getElementById('bestUseMode');
      if (!select) return;
      select.value = bestUseActiveMode();
      select.disabled = bestUseBusy || bestUseExploreBusy || tenantProjectSectionStatuses?.[BEST_USE_SECTION_KEY] === 'approved'
        || tenantProjectMode === 'presentation' || !hasPermission('create_presentation');
      const guided = document.getElementById('bestUseGuidedWorkspace');
      const explore = document.getElementById('bestUseExploreWorkspace');
      if (guided) guided.hidden = bestUseActiveMode() !== 'guided';
      if (explore) explore.hidden = bestUseActiveMode() !== 'explore';
    }

    function bestUseExploreUseLabel(value) {
      return bestUseOptionText(useTypes, value);
    }

    function bestUseExploreDecisionHtml(name) {
      const artifact = bestUseExploreState()[name];
      if (!artifact?.id) return '';
      const approved = bestUseExploreApproved(name);
      const locked = tenantProjectSectionStatuses?.[BEST_USE_SECTION_KEY] === 'approved';
      const disabled = bestUseExploreBusy || locked || !hasPermission('create_presentation')
        || tenantProjectMode === 'presentation' || (!approved && !bestUseExploreCurrent(name));
      const label = approved ? WFT('best_use.unapprove', 'الغاء الاعتماد')
        : name === 'floorDistribution' ? WFT('best_use.approve', 'اعتماد واستبدال المكونات') : WFT('best_use_explore.approve_content', 'اعتماد المحتوى');
      const status = !bestUseExploreCurrent(name) ? WFT('best_use.stale', 'تغيّرت المدخلات')
        : approved ? WFT('best_use.approved', 'معتمد') : WFT('best_use.pending', 'بانتظار الاعتماد');
      return '<div class="best-use-actions"><span class="best-use-status">' + escapeHtml(status) + '</span>'
        + '<button type="button" class="btn primary small" onclick="runBestUseExplore(\'decision\',{artifact:\'' + name
        + '\',decision:\'' + (approved ? 'unapproved' : 'approved') + '\'})" ' + (disabled ? 'disabled' : '') + '>' + label + '</button></div>';
    }

    function bestUseExplorePriceHtml(scan) {
      if (!scan?.id) return '';
      const missing = WFT('best_use_explore.price_missing', 'غير متوفر من دليل كافٍ');
      const headings = [WFT('best_use.use', 'الاستخدام'), WFT('best_use_explore.sale_rate', 'متوسط سعر البيع للمتر'),
        WFT('best_use_explore.rent_rate', 'متوسط الإيجار السنوي للمتر'), WFT('best_use_explore.samples', 'مشاهدات البيع / الإيجار'),
        WFT('best_use_explore.scope', 'النطاق الجغرافي')];
      const rows = bestUseArray(scan.table).map(row => '<tr>' + [bestUseExploreUseLabel(row.use),
        row.salePerSqm === null ? missing : bestUseFormat(row.salePerSqm),
        row.rentPerSqmYear === null ? missing : bestUseFormat(row.rentPerSqmYear),
        (row.metrics?.sale?.count || 0) + ' / ' + (row.metrics?.rent?.count || 0), [row.city, row.district].filter(Boolean).join('، ')]
        .map(value => '<td>' + escapeHtml(value) + '</td>').join('') + '</tr>').join('');
      const observations = bestUseArray(scan.observations).map(item => {
        const url = String(item.url || '');
        const safe = /^https:\/\//i.test(url);
        return '<article class="best-use-source"><p>' + escapeHtml(bestUseExploreUseLabel(item.use) + ' — '
          + bestUseFormat(item.value) + ' ' + item.currency + ' / ' + item.unit + ' / ' + item.period) + '</p>'
          + '<p>' + escapeHtml([item.city, item.district].filter(Boolean).join('، ')) + '</p>'
          + '<p>' + WFT('best_use_explore.listing_price', 'سعر منشور وليس متوسطًا مستقلًا') + '</p>'
          + '<p>' + WFT('best_use_explore.published', 'تاريخ نشر السعر') + ': '
          + escapeHtml(item.publishedAt || WFT('best_use_explore.unknown', 'غير محسوم')) + '</p>'
          + '<p>' + WFT('best_use_explore.retrieved', 'تاريخ الاسترجاع') + ': ' + escapeHtml(item.retrievedAt || '') + '</p>'
          + '<p>' + escapeHtml(item.excerpt || '') + '</p>'
          + (safe ? '<a href="' + escapeHtml(url) + '" target="_blank" rel="noopener noreferrer">'
            + WFT('best_use_explore.source', 'المصدر') + '</a>' : '') + '</article>';
      }).join('');
      return '<section class="best-use-price-scan"><h4>' + WFT('best_use_explore.prices_title', 'تقديرات من مصادر منشورة') + '</h4>'
        + '<div class="table-wrap"><table class="best-use-table"><thead><tr>' + headings.map(label => '<th>' + label + '</th>').join('')
        + '</tr></thead><tbody>' + rows + '</tbody></table></div>' + bestUseExploreDecisionHtml('priceScan')
        + '<details><summary>' + WFT('best_use_explore.price_evidence', 'أدلة الأسعار ونطاقها وتواريخها') + '</summary>' + observations + '</details></section>';
    }

    function bestUseExploreDistributionHtml(artifact) {
      if (!artifact?.id) return '<p class="tenant-hint">' + WFT('best_use.empty', 'لا يوجد توزيع مقترح.') + '</p>';
      const headings = [WFT('best_use.component', 'المكون'), WFT('best_use.use', 'الاستخدام'),
        WFT('best_use.allocated_footprint', 'الحصة الأرضية م²'), WFT('best_use.built_area', 'المساحة المبنية م²'),
        WFT('best_use.revenue_area', 'المساحة البيعية / التأجيرية م²'), WFT('best_use.investment_model', 'نموذج الاستفادة')];
      const rows = bestUseArray(artifact.components).map(row => '<tr>' + [row.name, bestUseExploreUseLabel(row.useType),
        bestUseFormat(row.footprintArea), bestUseFormat(row.builtArea), bestUseFormat(row.revenueArea),
        bestUseOptionText(investmentModels, row.investmentModel)].map(value => '<td>' + escapeHtml(value) + '</td>').join('') + '</tr>').join('');
      return '<h4>' + escapeHtml(artifact.title || '') + '</h4><div class="table-wrap"><table class="best-use-table"><thead><tr>'
        + headings.map(label => '<th>' + label + '</th>').join('') + '</tr></thead><tbody>' + rows + '</tbody></table></div>'
        + '<p class="best-use-warning">' + WFT('best_use_explore.planning_only', 'سيناريو تخطيطي لا يشمل التكاليف أو صافي العائد.') + '</p>'
        + '<p>' + escapeHtml(artifact.rationale || '') + '</p><p>' + escapeHtml(artifact.setbackExplanation || '') + '</p>'
        + bestUseArray(artifact.components).map(row => '<article class="best-use-source"><h5>' + escapeHtml(row.name) + '</h5><p>'
          + escapeHtml(row.reason || '') + '</p><p>' + escapeHtml(row.areaReason || '') + '</p><p>'
          + escapeHtml(row.revenueAreaBasis || '') + '</p>'
          + (bestUseArray(row.floorAllocations).length ? '<p>' + WFT('best_use_explore.floor_allocations', 'تخصيصات الأدوار') + ': '
            + bestUseArray(row.floorAllocations).map(item => bestUseFormat(item.floor) + ': ' + bestUseFormat(item.area)).join('، ') + '</p>' : '') + '</article>').join('')
        + bestUseRevenuePotentialHtml(artifact.revenuePotential);
    }

    function bestUseExploreMismatch(concept) {
      if (!concept) return '';
      const main = { residential: 'سكني', retail: 'تجاري', office: 'تجاري', entertainment: 'تجاري',
        hospitality: 'فندقي', industrial: 'صناعي ولوجستي', logistics: 'صناعي ولوجستي' };
      const types = bestUseDecoded(bestUseFieldValue('project_type'), []);
      const expected = [...new Set((concept.uses || []).map(use => main[use]).filter(Boolean))].sort();
      if (Array.isArray(types) && bestUseStable([...types].sort()) === bestUseStable(expected)) return '';
      return '<p class="best-use-warning">' + WFT('best_use_explore.type_mismatch',
        'استخدام المفهوم يختلف عن نوع المشروع المسجل؛ البيانات الأساسية ودراسة السوق تخصان النوع المسجل.') + '</p>';
    }

    function setBestUseExploreStage(stage) { bestUseExploreStage = stage; renderBestUse(); }

    function renderBestUseExplore() {
      const root = document.getElementById('bestUseExploreWorkspace');
      if (!root) return;
      const state = bestUseExploreState();
      if (bestUseExploreDraftId !== tenantProjectData?.draftId) {
        bestUseExploreDraftId = tenantProjectData?.draftId || '';
        bestUseExploreStage = state.floorDistribution?.id ? 'floors' : state.landDistribution?.id ? 'land' : 'concepts';
      }
      const missing = bestUseExploreMissing();
      const locked = tenantProjectSectionStatuses?.[BEST_USE_SECTION_KEY] === 'approved';
      const unavailable = bestUseExploreBusy || locked || missing.length > 0 || !hasPermission('create_presentation') || tenantProjectMode === 'presentation';
      const concepts = bestUseArray(state.concepts?.items);
      const selected = concepts.find(item => item.id === state.selectedConceptId);
      const stages = [
        ['concepts', WFT('best_use_explore.concepts_stage', 'المفاهيم والأسعار')],
        ['land', WFT('best_use_explore.land_stage', 'التوزيع الأرضي')],
        ['floors', WFT('best_use_explore.floors_stage', 'توزيع الأدوار')]
      ];
      let content = '';
      if (bestUseExploreStage === 'concepts') {
        const generationLocked = ['regulations', 'priceScan', 'concepts'].some(bestUseExploreApproved);
        content = '<button type="button" class="btn primary small" onclick="runBestUseExplore(\'concepts\')" '
          + (unavailable || generationLocked ? 'disabled' : '') + '>' + WFT('best_use_explore.generate_concepts', 'توليد المفاهيم ومسح الأسعار') + '</button>'
          + (state.regulations?.requiresApproval ? bestUseExploreDecisionHtml('regulations') : '')
          + (bestUseArray(state.regulations?.permittedUses).length ? '<p>' + WFT('best_use.need_uses', 'الاستخدامات المسموحة') + ': '
            + bestUseArray(state.regulations?.permittedUses).map(bestUseExploreUseLabel).map(escapeHtml).join('، ') + '</p>' : '')
          + bestUseExplorePriceHtml(state.priceScan)
          + '<div class="best-use-concept-grid">' + concepts.map(item => '<article class="best-use-concept-card '
            + (selected?.id === item.id ? 'selected' : '') + '"><h4>' + escapeHtml(item.name) + '</h4><p>' + escapeHtml(item.summary)
            + '</p><p>' + escapeHtml(item.siteFit) + '</p><p>' + escapeHtml(item.revenueBasis) + '</p>'
            + bestUseRevenuePotentialHtml(item.revenuePotential) + '<button type="button" class="btn ghost small" onclick="runBestUseExplore(\'select\',{conceptId:\''
            + escapeHtml(item.id) + '\'})" ' + (unavailable || !bestUseExploreCurrent('concepts') ? 'disabled' : '') + '>'
            + (selected?.id === item.id ? WFT('best_use_explore.selected', 'المفهوم المختار') : WFT('best_use_explore.select', 'اختيار المفهوم'))
            + '</button></article>').join('') + '</div>' + bestUseExploreDecisionHtml('concepts');
      } else {
        const name = bestUseExploreStage === 'land' ? 'landDistribution' : 'floorDistribution';
        const required = bestUseExploreStage === 'land' ? 'concepts' : 'landDistribution';
        content = '<button type="button" class="btn primary small" onclick="runBestUseExplore(\'generate\')" '
          + (unavailable || !selected || !bestUseExploreCurrent(required) || bestUseExploreApproved(name) ? 'disabled' : '') + '>'
          + WFT('best_use.generate', 'اقتراح أفضل توزيع') + '</button>' + bestUseExploreMismatch(selected)
          + bestUseExploreDistributionHtml(state[name]) + bestUseExploreDecisionHtml(name)
          + '<section class="best-use-chat best-use-explore-chat"><h4>' + WFT('best_use.chat_title', 'مناقشة التوزيع')
          + '</h4><div class="best-use-chat-messages" role="log">' + bestUseArray(bestUseExploreChat()[bestUseExploreStage])
            .map(turn => '<div class="best-use-chat-message ' + (turn.role === 'user' ? 'user' : 'assistant') + '">'
              + escapeHtml(turn.content || '') + '</div>').join('') + '</div>'
          + '<label for="bestUseExploreChatInput">' + WFT('best_use.message', 'الرسالة') + '</label>'
          + '<textarea id="bestUseExploreChatInput" rows="3" maxlength="4000" data-section-lock-ignore="1" '
          + (bestUseExploreBusy || missing.length || !selected ? 'disabled' : '') + '></textarea>'
          + '<div class="best-use-actions"><button type="button" class="btn primary small" data-section-lock-ignore="1" '
          + 'onclick="runBestUseExplore(\'chat\')" ' + (bestUseExploreBusy || !selected || !bestUseExploreCurrent(required) ? 'disabled' : '') + '>'
          + WFT('best_use.send', 'إرسال') + '</button><button type="button" class="btn ghost small" onclick="runBestUseExplore(\'revise\')" '
          + (unavailable || bestUseExploreApproved(name) || !bestUseExploreCurrent(required) ? 'disabled' : '') + '>'
          + WFT('best_use.revise', 'تحديث التوزيع') + '</button></div></section>';
      }
      const input = document.getElementById('bestUseExploreChatInput');
      const savedMessage = input?.value || '';
      root.innerHTML = '<nav class="best-use-stage-nav">' + stages.map(([stage, label]) => '<button type="button" class="btn '
        + (stage === bestUseExploreStage ? 'primary' : 'ghost') + ' small" onclick="setBestUseExploreStage(\'' + stage + '\')" '
        + (bestUseExploreBusy ? 'disabled' : '') + '>' + label + '</button>').join('') + '</nav>'
        + '<p class="tenant-hint" role="status">' + (bestUseExploreBusy ? WFT('best_use.busy', 'جاري معالجة التوزيع...')
          : missing.length ? WFT('best_use.missing', 'بيانات أو اعتمادات غير مكتملة: {items}', { items: missing.map(bestUseMissingLabel).join('، ') })
            : WFT('best_use_explore.ready', 'بيانات الأرض والموقع معتمدة؛ الاستكشاف مستقل عن فكرة المشروع ودراسة السوق.')) + '</p>'
        + content + '<button type="button" class="btn ghost small" onclick="saveProjectAsDraft()">' + WFT('best_use.save', 'حفظ كمسودة') + '</button>';
      const liveInput = document.getElementById('bestUseExploreChatInput');
      if (liveInput) {
        liveInput.value = savedMessage;
        liveInput.addEventListener('input', event => event.stopPropagation());
        liveInput.addEventListener('keydown', event => {
          if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); runBestUseExplore('chat'); }
        });
      }
      persistBestUseDraftState();
    }

    function applyBestUseExploreResponse(response, requestContext) {
      if (tenantProjectData?.draftId !== requestContext.draftId || response.draftId !== requestContext.draftId) {
        console.warn('[BEST-USE-EXPLORE] response rejected: draft mismatch',
          { expected: requestContext.draftId, current: tenantProjectData?.draftId, received: response?.draftId });
        toast(WFT('best_use.local_changed', 'تغيّرت المدخلات الحالية أثناء المعالجة؛ لم تُستبدل المكونات المحلية.'));
        return false;
      }
      const fresh = (typeof draftEditCounter === 'undefined' || draftEditCounter === requestContext.editCounter)
        && bestUseStable(bestUseExploreSourceSnapshot()) === bestUseStable(requestContext.sourceSnapshot);
      if (response.revision !== undefined) tenantDraftRevision = Number(response.revision);
      if (!fresh) {
        const current = bestUseExploreSourceSnapshot();
        console.warn('[BEST-USE-EXPLORE] response rejected: inputs changed while processing',
          { editCounter: typeof draftEditCounter === 'undefined' ? null : draftEditCounter,
            expectedEditCounter: requestContext.editCounter,
            changed: Object.keys({ ...requestContext.sourceSnapshot, ...current })
              .filter(key => bestUseStable(requestContext.sourceSnapshot[key]) !== bestUseStable(current[key])) });
        toast(WFT('best_use.local_changed', 'تغيّرت المدخلات الحالية أثناء المعالجة؛ لم تُستبدل المكونات المحلية.'));
        return false;
      }
      if (response.bestUseMode) tenantProjectData.best_use_mode = response.bestUseMode;
      if (response.explore) tenantProjectData.best_use_explore_data = bestUseObject(response.explore);
      if (response.exploreChat) tenantProjectData.best_use_explore_chat = bestUseObject(response.exploreChat);
      if (response.bestUse) tenantProjectData.best_use_data = bestUseObject(response.bestUse);
      if (response.chat) tenantProjectData.best_use_chat = bestUseObject(response.chat);
      if (response.sectionStatuses) applySectionStatuses(response.sectionStatuses);
      if (!bestUseSectionRequired()) delete tenantProjectSectionStatuses[BEST_USE_SECTION_KEY];
      if (response.componentsApplied && response.financialModel) applyBestUseFinancialModel(response);
      persistBestUseDraftState();
      renderBestUse();
      return true;
    }

    function bestUseExploreErrorText(response) {
      const keys = {
        BEST_USE_WRONG_MODE: ['best_use_explore.wrong_mode', 'العملية لا تخص وضع أفضل استخدام النشط.'],
        BEST_USE_INPUTS_CHANGED: ['best_use_explore.inputs_changed', 'تغيّرت بيانات الأرض أو الموقع أو أدلة الاستكشاف.'],
        BEST_USE_EVIDENCE_REQUIRED: ['best_use_explore.evidence_missing', 'السماح التنظيمي المستقل غير مثبت من المستندات.'],
        BEST_USE_STAGE_REQUIRED: ['best_use_explore.incomplete', 'مراحل الاستكشاف غير مكتملة.'],
        BEST_USE_ARTIFACT_CHANGED: ['best_use_explore.artifact_changed', 'نسخة المحتوى تغيرت منذ آخر قراءة.'],
        BEST_USE_SEARCH_FAILED: ['best_use_explore.search_failed', 'تعذر إجراء مسح أسعار حي موثق.']
      };
      const entry = keys[response?.error_code];
      return entry ? WFT(entry[0], entry[1]) : bestUseErrorText(response);
    }

    function runBestUseExplore(action, options = {}) {
      if (bestUseExploreTask) return bestUseExploreTask;
      if (bestUseBusy || tenantProjectMode === 'presentation' || !hasPermission('create_presentation')) return Promise.resolve(false);
      const stage = bestUseExploreStage;
      const state = bestUseExploreState();
      const message = String(document.getElementById('bestUseExploreChatInput')?.value || '').trim();
      if (['chat', 'revise'].includes(action) && !message) return Promise.resolve(false);
      if (action === 'decision' && options.artifact === 'floorDistribution' && options.decision === 'approved'
          && !confirm(WFT('best_use.replace_confirm', 'اعتماد هذا التوزيع واستبدال جميع المكونات الحالية؟ سيعود قسم الدراسة المالية إلى مسودة.'))) return Promise.resolve(false);
      bestUseExploreTask = (async () => {
        bestUseExploreBusy = true;
        renderBestUse();
        showLoader(WFT('best_use.processing_title', 'أفضل استخدامات'), WFT('best_use.saving', 'حفظ بيانات المشروع'), 5);
        try {
          const initialId = tenantProjectData?.draftId;
          let requestContext;
          if (action === 'mode') {
            // Switching modes only flips the server-owned best_use_mode flag —
            // it must not force a draft save (or inherit its revision
            // conflicts). The endpoint applies the switch to the stored draft
            // atomically, and the response heals the client's revision.
            if (!initialId) {
              toast(WFT('best_use.draft_missing', 'المسودة غير محفوظة بعد.'));
              return false;
            }
            requestContext = { draftId: initialId,
              editCounter: typeof draftEditCounter === 'undefined' ? 0 : draftEditCounter,
              sourceSnapshot: bestUseExploreSourceSnapshot() };
          } else {
            const initial = bestUseExploreSourceSnapshot();
            if (!(await saveProjectAsDraft(true, false))) {
              console.warn('[BEST-USE-EXPLORE]', action, 'aborted: draft save failed');
              toast(WFT('best_use.save_failed', 'تعذر حفظ المسودة قبل المتابعة.'));
              return false;
            }
            const afterSave = bestUseExploreSourceSnapshot();
            if (bestUseStable(initial) !== bestUseStable(afterSave)) {
              console.warn('[BEST-USE-EXPLORE] inputs changed during save:',
                Object.keys({ ...initial, ...afterSave })
                  .filter(key => bestUseStable(initial[key]) !== bestUseStable(afterSave[key])));
            }
            if (tenantProjectData?.draftId !== initialId
                || bestUseStable(initial) !== bestUseStable(afterSave)) {
              toast(WFT('best_use.local_changed', 'تغيّرت المدخلات الحالية أثناء المعالجة؛ لم تُستبدل المكونات المحلية.'));
              return false;
            }
            requestContext = { draftId: initialId, editCounter: typeof draftEditCounter === 'undefined' ? 0 : draftEditCounter, sourceSnapshot: afterSave };
          }
          const payload = { draftId: initialId };
          if (action !== 'mode') payload.expectedRevision = tenantDraftRevision;
          let endpoint = '/api/best-use/explore/';
          if (action === 'mode') { endpoint = '/api/best-use/mode'; payload.mode = options.mode; }
          else if (action === 'select') {
            endpoint += 'concepts/select';
            Object.assign(payload, { conceptId: options.conceptId, artifactId: state.concepts?.id, contentHash: state.concepts?.contentHash });
          } else if (action === 'decision') {
            endpoint += 'decision';
            const artifact = state[options.artifact] || {};
            Object.assign(payload, { artifact: options.artifact, decision: options.decision,
              artifactId: artifact.id, contentHash: artifact.contentHash, inputHash: artifact.inputHash });
          } else {
            endpoint += ['chat', 'revise'].includes(action) ? 'chat' : action;
            Object.assign(payload, { stage, message, revise: action === 'revise' });
          }
          updateLoaderProgress(15, WFT('best_use_explore.processing', 'معالجة أدلة الأرض والأسعار والمفاهيم'));
          let response = await apiWithTimeout('POST', endpoint, payload);
          const deadline = Date.now() + 1200000;
          while (response?.success && response.jobId && !['completed', 'failed'].includes(response.status)
                 && Date.now() < deadline && tenantProjectData?.draftId === initialId) {
            await new Promise(resolve => setTimeout(resolve, 1500));
            response = await apiWithTimeout('GET', '/api/best-use/explore/jobs/' + response.jobId, undefined, 30000);
            const labels = {
              regulations: WFT('best_use_explore.progress_regulations', 'التحقق من الاستخدامات المسموحة'),
              prices: WFT('best_use_explore.progress_prices', 'مسح الأسعار الحي'),
              priceEvidence: WFT('best_use_explore.progress_evidence', 'التحقق من صفحات الأسعار'),
              concepts: WFT('best_use_explore.concepts_stage', 'المفاهيم والأسعار'),
              land: WFT('best_use_explore.land_stage', 'التوزيع الأرضي'), floors: WFT('best_use_explore.floors_stage', 'توزيع الأدوار'),
              saving: WFT('best_use.saving', 'حفظ بيانات المشروع')
            };
            updateLoaderProgress(response?.progress || 20, labels[response?.step] || WFT('best_use_explore.processing', 'معالجة أدلة الأرض والأسعار والمفاهيم'));
          }
          if (response?.jobId && !['completed', 'failed'].includes(response.status)) response = { success: false, error_code: 'BEST_USE_JOB_INTERRUPTED' };
          if (!response?.success) {
            console.warn('[BEST-USE-EXPLORE]', action, 'request failed:', response);
            toast(bestUseExploreErrorText(response));
            return false;
          }
          const received = applyBestUseExploreResponse(response, requestContext);
          if (received && ['chat', 'revise'].includes(action)) {
            const input = document.getElementById('bestUseExploreChatInput');
            if (input?.value.trim() === message) input.value = '';
          }
          updateLoaderProgress(100, WFT('best_use.done', 'اكتملت المعالجة'));
          return received;
        } catch (error) {
          console.warn('[BEST-USE-EXPLORE]', action, 'threw:', error);
          toast(WFT('best_use.failed', 'تعذر معالجة أفضل استخدامات.'));
          return false;
        } finally {
          bestUseExploreBusy = false;
          hideLoader();
          renderBestUse();
        }
      })().finally(() => { bestUseExploreTask = null; });
      return bestUseExploreTask;
    }

    function changeBestUseMode(mode) { return runBestUseExplore('mode', { mode }); }
