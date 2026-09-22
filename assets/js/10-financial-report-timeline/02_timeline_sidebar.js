    function seedDefaultTimelinePhases() {
      const tbody = document.getElementById('timelineTableBody');
      if (!tbody) return;
      if (Array.from(tbody.rows).some(row => (row.querySelector('.tl-name')?.value || '').trim())) return;
      tbody.innerHTML = '';
      TIMELINE_DEFAULT_PHASES.forEach(name => addTimelineRow({ name }));
      const hidden = document.getElementById('timelineTableData');
      if (hidden) hidden.value = JSON.stringify(collectTimelineRows());
      syncFinancialFromTimeline();
    }

    function addTimelineRow(data = {}) {
      const tbody = document.getElementById('timelineTableBody');
      if (!tbody) return null;
      if (arguments.length === 0 && tbody.rows.length) {
        const incompleteRow = Array.from(tbody.rows).find(row =>
          !(row.querySelector('.tl-name')?.value || '').trim());
        if (incompleteRow) {
          const nameInput = incompleteRow.querySelector('.tl-name');
          toast('أكمل اسم المرحلة الحالية أولًا قبل إضافة مرحلة جديدة');
          nameInput?.focus();
          return null;
        }
      }
      const tr = document.createElement('tr');
      tr.innerHTML = timelineRowHtml(data);
      tbody.appendChild(tr);
      refreshTimelineQuarterLabels(tr);
      updateTimelineRowEnd(tr);
      return tr;
    }

    function removeTimelineRow(button) {
      const row = button?.closest('tr');
      const tbody = document.getElementById('timelineTableBody');
      if (!row || !tbody) return;
      row.remove();
      // Always leave one editable row so the table never becomes unusable.
      if (!tbody.rows.length) addTimelineRow();
      saveTimelineData();
    }

    function collectTimelineRows() {
      return Array.from(document.querySelectorAll('#timelineTableBody tr')).map(tr => {
        const year = tr.querySelector('.tl-year')?.value || '';
        const quarter = tr.querySelector('.tl-quarter')?.value || '';
        const duration = tr.querySelector('.tl-duration')?.value || '';
        const end = computeTimelineEnd(year, quarter, duration);
        return {
          name: tr.querySelector('.tl-name')?.value || '',
          year,
          quarter,
          duration,
          endYear: end ? String(end.year) : '',
          endQuarter: end ? end.quarter : '',
          notes: tr.querySelector('.tl-notes')?.value || ''
        };
      });
    }

    // The timeline is the single source of truth for the development duration and the stage list;
    // the financial study mirrors them read-only so the two can never disagree.
    function syncFinancialFromTimeline() {
      const scheduleBody = document.querySelector('#scheduleTable tbody');
      const devYearsInput = document.getElementById('developmentYears');
      if (!scheduleBody && !devYearsInput) return;

      const timelineYears = parseInt(document.getElementById('tlYears')?.value, 10);
      const projectStart = timelineProjectStart();
      const namedStages = collectTimelineRows().filter(row => row.name.trim());

      // «عدد السنوات» is the timeline's own field, so it mirrors whether or not a stage has been
      // named yet. Gating it on the stage list left «مدة تطوير المشروع» showing its own default 4
      // while the timeline said 5, in a box the user cannot edit and a hint that says the value
      // comes from there.
      const nextDevYears = Number.isFinite(timelineYears) && timelineYears > 0 ? String(timelineYears) : '';
      let devYearsChanged = false;
      if (devYearsInput && devYearsInput.value !== nextDevYears) {
        devYearsInput.value = nextDevYears;
        devYearsChanged = true;
      }
      const devYears = Math.max(1, parseInt(devYearsInput?.value, 10) || 1);
      // The recalculation used to sit past both early returns, so a duration mirrored on its own
      // never reached «إجمالي سنوات المشروع», «سنة بدء التشغيل» or the cashflow.
      const recalculate = () => {
        if (window.__batchLoading || typeof calculateAll !== 'function') return;
        try { calculateAll(); } catch (e) { console.warn('calculateAll failed:', e); }
      };

      const warning = document.getElementById('timelineStagesWarning');
      if (warning) warning.hidden = namedStages.length > 0;
      // Without a start date the rows keep working as relative years/quarters, but no real
      // month labels can be shown for them.
      const startYearWarning = document.getElementById('timelineStartYearWarning');
      if (startYearWarning) {
        startYearWarning.hidden = !!projectStart || !namedStages.length;
      }
      if (!scheduleBody) {
        if (devYearsChanged) recalculate();
        return;
      }

      // Percentages are this study's own data, so carry them over by stage name on every rebuild.
      const previous = new Map();
      scheduleBody.querySelectorAll('tr').forEach(tr => {
        const name = (tr.querySelector('[data-field="name"] input')?.value || '').trim();
        if (!name) return;
        previous.set(name, {
          costPct: tr.querySelector('[data-field="costPct"] input')?.value ?? 0,
          devPct: tr.querySelector('[data-field="devPct"] input')?.value ?? 0,
          year: tr.dataset.stageYear,
          endYear: tr.dataset.stageEndYear
        });
      });
      // An empty timeline used to wipe a just-restored schedule table. Keep the
      // already-hydrated stages until the user actually names phases.
      if (!namedStages.length) {
        if (devYearsChanged) recalculate();
        return;
      }

      const wasBatching = window.__batchLoading;
      window.__batchLoading = true;
      scheduleBody.innerHTML = '';
      namedStages.forEach(row => {
        const name = row.name.trim();
        // Timeline rows already carry project-relative years — the same axis the cashflow uses.
        const relative = parseInt(row.year, 10);
        const kept = previous.get(name) || {};
        const startRelative = Math.max(1, Math.min(devYears, Number.isFinite(relative) ? relative : 1));
        const relativeEnd = parseInt(row.endYear, 10);
        const endRelative = Number.isFinite(relativeEnd) ? relativeEnd : startRelative;
        addScheduleStage({
          name,
          year: startRelative,
          endYear: Math.max(startRelative, Math.min(devYears, endRelative)),
          costPct: kept.costPct ?? 0,
          devPct: kept.devPct ?? 0
        });
      });
      window.__batchLoading = wasBatching;
      recalculate();
    }

    // The land/croquis section is the single source of truth for the approved area, floor count
    // and coverage ratio; the financial study mirrors them read-only so the two cannot disagree.
    function syncFinancialFromLand() {
      const landAreaInput = document.getElementById('landArea');
      const coverageInput = document.getElementById('coverageRate');
      const floorInput = document.getElementById('floorCount');
      if (!landAreaInput && !coverageInput && !floorInput) return;

      const readLand = key => {
        const input = document.querySelector('#tenantProjectForm [data-key="' + key + '"]');
        return String(input?.value ?? tenantProjectData?.[key] ?? '').trim();
      };

      // A mirror carries the source's emptiness too. Writing only when the source held a number
      // left the previous value — or the markup's own invented default — sitting in a read-only
      // box under a hint that says the figure comes from the land section. The study then ran on
      // 70,000 م² and 35% that nobody had entered.
      const mirrorApproved = (input, key) => {
        if (!input) return;
        const raw = readLand(key);
        const number = parseNumber(raw);
        const next = raw !== '' && number > 0 ? String(number) : '';
        if (parseNumber(input.value) === number && (next !== '' || input.value === '')) return;
        input.value = next;
      };
      mirrorApproved(landAreaInput, 'approved_financial_area');
      mirrorApproved(floorInput, 'approved_floor_count');
      mirrorApproved(coverageInput, 'approved_coverage_ratio');

      if (typeof calculateAll === 'function') {
        try { calculateAll(); } catch (e) { console.warn('calculateAll failed:', e); }
      }
    }

    function saveTimelineData() {
      const data = collectTimelineRows();
      const hidden = document.getElementById('timelineTableData');
      if (hidden) hidden.value = JSON.stringify(data);
      syncFinancialFromTimeline();
      if (typeof triggerAutoSaveDraft === 'function') triggerAutoSaveDraft();
    }

    function populateProjectSidebar(sections) {
      const sidebar = document.getElementById('tenantProjectSidebar');
      if (!sidebar) return;
      sidebar.innerHTML = '';

      const title = document.createElement('p');
      title.className = 'project-form-sidebar-title';
      title.textContent = 'أقسام المشروع';
      sidebar.appendChild(title);

      sections.forEach(section => {
        const sectionKey = section.dataset.section;
        const sectionLabel = section.querySelector('.project-section-title-label')?.textContent || 'قسم المشروع';
        const underConstruction = section.dataset.underConstruction === '1';
        const status = tenantProjectSectionStatuses[sectionKey] || 'draft';
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'project-section-nav-item';
        button.dataset.sectionKey = sectionKey;
        button.setAttribute('aria-controls', section.id || '');
        button.addEventListener('click', () => showSection(sectionKey));

        const label = document.createElement('span');
        label.className = 'project-section-nav-label';
        label.textContent = sectionLabel;
        button.appendChild(label);

        const statusLabel = document.createElement('span');
        statusLabel.className = 'project-section-nav-status' + (!underConstruction && status === 'approved' ? ' approved' : '');
        statusLabel.textContent = underConstruction ? 'تحت الإنشاء' : (status === 'approved' ? 'معتمد' : 'مسودة');
        button.appendChild(statusLabel);
        sidebar.appendChild(button);
      });

      appendWorkflowNavigation(sidebar, 'tenantProjectPage', false);
    }

    function showSection(sectionKey, fromHistory = false) {
      const sections = Array.from(document.querySelectorAll('#tenantProjectForm .tenant-form-section[data-section]'));
      const target = sections.find(section => section.dataset.section === sectionKey);
      if (!target) return;

      sections.forEach(section => section.classList.toggle('active', section === target));
      document.querySelectorAll('#tenantProjectSidebar [data-section-key]').forEach(button => {
        const active = button.dataset.sectionKey === sectionKey;
        button.classList.toggle('active', active);
        button.setAttribute('aria-current', active ? 'page' : 'false');
      });
      tenantActiveProjectSection = sectionKey;
      if (tgrCurrentPageId() === 'tenantProjectPage') {
        syncTenantBrowserHistory('tenantProjectPage', { activeSection: sectionKey }, fromHistory);
      } else {
        saveTenantNavigationState('tenantProjectPage', { activeSection: sectionKey });
      }
      if (typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en' && target) {
        window.WFI18n.autoTranslate(target);
      }
    }

    // Keep for backward compatibility with older callers.
    function scrollToSection(sectionKey) {
      showSection(sectionKey);
    }

    function setupSidebarObserver() { }

    // Drafts are saved only when the user explicitly asks for it. Changes stay in the current
    // workspace until the save button is used, so a refresh restores the last saved version.
    let tenantDraftDirty = false;
    // Every edit bumps this counter, so a save response arriving after a newer
    // edit can be told apart from one that still describes the current state.
    let draftEditCounter = 0;

    function setDraftDirty(dirty) {
      tenantDraftDirty = !!dirty;
      if (dirty) draftEditCounter += 1;
      const badge = document.getElementById('draftSyncBadge');
      if (badge) {
        if (tenantDraftDirty) {
          badge.style.background = '#fef3c7';
          badge.style.color = '#92400e';
          badge.innerHTML = 'تغييرات غير محفوظة';
        } else {
          badge.style.background = '#edf7f3';
          badge.style.color = '#126247';
          badge.innerHTML = 'محفوظ';
        }
      }
      const ib = document.getElementById('tgrInputs');
      if (ib && !ib.classList.contains('tgr-hidden')) renderGlobalRailInputs();
    }

    function triggerAutoSaveDraft() {
      setDraftDirty(true);
    }

    // Nothing is saved silently any more, so warn before the tab is closed with pending edits.
    window.addEventListener('beforeunload', event => {
      if (!tenantDraftDirty) return;
      event.preventDefault();
      event.returnValue = '';
      return '';
    });

    let draftSaveChain = Promise.resolve();

    function saveProjectAsDraft(silent = false) {
      const task = () => saveProjectAsDraftNow(silent);
      draftSaveChain = draftSaveChain.catch(() => undefined).then(task);
      return draftSaveChain;
    }

    async function saveProjectAsDraftNow(silent = false, syncPresentation = true, slideCheckpoint = false, checkpointProjectData = null) {
      try {
        if (typeof tenantProjectMode !== 'undefined' && tenantProjectMode === 'presentation' && !slideCheckpoint) {
          // When viewing or editing an existing presentation, the workspace is scoped
          // to that presentation. Overwriting the live project draft with an older
          // presentation snapshot would destroy live project data and void approved sections.
          return true;
        }
        let data;
        if (slideCheckpoint) {
          renumberTenantSlides();
          data = {
            ...(checkpointProjectData || tenantProjectData),
            tenantSlidePlan,
            tenantSlidesData,
            tenantCreativeImages,
            slide_generation_checkpoint: tenantSlideGenerationCheckpoint,
          };
        } else {
          Object.keys(LOCATION_TABLE_FIELDS).forEach(serializeLocationTable);
          if (typeof persistMarketStudyFromDom === 'function' && document.getElementById('marketStudyData')) {
            persistMarketStudyFromDom();
          }
          if (typeof persistExecutiveContentFromDom === 'function' && document.getElementById('executiveContentData')) {
            persistExecutiveContentFromDom();
          }
          if (typeof persistClassificationDraftState === 'function') persistClassificationDraftState();
          if (typeof persistVisualConceptDraftState === 'function') persistVisualConceptDraftState();
          if (typeof persistFinancialStudyDraftState === 'function') persistFinancialStudyDraftState();
          renumberTenantSlides();
          const formData = await collectTenantFormData();
          data = { ...tenantProjectData, ...formData };
          if (!data.project_logo && tenantProjectData.project_logo) data.project_logo = tenantProjectData.project_logo;
          if (!data.project_logo_file_id && tenantProjectData.project_logo_file_id) data.project_logo_file_id = tenantProjectData.project_logo_file_id;
          if (!data.project_logo_file_meta && tenantProjectData.project_logo_file_meta) data.project_logo_file_meta = tenantProjectData.project_logo_file_meta;
          if (!data.target_audience && tenantProjectData.target_audience) data.target_audience = tenantProjectData.target_audience;
          if (!data.visual_concept && tenantProjectData.visual_concept) data.visual_concept = tenantProjectData.visual_concept;
          if (typeof persistFinancialStudyDraftState === 'function') {
            data.financial_study_model = persistFinancialStudyDraftState() || data.financial_study_model;
          }
          data.draftId = tenantProjectData.draftId || crypto.randomUUID();
          tenantProjectData.draftId = data.draftId;
          data.nearby_landmarks_data = Array.isArray(tenantNearbyLandmarks) ? tenantNearbyLandmarks : parseLocationFieldText('nearby_landmarks', data.nearby_landmarks);
          if (tenantProjectData.calculate_landmark_driving !== undefined) {
            data.calculate_landmark_driving = !!tenantProjectData.calculate_landmark_driving;
          }
          data.tenantSlidePlan = tenantSlidePlan;
          if (typeof persistVisualConceptDraftState === 'function') persistVisualConceptDraftState();
          if (tenantVisualConceptState) {
            data.visual_concept = tenantVisualConceptState;
            tenantProjectData.visual_concept = tenantVisualConceptState;
          }
          data.tenantCreativeImages = tenantCreativeImages;
          data.tenantSlidesData = tenantSlidesData;
          // Keep the conversation with this presentation so reopening it does not lose the agent's
          // context, while a newly generated presentation starts with a clean history.
          data.designerChat = designerChatPersistence(syncPresentation ? tenantPresentationId : null);
          data.site_analysis_approved = !!tenantProjectData.site_analysis_approved;
          collectMapStylePanel();
          data.map_styles = tenantProjectData.map_styles || {};
          data.map_type = tenantProjectData.map_type || '';
          data.pageDrafts = {
            project: {
              sectionStatuses: { ...tenantProjectSectionStatuses },
              status: 'draft'
            },
            mainImage: {
              prompt: tenantCreativeImages.cover_prompt || '',
              image: tempCoverImage || tenantCreativeImages.cover || '',
              approved: !!tenantCreativeImages.cover
            },
            moodboard: {
              prompts: Array.isArray(tenantCreativeImages.moodboard_prompts) ? [...tenantCreativeImages.moodboard_prompts] : [],
              images: VISUAL_CONCEPT_EXTERNAL_SLOTS.slice(1).reduce((acc, item, index) => {
                acc[index] = tenantVisualConceptState?.slots?.[item.id]?.approvedImageUrl
                  || tenantVisualConceptState?.slots?.[item.id]?.imageUrl
                  || tenantCreativeImages.moodboard?.[index]
                  || tempMoodboardImages[index]
                  || '';
                return acc;
              }, { ...tempMoodboardImages }),
              approved: Array.isArray(tenantCreativeImages.moodboard)
                ? tenantCreativeImages.moodboard.map(image => !!image)
                : []
            },
            // tenantSlidesData already rides at the top level of this payload; the copy that
            // used to live here doubled every draft's stored and transferred size.
            slides: {
              generated: tenantSlidesData.length > 0,
              status: tenantSlidesData.length ? 'draft' : 'empty'
            }
          };
        }
        // Saving can now be megabytes (slides + images), so it uses parallel chunked uploads.
        // Show progress in the badge so a large save does not look like nothing is happening.
        const badge = document.getElementById('draftSyncBadge');
        if (badge) {
          badge.style.background = '#eef5fb';
          badge.style.color = '#123B6D';
          badge.innerHTML = 'جاري الحفظ...';
        }
        const onProgress = badge ? (sent, total) => {
          const pct = Math.round(100 * sent / total);
          badge.style.background = '#eef5fb';
          badge.style.color = '#123B6D';
          badge.innerHTML = 'جاري الحفظ... ' + pct + '%';
        } : null;

        // Both records receive the same immutable snapshot, not two different
        // generations of the live workspace separated by an asynchronous save.
        const snapshot = JSON.parse(JSON.stringify(data));
        const savedPresentationId = tenantPresentationId;
        const savedPresentationTitle = tenantPresentationTitle;
        const savedWorkspaceRef = tenantProjectData;
        const savedEditCounter = draftEditCounter;
        const resp = await api('POST', '/api/project-draft',
          { draftData: snapshot, sectionStatuses: tenantProjectSectionStatuses, status: 'draft',
            slideCheckpoint, expectedRevision: tenantDraftRevision },
          false, { onProgress });
        // The response describes the workspace captured above. A draft-id ack
        // belongs to the draft row, so it lands whenever the same draft is
        // still open — an edit meanwhile does not invalidate it — while the
        // saved-badge and the dirty flag require the state to be untouched.
        const sameDraftOpen = resp.draftId
          ? tenantProjectData.draftId === resp.draftId
          : tenantProjectData === savedWorkspaceRef;
        const stillCurrent = tenantProjectData === savedWorkspaceRef
          && draftEditCounter === savedEditCounter;
        if (sameDraftOpen) {
          if (resp.draftId) tenantProjectData.draftId = resp.draftId;
          if (resp.revision) tenantDraftRevision = Number(resp.revision) || tenantDraftRevision;
        }
        if (resp.success) {
          if (syncPresentation && savedPresentationId && snapshot.tenantSlidesData.length) {
            try {
              const presTitle = savedPresentationTitle
                || snapshot.project_name || snapshot.projectName || 'عرض بدون عنوان';
              const presResp = await commitTenantPresentation(snapshot, savedPresentationId, presTitle, { silent });
              if (!presResp?.success) throw new Error(presResp?.error || 'تعذر حفظ العرض');
            } catch (presErr) {
              console.error('[PRESENTATION SAVE]', presErr);
              setDraftDirty(true);
              tenantArchiveCache = null;
              if (badge) {
                badge.style.background = '#fee2e2';
                badge.style.color = '#991b1b';
                badge.textContent = 'المسودة محفوظة؛ تعذر حفظ العرض';
              }
              if (!silent) toast('حُفظت المسودة، لكن تعذر حفظ العرض: ' + (presErr?.message || presErr));
              return false;
            }
          }
          if (stillCurrent) {
            if (!slideCheckpoint) tenantDraftDirty = false;
            if (badge) {
              const timeStr = new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' });
              badge.style.background = '#dcfce7';
              badge.style.color = '#166534';
              badge.innerHTML = 'محفوظ (' + timeStr + ')';
            }
          }
          tenantArchiveCache = null;
          if (!silent) toast('تم حفظ المسودة على الخادم');
          return true;
        } else {
          if (badge) {
            badge.style.background = '#fee2e2';
            badge.style.color = '#991b1b';
            badge.innerHTML = 'فشل الحفظ — التغييرات ما زالت غير محفوظة';
          }
          if (!silent) toast(resp.error || 'فشل حفظ المسودة');
          return false;
        }
      } catch (e) {
        // This used to paint a badge and stop. collectTenantFormData can throw on a failed file
        // upload, so a save could fail with no message anywhere and no entry in the console.
        console.error('[DRAFT SAVE]', e);
        const badge = document.getElementById('draftSyncBadge');
        if (badge) {
          badge.style.background = '#fee2e2';
          badge.style.color = '#991b1b';
          badge.innerHTML = 'لم يتم الحفظ — التغييرات غير محفوظة';
        }
        if (!silent) toast('تعذر حفظ المسودة: ' + (e?.message || e));
        return false;
      }
    }

    async function confirmDeleteProject() {
      if (confirm('هل أنتِ متأكدة من حذف بيانات المشروع؟ هذا الإجراء لا يمكن التراجع عنه.')) {
        // The draft id has to be sent: DELETE /api/project-draft has no handler, so the old
        // call returned 405 and the draft stayed on the server while the form looked emptied.
        const draftId = tenantProjectData?.draftId;
        const resp = draftId
          ? await api('DELETE', '/api/project-draft/' + encodeURIComponent(draftId))
          : { success: true };
        if (!resp?.success) {
          toast(resp?.error || 'تعذر حذف المسودة من الخادم');
          return;
        }
        document.getElementById('tenantProjectForm').innerHTML = '';
        tenantDraftDirty = false;
        tenantArchiveCache = null;
        clearTenantNavigationState();
        toast('تم حذف بيانات المشروع');
        showTenantPage('tenantDashboardPage');
      }
    }

    async function geocodeProjectAddress(addressInput, latInput, lngInput, force = false) {
      const val = addressInput ? addressInput.value.trim() : '';
      if (!force && latInput && latInput.value.trim() && lngInput && lngInput.value.trim()) return true;
      if (!val) { toast('أدخل عنوان الموقع أو رابط قوقل ماب أولاً'); return false; }
      showLoader('جاري تحديد الإحداثيات', '');
      const payload = { address: val, maps_link: val };
      const data = await api('POST', '/api/geocode', payload);
      hideLoader();
      if (data.success && data.lat && data.lng) {
        if (latInput) latInput.value = data.lat;
        if (lngInput) lngInput.value = data.lng;
        tenantProjectData.location_address = val;
        tenantProjectData.location_lat = data.lat;
        tenantProjectData.location_lng = data.lng;
        tenantProjectData.location_coordinates_confirmed = false;
        if (data.city || data.district) applyCityDistrictToForm(data.city, data.district, true);
        const msg = data.source === 'maps_link' ? 'تم الاستخراج من رابط خرائط جوجل' : (data.formatted_address || val);
        toast('تم تحديد الموقع: ' + msg);
        return true;
      }
      toast(data.error || 'تعذر تحديد الإحداثيات — جربي رابط قوقل ماب مباشر أو عنوان نصي');
      return false;
    }

    function normalizeLandUseStatus(value) {
      const text = String(value || '').trim();
      if (!text) return '';
      if (/غير\s*مسموح|ممنوع/.test(text)) return 'غير مسموح';
      if (/غير\s*محسوم|غير\s*محدد/.test(text)) return 'غير محسوم';
      if (text === 'مسموح' || /(^|[^\u0621-\u064A])مسموح([^\u0621-\u064A]|$)/.test(text)) return 'مسموح';
      return '';
    }

    function stripLandUseStatusFromText(value) {
      const raw = String(value || '');
      const lineRe = /(?:حالة\s*)?استخدام\s*(?:نوع\s*)?(?:المشروع|الأرض)\s*[:：]?\s*(مسموح|غير\s*مسموح|غير\s*محسوم|غير\s*محدد|ممنوع)/i;
      const onlyRe = /^(حالة\s*استخدام\s*المشروع\s*[:：]\s*)?(مسموح|غير\s*مسموح|غير\s*محسوم|غير\s*محدد|ممنوع)\.?$/i;
      const match = raw.match(lineRe);
      const only = raw.trim().match(onlyRe);
      const status = normalizeLandUseStatus((match && match[1]) || (only && only[2]) || raw);
      let text = raw.replace(lineRe, '').replace(/ولم ي[ُو]حدد نوع المشروع[^\n.]*/g, '')
        .replace(/\n{2,}/g, '\n').replace(/^[\s\-–—:]+|[\s\-–—:]+$/g, '');
      if (onlyRe.test(text)) text = '';
      return { status, text };
    }

    function landUseStatusNote(status) {
      if (status === 'مسموح') {
        return { tone: 'ok', text: 'استخدام نوع المشروع مسموح حسب الاشتراطات' };
      }
      if (status === 'غير مسموح') {
        return { tone: 'bad', text: 'استخدام نوع المشروع غير مسموح حسب الاشتراطات' };
      }
      if (status === 'غير محسوم') {
        return { tone: 'bad', text: 'استخدام نوع المشروع غير محدد حسب الاشتراطات' };
      }
      return null;
    }

    function resolveLandUseStatus(projectType, allowedUses) {
      const projects = parseSelectedMarketList(projectType);
      const uses = stripLandUseStatusFromText(allowedUses).text;
      if (!projects.length) return 'غير محسوم';
      if (!uses || uses.startsWith('غير محدد')) return 'غير محسوم';
      const aliases = {
        'سكني': ['سكني'],
        'تجاري': ['تجاري'],
        'إداري': ['إداري', 'مكتبي', 'مكاتب'],
        'فندقي': ['فندقي', 'فندق'],
        'ترفيهي': ['ترفيهي', 'سياحي', 'ترفيه'],
        'صناعي': ['صناعي'],
        'لوجستي': ['لوجستي', 'مستودع', 'تخزين'],
        'صناعي ولوجستي': ['صناعي', 'لوجستي', 'مستودع', 'تخزين'],
        'متعدد الاستخدامات': ['متعدد', 'مختلط', 'متنوع', 'سكني', 'تجاري'],
        'طبي': ['طبي', 'صحي'],
        'تعليمي': ['تعليمي', 'مدرسة', 'جامعة'],
        'سيارات وترفيه': ['سيارات', 'ترفيهي', 'ترفيه'],
        'مختلط': ['مختلط', 'متنوع', 'سكني', 'تجاري', 'متعدد']
      };
      const keys = projects.flatMap(project => aliases[project] || [project]);
      return keys.some(alias => alias && uses.includes(alias)) ? 'مسموح' : 'غير مسموح';
    }

    function refreshAllowedUsesStatusNote() {
      const projectType = selectedProjectTypeMains().join('، ')
        || document.querySelector('#tenantProjectForm [data-key="project_type"]')?.value
        || tenantProjectData.project_type;
      const allowedUses = document.querySelector('#tenantProjectForm [data-key="allowed_uses"]')?.value
        || tenantProjectData.allowed_uses;
      const status = resolveLandUseStatus(projectType, allowedUses);
      tenantProjectData.land_use_status = status;
      renderAllowedUsesStatusNote(status);
      renderComponentsAllowedUsesNote(allowedUses, status);
    }

    function renderComponentsAllowedUsesNote(allowedUses, status) {
      // The components table is where the activities are actually chosen, so the regulated
      // list belongs next to it. This is data read from the land section, not guidance.
      const note = document.getElementById('componentsAllowedUsesNote');
      if (!note) return;
      const uses = stripLandUseStatusFromText(allowedUses ?? tenantProjectData.allowed_uses).text.trim();
      if (!uses) {
        note.hidden = true;
        note.textContent = '';
        return;
      }
      note.hidden = false;
      note.innerHTML = '<span>الاستخدامات المسموحة تنظيميًا:</span> ' + escapeHtml(uses);
    }

    function renderAllowedUsesStatusNote(status) {
      const note = document.getElementById('allowedUsesStatusNote');
      if (!note) return;
      const info = landUseStatusNote(normalizeLandUseStatus(status));
      if (!info) {
        note.hidden = true;
        note.textContent = '';
        return;
      }
      note.hidden = false;
      note.textContent = info.text;
      note.style.color = info.tone === 'ok' ? '#0b7a3b' : '#9c1d1d';
    }

    function buildExtractedLandFieldData(data) {
      const fields = { ...(data || {}) };
      const parcel = Array.isArray(data?.parcels) ? data.parcels[0] : null;
      if (!parcel) return fields;

      const directions = parcel.directions && typeof parcel.directions === 'object' ? parcel.directions : {};
      const directionRows = normalizeSurveyDirections(directions);
      const directionText = directionRows
        .filter(row => row.regulation_text)
        .map(row => row.label + ': ' + row.regulation_text)
        .join(' | ');
      const streetsText = directionRows
        .map(row => {
          const direction = directions[row.direction] || {};
          const street = direction.street_name || direction.uses || '';
          const width = direction.street_width_m ? ' (' + direction.street_width_m + 'م)' : '';
          return street ? row.label + ': ' + street + width : '';
        })
        .filter(Boolean)
        .join(' | ');
      const boundariesText = directionRows
        .map(row => {
          const direction = directions[row.direction] || {};
          return direction.boundary_length_m ? row.label + ': ' + direction.boundary_length_m + 'م' : '';
        })
        .filter(Boolean)
        .join(' | ');
      // The field is labelled "نسبة البناء والتغطية والارتدادات", so all three parts have to be
      // shown. Taking `building_ratio || setbacks` used to reduce it to a bare "60%".
      const buildingRatioCoverageText = [
        ['نسبة البناء', parcel.building_ratio],
        ['نسبة التغطية', parcel.coverage_ratio],
        ['معامل مسطح البناء (FAR)', parcel.floor_area_ratio],
        ['عدد الأدوار بموجب الجدول', parcel.table_floors]
      ].filter(([, value]) => value !== undefined && value !== null && String(value).trim() !== '')
        .map(([label, value]) => label + ': ' + String(value).trim())
        .join('\n');
      const directionSetbacksText = directionRows
        .map(row => row.setback ? row.label + ': ' + row.setback : '')
        .filter(Boolean)
        .join(' | ');
      const setbacksText = String(parcel.setbacks || '').trim() || directionSetbacksText;
      const buildingRulesText = [buildingRatioCoverageText, setbacksText]
        .filter(Boolean)
        .join('\n');

      const strippedUses = stripLandUseStatusFromText(parcel.allowed_uses || parcel.allowed_uses_restrictions || '');
      const allowedUsesText = strippedUses.text;
      const constraintsText = String(parcel.regulatory_constraints || '').trim();
      const legacyRestrictionsText = [allowedUsesText, constraintsText]
        .filter(Boolean)
        .join('\n');

      const parcelFields = {
        plot_number_croquis: parcel.plot_number,
        plan_number: parcel.plan_number,
        subdivision_number: parcel.subdivision_number,
        deed_number: parcel.deed_number,
        deed_date: parcel.deed_date,
        croquis_land_area: parcel.area_sqm,
        facades_count: parcel.facades_count,
        facades_directions: parcel.facades_directions,
        boundary_lengths: parcel.boundary_lengths || boundariesText,
        surrounding_streets: parcel.surrounding_streets || streetsText,
        north_direction: parcel.north_direction,
        building_ratio_coverage: parcel.building_ratio_coverage || buildingRatioCoverageText,
        setbacks: parcel.setbacks || setbacksText,
        building_ratio_setbacks: parcel.building_ratio_setbacks || buildingRulesText,
        max_floors_height: parcel.max_floors_height,
        allowed_uses: allowedUsesText,
        regulatory_constraints: constraintsText,
        allowed_uses_restrictions: parcel.allowed_uses_restrictions || legacyRestrictionsText,
        // The whole-document summary is the detailed narrative; parcel.summary is only a
        // per-parcel note and must never replace it.
        land_and_building_summary: data.land_and_building_summary || parcel.summary,
        directions_table: data.directions_table || directionRows
      };
      Object.entries(parcelFields).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') fields[key] = value;
      });
      // Client-entered decisions must never be populated by document analysis.
      delete fields.approved_financial_area;
      delete fields.approved_financial_area_sqm;
      delete fields.approved_floor_count;
      delete fields.approved_floors;
      delete fields.approved_coverage_ratio;
      delete fields.land_use_status;
      return fields;
    }

    function showLandAnalysisDiagnostics(analysis = {}) {
      const host = document.getElementById('landDocumentsUploadStatus');
      if (!host) return;
      const diagnostics = analysis && typeof analysis.extraction_diagnostics === 'object'
        ? analysis.extraction_diagnostics : {};
      const parcel = Array.isArray(analysis?.parcels) ? analysis.parcels[0] : null;
      const coordinateRows = Number.isFinite(Number(diagnostics.coordinates_rows))
        ? Number(diagnostics.coordinates_rows)
        : (Array.isArray(analysis?.survey_coordinates) ? analysis.survey_coordinates.length
          : (Array.isArray(parcel?.survey_coordinates) ? parcel.survey_coordinates.length : 0));
      const completeCoordinateRows = Number.isFinite(Number(diagnostics.coordinates_complete_rows))
        ? Number(diagnostics.coordinates_complete_rows)
        : (Array.isArray(analysis?.survey_coordinates)
          ? analysis.survey_coordinates.filter(row => row?.eastings && row?.northings).length : 0);
      const directionMap = parcel?.directions && typeof parcel.directions === 'object' ? parcel.directions : {};
      const directionRows = Number.isFinite(Number(diagnostics.directions_with_values))
        ? Number(diagnostics.directions_with_values)
        : Object.values(directionMap).filter(value => {
          if (!value || typeof value !== 'object') return Boolean(String(value || '').trim());
          return ['regulation_text', 'street_name', 'street_width_m', 'boundary_length_m', 'uses', 'notes']
            .some(key => String(value[key] ?? '').trim());
        }).length;
      const missingTables = Array.isArray(diagnostics.missing_tables) ? diagnostics.missing_tables : [];
      const conflicts = Array.isArray(analysis?.conflicts) ? analysis.conflicts : [];
      const conflictTexts = conflicts.map(item => {
        if (typeof item === 'string') return item;
        return item?.description || item?.field || '';
      }).map(value => String(value).trim()).filter(Boolean);
      const uncertaintyMarkers = [
        'غير مقروء', 'غير مقروءة', 'غير واضح', 'غير واضحة', 'غير متوفر', 'غير محدد',
        'غير مؤكد', 'غير مكتمل', 'لم تُقرأ', 'لم يقرأ', 'لم يتم', 'يتعذر', 'تعذر',
        'ناقص', 'مفقود', 'يحتاج مراجعة', 'بحاجة إلى مراجعة'
      ];
      const uncertainConflicts = conflictTexts.filter(text =>
        uncertaintyMarkers.some(marker => text.includes(marker))
      ).slice(0, 3);
      const issueTexts = [...missingTables.map(table => 'لم تُقرأ بيانات ' + table)];
      if (!coordinateRows) issueTexts.push('جدول إحداثيات التنظيم فارغ أو غير مقروء');
      else if (completeCoordinateRows < coordinateRows) issueTexts.push('بعض صفوف الإحداثيات ناقصة أو غير واضحة');
      if (directionRows < 4) issueTexts.push('جدول الاتجاهات بموجب التنظيم ناقص أو غير واضح');
      issueTexts.push(...uncertainConflicts);
      let panel = document.getElementById('landAnalysisDiagnostics');
      if (!issueTexts.length) {
        if (panel) panel.hidden = true;
        return;
      }
      if (!panel) {
        panel = document.createElement('div');
        panel.id = 'landAnalysisDiagnostics';
        host.insertAdjacentElement('afterend', panel);
      }
      panel.hidden = false;
      panel.style.cssText = 'margin-top:10px;padding:11px 13px;border-radius:12px;' +
        'background:#fff8e8;border:1px solid #ead39a;color:#755b12;' +
        'font-size:13px;line-height:1.7';
      panel.innerHTML = '<strong>ملاحظات تحتاج مراجعة</strong>' + issueTexts
        .map(text => '<div>' + escapeHtml(text) + '</div>').join('');
    }

    function clearLandAnalysisDiagnostics() {
      const panel = document.getElementById('landAnalysisDiagnostics');
      if (panel) panel.hidden = true;
    }