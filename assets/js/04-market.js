/* 04-market.js - index.html lines 10648-11652, shared global scope, classic scripts in order */

    function collectMarketStudyFromDom() {
      const state = getMarketStudyState();
      state.competitor_radius = document.getElementById('marketCompetitorRadius')?.value || state.competitor_radius;
      state.competitor_radius_custom_km = document.getElementById('marketCompetitorRadiusCustom')?.value || '';
      state.data_period = document.getElementById('marketDataPeriod')?.value || state.data_period;
      state.data_period_from = document.getElementById('marketDataPeriodFrom')?.value || '';
      state.data_period_to = document.getElementById('marketDataPeriodTo')?.value || '';
      state.competitors = collectMarketCompetitorRows();
      const summary = {};
      MARKET_STUDY_SUMMARY_SECTIONS.forEach(item => {
        summary[item.key] = document.getElementById('marketSummary_' + item.key)?.value || '';
      });
      state.summary = summary;
      const swot = {};
      MARKET_STUDY_SWOT_SECTIONS.forEach(item => {
        swot[item.key] = document.getElementById('marketSwot_' + item.key)?.value || '';
      });
      state.swot = swot;
      state.decision = document.getElementById('marketDecision')?.value || '';
      state.disclaimer = document.getElementById('marketDisclaimer')?.value || state.disclaimer;
      state.sources = mergeMarketSourceRows(
        collectMarketSourceRows(),
        buildMarketCompetitorSourceRows(state.competitors)
      );
      state.one_block_summary = buildMarketStudyOneBlockSummary(state);
      return state;
    }

    function persistMarketStudyFromDom() {
      setMarketStudyState(collectMarketStudyFromDom());
    }

    function refreshDynamicI18n(scope) {
      try {
        if (typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en' && scope) {
          window.WFI18n.autoTranslate(scope);
        }
      } catch (e) { /* ignore */ }
    }

    // Fragment translator for chrome/data composites (option labels, card metas):
    // exact-match auto-translate cannot split them, so chrome fragments are
    // resolved at build time from the shared EN_AUTO map. Data stays untouched.
    function trDynamicI18n(text) {
      try {
        if (typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en') {
          const dict = window.WFI18n.autoDict || {};
          if (text && dict[text]) return dict[text];
        }
      } catch (e) { /* ignore */ }
      return text;
    }

    function addMarketStudySection(form, before) {
      const div = document.createElement('div');
      div.className = 'tenant-form-section';
      div.id = 'section-market-study';
      div.dataset.section = 'section-market-study';
      div.appendChild(createProjectSectionHeader('section-market-study', 'دراسة السوق'));
      const body = document.createElement('div');
      body.className = 'market-study-body';
      body.innerHTML = `
        <div class="market-block">
          <h4>نطاق الدراسة</h4>
          <div class="market-grid">
            <div><label>نطاق المنافسين</label>
              <select id="marketCompetitorRadius">
                <option value="3">3 كم</option>
                <option value="5">5 كم</option>
                <option value="10" selected>10 كم</option>
                <option value="city">كامل المدينة</option>
                <option value="custom">نطاق مخصص</option>
              </select>
            </div>
            <div id="marketCustomRadiusWrap" hidden><label>النطاق المخصص (كم)</label><input id="marketCompetitorRadiusCustom" type="number" min="1" step="0.1"></div>
            <div><label>فترة البيانات</label>
              <select id="marketDataPeriod">
                <option value="12m">آخر 12 شهرًا</option>
                <option value="24m">آخر 24 شهرًا</option>
                <option value="3y">آخر 3 سنوات</option>
                <option value="5y">آخر 5 سنوات</option>
                <option value="custom">فترة مخصصة</option>
              </select>
            </div>
            <div id="marketCustomPeriodWrap" hidden>
              <label>من تاريخ</label><input id="marketDataPeriodFrom" type="date">
              <label style="margin-top:8px">إلى تاريخ</label><input id="marketDataPeriodTo" type="date">
            </div>
          </div>
          <div class="market-grid" style="margin-top:12px">
            <div><label>المدينة</label><input id="marketCityMirror" readonly></div>
            <div><label>الحي</label><input id="marketDistrictMirror" readonly></div>
          </div>
        </div>
        <div class="market-block">
          <h4>المنافسون</h4>
          <div class="market-actions">
            <button type="button" class="btn ghost" onclick="addMarketCompetitorRow()">إضافة منافس</button>
            <button type="button" class="btn ghost" id="marketFillCompetitorsBtn" onclick="runMarketCompetitorsJob('fill')">إكمال بيانات المنافسين بالاسم</button>
            <button type="button" class="btn primary" id="marketGenerateCompetitorsBtn" onclick="runMarketCompetitorsJob('generate')">توليد المنافسين</button>
          </div>
          <div id="marketCompetitorsNote"></div>
          <div class="table-wrap">
            <table id="marketCompetitorsTable">
              <thead><tr>
                <th>اسم المشروع</th><th>الشعار</th><th>النوع</th><th>التصنيف</th><th>المساحة م²</th><th>الحالة</th><th>المصدر</th>
                <th>نوع العملية</th><th>نوع السعر</th><th>القيمة (ر.س)</th><th></th>
              </tr></thead>
              <tbody></tbody>
            </table>
          </div>
        </div>
        <div class="market-block">
          <h4>الملخص التنفيذي لسوق المشروع</h4>
          <div class="market-actions">
            <button type="button" class="btn primary" id="marketGenerateSummaryBtn" onclick="runMarketSummaryJob()">توليد ملخص السوق</button>
          </div>
          <div id="marketSummaryFailure"></div>
          <div id="marketSummaryCompare" hidden></div>
          <div id="marketSummaryFields"></div>
          <h4 style="margin-top:18px">تحليل SWOT</h4>
          <div id="marketSwotFields"></div>
          <div style="margin-top:12px"><label>تصنيف القرار</label>
            <select id="marketDecision">
              <option value="">-- اختر القيمة --</option>
              <option>فرصة قوية</option>
              <option>فرصة واعدة بشروط</option>
              <option>فرصة متوسطة</option>
              <option>فرصة مرتفعة المخاطر</option>
              <option>البيانات غير كافية</option>
            </select>
          </div>
          <div style="margin-top:12px"><label>إخلاء المسؤولية</label>
            <textarea id="marketDisclaimer" rows="2"></textarea>
          </div>
        </div>
        <div class="market-block">
          <h4>ملخص دراسة سوق العمل</h4>
          <textarea id="marketStudyOneBlockSummary" rows="18" readonly></textarea>
        </div>
        <div class="market-block">
          <h4>المصادر</h4>
          <div class="market-actions">
            <button type="button" class="btn ghost" onclick="addMarketSourceRow()">إضافة مصدر</button>
          </div>
          <div id="marketSourcesTabs" class="market-source-tabs" role="tablist"></div>
          <div id="marketSourcesPanels" class="market-source-panels"></div>
        </div>
        <input type="hidden" data-key="market_study_data" data-type="text" id="marketStudyData">
      `;
      div.appendChild(body);
      if (before) form.insertBefore(div, before);
      else form.appendChild(div);
      const summaryHost = document.getElementById('marketSummaryFields');
      if (summaryHost) {
        summaryHost.innerHTML = MARKET_STUDY_SUMMARY_SECTIONS.map(item =>
          '<div style="margin-top:12px"><label>' + item.label + '</label>' +
          '<textarea id="marketSummary_' + item.key + '" rows="4"></textarea></div>'
        ).join('');
      }
      const swotHost = document.getElementById('marketSwotFields');
      if (swotHost) {
        swotHost.innerHTML = MARKET_STUDY_SWOT_SECTIONS.map(item =>
          '<div style="margin-top:12px"><label>' + item.label + '</label>' +
          '<textarea id="marketSwot_' + item.key + '" rows="4"></textarea></div>'
        ).join('');
      }
      ['marketCompetitorRadius', 'marketDataPeriod'].forEach(id => {
        document.getElementById(id)?.addEventListener('change', () => {
          updateMarketStudyFieldVisibility();
          persistMarketStudyFromDom();
        });
      });
      ['marketCompetitorRadiusCustom', 'marketDataPeriodFrom', 'marketDataPeriodTo', 'marketDecision', 'marketDisclaimer']
        .forEach(id => document.getElementById(id)?.addEventListener('input', persistMarketStudyFromDom));
      MARKET_STUDY_SUMMARY_SECTIONS.forEach(item => {
        document.getElementById('marketSummary_' + item.key)?.addEventListener('input', persistMarketStudyFromDom);
      });
      MARKET_STUDY_SWOT_SECTIONS.forEach(item => {
        document.getElementById('marketSwot_' + item.key)?.addEventListener('input', persistMarketStudyFromDom);
      });
      refreshDynamicI18n(div);
    }

    function updateMarketStudyFieldVisibility() {
      const radius = document.getElementById('marketCompetitorRadius')?.value;
      const period = document.getElementById('marketDataPeriod')?.value;
      const radiusWrap = document.getElementById('marketCustomRadiusWrap');
      const periodWrap = document.getElementById('marketCustomPeriodWrap');
      if (radiusWrap) radiusWrap.hidden = radius !== 'custom';
      if (periodWrap) periodWrap.hidden = period !== 'custom';
    }

    function syncMarketLocationMirrors() {
      const city = document.querySelector('#tenantProjectForm [data-key="city"]')?.value || tenantProjectData.city || '';
      const district = document.querySelector('#tenantProjectForm [data-key="district"]')?.value || tenantProjectData.district || '';
      const cityMirror = document.getElementById('marketCityMirror');
      const districtMirror = document.getElementById('marketDistrictMirror');
      if (cityMirror) {
        cityMirror.readOnly = true;
        cityMirror.setAttribute('aria-readonly', 'true');
        cityMirror.value = city;
      }
      if (districtMirror) {
        districtMirror.readOnly = true;
        districtMirror.setAttribute('aria-readonly', 'true');
        districtMirror.value = district;
      }
    }

    function applyCityDistrictToForm(city, district, overwrite = false) {
      const cityInput = document.querySelector('#tenantProjectForm [data-key="city"]');
      const districtInput = document.querySelector('#tenantProjectForm [data-key="district"]');
      if (city && cityInput && (overwrite || !String(cityInput.value || '').trim())) {
        cityInput.value = city;
        tenantProjectData.city = city;
      }
      if (district && districtInput && (overwrite || !String(districtInput.value || '').trim())) {
        districtInput.value = district;
        tenantProjectData.district = district;
      }
      syncMarketLocationMirrors();
    }

    function fillSelectOptions(select, options, current, placeholder) {
      if (!select) return;
      const value = current == null ? select.value : current;
      select.innerHTML = '';
      const empty = document.createElement('option');
      empty.value = '';
      empty.textContent = placeholder || '-- اختر القيمة --';
      select.appendChild(empty);
      (options || []).forEach(option => {
        const item = document.createElement('option');
        item.value = option;
        item.textContent = option;
        select.appendChild(item);
      });
      if (value && !(options || []).includes(value)) {
        const extra = document.createElement('option');
        extra.value = value;
        extra.textContent = value;
        select.appendChild(extra);
      }
      if (value) select.value = value;
      if (value && select.value !== value) select.value = '';
      refreshDynamicI18n(select);
    }

    function keepProjectMultiSelectOpen(hostId) {
      setTimeout(() => {
        const host = document.getElementById(hostId);
        const details = host && host.matches('details') ? host : host?.querySelector('details');
        if (details) details.open = true;
      }, 0);
    }

    function closeOtherProjectMultiSelects(current) {
      document.querySelectorAll('.project-multi-select[open]').forEach(dropdown => {
        if (dropdown !== current) dropdown.open = false;
      });
    }

    function renderMultiSelectDropdown(host, options, selected, placeholder, onChange, closeAfterSelection = false) {
      if (!host) return;
      const choices = (options || []).map(String);
      const selectedValues = Array.isArray(selected) ? selected.map(String) : [];
      const isEn = typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en';
      const trVal = (val) => (isEn && typeof WFI18N_EN_AUTO !== 'undefined' && WFI18N_EN_AUTO[val]) ? WFI18N_EN_AUTO[val] : val;
      const formatSummary = (vals) => vals.length ? (isEn ? vals.map(trVal).join(', ') : vals.join('، ')) : trVal(placeholder);
      const signature = JSON.stringify({ choices, selectedValues, placeholder, closeAfterSelection, lang: isEn ? 'en' : 'ar' });
      const existing = host.querySelector('details.project-multi-select');
      if (existing && host.dataset.multiSelectSignature === signature) return;
      const keepOpen = existing?.open === true;
      host.dataset.multiSelectSignature = signature;
      const picked = new Set(selectedValues);
      host.innerHTML = '<details class="project-multi-select"><summary></summary><div class="project-multi-select-menu">' +
        choices.map(value => '<button type="button" class="project-multi-select-option' +
          (picked.has(value) ? ' selected' : '') + '" data-value="' + escapeHtml(value) + '">' +
          escapeHtml(trVal(value)) + '</button>').join('') + '</div></details>';
      const details = host.querySelector('details');
      const summary = host.querySelector('summary');
      const update = () => {
        const next = choices.filter(value => picked.has(value));
        if (summary) summary.textContent = formatSummary(next);
        host.dataset.multiSelectSignature = JSON.stringify({ choices, selectedValues: next, placeholder, closeAfterSelection, lang: isEn ? 'en' : 'ar' });
        if (closeAfterSelection && details) details.open = false;
        if (typeof onChange === 'function') onChange(next);
      };
      if (summary) summary.textContent = formatSummary(selectedValues);
      host.querySelectorAll('.project-multi-select-option').forEach(button => {
        button.addEventListener('click', () => {
          const value = button.dataset.value || '';
          if (picked.has(value)) picked.delete(value);
          else picked.add(value);
          button.classList.toggle('selected', picked.has(value));
          update();
        });
      });
      details?.addEventListener('toggle', () => {
        if (details.open) closeOtherProjectMultiSelects(details);
      });
      details?.addEventListener('click', event => event.stopPropagation());
      if (keepOpen && details) details.open = true;
    }

    function renderChoiceGrid(host, key, options, selected) {
      renderMultiSelectDropdown(host, options, selected, 'اختر قيمة أو أكثر', values => {
        const hidden = document.querySelector('#tenantProjectForm [data-key="' + key + '"]');
        const encoded = JSON.stringify(values);
        if (hidden) hidden.value = encoded;
        tenantProjectData[key] = encoded;
        if (key === 'project_subtype') syncProjectClassificationFields();
        triggerAutoSaveDraft();
      });
    }

    function syncProjectClassificationFields() {
      const mains = selectedProjectTypeMains();
      const typeInput = document.querySelector('#tenantProjectForm [data-key="project_type"]');
      const typeHost = document.getElementById('projectTypeGrid');
      if (typeInput) {
        typeInput.type = 'hidden';
        typeInput.style.display = 'none';
        persistProjectTypes(mains);
        if (typeHost) {
          renderMultiSelectDropdown(typeHost, MARKET_PROJECT_TYPES, mains, 'اختر نوعًا أو أكثر', selected => {
            persistProjectTypes(selected);
            triggerAutoSaveDraft();
            syncProjectClassificationFields();
            keepProjectMultiSelectOpen('projectTypeGrid');
          });
        }
      }
      const mixedInput = document.querySelector('#tenantProjectForm [data-key="project_mixed_components"]');
      const mixedHost = document.getElementById('projectMixedComponentsGrid');
      if (mixedInput) {
        mixedInput.type = 'hidden';
        mixedInput.style.display = 'none';
        const mixedWrap = mixedInput.closest('.tenant-field');
        if (mixedWrap) mixedWrap.style.display = 'none';
        if (mixedHost) mixedHost.innerHTML = '';
      }
      const subtypeInput = document.querySelector('#tenantProjectForm [data-key="project_subtype"]');
      const subtypeHost = document.getElementById('projectSubtypeGrid');
      if (subtypeInput) {
        subtypeInput.type = 'hidden';
        subtypeInput.style.display = 'none';
        const wrap = subtypeInput.closest('.tenant-field');
        const subtypeOptions = mains.flatMap(typeName => MARKET_SUBTYPES[typeName] || []);
        if (wrap) wrap.style.display = subtypeOptions.length ? '' : 'none';
        const currentSubtypes = selectedProjectSubtypesByMain();
        const prunedSubtypes = {};
        mains.forEach(typeName => {
          if ((currentSubtypes[typeName] || []).length) prunedSubtypes[typeName] = currentSubtypes[typeName];
        });
        const hasStaleSubtypes = Object.keys(currentSubtypes).some(typeName => !mains.includes(typeName));
        if (hasStaleSubtypes) persistGroupedChoice(subtypeInput, prunedSubtypes);
        if (subtypeHost) renderProjectSubtypeFields(mains, subtypeHost, subtypeInput);
      }
      refreshClassificationDependents();
    }

    function refreshClassificationDependents() {
      const mains = selectedProjectTypeMains();
      const classInput = document.querySelector('#tenantProjectForm [data-key="activity_class"]');
      const levelInput = document.querySelector('#tenantProjectForm [data-key="project_level"]');
      const audienceHidden = document.querySelector('#tenantProjectForm [data-key="target_audience"]');
      const audienceHost = document.getElementById('projectAudienceGrid');
      renderActivityClassFields(mains, false, projectAnalysisKinds(), classInput, levelInput);
      if (audienceHost && audienceHidden) {
        const audienceWrap = audienceHidden.closest('.tenant-field');
        const hasAudience = mains.includes('سكني') || mains.some(typeName => (selectedProjectSubtypesByMain()[typeName] || []).length > 0);
        if (!mains.length || !hasAudience) {
          audienceHost.innerHTML = '';
          audienceHost.dataset.audienceSignature = '';
          if (audienceWrap) audienceWrap.style.display = 'none';
        } else {
          if (audienceWrap) audienceWrap.style.display = '';
          renderGroupedAudienceFields(mains, audienceHidden, audienceHost);
        }
      }
      refreshAllowedUsesStatusNote();
    }

    function persistClassificationDraftState() {
      persistProjectTypes(selectedProjectTypeMains());
      const subtypeInput = document.querySelector('#tenantProjectForm [data-key="project_subtype"]');
      if (subtypeInput) persistGroupedChoiceValue(subtypeInput, selectedProjectSubtypesByMain());
      const audienceInput = document.querySelector('#tenantProjectForm [data-key="target_audience"]');
      if (audienceInput) persistGroupedChoiceValue(audienceInput, groupedAudienceSelection());
      const classInput = document.querySelector('#tenantProjectForm [data-key="activity_class"]');
      if (classInput) {
        classInput.type = 'hidden';
        const stored = tenantProjectData.activity_class;
        if (Array.isArray(stored) || (stored && typeof stored === 'object')) {
          classInput.value = JSON.stringify(stored);
        } else {
          classInput.value = String(stored || classInput.value || '');
        }
        tenantProjectData.activity_class = classInput.value;
      }
      const mixedInput = document.querySelector('#tenantProjectForm [data-key="project_mixed_components"]');
      if (mixedInput) {
        mixedInput.type = 'hidden';
        mixedInput.value = String(tenantProjectData.project_mixed_components || mixedInput.value || '');
      }
    }

    function renderProjectSubtypeFields(mains, host, hidden) {
      if (!host || !hidden) return;
      const current = selectedProjectSubtypesByMain();
      const groups = (mains || []).map(main => ({ main, options: MARKET_SUBTYPES[main] || [] }))
        .filter(group => group.options.length);
      if (!groups.length) {
        host.innerHTML = '';
        host.dataset.subtypeSignature = '';
        return;
      }
      const isEn = typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en';
      const trVal = (val) => (isEn && typeof WFI18N_EN_AUTO !== 'undefined' && WFI18N_EN_AUTO[val]) ? WFI18N_EN_AUTO[val] : val;
      const showSubtypeLabels = groups.length > 1;
      const signature = JSON.stringify({ groups: groups.map(group => group.main), lang: isEn ? 'en' : 'ar' });
      if (host.dataset.subtypeSignature !== signature) {
        host.dataset.subtypeSignature = signature;
        host.innerHTML = groups.map((group, index) => {
          const rawLbl = MARKET_SUBTYPE_LABELS[group.main] || ('الأنواع الفرعية ل' + group.main);
          const lbl = isEn ? (WFI18N_EN_AUTO[rawLbl] || (trVal(group.main) + ' Subtypes')) : rawLbl;
          return '<div style="margin-top:10px"><label>' + (showSubtypeLabels ? lbl : '') +
            '</label><div data-subtype-group-index="' + index + '"></div></div>';
        }).join('');
      }
      groups.forEach((group, index) => {
        const groupHost = host.querySelector('[data-subtype-group-index="' + index + '"]');
        renderMultiSelectDropdown(groupHost, group.options, current[group.main] || [], 'اختر نوعًا فرعيًا أو أكثر', selected => {
          const next = selectedProjectSubtypesByMain();
          if (selected.length) next[group.main] = selected;
          else delete next[group.main];
          persistGroupedChoice(hidden, next);
          refreshClassificationDependents();
        });
      });
    }

    function groupedAudienceSelection() {
      const hidden = document.querySelector('#tenantProjectForm [data-key="target_audience"]');
      const raw = (hidden && hidden.value) || tenantProjectData.target_audience;
      const parsed = parseStoredLandTable(raw);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        const mapped = {};
        Object.entries(parsed).forEach(([typeName, values]) => {
          mapped[typeName] = [...new Set(parseSelectedMarketList(values))];
        });
        return mapped;
      }
      return { general: [...new Set(parseSelectedMarketList(raw))] };
    }

    function encodeGroupedChoiceValue(groups) {
      const encoded = JSON.stringify(groups || {});
      return encoded === '{}' ? '' : encoded;
    }

    function persistGroupedChoiceValue(hidden, groups, markDirty = false) {
      const encoded = encodeGroupedChoiceValue(groups);
      if (hidden) hidden.value = encoded;
      if (hidden?.dataset?.key) tenantProjectData[hidden.dataset.key] = encoded;
      if (markDirty) triggerAutoSaveDraft();
      return encoded;
    }

    function setGroupedChoiceValue(hidden, groups, markDirty = true) {
      persistGroupedChoiceValue(hidden, groups, markDirty);
    }

    function persistGroupedChoice(hidden, groups) {
      persistGroupedChoiceValue(hidden, groups, true);
    }

    function audienceGroupInfo(main, subtype) {
      const parent = main === 'متعدد الاستخدامات' ? parentMainForSubtype(subtype) : main;
      const kind = audienceKindForMain(parent, subtype) || parent;
      return { parent, kind };
    }

    function audienceValuesForGroup(current, group) {
      const values = [];
      [group.key, ...(group.legacyKeys || [])].forEach(key => {
        values.push(...parseSelectedMarketList(current[key]));
      });
      return [...new Set(values)];
    }

    function renderGroupedAudienceFields(mains, hidden, host) {
      const current = groupedAudienceSelection();
      const subtypeMap = selectedProjectSubtypesByMain();
      const groups = [];
      const addGroup = (main, subtype = '') => {
        const info = audienceGroupInfo(main, subtype);
        const legacyKey = subtype ? main + '::' + subtype : main;
        let group = groups.find(item => item.kind === info.kind);
        if (!group) {
          group = {
            key: 'audience::' + info.kind,
            kind: info.kind,
            parent: info.parent,
            subtype,
            subtypes: [],
            legacyKeys: []
          };
          groups.push(group);
        }
        if (subtype && !group.subtypes.includes(subtype)) group.subtypes.push(subtype);
        if (!group.legacyKeys.includes(legacyKey)) group.legacyKeys.push(legacyKey);
      };
      (mains || []).forEach(main => {
        const selectedSubtypes = subtypeMap[main] || [];
        if (main === 'سكني') addGroup(main);
        else if (['تجاري', 'فندقي', 'صناعي ولوجستي', 'متعدد الاستخدامات'].includes(main)) {
          [...new Set(selectedSubtypes)].forEach(subtype => addGroup(main, subtype));
        }
      });
      if (!groups.length) {
        host.innerHTML = '';
        host.dataset.audienceSignature = '';
        return;
      }
      const normalized = {};
      groups.forEach(group => {
        const selected = audienceValuesForGroup(current, group);
        if (selected.length) normalized[group.key] = selected;
      });
      if (groups.length === 1 && !Object.keys(normalized).length && current.general?.length) {
        normalized[groups[0].key] = [...new Set(current.general)];
      }
      if (Object.keys(normalized).length && JSON.stringify(current) !== JSON.stringify(normalized)) {
        persistGroupedChoiceValue(hidden, normalized, false);
      }
      const isEn = typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en';
      const trVal = (val) => (isEn && typeof WFI18N_EN_AUTO !== 'undefined' && WFI18N_EN_AUTO[val]) ? WFI18N_EN_AUTO[val] : val;
      const signature = JSON.stringify({ groups: groups.map(group => group.key), lang: isEn ? 'en' : 'ar' });
      if (host.dataset.audienceSignature !== signature) {
        host.dataset.audienceSignature = signature;
        host.innerHTML = groups.map((group, index) => {
          const subtypeText = group.subtypes.length ? (' (' + (isEn ? group.subtypes.map(trVal).join(', ') : group.subtypes.join('، ')) + ')') : '';
          const rawLabel = MARKET_AUDIENCE_LABELS[group.kind] || ('الفئة المستهدفة ل' + group.kind);
          const label = isEn ? (WFI18N_EN_AUTO[rawLabel] || (trVal(group.kind) + ' Target Audience')) : rawLabel;
          return '<div style="margin-top:10px"><label>' + label + subtypeText +
            '</label><div data-audience-group-index="' + index + '"></div></div>';
        }).join('');
      }
      groups.forEach((group, index) => {
        const groupHost = host.querySelector('[data-audience-group-index="' + index + '"]');
        const options = audienceOptionsForMain(group.parent, group.subtype).filter(option => option !== 'أخرى');
        const selected = audienceValuesForGroup(current, group);
        renderMultiSelectDropdown(groupHost, options, selected, 'اختر فئة أو أكثر', values => {
          const next = groupedAudienceSelection();
          delete next.general;
          (group.legacyKeys || []).forEach(key => {
            if (key !== group.key) delete next[key];
          });
          next[group.key] = values;
          setGroupedChoiceValue(hidden, next);
        });
      });
    }

    function classificationGroupsForProject(mains, isOther, kinds) {
      const groups = [];
      const addGroup = (typeName) => {
        const specializedKind = MARKET_SPECIALIZED_CLASS_KINDS.includes(typeName)
          ? typeName
          : (MARKET_SPECIALIZED_CLASS_KINDS.includes(marketAudienceKind(typeName)) ? marketAudienceKind(typeName) : '');
        const key = specializedKind || typeName;
        if (key && !groups.includes(key)) groups.push(key);
      };
      const subtypeMap = selectedProjectSubtypesByMain();
      (mains || []).forEach(main => {
        const subtypes = subtypeMap[main] || [];
        if (main === 'سكني') {
          addGroup(main);
        } else if (main === 'متعدد الاستخدامات') {
          subtypes.forEach(subtype => addGroup(parentMainForSubtype(subtype) === 'تجاري' && subtype === 'مكاتب' ? 'مكاتب' : parentMainForSubtype(subtype)));
        } else if (['تجاري', 'فندقي', 'صناعي ولوجستي'].includes(main)) {
          subtypes.forEach(subtype => addGroup(main === 'تجاري' && subtype === 'مكاتب' ? 'مكاتب' : main));
        }
      });
      return groups;
    }

    function renderActivityClassFields(mains, isOther, kinds, classInput, levelInput) {
      if (levelInput) {
        const levelWrap = levelInput.closest('.tenant-field');
        if (levelWrap) levelWrap.style.display = 'none';
        levelInput.style.display = 'none';
      }
      if (!classInput) return;
      const wrap = classInput.closest('.tenant-field');
      const host = document.getElementById('projectActivityClassFields');
      const groups = classificationGroupsForProject(mains, isOther, kinds);
      classInput.style.display = 'none';
      const isEn = typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en';
      const trVal = (val) => (isEn && typeof WFI18N_EN_AUTO !== 'undefined' && WFI18N_EN_AUTO[val]) ? WFI18N_EN_AUTO[val] : val;
      if (wrap) {
        wrap.style.display = groups.length ? '' : 'none';
        const fieldLabel = wrap.querySelector(':scope > label');
        if (fieldLabel) fieldLabel.textContent = trVal('تصنيف النشاط');
      }
      if (!host) return;
      const stored = parseStoredLandTable(classInput.value || tenantProjectData.activity_class || tenantProjectData.project_level);
      const current = (stored && typeof stored === 'object' && !Array.isArray(stored))
        ? stored
        : { value: classInput.value || tenantProjectData.activity_class || tenantProjectData.project_level || '' };
      host.innerHTML = groups.map(kind => {
        const specialized = MARKET_ACTIVITY_CLASS[kind] || MARKET_ACTIVITY_CLASS[marketAudienceKind(kind)];
        const options = specialized || MARKET_PROJECT_LEVELS;
        const selected = current[kind] || (groups.length === 1 ? (current.value || '') : '');
        const selectOptions = '<option value="">' + trVal('-- اختر القيمة --') + '</option>' + options.map(option =>
          '<option value="' + String(option).replace(/"/g, '&quot;') + '"' +
          (option === selected ? ' selected' : '') + '>' + trVal(option) + '</option>'
        ).join('');
        const rawHint = MARKET_ACTIVITY_CLASS_LABELS[kind] || MARKET_ACTIVITY_CLASS_LABELS[marketAudienceKind(kind)] || kind;
        const hint = isEn ? (WFI18N_EN_AUTO[rawHint] || trVal(rawHint)) : rawHint;
        return groups.length > 1
          ? '<div style="margin-top:10px"><div class="tenant-hint" style="margin-bottom:6px">' + hint +
          '</div><select data-activity-kind="' + kind + '">' + selectOptions + '</select></div>'
          : '<select data-activity-kind="' + kind + '">' + selectOptions + '</select>';
      }).join('');
      const persist = () => {
        const next = {};
        host.querySelectorAll('[data-activity-kind]').forEach(select => {
          if (select.value) next[select.dataset.activityKind] = select.value;
        });
        const encoded = Object.keys(next).length ? JSON.stringify(next) : '';
        classInput.value = encoded;
        tenantProjectData.activity_class = encoded;
        if (levelInput) {
          const genericValues = Object.entries(next)
            .filter(([kind]) => !MARKET_SPECIALIZED_CLASS_KINDS.includes(kind) && !MARKET_ACTIVITY_CLASS[kind])
            .map(([, value]) => value);
          levelInput.value = genericValues[0] || '';
          tenantProjectData.project_level = levelInput.value;
        }
        triggerAutoSaveDraft();
      };
      host.querySelectorAll('select').forEach(select => select.addEventListener('change', persist));
    }

    function enhanceProjectClassificationFields() {
      const subtypeInput = document.querySelector('#tenantProjectForm [data-key="project_subtype"]');
      const mixedInput = document.querySelector('#tenantProjectForm [data-key="project_mixed_components"]');
      const audienceInput = document.querySelector('#tenantProjectForm [data-key="target_audience"]');
      const typeInput = document.querySelector('#tenantProjectForm [data-key="project_type"]');
      const classInput = document.querySelector('#tenantProjectForm [data-key="activity_class"]');
      if (typeInput && !document.getElementById('projectTypeGrid')) {
        typeInput.type = 'hidden';
        typeInput.style.display = 'none';
        const grid = document.createElement('div');
        grid.id = 'projectTypeGrid';
        grid.className = 'project-choice-grid';
        typeInput.insertAdjacentElement('afterend', grid);
      }
      if (mixedInput) {
        mixedInput.type = 'hidden';
        mixedInput.style.display = 'none';
        const mixedWrap = mixedInput.closest('.tenant-field');
        if (mixedWrap) mixedWrap.style.display = 'none';
      }
      if (subtypeInput && !document.getElementById('projectSubtypeGrid')) {
        subtypeInput.type = 'hidden';
        const grid = document.createElement('div');
        grid.id = 'projectSubtypeGrid';
        grid.className = 'project-choice-grid';
        subtypeInput.insertAdjacentElement('afterend', grid);
      }
      if (classInput && !document.getElementById('projectActivityClassFields')) {
        const host = document.createElement('div');
        host.id = 'projectActivityClassFields';
        classInput.insertAdjacentElement('afterend', host);
      }
      if (audienceInput && !document.getElementById('projectAudienceGrid')) {
        audienceInput.style.display = 'none';
        const grid = document.createElement('div');
        grid.id = 'projectAudienceGrid';
        grid.className = 'project-choice-grid';
        audienceInput.insertAdjacentElement('afterend', grid);
      }
      if (typeInput && !typeInput.dataset.classificationBound) {
        typeInput.dataset.classificationBound = '1';
        typeInput.addEventListener('change', syncProjectClassificationFields);
      }
      if (subtypeInput && !subtypeInput.dataset.classificationBound) {
        subtypeInput.dataset.classificationBound = '1';
        subtypeInput.addEventListener('change', syncProjectClassificationFields);
      }
      ['city', 'district'].forEach(key => {
        document.querySelector('#tenantProjectForm [data-key="' + key + '"]')
          ?.addEventListener('input', () => {
            tenantProjectData[key] = document.querySelector('#tenantProjectForm [data-key="' + key + '"]').value;
            syncMarketLocationMirrors();
          });
      });
      if (!window.__wfClassificationLangBound) {
        window.__wfClassificationLangBound = true;
        document.addEventListener('wf:lang', () => {
          try { syncProjectClassificationFields(); } catch (e) { /* ignore */ }
          try { renderLocationWorkflowState(); } catch (e) { /* ignore */ }
          try {
            const isEn = typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en';
            const dict = (typeof window.WFI18n !== 'undefined' && window.WFI18n.autoDict) || (typeof WFI18N_EN_AUTO !== 'undefined' ? WFI18N_EN_AUTO : (window.WFI18N_EN_AUTO || null));
            document.querySelectorAll('#tenantProjectForm label[data-ar-label]').forEach(lblEl => {
              const raw = lblEl.dataset.arLabel;
              const req = lblEl.dataset.isRequired === '1' ? ' *' : '';
              const badge = lblEl.querySelector('.tenant-client-required-badge');
              let text = raw;
              if (isEn && dict) {
                text = dict[raw] || (raw.indexOf('²') !== -1 && dict[raw.replace(/²/g, '2')]) || (raw.indexOf('2') !== -1 && dict[raw.replace(/2/g, '²')]) || raw;
              }
              lblEl.textContent = text + req;
              if (badge) {
                badge.textContent = isEn ? 'Client-Entered Only' : 'إدخال العميل';
                lblEl.appendChild(badge);
              }
            });
            document.querySelectorAll('.tenant-section-title').forEach(st => {
              const secLbl = st.querySelector('.project-section-title-label');
              if (secLbl && secLbl.dataset.arText) {
                secLbl.textContent = isEn && dict && dict[secLbl.dataset.arText] ? dict[secLbl.dataset.arText] : secLbl.dataset.arText;
              }
              const b = st.querySelector('.section-status-badge');
              if (b && b.dataset.arText) {
                b.textContent = isEn && dict && dict[b.dataset.arText] ? dict[b.dataset.arText] : b.dataset.arText;
              }
              const genBtn = st.querySelector('.section-presentation-btn');
              if (genBtn && genBtn.dataset.arText) {
                genBtn.textContent = isEn && dict && dict[genBtn.dataset.arText] ? dict[genBtn.dataset.arText] : genBtn.dataset.arText;
              }
              const lockBtn = st.querySelector('.section-approve-btn:not(.section-presentation-btn)');
              if (lockBtn && lockBtn.dataset.arText) {
                lockBtn.textContent = isEn && dict && dict[lockBtn.dataset.arText] ? dict[lockBtn.dataset.arText] : lockBtn.dataset.arText;
              }
            });
            const formEl = document.getElementById('tenantProjectForm');
            if (formEl && isEn && typeof window.WFI18n !== 'undefined') {
              window.WFI18n.autoTranslate(formEl);
            }
          } catch (e) { /* ignore */ }
        });
      }
      syncProjectClassificationFields();
    }

    function marketValueList(value) {
      if (Array.isArray(value)) return value.reduce((items, item) => items.concat(marketValueList(item)), []);
      if (value && typeof value === 'object') {
        return ['url', 'urls', 'source_url', 'source_urls', 'sourceUrl', 'sourceUrls', 'href'].reduce((items, key) =>
          items.concat(marketValueList(value[key])), []);
      }
      const text = String(value || '').trim();
      if (!text) return [];
      const urls = text.match(/https?:\/\/[^\s<>"'\[\]{}]+/g);
      if (urls && urls.length) return urls.map(url => url.replace(/[.,،;:!?)]}]+$/g, ''));
      try {
        const parsed = JSON.parse(text);
        if (parsed && typeof parsed === 'object') return marketValueList(parsed);
      } catch (error) {
        return text.split(/[\r\n,،;|]+/).map(item => item.trim()).filter(Boolean);
      }
      return [text];
    }

    function marketFieldSources(row = {}) {
      const raw = row.field_sources || row.fieldSources || {};
      const entries = [];
      if (Array.isArray(raw)) {
        raw.forEach(item => {
          if (!item || typeof item !== 'object') return;
          const field = item.field || item.key || item.name;
          const urls = item.urls || item.source_urls || item.sourceUrls || item.url;
          if (field) entries.push([field, urls]);
        });
      } else if (raw && typeof raw === 'object') {
        entries.push(...Object.entries(raw));
      }
      const result = {};
      entries.forEach(([field, value]) => {
        const urls = Array.from(new Set(marketValueList(value)
          .map(item => String(item || '').trim())
          .filter(item => /^https?:\/\//i.test(item))));
        if (field && urls.length) result[String(field)] = urls;
      });
      return result;
    }

    const MARKET_SOURCE_FIELD_LABELS = {
      name: 'اسم المشروع', project_name: 'اسم المشروع',
      project_type: 'نوع المشروع', projectType: 'نوع المشروع',
      area_sqm: 'مساحة الوحدة', areaSqm: 'مساحة الوحدة', area: 'مساحة الوحدة',
      area_from: 'مساحة الوحدة من', areaFrom: 'مساحة الوحدة من',
      area_to: 'مساحة الوحدة إلى', areaTo: 'مساحة الوحدة إلى',
      status: 'الحالة', project_status: 'الحالة',
      classification: 'التصنيف', logo_url: 'شعار المنافس', logoUrl: 'شعار المنافس',
      operation_type: 'نوع العملية', operationType: 'نوع العملية', operation: 'نوع العملية',
      price_type: 'نوع السعر', priceType: 'نوع السعر',
      price_value: 'قيمة السعر', priceValue: 'قيمة السعر', value: 'قيمة السعر',
      price_from: 'حد السعر الأدنى', priceFrom: 'حد السعر الأدنى',
      price_to: 'حد السعر الأعلى', priceTo: 'حد السعر الأعلى',
      district: 'الحي', neighborhood: 'الحي',
      distance_km: 'المسافة من موقع المشروع', distanceKm: 'المسافة من موقع المشروع',
      lat: 'خط العرض', latitude: 'خط العرض',
      lng: 'خط الطول', lon: 'خط الطول', longitude: 'خط الطول',
      data_date: 'تاريخ البيانات', dataDate: 'تاريخ البيانات'
    };

    function marketSourceFieldLabel(field) {
      return MARKET_SOURCE_FIELD_LABELS[String(field || '').trim()] || String(field || '').trim();
    }

    function marketSourceFields(row, url) {
      const target = String(url || '').toLowerCase();
      return Object.entries(marketFieldSources(row))
        .filter(([, urls]) => urls.some(item => String(item).toLowerCase() === target))
        .map(([field]) => marketSourceFieldLabel(field));
    }

    function marketSourceNote(row, sourceFields) {
      const notes = [row.notes || row.note || ''];
      if (sourceFields && sourceFields.length) notes.push('الحقول: ' + sourceFields.join('، '));
      return notes.filter(Boolean).join(' — ');
    }

    function marketSourceUrls(row = {}) {
      const values = [];
      ['source_urls', 'sourceUrls', 'urls', 'source_url', 'sourceUrl', 'url', 'sources', 'source']
        .forEach(key => values.push(...marketValueList(row[key])));
      Object.values(marketFieldSources(row)).forEach(urls => values.push(...urls));
      return Array.from(new Set(values
        .map(value => String(value || '').trim())
        .filter(value => /^https?:\/\//i.test(value))));
    }

    function safeMarketUrl(value) {
      try {
        const url = new URL(String(value || '').trim(), window.location.origin);
        return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
      } catch (error) {
        return '';
      }
    }

    function marketSourceLinksHtml(row = {}) {
      return marketSourceUrls(row).map(url => {
        const safeUrl = safeMarketUrl(url);
        return safeUrl
          ? '<a href="' + escapeHtml(safeUrl) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(url) + '</a>'
          : '<span>' + escapeHtml(url) + '</span>';
      }).join('<br>');
    }

    function marketOfficialSourceReliability(entityName, sourceName, url) {
      const source = String(sourceName || '').replace(/[أإآ]/g, 'ا').toLowerCase();
      let host = '';
      try { host = new URL(url).hostname.toLowerCase().replace(/^www\./, ''); } catch (error) { host = ''; }
      if (host && /(رسمي|المشروع|المطور|official)/.test(source)) return 'مصدر رسمي للجهة';
      const tokens = String(entityName || '').toLowerCase().match(/[a-z0-9]{4,}/g) || [];
      return host && tokens.some(token => host.includes(token)) ? 'مصدر رسمي للجهة' : '';
    }

    function buildMarketCompetitorSourceRows(competitors) {
      const rows = [];
      (Array.isArray(competitors) ? competitors : []).forEach(competitor => {
        const urls = marketSourceUrls(competitor);
        urls.forEach(url => {
          const sourceFields = marketSourceFields(competitor, url);
          rows.push({
            id: 'competitor-source-' + encodeURIComponent(String(competitor.id || competitor.name || '') + '|' + url),
            competitor_id: competitor.id || '',
            competitor_name: competitor.name || '',
            source_kind: 'competitor',
            source_fields: sourceFields,
            name: competitor.source || 'مصدر المنافس',
            url,
            data_date: competitor.data_date || competitor.dataDate || '',
            accessed_at: '',
            reliability: marketOfficialSourceReliability(competitor.name, competitor.source, url),
            note: marketSourceNote(competitor, sourceFields)
          });
        });
      });
      return rows;
    }

    function mergeMarketSourceRows(existing, incoming) {
      const existingRows = Array.isArray(existing) ? existing : [];
      const base = existingRows.filter(row => row && row.source_kind !== 'competitor');
      const byKey = new Map(existingRows.filter(Boolean).map(row => [[
        row.source_kind || 'source', row.competitor_id || '', String(row.url || '').trim().toLowerCase()
      ].join('|'), row]));
      const rows = [];
      const seen = new Set();
      (Array.isArray(incoming) ? incoming : []).forEach(row => {
        if (!row || !String(row.url || '').trim()) return;
        const key = [row.source_kind || 'source', row.competitor_id || '', String(row.url).trim().toLowerCase()].join('|');
        if (seen.has(key)) return;
        seen.add(key);
        const previous = byKey.get(key) || {};
        rows.push({ ...row, ...previous, reliability: previous.reliability || row.reliability || '' });
      });
      return base.concat(rows);
    }

    function marketSelectHtml(options, selected) {
      const values = Array.from(new Set([...(options || []), ...(selected ? [selected] : [])]));
      return '<option value="">--</option>' + values.map(option =>
        '<option value="' + String(option).replace(/"/g, '&quot;') + '"' +
        (option === selected ? ' selected' : '') + '>' + option + '</option>'
      ).join('');
    }

    function competitorPriceIsRange(priceType) {
      return MARKET_RANGE_PRICE_TYPES.includes(String(priceType || '').trim())
        || String(priceType || '').includes('نطاق');
    }

    function inferCompetitorOperation(row = {}) {
      const explicit = String(row.operation_type || row.operationType || row.operation || row['نوع العملية'] || row['نوع التشغيل'] || row['التشغيل'] || '').trim();
      if (MARKET_PRICE_TYPES[explicit]) return explicit;
      const folded = explicit.replace(/[أإآ]/g, 'ا').toLowerCase();
      if (folded.includes('بيع') || folded.includes('sale') || folded.includes('sell')) return 'بيع';
      if (folded.includes('ايجار') || folded.includes('تأجير') || folded.includes('rent')) return 'إيجار';
      if (folded.includes('فندقي') || folded.includes('فندق') || folded.includes('hotel') || folded === 'تشغيل' || folded.startsWith('تشغيل ')) return 'تشغيل فندقي';
      const priceType = String(row.price_type || row.priceType || '').trim();
      for (const [operation, options] of Object.entries(MARKET_PRICE_TYPES)) {
        if (priceType && options.includes(priceType)) return operation;
      }
      if (String(row.project_type || '').trim() === 'فندقي') return 'تشغيل فندقي';
      return explicit ? 'أخرى' : '';
    }

    function inferCompetitorPriceType(row = {}) {
      const explicit = String(row.price_type || row.priceType || row['نوع السعر'] || row['نوع التسعير'] || '').trim();
      if (explicit) return explicit;
      if (String(competitorPriceField(row, 'price_from') || '').trim() || String(competitorPriceField(row, 'price_to') || '').trim()) {
        return inferCompetitorOperation(row) === 'تشغيل فندقي' ? 'نطاق أسعار الغرف' : 'نطاق سعري';
      }
      return String(competitorPriceField(row, 'price_value') || '').trim() ? 'أخرى' : '';
    }

    function competitorPriceField(row, key) {
      const direct = row && row[key];
      if (direct !== undefined && direct !== null && String(direct).trim()) return direct;
      const aliases = {
        price_value: ['priceValue', 'value', 'القيمة', 'السعر', 'المبلغ', 'amount'],
        price_from: ['priceFrom', 'price_min', 'priceMin', 'min_price', 'minPrice', 'from', 'من', 'الحد الأدنى'],
        price_to: ['priceTo', 'price_max', 'priceMax', 'max_price', 'maxPrice', 'to', 'إلى', 'الى', 'الحد الأعلى']
      };
      for (const alias of aliases[key] || []) {
        if (row && row[alias] !== undefined && row[alias] !== null && String(row[alias]).trim()) return row[alias];
      }
      if (row && row.price && typeof row.price === 'object') {
        const nested = {
          price_value: ['value', 'price_value', 'priceValue', 'القيمة', 'السعر', 'amount'],
          price_from: ['from', 'min', 'minimum', 'من', 'الحد الأدنى'],
          price_to: ['to', 'max', 'maximum', 'إلى', 'الى', 'الحد الأعلى']
        };
        for (const alias of nested[key] || []) {
          if (row.price[alias] !== undefined && row.price[alias] !== null && String(row.price[alias]).trim()) return row.price[alias];
        }
      }
      return '';
    }

    function roundSystemNumber(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return 0;
      const rounded = Math.sign(number) * Math.round((Math.abs(number) + Number.EPSILON) * 10) / 10;
      return Object.is(rounded, -0) ? 0 : rounded;
    }

    function cleanMarketNumber(value) {
      let text = String(value ?? '').trim();
      if (!text) return '';
      text = text.replace(/[٠-٩]/g, ch => String('٠١٢٣٤٥٦٧٨٩'.indexOf(ch)))
        .replace(/[٬،,]/g, '').replace(/٫/g, '.').replace(/\s/g, '');
      return /^-?\d+(?:\.\d+)?$/.test(text) ? String(roundSystemNumber(Number(text))) : String(value ?? '').trim();
    }

    function formatMarketNumber(value) {
      const clean = cleanMarketNumber(value);
      if (clean === '') return '';
      const number = Number(clean);
      if (!Number.isFinite(number)) return clean;
      const decimals = clean.includes('.') ? clean.split('.')[1].length : 0;
      return new Intl.NumberFormat('en-US', {
        minimumFractionDigits: decimals, maximumFractionDigits: decimals
      }).format(number);
    }

    function formatMarketNumericInput(input) {
      if (!input || input.dataset.marketNumericReady) return;
      input.dataset.marketNumericReady = '1';
      input.addEventListener('focus', () => { input.value = cleanMarketNumber(input.value); });
      input.addEventListener('blur', () => { input.value = formatMarketNumber(input.value); });
      input.value = formatMarketNumber(input.value);
    }

    function cacheCompetitorAreaInputs(tr) {
      const fixed = tr.querySelector('[data-field="area_sqm"]');
      const from = tr.querySelector('[data-field="area_from"]');
      const to = tr.querySelector('[data-field="area_to"]');
      if (fixed) tr.dataset.areaFixed = cleanMarketNumber(fixed.value);
      if (from) tr.dataset.areaFrom = cleanMarketNumber(from.value);
      if (to) tr.dataset.areaTo = cleanMarketNumber(to.value);
    }