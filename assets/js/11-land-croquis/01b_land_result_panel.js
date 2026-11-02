/* 11-land-croquis/01b_land_result_panel.js - the land analysis result view.
 *
 * The section used to expose every extracted value as its own box, several of
 * them paragraphs long. The reader had to scan a wall of inputs to find the
 * area or the setbacks. This file leaves the data and its inputs untouched and
 * changes only how they are presented:
 *   - an overview card at the top with the six facts a reader looks for first;
 *   - the narrative summary as readable prose;
 *   - the detail fields grouped into titled, collapsible blocks.
 * Values still come from the same [data-key] inputs, so persistence, approval
 * locks and the slide prompts never change.
 */

    const LAND_ANALYSIS_GROUPS = [
      { key: 'documents', title: 'مستندات التحليل', open: true,
        fields: ['land_documents_files', 'land_photos'] },
      { key: 'decisions', title: 'البيانات المعتمدة للدراسة المالية', open: true,
        fields: ['approved_financial_area', 'approved_floor_count', 'approved_coverage_ratio',
          'approved_floor_area_ratio', 'approved_typical_floor_coverage'] },
      { key: 'identity', title: 'هوية القطعة', open: false,
        fields: ['plot_number_croquis', 'plan_number', 'deed_number', 'deed_date', 'croquis_land_area'] },
      { key: 'boundaries', title: 'الحدود والاتجاهات والإحداثيات', open: false,
        fields: ['facades_count', 'facades_directions', 'boundary_lengths', 'surrounding_streets',
          'directions_table', 'survey_coordinates', 'land_documents_analysis'] },
      { key: 'rules', title: 'اشتراطات البناء', open: false,
        fields: ['building_ratio_coverage', 'setbacks', 'max_floors_height'], computed: true },
      { key: 'uses', title: 'الاستخدامات والقيود', open: false,
        fields: ['allowed_uses', 'regulatory_constraints'] },
      { key: 'summary', title: 'ملخص التحليل', open: false,
        fields: ['land_and_building_summary'] }
    ];

    function landAnalysisPayload() {
      const raw = tenantProjectData ? tenantProjectData.land_documents_analysis : null;
      if (!raw) return {};
      if (typeof raw === 'string') {
        try {
          const parsed = JSON.parse(raw);
          return parsed && typeof parsed === 'object' ? parsed : {};
        } catch (error) {
          return {};
        }
      }
      return typeof raw === 'object' ? raw : {};
    }

    function landAnalysisParcel() {
      const payload = landAnalysisPayload();
      return Array.isArray(payload.parcels) && payload.parcels.length ? payload.parcels[0] : {};
    }

    // The stored input is the display truth after a reload; the analysis payload
    // is only a fallback for values that never reached a field.
    function landFieldValue(key) {
      const input = document.querySelector('#tenantProjectForm [data-key="' + key + '"]');
      if (input && typeof input.value === 'string' && input.value.trim() !== '') return input.value.trim();
      const stored = tenantProjectData ? tenantProjectData[key] : '';
      if (stored === undefined || stored === null) return '';
      return typeof stored === 'string' ? stored.trim() : String(stored);
    }

    function landFactFirstLine(value, limit) {
      const text = String(value || '').split(/\n/).map(part => part.trim()).filter(Boolean)[0] || '';
      return text.length > limit ? text.slice(0, limit).trim() + '…' : text;
    }

    function landAreaFact() {
      const raw = landFieldValue('croquis_land_area');
      const numeric = Number(String(raw).replace(/,/g, ''));
      if (raw && Number.isFinite(numeric) && numeric > 0) {
        return numeric.toLocaleString('en-US') + ' م²';
      }
      return '';
    }

    function landFacadesFact() {
      const count = landFieldValue('facades_count');
      return count && count !== '0' ? count : '';
    }

    function landAnalysisFactTiles() {
      const parcel = landAnalysisParcel();
      // Only the facts the client needs at a glance. The setbacks, floors and
      // coordinates are detailed below in their own groups; repeating them here
      // only crowded the card.
      const facts = [
        [WFT('land.result.fact_area', 'المساحة'), landAreaFact()],
        [WFT('land.result.fact_zoning', 'التنظيم'), landFactFirstLine(parcel.zoning_code || '', 48)],
        [WFT('land.result.fact_facades', 'الواجهات'), landFacadesFact()]
      ];
      return facts.filter(([, value]) => String(value || '').trim() !== '');
    }

    function landAnalysisNarrative() {
      const fromField = landFieldValue('land_and_building_summary');
      if (fromField) return fromField;
      const payload = landAnalysisPayload();
      if (payload.land_and_building_summary) return String(payload.land_and_building_summary);
      const parcel = landAnalysisParcel();
      return String(parcel.summary || '');
    }

    function landAnalysisOverviewElement() {
      const tiles = landAnalysisFactTiles();
      const narrative = landAnalysisNarrative();
      const payload = landAnalysisPayload();
      const conflicts = Array.isArray(payload.conflicts) ? payload.conflicts.length : 0;
      if (!tiles.length && !narrative) return null;

      const card = document.createElement('section');
      card.className = 'land-analysis-overview';
      card.id = 'landAnalysisOverview';

      const head = document.createElement('div');
      head.className = 'land-overview-head';
      const title = document.createElement('strong');
      title.className = 'land-overview-title';
      title.textContent = WFT('land.result.title', 'نتائج تحليل الأرض');
      head.appendChild(title);
      if (conflicts) {
        const chip = document.createElement('span');
        chip.className = 'land-overview-chip';
        chip.textContent = WFT('land.result.conflicts_count', 'التعارضات: {n}', { n: String(conflicts) });
        head.appendChild(chip);
      }
      card.appendChild(head);

      if (tiles.length) {
        const grid = document.createElement('div');
        grid.className = 'land-facts';
        tiles.forEach(([label, value]) => {
          const tile = document.createElement('div');
          tile.className = 'land-fact';
          const labelEl = document.createElement('span');
          labelEl.className = 'land-fact-label';
          labelEl.textContent = label;
          const valueEl = document.createElement('strong');
          valueEl.className = 'land-fact-value';
          valueEl.textContent = value;
          tile.appendChild(labelEl);
          tile.appendChild(valueEl);
          grid.appendChild(tile);
        });
        card.appendChild(grid);
      }

      if (narrative) {
        const body = document.createElement('div');
        body.className = 'land-narrative land-narrative-collapsed';
        String(narrative).split(/\n+/).map(part => part.trim()).filter(Boolean).forEach(part => {
          const paragraph = document.createElement('p');
          paragraph.textContent = part;
          body.appendChild(paragraph);
        });
        card.appendChild(body);
        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'land-overview-toggle';
        toggle.dataset.arText = 'عرض الملخص كاملًا';
        toggle.textContent = WFT('land.result.summary_expand', 'عرض الملخص كاملًا');
        toggle.addEventListener('click', () => {
          const collapsed = body.classList.toggle('land-narrative-collapsed');
          toggle.textContent = collapsed
            ? WFT('land.result.summary_expand', 'عرض الملخص كاملًا')
            : WFT('land.result.summary_collapse', 'إخفاء الملخص');
          toggle.dataset.arText = toggle.textContent;
        });
        card.appendChild(toggle);
      }
      return card;
    }

    function refreshLandAnalysisOverview() {
      const section = document.getElementById('project-section-land_croquis');
      if (!section) return;
      const fresh = landAnalysisOverviewElement();
      const existing = document.getElementById('landAnalysisOverview');
      if (existing && fresh) {
        existing.replaceWith(fresh);
        return;
      }
      if (existing) {
        existing.remove();
        return;
      }
      if (!fresh) return;
      const header = section.querySelector('.tenant-section-title');
      const firstGroup = section.querySelector('.land-field-group');
      if (firstGroup) firstGroup.before(fresh);
      else if (header) header.after(fresh);
      else section.prepend(fresh);
    }

    function landGroupStateText(open) {
      return open ? WFT('land.group.close', 'إخفاء') : WFT('land.group.open', 'عرض');
    }

    function revealLandAnalysisField(key) {
      const input = document.querySelector('#tenantProjectForm [data-key="' + key + '"]');
      if (!input) return;
      const group = input.closest('details.land-field-group');
      if (group) {
        group.open = true;
        const state = group.querySelector('.land-group-state');
        if (state) state.textContent = landGroupStateText(true);
      }
      input.scrollIntoView({ behavior: 'smooth', block: 'center' });
      if (typeof input.focus === 'function') input.focus();
    }

    // Runs once per rendered land section, after every field and its panels exist.
    function groupLandAnalysisFields(sectionDiv) {
      if (!sectionDiv || sectionDiv.dataset.landGroups === '1') return;
      sectionDiv.dataset.landGroups = '1';
      const header = sectionDiv.querySelector('.tenant-section-title');
      const groupByKey = {};
      let anchor = header || null;
      const insertAfterAnchor = element => {
        if (anchor) anchor.after(element);
        else sectionDiv.insertBefore(element, sectionDiv.firstChild);
        anchor = element;
      };

      const overview = landAnalysisOverviewElement();
      if (overview) insertAfterAnchor(overview);

      LAND_ANALYSIS_GROUPS.forEach(definition => {
        const details = document.createElement('details');
        details.className = 'land-field-group';
        details.dataset.landGroup = definition.key;
        details.open = !!definition.open;

        const summary = document.createElement('summary');
        summary.className = 'land-field-group-title';
        const title = document.createElement('span');
        title.className = 'land-field-group-label';
        title.textContent = WFT('land.group.' + definition.key, definition.title);
        const count = document.createElement('span');
        count.className = 'land-field-group-count';
        const state = document.createElement('span');
        state.className = 'land-group-state';
        state.textContent = landGroupStateText(details.open);
        state.dataset.arText = state.textContent;
        summary.appendChild(title);
        summary.appendChild(count);
        summary.appendChild(state);
        details.appendChild(summary);
        const grid = document.createElement('div');
        grid.className = 'land-group-grid';
        details.appendChild(grid);
        details.addEventListener('toggle', () => {
          state.textContent = landGroupStateText(details.open);
          state.dataset.arText = state.textContent;
        });
        groupByKey[definition.key] = { details, grid, count };
        insertAfterAnchor(details);
      });

      const fieldToGroup = {};
      LAND_ANALYSIS_GROUPS.forEach(definition => {
        (definition.fields || []).forEach(key => { fieldToGroup[key] = definition.key; });
      });
      const computedGroupKey = (LAND_ANALYSIS_GROUPS.find(definition => definition.computed) || {}).key;

      Array.from(sectionDiv.children).forEach(child => {
        if (child === header || child.classList.contains('land-analysis-overview')
          || child.classList.contains('land-field-group')) return;
        let key = '';
        const control = child.querySelector ? child.querySelector('[data-key]') : null;
        if (control) key = control.dataset.key || '';
        if (!key && computedGroupKey && child.querySelector && child.querySelector('#landComputedMetrics')) {
          key = '__computed';
        }
        const targetKey = key === '__computed' ? computedGroupKey : fieldToGroup[key];
        const target = targetKey ? groupByKey[targetKey] : null;
        if (!target) return;
        target.grid.appendChild(child);
        target.count.textContent = String(target.grid.children.length);
      });
      Object.values(groupByKey).forEach(group => {
        group.count.textContent = String(group.grid.children.length);
      });
    }
