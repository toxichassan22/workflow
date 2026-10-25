/* 04-market.js - index.html lines 10648-11652, shared global scope, classic scripts in order */

    function collectMarketStudyFromDom() {
      const state = getMarketStudyState();
      const competitorRadius = document.getElementById('marketCompetitorRadius');
      const competitorRadiusCustom = document.getElementById('marketCompetitorRadiusCustomKm');
      state.competitor_scope = {
        mode: document.getElementById('marketCompetitorScopeMode')?.value || 'district',
        radius: competitorRadius?.value || '10',
        radius_custom_km: competitorRadiusCustom?.value || ''
      };
      state.comparison_types = typeof collectMarketComparisonTypes === 'function'
        ? collectMarketComparisonTypes() : (state.comparison_types || []);
      state.data_period = document.getElementById('marketDataPeriod')?.value || state.data_period;
      state.data_period_from = document.getElementById('marketDataPeriodFrom')?.value || '';
      state.data_period_to = document.getElementById('marketDataPeriodTo')?.value || '';
      state.summary_period = document.getElementById('marketSummaryPeriod')?.value
        || state.summary_period || state.data_period;
      state.summary_period_from = document.getElementById('marketSummaryPeriodFrom')?.value
        || state.summary_period_from || '';
      state.summary_period_to = document.getElementById('marketSummaryPeriodTo')?.value
        || state.summary_period_to || '';
      state.summary_research_depth = document.getElementById('marketSummaryResearchDepth')?.value
        || state.summary_research_depth || 'full';
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
      state.competitor_mode = document.getElementById('marketCompetitorsMode')?.value
        || state.competitor_mode || 'generate';
      state.disclaimer = document.getElementById('marketDisclaimer')?.value || state.disclaimer;
      state.summary_scope = collectMarketSummaryScope();
      // The summary register owns the summary's sources only. A competitor's
      // link lives in that competitor's row/slide, never here as well.
      state.sources = mergeMarketSourceRows(collectMarketSourceRows(), []);
      state.one_block_summary = buildMarketStudyOneBlockSummary(state);
      return state;
    }

    function persistMarketStudyFromDom() {
      setMarketStudyState(collectMarketStudyFromDom());
    }

    function updateMarketStudyFieldVisibility() {
      const period = document.getElementById('marketDataPeriod')?.value;
      const periodWrap = document.getElementById('marketCustomPeriodWrap');
      if (periodWrap) periodWrap.hidden = period !== 'custom';
      const summaryPeriod = document.getElementById('marketSummaryPeriod')?.value;
      const summaryPeriodWrap = document.getElementById('marketSummaryCustomPeriodWrap');
      if (summaryPeriodWrap) summaryPeriodWrap.hidden = summaryPeriod !== 'custom';
      const scopeMode = document.getElementById('marketCompetitorScopeMode')?.value || 'district';
      const radius = document.getElementById('marketCompetitorRadius')?.value || '10';
      const radiusWrap = document.getElementById('marketCompetitorRadiusWrap');
      const customRadiusWrap = document.getElementById('marketCompetitorRadiusCustomWrap');
      if (radiusWrap) radiusWrap.hidden = scopeMode !== 'distance';
      if (customRadiusWrap) customRadiusWrap.hidden = scopeMode !== 'distance' || radius !== 'custom';
      syncMarketSummaryScopeUI();
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
      const isEn = wfIsEn();
      const trVal = (val) => wfTr(val);
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
      const isEn = wfIsEn();
      const trVal = (val) => wfTr(val);
      const showSubtypeLabels = groups.length > 1;
      const signature = JSON.stringify({ groups: groups.map(group => group.main), lang: isEn ? 'en' : 'ar' });
      if (host.dataset.subtypeSignature !== signature) {
        host.dataset.subtypeSignature = signature;
        host.innerHTML = groups.map((group, index) => {
          const rawLbl = MARKET_SUBTYPE_LABELS[group.main] || ('الأنواع الفرعية ل' + group.main);
          const lbl = isEn ? (wfTr(rawLbl) || (trVal(group.main) + ' Subtypes')) : rawLbl;
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
      const isEn = wfIsEn();
      const trVal = (val) => wfTr(val);
      const signature = JSON.stringify({ groups: groups.map(group => group.key), lang: isEn ? 'en' : 'ar' });
      if (host.dataset.audienceSignature !== signature) {
        host.dataset.audienceSignature = signature;
        host.innerHTML = groups.map((group, index) => {
          const subtypeText = group.subtypes.length ? (' (' + (isEn ? group.subtypes.map(trVal).join(', ') : group.subtypes.join('، ')) + ')') : '';
          const rawLabel = MARKET_AUDIENCE_LABELS[group.kind] || ('الفئة المستهدفة ل' + group.kind);
          const label = isEn ? (wfTr(rawLabel) || (trVal(group.kind) + ' Target Audience')) : rawLabel;
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
      const isEn = wfIsEn();
      const trVal = (val) => wfTr(val);
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
            const isEn = wfIsEn();
            document.querySelectorAll('#tenantProjectForm label[data-ar-label]').forEach(lblEl => {
              const raw = lblEl.dataset.arLabel;
              const req = lblEl.dataset.isRequired === '1' ? ' *' : '';
              const badge = lblEl.querySelector('.tenant-client-required-badge');
              let text = raw;
              // wfTr already knows the m²/2 superscript twin, which this
              // lookup used to re-implement inline.
              if (isEn) text = wfTr(raw);
              lblEl.textContent = text + req;
              if (badge) {
                badge.textContent = WFT('form.client_entered_only', 'إدخال العميل');
                lblEl.appendChild(badge);
              }
            });
            document.querySelectorAll('.tenant-section-title').forEach(st => {
              const secLbl = st.querySelector('.project-section-title-label');
              if (secLbl && secLbl.dataset.arText) {
                secLbl.textContent = wfTr(secLbl.dataset.arText);
              }
              const b = st.querySelector('.section-status-badge');
              if (b && b.dataset.arText) {
                b.textContent = wfTr(b.dataset.arText);
              }
              const genBtn = st.querySelector('.section-presentation-btn');
              if (genBtn && genBtn.dataset.arText) {
                genBtn.textContent = wfTr(genBtn.dataset.arText);
              }
              const lockBtn = st.querySelector('.section-approve-btn:not(.section-presentation-btn)');
              if (lockBtn && lockBtn.dataset.arText) {
                lockBtn.textContent = wfTr(lockBtn.dataset.arText);
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

        function canonicalMarketSourceKey(url) {
      try {
        const parsed = new URL(String(url || '').trim(), window.location.origin);
        if (!['http:', 'https:'].includes(parsed.protocol)) {
          return String(url || '').trim().toLowerCase();
        }
        const tracking = new Set([
          's', 't', 'v', 'cb', 'utm_source', 'utm_medium', 'utm_campaign',
          'utm_term', 'utm_content', 'utm_id', 'gclid', 'fbclid', 'msclkid',
          'yclid', 'ref', 'referrer', 'source', 'src'
        ]);
        const params = [...parsed.searchParams.entries()]
          .filter(([key]) => !tracking.has(String(key || '').toLowerCase()))
          .sort((a, b) => String(a[0]).localeCompare(String(b[0])));
        const host = parsed.hostname.toLowerCase().replace(/^www\./, '');
        const path = (parsed.pathname || '/').replace(/\/+$/, '') || '/';
        const query = params.map(([key, value]) =>
          encodeURIComponent(key) + '=' + encodeURIComponent(value)).join('&');
        return host + path + (query ? '?' + query : '');
      } catch (error) {
        return String(url || '').trim().toLowerCase();
      }
    }

    function marketSourceIsSearchOrHomepage(url) {
      try {
        const parsed = new URL(String(url || '').trim(), window.location.origin);
        const host = parsed.hostname.toLowerCase().replace(/^www\./, '');
        const path = (parsed.pathname || '/').toLowerCase();
        if ((path === '' || path === '/') && !parsed.search) return true;
        if (/(^|\/)(search|searchresults|search-results|results|result)(\/|$|\.)/.test(path)) return true;
        if (host.endsWith('booking.com')
          && (path === '/' || path.startsWith('/search')
            || path.startsWith('/district') || path.startsWith('/city'))) return true;
        return false;
      } catch (error) {
        return false;
      }
    }

    function marketSourceUrlDepth(url) {
      try {
        const path = new URL(String(url || ''), window.location.origin).pathname || '';
        return [(path.replace(/^\/+|\/+$/g, '').split('/').filter(Boolean).length), path.length];
      } catch (error) {
        return [0, 0];
      }
    }

    function competitorPrimarySourceUrl(row = {}) {
      const explicit = [row.source_url, row.sourceUrl, row.url]
        .map(value => String(value || '').trim())
        .filter(value => /^https?:\/\//i.test(value));
      if (row.source_url_manual || row.sourceUrlManual) {
        // The client's own link wins; an empty one stays empty.
        return explicit[0] || '';
      }
      const priceUrls = [];
      Object.entries(marketFieldSources(row)).forEach(([field, urls]) => {
        if (['price_value', 'price_from', 'price_to'].includes(field)) {
          priceUrls.push(...(Array.isArray(urls) ? urls : []));
        }
      });
      const candidates = Array.from(new Set(
        [...priceUrls, ...explicit, ...marketSourceUrls(row)]
          .map(value => String(value || '').trim())
          .filter(value => /^https?:\/\//i.test(value))));
      const specific = candidates.filter(url => !marketSourceIsSearchOrHomepage(url));
      const priceSpecific = priceUrls
        .map(value => String(value || '').trim())
        .filter(value => /^https?:\/\//i.test(value) && !marketSourceIsSearchOrHomepage(value));
      if (priceSpecific.length) return priceSpecific[0];
      const explicitSpecific = explicit.filter(url => !marketSourceIsSearchOrHomepage(url));
      if (explicitSpecific.length) return explicitSpecific[0];
      if (specific.length) {
        return specific.sort((a, b) => {
          const [depthA, lengthA] = marketSourceUrlDepth(a);
          const [depthB, lengthB] = marketSourceUrlDepth(b);
          return depthB - depthA || lengthB - lengthA;
        })[0];
      }
      return '';
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

    function marketOfficialSourceReliability(entityName, sourceName, url) {
      const source = String(sourceName || '').replace(/[أإآ]/g, 'ا').toLowerCase();
      let host = '';
      try { host = new URL(url).hostname.toLowerCase().replace(/^www\./, ''); } catch (error) { host = ''; }
      if (host && /(رسمي|المشروع|المطور|official)/.test(source)) return 'مصدر رسمي للجهة';
      const tokens = String(entityName || '').toLowerCase().match(/[a-z0-9]{4,}/g) || [];
      return host && tokens.some(token => host.includes(token)) ? 'مصدر رسمي للجهة' : '';
    }

    function mergeMarketSourceRows(existing, incoming) {
      // One register for the summary's sources. Competitor rows saved by an
      // older build are dropped here, so reopening a draft heals it too.
      const rows = [];
      const seen = new Set();
      [...(Array.isArray(existing) ? existing : []),
       ...(Array.isArray(incoming) ? incoming : [])].forEach(row => {
        if (!row || typeof row !== 'object' || row.source_kind === 'competitor') return;
        const url = String(row.url || row.source_url || row.sourceUrl || '').trim();
        const key = url ? canonicalMarketSourceKey(url) : ('row:' + rows.length);
        if (seen.has(key)) return;
        seen.add(key);
        rows.push(row);
      });
      return rows;
    }

    function marketSelectHtml(options, selected) {
      const values = Array.from(new Set([...(options || []), ...(selected ? [selected] : [])]));
      return '<option value="">--</option>' + values.map(option =>
        '<option value="' + String(option).replace(/"/g, '&quot;') + '"' +
        (option === selected ? ' selected' : '') + '>' + option + '</option>'
      ).join('');
    }

    function marketProjectIsEnglish() {
      return typeof tenantProjectData !== 'undefined'
        && String((tenantProjectData && tenantProjectData.project_language) || '') === 'en';
    }

    function marketCompetitorPriceTypes() {
      return marketProjectIsEnglish() ? MARKET_PRICE_TYPES_EN : MARKET_PRICE_TYPES;
    }

    function marketPriceTypesForOperation(operation) {
      const map = marketCompetitorPriceTypes();
      return map[operation] || map[marketProjectIsEnglish() ? 'Other' : 'أخرى'] || [];
    }

    function marketTranslateCompetitorValue(value) {
      const text = String(value || '').trim();
      return marketProjectIsEnglish() ? (MARKET_AR_TO_EN_COMPETITOR[text] || text) : text;
    }

    function competitorPriceIsRange(priceType) {
      const text = String(priceType || '').trim();
      return MARKET_RANGE_PRICE_TYPES.includes(text)
        || MARKET_RANGE_PRICE_TYPES_EN.includes(text)
        || text.includes('نطاق')
        || /range/i.test(text);
    }

    function inferCompetitorOperation(row = {}) {
      const explicit = String(row.operation_type || row.operationType || row.operation || row['نوع العملية'] || row['نوع التشغيل'] || row['التشغيل'] || '').trim();
      const priceTypesMap = marketCompetitorPriceTypes();
      if (priceTypesMap[explicit]) return explicit;
      const en = marketProjectIsEnglish();
      const folded = explicit.replace(/[أإآ]/g, 'ا').toLowerCase();
      if (folded.includes('بيع') || folded.includes('sale') || folded.includes('sell')) return en ? 'Sale' : 'بيع';
      if (folded.includes('ايجار') || folded.includes('تأجير') || folded.includes('rent')) return en ? 'Rent' : 'إيجار';
      if (folded.includes('فندقي') || folded.includes('فندق') || folded.includes('hotel') || folded.includes('hospital') || folded === 'تشغيل' || folded.startsWith('تشغيل ')) return en ? 'Hotel Operation' : 'تشغيل فندقي';
      const priceType = String(row.price_type || row.priceType || '').trim();
      for (const [operation, options] of Object.entries(priceTypesMap)) {
        if (priceType && options.includes(priceType)) return operation;
      }
      if (['فندقي', 'hospitality', 'hotel'].includes(String(row.project_type || '').trim().toLowerCase())) return en ? 'Hotel Operation' : 'تشغيل فندقي';
      return explicit ? (en ? 'Other' : 'أخرى') : '';
    }

    function inferCompetitorPriceType(row = {}) {
      const explicit = String(row.price_type || row.priceType || row['نوع السعر'] || row['نوع التسعير'] || '').trim();
      if (explicit) return marketTranslateCompetitorValue(explicit);
      const en = marketProjectIsEnglish();
      if (String(competitorPriceField(row, 'price_from') || '').trim() || String(competitorPriceField(row, 'price_to') || '').trim()) {
        const hotel = inferCompetitorOperation(row) === (en ? 'Hotel Operation' : 'تشغيل فندقي');
        return en ? (hotel ? 'Room Price Range' : 'Price Range') : (hotel ? 'نطاق أسعار الغرف' : 'نطاق سعري');
      }
      return String(competitorPriceField(row, 'price_value') || '').trim() ? (en ? 'Other' : 'أخرى') : '';
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

    function normalizeSystemNumber(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return 0;
      return Object.is(number, -0) ? 0 : number;
    }

    function formatExactSystemNumber(value, grouped = true) {
      let text = typeof value === 'number'
        ? String(normalizeSystemNumber(value))
        : String(value ?? '').trim();
      if (/[eE]/.test(text)) {
        const [mantissa, exponentText] = text.toLowerCase().split('e');
        const exponent = Number(exponentText);
        if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > 10000) return text;
        const sign = mantissa.startsWith('-') ? '-' : '';
        const unsigned = sign ? mantissa.slice(1) : mantissa;
        const [whole, fraction = ''] = unsigned.split('.');
        const digits = whole + fraction;
        const decimalIndex = whole.length + exponent;
        text = decimalIndex <= 0
          ? sign + '0.' + '0'.repeat(-decimalIndex) + digits
          : decimalIndex >= digits.length
            ? sign + digits + '0'.repeat(decimalIndex - digits.length)
            : sign + digits.slice(0, decimalIndex) + '.' + digits.slice(decimalIndex);
      }
      if (!/^-?\d+(?:\.\d+)?$/.test(text)) {
        const number = Number(value);
        return Number.isFinite(number) ? String(normalizeSystemNumber(number)) : (text || '0');
      }
      const sign = text.startsWith('-') ? '-' : '';
      const unsigned = sign ? text.slice(1) : text;
      const [whole, fraction] = unsigned.split('.');
      const integer = grouped ? whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',') : whole;
      return sign + integer + (fraction ? '.' + fraction : '');
    }

    function cleanMarketNumber(value) {
      let text = String(value ?? '').trim();
      if (!text) return '';
      text = text.replace(/[٠-٩]/g, ch => String('٠١٢٣٤٥٦٧٨٩'.indexOf(ch)))
        .replace(/[٬،,]/g, '').replace(/٫/g, '.').replace(/\s/g, '');
      if (!/^-?\d+(?:\.\d+)?$/.test(text)) return String(value ?? '').trim();
      const sign = text.startsWith('-') ? '-' : '';
      const unsigned = sign ? text.slice(1) : text;
      const [whole, fraction] = unsigned.split('.');
      const normalizedWhole = whole.replace(/^0+(?=\d)/, '');
      return sign + normalizedWhole + (fraction !== undefined ? '.' + fraction : '');
    }

    function formatMarketNumber(value) {
      const clean = cleanMarketNumber(value);
      if (clean === '') return '';
      return formatExactSystemNumber(clean, true);
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
