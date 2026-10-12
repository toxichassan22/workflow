    const BEST_USE_SECTION_KEY = 'section-best-use';
    const BEST_USE_SOURCE_FIELDS = [
      'draftId', 'project_name', 'project_type', 'project_subtype', 'project_idea',
      'project_level', 'activity_class', 'target_audience', 'project_language',
      'land_documents_files_file_ids', 'land_documents_analysis', 'croquis_land_area',
      'approved_financial_area', 'approved_coverage_ratio', 'approved_floor_count',
      'approved_floor_area_ratio', 'building_ratio_coverage', 'setbacks', 'allowed_uses',
      'land_use_status', 'regulatory_constraints', 'max_floors_height',
      'land_and_building_summary', 'boundary_lengths', 'surrounding_streets',
      'survey_coordinates', 'directions_table', 'location_address', 'location_lat',
      'location_lng', 'city', 'district', 'site_analysis', 'main_roads',
      'nearby_landmarks_data', 'city_landmarks_data', 'catchment_areas',
      'location_polygon', 'location_polygon_source', 'market_study_data'
    ];
    const BEST_USE_JSON_FIELDS = {
      project_type: [], project_subtype: {}, target_audience: {}, land_documents_files_file_ids: [],
      land_documents_analysis: {}, survey_coordinates: [], directions_table: [],
      nearby_landmarks_data: [], city_landmarks_data: [], location_polygon: [], market_study_data: {}
    };
    const BEST_USE_NUMBER_FIELDS = new Set([
      'croquis_land_area', 'approved_financial_area', 'approved_coverage_ratio', 'approved_floor_count',
      'approved_floor_area_ratio', 'location_lat', 'location_lng'
    ]);
    const BEST_USE_MAIN_TYPES = ['سكني', 'تجاري', 'فندقي', 'صناعي ولوجستي'];
    const BEST_USE_TYPE_ALIASES = { residential: 'سكني', commercial: 'تجاري', hospitality: 'فندقي',
      'industrial & logistics': 'صناعي ولوجستي' };
    let bestUseBusy = false;
    let bestUseRequestTask = null;

    function bestUseDecoded(value, fallback = {}) {
      if (typeof value === 'string') {
        try { value = JSON.parse(value); } catch (error) { value = null; }
      }
      return value && typeof value === 'object' ? value : JSON.parse(JSON.stringify(fallback));
    }

    function bestUseObject(value) {
      const result = bestUseDecoded(value);
      return Array.isArray(result) ? {} : result;
    }

    function bestUseNumber(value) {
      if (value === null || value === undefined || typeof value === 'boolean') return null;
      const raw = String(value).replace(/[٠-٩]/g, digit => String(digit.charCodeAt(0) - 1632))
        .replace(/[۰-۹]/g, digit => String(digit.charCodeAt(0) - 1776))
        .replace(/[,٬]/g, '').replace(/٫/g, '.').trim();
      if (!raw) return null;
      const parsed = Number(raw);
      return Number.isFinite(parsed) ? parsed : null;
    }

    function bestUseNormalizeMedia(value) {
      if (Array.isArray(value)) return value.map(bestUseNormalizeMedia);
      if (value && typeof value === 'object') {
        return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, bestUseNormalizeMedia(item)]));
      }
      if (typeof value !== 'string' || !value.startsWith('/uploads/')) return value;
      const url = new URL(value, window.location.origin);
      ['s', 't', 'v', 'cb'].forEach(key => url.searchParams.delete(key));
      return url.pathname + url.search + url.hash;
    }

    function bestUseStable(value) {
      if (Array.isArray(value)) return '[' + value.map(bestUseStable).join(',') + ']';
      if (value && typeof value === 'object') {
        return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + bestUseStable(value[key])).join(',') + '}';
      }
      return JSON.stringify(value);
    }

    function bestUseFieldValue(key) {
      const control = document.querySelector('#tenantProjectForm [data-key="' + key + '"]');
      return control?.value ?? tenantProjectData?.[key] ?? '';
    }

    function bestUseSourceSnapshot() {
      const snapshot = {};
      BEST_USE_SOURCE_FIELDS.forEach(key => {
        const value = bestUseFieldValue(key);
        if (key === 'project_type') {
          let types = bestUseDecoded(value, []);
          if (!Array.isArray(types)) types = [];
          if (!types.length && typeof value === 'string') types = value.split(/[,،;\n]+/);
          snapshot[key] = types.map(item => String(item || '').trim()).filter(Boolean)
            .map(item => BEST_USE_TYPE_ALIASES[item.toLowerCase()] || item);
        } else if (Object.prototype.hasOwnProperty.call(BEST_USE_JSON_FIELDS, key)) {
          snapshot[key] = bestUseDecoded(value, BEST_USE_JSON_FIELDS[key]);
        } else if (BEST_USE_NUMBER_FIELDS.has(key)) {
          snapshot[key] = bestUseNumber(value);
        } else {
          snapshot[key] = String(value ?? '').trim().slice(0, 30000);
        }
      });
      const creative = bestUseObject(tenantProjectData?.tenantCreativeImages);
      const maps = bestUseObject(creative.map_placeholders);
      snapshot.maps = Object.fromEntries(['##MAP_OVERVIEW##', '##MAP_ACCESS##', '##MAP_CATCHMENT##', '##MAP_LANDMARKS##']
        .filter(key => maps[key]).map(key => [key, maps[key]]));
      snapshot.mode = String(bestUseState().mode || 'guided').trim();
      return bestUseNormalizeMedia(snapshot);
    }

    function bestUseState() { return bestUseObject(tenantProjectData?.best_use_data); }
    function bestUseChatState() { return bestUseObject(tenantProjectData?.best_use_chat); }
    function bestUseSectionRequired() {
      if (typeof bestUseActiveMode === 'function' && bestUseActiveMode() === 'explore') return bestUseExploreSectionRequired();
      const state = bestUseState(); return !!state.id && !state.rejected;
    }

    function bestUseCurrent() {
      const state = bestUseState();
      // Responses re-sign /uploads/ links (an expiring ?s= token), so the stored
      // snapshot arrives signed while the live snapshot is normalized. Compare
      // both sides through the same normalization or the approval stays disabled.
      return !!state.id && !state.inputsChanged
        && bestUseStable(bestUseSourceSnapshot()) === bestUseStable(bestUseNormalizeMedia(state.sourceSnapshot || {}));
    }

    function bestUseSectionError() {
      if (typeof bestUseActiveMode === 'function' && bestUseActiveMode() === 'explore') return bestUseExploreSectionError();
      if (!bestUseSectionRequired()) return '';
      if (!bestUseCurrent()) return WFT('best_use.inputs_changed', 'تغيّرت بيانات الأرض أو الموقع أو دراسة السوق التي بُني عليها الاقتراح.');
      return bestUseState().approved === true ? '' : WFT('best_use.approval_required', 'اقتراح أفضل استخدامات غير معتمد.');
    }

    function bestUseOptionalStatuses(statuses) {
      const result = { ...(statuses || {}) };
      if (!bestUseSectionRequired()) delete result[BEST_USE_SECTION_KEY];
      else if (bestUseSectionError()) result[BEST_USE_SECTION_KEY] = 'draft';
      return result;
    }

    function persistBestUseDraftState() {
      [['best_use_data', 'bestUseData'], ['best_use_chat', 'bestUseChatData'],
        ['best_use_explore_data', 'bestUseExploreData'], ['best_use_explore_chat', 'bestUseExploreChatData']].forEach(([key, id]) => {
        const value = bestUseObject(tenantProjectData?.[key]);
        const hidden = document.getElementById(id);
        if (hidden) hidden.value = JSON.stringify(value);
      });
      const mode = document.getElementById('bestUseModeData');
      if (mode) mode.value = tenantProjectData?.best_use_mode || 'guided';
    }

    function bestUseMissingFields() {
      const source = bestUseSourceSnapshot();
      const missing = [];
      if (source.mode !== 'guided') missing.push('best_use_mode');
      if (!source.project_type.length || source.project_type.some(kind => !BEST_USE_MAIN_TYPES.includes(kind))) missing.push('project_type');
      if (!source.land_documents_files_file_ids.length || !Object.keys(bestUseObject(source.land_documents_analysis)).length) missing.push('croquis');
      if (!source.location_address || source.location_lat === null || source.location_lng === null
          || Math.abs(source.location_lat) > 90 || Math.abs(source.location_lng) > 180) missing.push('site_location');
      const market = bestUseObject(source.market_study_data);
      const summary = market.summary;
      const hasSummary = summary && typeof summary === 'object'
        ? Object.values(summary).some(value => String(value || '').trim()) : !!String(summary || '').trim();
      if (!hasSummary && !String(market.one_block_summary || '').trim()) missing.push('market');
      ['land_croquis', 'location', 'section-market-study'].forEach(key => {
        if (tenantProjectSectionStatuses?.[key] !== 'approved') missing.push(key);
      });
      ['croquis_land_area', 'approved_financial_area', 'approved_floor_count', 'approved_floor_area_ratio'].forEach(key => {
        if (!(source[key] > 0) || (key === 'approved_floor_count' && !Number.isInteger(source[key]))) missing.push(key);
      });
      if (!(source.approved_coverage_ratio > 0 && source.approved_coverage_ratio <= 100)) missing.push('approved_coverage_ratio');
      ['setbacks', 'allowed_uses'].forEach(key => { if (!source[key]) missing.push(key); });
      return [...new Set(missing)];
    }

    function bestUseMissingLabel(key) {
      const labels = {
        project_type: ['best_use.need_type', 'نوع المشروع'], croquis: ['best_use.need_croquis', 'الكروكي وتحليل الأرض'],
        site_location: ['best_use.need_location', 'موقع الأرض'], market: ['best_use.need_market', 'دراسة السوق'],
        land_croquis: ['best_use.need_land_approval', 'اعتماد قسم الأرض والكروكي'],
        location: ['best_use.need_location_approval', 'اعتماد قسم الموقع والخرائط'],
        'section-market-study': ['best_use.need_market_approval', 'اعتماد قسم دراسة السوق'],
        croquis_land_area: ['best_use.need_croquis_area', 'مساحة الأرض حسب الكروكي'],
        approved_financial_area: ['best_use.need_area', 'المساحة المعتمدة'],
        approved_floor_count: ['best_use.need_floors', 'الأدوار المعتمدة'],
        approved_floor_area_ratio: ['best_use.need_far', 'معامل مسطح البناء المعتمد FAR'],
        approved_coverage_ratio: ['best_use.need_coverage', 'تغطية البناء'],
        setbacks: ['best_use.need_setbacks', 'الارتدادات'], allowed_uses: ['best_use.need_uses', 'الاستخدامات المسموحة'],
        buildable_area: ['best_use.need_buildable', 'مساحة بناء متاحة'],
        best_use_mode: ['best_use.mode_unavailable', 'وضع أفضل استخدام غير متاح حاليًا'],
        city: ['best_use.need_city', 'مدينة الأرض']
      };
      const pair = labels[key];
      return pair ? WFT(pair[0], pair[1]) : key;
    }

    function bestUseErrorText(response) {
      const keys = {
        BEST_USE_APPROVAL_REQUIRED: ['best_use.approval_required', 'اقتراح أفضل استخدامات غير معتمد.'],
        BEST_USE_INPUTS_CHANGED: ['best_use.inputs_changed', 'تغيّرت بيانات الأرض أو الموقع أو دراسة السوق التي بُني عليها الاقتراح.'],
        BEST_USE_APPROVAL_LOCKED: ['best_use.locked', 'اقتراح أفضل استخدامات معتمد ومقفل للتعديل.'],
        BEST_USE_PROPOSAL_CHANGED: ['best_use.proposal_changed', 'الاقتراح غير متوفر أو تغيّر منذ آخر قراءة.'],
        BEST_USE_INVALID_PROPOSAL: ['best_use.invalid_proposal', 'التوزيع المولد غير مكتمل أو يتجاوز الحدود المعتمدة.'],
        BEST_USE_JOB_INTERRUPTED: ['best_use.interrupted', 'توقفت معالجة أفضل استخدامات قبل اكتمالها.'],
        DRAFT_REVISION_CONFLICT: ['best_use.conflict', 'المسودة تغيّرت أثناء معالجة أفضل استخدامات.'],
        SECTION_FORBIDDEN: ['best_use.forbidden', 'قسم غير متاح لهذا المستخدم']
      };
      if (response?.error_code === 'BEST_USE_PREREQUISITES_REQUIRED') {
        return WFT('best_use.missing', 'بيانات أو اعتمادات غير مكتملة: {items}', {
          items: (response.missing || []).map(bestUseMissingLabel).join('، ')
        });
      }
      const pair = keys[response?.error_code];
      const base = pair ? WFT(pair[0], pair[1]) : wfTr(response?.error || WFT('best_use.failed', 'تعذر معالجة أفضل استخدامات.'));
      return response?.validation ? base + ' ' + wfTr(String(response.validation)) : base;
    }

    function bestUseFormat(value) {
      const number = bestUseNumber(value);
      return number === null ? '' : new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(number);
    }

    function bestUseOptionText(options, value) {
      const option = options.find(item => item.v === value);
      return wfTr(option?.t || value || '');
    }

    function addBestUseSection(form) {
      if (!form || !tenantAllowedFieldSections[BEST_USE_SECTION_KEY]
          || ['basic', 'land_croquis', 'location', 'section-market-study', 'section-financial-calc']
            .some(key => tenantAllowedFieldSections[key] === false)) return;
      const section = document.createElement('div');
      section.className = 'tenant-form-section best-use-section';
      section.dataset.section = BEST_USE_SECTION_KEY;
      section.dataset.optional = '1';
      section.id = BEST_USE_SECTION_KEY;
      section.appendChild(createProjectSectionHeader(BEST_USE_SECTION_KEY, 'أفضل استخدامات'));
      const body = document.createElement('div');
      body.className = 'best-use-body';
      body.innerHTML = `
        <label class="best-use-mode-label" for="bestUseMode">${WFT('best_use_explore.mode', 'وضع أفضل استخدام')}</label>
        <select id="bestUseMode" oninput="event.stopPropagation()" onchange="event.stopPropagation(); changeBestUseMode(this.value)">
          <option value="guided">${WFT('best_use_explore.guided', 'توزيع موجّه بفكرة المشروع')}</option>
          <option value="explore">${WFT('best_use_explore.explore', 'استكشاف مستقل للأرض')}</option>
        </select>
        <div id="bestUseGuidedWorkspace">
        <div class="best-use-toolbar">
          <span class="best-use-optional" data-i18n="best_use.optional">${WFT('best_use.optional', 'اختياري')}</span>
          <div class="best-use-actions">
            <button type="button" id="bestUseGenerateButton" class="btn primary small" onclick="runBestUseAction('generate')">${WFT('best_use.generate', 'اقتراح أفضل توزيع')}</button>
            <button type="button" class="btn ghost small" data-i18n="best_use.save" onclick="saveProjectAsDraft()">${WFT('best_use.save', 'حفظ كمسودة')}</button>
          </div>
        </div>
        <p id="bestUseReadiness" class="tenant-hint" role="status"></p>
        <div id="bestUseProposal"></div>
        <section class="best-use-chat" aria-labelledby="bestUseChatTitle">
          <h4 id="bestUseChatTitle" data-i18n="best_use.chat_title">${WFT('best_use.chat_title', 'مناقشة التوزيع')}</h4>
          <div id="bestUseChatMessages" class="best-use-chat-messages" role="log" aria-live="polite"></div>
          <label for="bestUseChatInput" data-i18n="best_use.message">${WFT('best_use.message', 'الرسالة')}</label>
          <textarea id="bestUseChatInput" rows="3" maxlength="4000" data-section-lock-ignore="1"></textarea>
          <div class="best-use-actions">
            <button type="button" id="bestUseChatSend" class="btn primary small" data-section-lock-ignore="1" onclick="sendBestUseChat()">${WFT('best_use.send', 'إرسال')}</button>
            <button type="button" id="bestUseChatRevise" class="btn ghost small" onclick="sendBestUseChat(true)">${WFT('best_use.revise', 'تحديث التوزيع')}</button>
          </div>
        </section>
        </div>
        <div id="bestUseExploreWorkspace" hidden></div>
        <input type="hidden" id="bestUseModeData" data-key="best_use_mode" data-type="text">
        <input type="hidden" id="bestUseExploreData" data-key="best_use_explore_data" data-type="text">
        <input type="hidden" id="bestUseExploreChatData" data-key="best_use_explore_chat" data-type="text">
        <input type="hidden" id="bestUseData" data-key="best_use_data" data-type="text">
        <input type="hidden" id="bestUseChatData" data-key="best_use_chat" data-type="text">`;
      section.appendChild(body);
      form.appendChild(section);
      const input = body.querySelector('#bestUseChatInput');
      input.addEventListener('input', event => event.stopPropagation());
      input.addEventListener('keydown', event => {
        if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendBestUseChat(); }
      });
      persistBestUseDraftState();
      renderBestUse();
    }

    function bestUseWarningHtml(text) {
      return '<p class="best-use-warning"><strong class="best-use-warning-tag">'
        + escapeHtml(WFT('best_use.warning_tag', 'تنبيه')) + '</strong><span>' + escapeHtml(text) + '</span></p>';
    }

    function renderBestUse() {
      const root = document.getElementById(BEST_USE_SECTION_KEY);
      if (!root) return;
      if (typeof renderBestUseModeControls === 'function') renderBestUseModeControls();
      if (typeof bestUseActiveMode === 'function' && bestUseActiveMode() === 'explore') { renderBestUseExplore(); return; }
      const state = bestUseState();
      const current = bestUseCurrent();
      const approved = state.approved === true;
      const locked = tenantProjectSectionStatuses?.[BEST_USE_SECTION_KEY] === 'approved';
      const missing = bestUseMissingFields();
      const unavailable = bestUseBusy || missing.length > 0 || !hasPermission('create_presentation')
        || (typeof tenantProjectMode !== 'undefined' && tenantProjectMode === 'presentation');
      const readiness = document.getElementById('bestUseReadiness');
      readiness.textContent = bestUseBusy ? WFT('best_use.busy', 'جاري معالجة التوزيع...')
        : missing.length ? WFT('best_use.missing', 'بيانات أو اعتمادات غير مكتملة: {items}', { items: missing.map(bestUseMissingLabel).join('، ') })
          : WFT('best_use.ready', 'بيانات الأرض والموقع ودراسة السوق معتمدة.');
      const generate = document.getElementById('bestUseGenerateButton');
      generate.disabled = unavailable || locked || (approved && current);
      generate.textContent = state.id ? WFT('best_use.regenerate', 'إعادة التوليد') : WFT('best_use.generate', 'اقتراح أفضل توزيع');
      document.getElementById('bestUseChatSend').disabled = unavailable;
      document.getElementById('bestUseChatInput').disabled = unavailable;
      document.getElementById('bestUseChatRevise').disabled = unavailable || locked || (approved && current) || !state.id;
      const proposal = document.getElementById('bestUseProposal');
      if (!state.id) {
        proposal.innerHTML = '<p class="tenant-hint">' + escapeHtml(WFT('best_use.empty', 'لا يوجد توزيع مقترح.')) + '</p>';
      } else {
        const budget = state.capacity || {};
        const totals = state.totals || {};
        const headings = [WFT('best_use.component', 'المكون'), WFT('best_use.use', 'الاستخدام'),
          WFT('best_use.units', 'عدد الوحدات'), WFT('best_use.unit_area', 'مساحة الوحدة م²'),
          WFT('best_use.built_area', 'المساحة المبنية م²'), WFT('best_use.revenue_area', 'المساحة البيعية / التأجيرية م²'),
          WFT('best_use.allocated_footprint', 'الحصة الأرضية م²'), WFT('best_use.investment_model', 'نموذج الاستفادة')];
        const rows = Array.isArray(state.components) ? state.components : [];
        const cells = rows.map(row => '<tr>' + [row.name, bestUseOptionText(useTypes, row.useType),
          bestUseFormat(row.units), bestUseFormat(row.unitArea), bestUseFormat(row.builtArea), bestUseFormat(row.revenueArea),
          bestUseFormat(row.footprintArea), bestUseOptionText(investmentModels, row.investmentModel)]
          .map(value => '<td>' + escapeHtml(String(value ?? '')) + '</td>').join('') + '</tr>').join('');
        const status = !current ? WFT('best_use.stale', 'تغيّرت المدخلات')
          : state.rejected ? WFT('best_use.rejected', 'مرفوض')
            : approved ? WFT('best_use.approved', 'معتمد') : WFT('best_use.pending', 'بانتظار الاعتماد');
        proposal.innerHTML = `
          <div class="best-use-proposal-heading"><h4>${escapeHtml(state.title || WFT('best_use.distribution', 'التوزيع المقترح'))}</h4><span class="best-use-status">${escapeHtml(status)}</span></div>
          ${budget.setbackVerified === false ? bestUseWarningHtml(WFT('best_use.geometry_unverified', 'غلاف الارتدادات غير متحقق هندسيًا من البيانات المتاحة؛ المساحات توصية تخطيطية وليست مخططًا معماريًا.')) : ''}
          ${totals.basementArea > 0 && budget.basementVerified === false ? bestUseWarningHtml(WFT('best_use.basement_unverified', 'سقف البدروم تخطيطي لطبقة واحدة ضمن مساحة الأرض؛ السماح التنظيمي وغلاف الارتدادات تحت الأرض غير متحققين.')) : ''}
          ${!current ? bestUseWarningHtml(WFT('best_use.inputs_changed', 'تغيّرت بيانات الأرض أو الموقع أو دراسة السوق التي بُني عليها الاقتراح.')) : ''}
          <div class="table-wrap"><table class="best-use-table"><thead><tr>${headings.map(label => '<th>' + escapeHtml(label) + '</th>').join('')}</tr></thead><tbody>${cells}</tbody></table></div>
          ${typeof bestUseRevenuePotentialHtml === 'function' ? bestUseRevenuePotentialHtml(state.revenuePotential) : ''}
          <div class="best-use-actions best-use-decisions">
            <button type="button" class="btn primary small" onclick="runBestUseAction('${approved ? 'unapproved' : 'approved'}')" ${bestUseBusy || locked || (!approved && (!current || unavailable)) ? 'disabled' : ''}>${approved ? WFT('best_use.unapprove', 'الغاء الاعتماد') : WFT('best_use.approve', 'اعتماد واستبدال المكونات')}</button>
            <button type="button" class="btn ghost small" onclick="runBestUseAction('rejected')" ${bestUseBusy || locked || approved || state.rejected ? 'disabled' : ''}>${WFT('best_use.reject', 'رفض الاقتراح')}</button>
          </div>
          ${state.unlinkedRevenueRows ? bestUseWarningHtml(WFT('best_use.revenue_links', 'بنود إيرادات بدون ارتباط بمكون بعد الاستبدال: {n}', { n: bestUseFormat(state.unlinkedRevenueRows) })) : ''}
          <section class="best-use-reasons"><span class="best-use-note-tag">${WFT('best_use.notes_tag', 'ملاحظات الاقتراح')}</span><h4>${WFT('best_use.reason_title', 'سبب اختيار هذا التوزيع')}</h4>
            <p>${escapeHtml(state.rationale || '')}</p>
            <p>${escapeHtml(state.setbackExplanation || '')}</p>
            ${rows.map(row => '<article><h5>' + escapeHtml(row.name || '') + '</h5><h6>' + WFT('best_use.pick_reason', 'سبب الاختيار') + '</h6><p>' + escapeHtml(row.reason || '') + '</p><h6>' + WFT('best_use.area_reason', 'أساس توزيع المساحة') + '</h6><p>' + escapeHtml(row.areaReason || '') + '</p></article>').join('')}
          </section>`;
      }
      const messages = document.getElementById('bestUseChatMessages');
      messages.innerHTML = '';
      const history = bestUseArray(bestUseChatState().messages);
      const chatSection = root.querySelector('.best-use-chat');
      if (chatSection) chatSection.hidden = !(state.id || history.length || bestUseBusy);
      if (!history.length) {
        const empty = document.createElement('p');
        empty.className = 'best-use-chat-empty';
        empty.textContent = WFT('best_use.chat_empty', 'لا توجد رسائل في هذه المحادثة.');
        messages.appendChild(empty);
      }
      history.forEach(item => {
        const bubble = document.createElement('div');
        bubble.className = 'best-use-chat-message ' + (item.role === 'user' ? 'user' : 'assistant');
        bubble.textContent = item.content || '';
        messages.appendChild(bubble);
      });
      if (bestUseBusy) {
        const pending = document.createElement('p');
        pending.textContent = WFT('best_use.busy', 'جاري معالجة التوزيع...');
        messages.appendChild(pending);
      }
      messages.scrollTop = messages.scrollHeight;
      persistBestUseDraftState();
    }

    function applyBestUseResponse(response, requestContext) {
      if (tenantProjectData?.draftId !== requestContext.draftId || response.draftId !== requestContext.draftId) {
        console.warn('[BEST-USE] response rejected: draft mismatch',
          { expected: requestContext.draftId, current: tenantProjectData?.draftId, received: response?.draftId });
        toast(WFT('best_use.local_changed', 'تغيّرت المدخلات الحالية أثناء المعالجة؛ لم تُستبدل المكونات المحلية.'));
        return false;
      }
      const fresh = (typeof draftEditCounter === 'undefined' || draftEditCounter === requestContext.editCounter)
        && bestUseStable(bestUseSourceSnapshot()) === bestUseStable(requestContext.sourceSnapshot);
      if (response.revision !== undefined) tenantDraftRevision = Number(response.revision);
      if (response.bestUse) tenantProjectData.best_use_data = bestUseObject(response.bestUse);
      if (response.chat) tenantProjectData.best_use_chat = bestUseObject(response.chat);
      if (response.sectionStatuses && typeof applySectionStatuses === 'function') applySectionStatuses(response.sectionStatuses);
      if (!bestUseSectionRequired()) delete tenantProjectSectionStatuses[BEST_USE_SECTION_KEY];
      if (response.componentsApplied && !fresh) {
        const current = bestUseSourceSnapshot();
        console.warn('[BEST-USE] response rejected: inputs changed while processing',
          { editCounter: typeof draftEditCounter === 'undefined' ? null : draftEditCounter,
            expectedEditCounter: requestContext.editCounter,
            changed: Object.keys({ ...requestContext.sourceSnapshot, ...current })
              .filter(key => bestUseStable(requestContext.sourceSnapshot[key]) !== bestUseStable(current[key])) });
        persistBestUseDraftState();
        toast(WFT('best_use.local_changed', 'تغيّرت المدخلات الحالية أثناء المعالجة؛ لم تُستبدل المكونات المحلية.'));
        renderBestUse();
        return false;
      }
      if (response.componentsApplied && response.financialModel) {
        applyBestUseFinancialModel(response);
      }
      persistBestUseDraftState();
      renderBestUse();
      return true;
    }

    async function bestUseAwaitJob(response, draftId) {
      if (!response?.success || !response.jobId) return response;
      const deadline = Date.now() + 310000;
      while (Date.now() < deadline && tenantProjectData?.draftId === draftId) {
        await new Promise(resolve => setTimeout(resolve, 1500));
        response = await api('GET', '/api/best-use/jobs/' + response.jobId);
        if (!response?.success || response.status === 'completed' || response.status === 'failed') return response;
        updateLoaderProgress(response.progress || 20, WFT('best_use.processing', 'تحليل بيانات الأرض والسوق والتوزيع'));
      }
      return { success: false, error_code: 'BEST_USE_JOB_INTERRUPTED' };
    }

    function runBestUseAction(action) {
      if (bestUseRequestTask) return bestUseRequestTask;
      const state = bestUseState();
      if (typeof tenantProjectMode !== 'undefined' && tenantProjectMode === 'presentation') return Promise.resolve(false);
      if (!hasPermission('create_presentation')) return Promise.resolve(false);
      if (action === 'approved' && !confirm(WFT('best_use.replace_confirm', 'اعتماد هذا التوزيع واستبدال جميع المكونات الحالية؟ سيعود قسم الدراسة المالية إلى مسودة.'))) return Promise.resolve(false);
      const input = document.getElementById('bestUseChatInput');
      const message = String(input?.value || '').trim();
      if (['chat', 'revise'].includes(action) && !message) return Promise.resolve(false);
      bestUseRequestTask = (async () => {
        bestUseBusy = true;
        renderBestUse();
        showLoader(WFT('best_use.processing_title', 'أفضل استخدامات'), WFT('best_use.saving', 'حفظ بيانات المشروع'), 5);
        try {
          const initialId = tenantProjectData.draftId;
          const initial = bestUseSourceSnapshot();
          if (!(await saveProjectAsDraft(true, false))) {
            console.warn('[BEST-USE]', action, 'aborted: draft save failed');
            toast(WFT('best_use.save_failed', 'تعذر حفظ المسودة قبل المتابعة.'));
            return false;
          }
          const afterSave = bestUseSourceSnapshot();
          if (tenantProjectData.draftId !== initialId || bestUseStable(initial) !== bestUseStable(afterSave)) {
            console.warn('[BEST-USE] inputs changed during save:',
              Object.keys({ ...initial, ...afterSave })
                .filter(key => bestUseStable(initial[key]) !== bestUseStable(afterSave[key])));
            toast(WFT('best_use.local_changed', 'تغيّرت المدخلات الحالية أثناء المعالجة؛ لم تُستبدل المكونات المحلية.'));
            return false;
          }
          const requestContext = { draftId: tenantProjectData.draftId,
            editCounter: typeof draftEditCounter === 'undefined' ? 0 : draftEditCounter,
            sourceSnapshot: afterSave };
          const payload = { draftId: requestContext.draftId, expectedRevision: tenantDraftRevision };
          let endpoint = 'decision';
          if (action === 'generate') endpoint = 'generate';
          else if (action === 'chat' || action === 'revise') {
            Object.assign(payload, { message, revise: action === 'revise' });
            endpoint = 'chat';
          }
          else Object.assign(payload, { proposalId: state.id, decision: action });
          updateLoaderProgress(20, WFT('best_use.processing', 'تحليل بيانات الأرض والسوق والتوزيع'));
          let response = await api('POST', '/api/best-use/' + endpoint, payload);
          response = await bestUseAwaitJob(response, requestContext.draftId);
          if (!response?.success) {
            console.warn('[BEST-USE]', action, 'request failed:', response);
            toast(bestUseErrorText(response));
            return false;
          }
          const received = applyBestUseResponse(response, requestContext);
          if (received && endpoint === 'chat' && input?.value.trim() === message) input.value = '';
          updateLoaderProgress(100, WFT('best_use.done', 'اكتملت المعالجة'));
          return received;
        } catch (error) {
          console.warn('[BEST-USE]', action, 'threw:', error);
          toast(WFT('best_use.failed', 'تعذر معالجة أفضل استخدامات.'));
          return false;
        } finally {
          bestUseBusy = false;
          hideLoader();
          renderBestUse();
        }
      })().finally(() => { bestUseRequestTask = null; });
      return bestUseRequestTask;
    }

    function sendBestUseChat(revise = false) { return runBestUseAction(revise ? 'revise' : 'chat'); }

    document.addEventListener('wf:lang', () => renderBestUse());
    document.addEventListener('input', event => {
      if (event.target?.closest('#tenantProjectForm') && event.target.id !== 'bestUseChatInput'
          && !window.__batchLoading && !bestUseBusy) renderBestUse();
    });
    document.addEventListener('change', event => {
      if (event.target?.closest('#tenantProjectForm') && !window.__batchLoading && !bestUseBusy) renderBestUse();
    });
