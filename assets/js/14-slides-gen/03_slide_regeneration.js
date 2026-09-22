    /* ── Tenant slide regeneration: plan-job polling, section-targeted
       regen, snapshot replacement and the assets sent to the planner. ── */


    // The planner reads every section of the project, so it can take minutes. The server queues it
    // and answers with a job id, because the hosting proxy drops a request held open that long and
    // the browser then reported a timeout for a plan the server had actually produced.
    async function pollTenantSlidePlanJob(jobId, onProgress) {
      const started = Date.now();
      let res = null;
      while (Date.now() - started < 2 * 60 * 1000) {
        await new Promise(resolve => setTimeout(resolve, 2500));
        res = await apiWithTimeout('GET', '/api/slide-plan/jobs/' + encodeURIComponent(jobId), null,
          30000);
        const status = String(res && res.status || '');
        if (typeof onProgress === 'function') onProgress(res);
        if (status === 'completed' || status === 'failed' || (res && res.plan)) break;
        if (!res || res.failureReason === 'job_not_found') break;
      }
      if (res && !res.plan && !res.error) {
        res = { success: false, error: 'تعذر إعداد خطة الشرائح في الوقت المتاح', error_code: 'PLAN_JOB_TIMEOUT' };
      }
      return res;
    }

    // A slide can take longer than the shared hosting proxy allows. Queueing the request keeps the
    // browser connected only to short status calls and guarantees that a timeout cannot start the
    // same paid AI generation three more times. While the job runs, the worker publishes the
    // streamed text as `partial`, so the caller can paint the slide live; the completed slide
    // below is still the same finalized response, never the preview.
    async function requestTenantSlideGeneration(payload, onPartial) {
      const queued = await apiWithTimeout(
        'POST', '/api/generate-slide-single-job', payload, 30000,
        'تعذر تسجيل مهمة توليد الشريحة؛ لم يبدأ استهلاك جديد.'
      );
      if (!queued?.jobId) return queued;

      const started = Date.now();
      const maxWaitMs = 10 * 60 * 1000;
      let lastPartial = '';
      while (Date.now() - started < maxWaitMs) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        const result = await apiWithTimeout(
          'GET', '/api/generate-slide-single/jobs/' + encodeURIComponent(queued.jobId), null,
          30000, 'انتهت مهلة متابعة مهمة توليد الشريحة.'
        );
        if (result && typeof result.partial === 'string' && result.partial && result.partial !== lastPartial) {
          lastPartial = result.partial;
          if (typeof onPartial === 'function') {
            try { onPartial(result.partial); } catch (previewError) { /* preview-only */ }
          }
        }
        if (result?.status === 'completed' || (result?.success && result?.slide)) return result;
        if (result?.status === 'failed' || result?.status === 'not_found' || result?.error_code) return result;
        if (result?.error && !['queued', 'running'].includes(result?.status)) return result;
      }
      return {
        success: false,
        error: 'انتهت مهلة توليد الشريحة. يمكن استكمال العرض من آخر شريحة محفوظة.',
        error_code: 'SLIDE_JOB_TIMEOUT'
      };
    }

    const TENANT_SECTION_REGENERATION_TARGETS = [
      { key: 'overview', label: 'نبذة عن المشروع', pattern: /نبذة عن المشروع|نظرة عامة|فكرة المشروع/i },
      { key: 'components', label: 'مكونات المشروع', pattern: /مكونات المشروع|المكونات|الوحدات والمساحات/i },
      { key: 'land', label: 'تحليل الأرض', pattern: /تحليل الأرض|الأرض والكروكي|الكروكي|حدود الأرض/i },
      { key: 'location', label: 'تحليل الموقع الجغرافي', pattern: /تحليل الموقع الجغرافي|تحليل الموقع|الموقع الجغرافي/i },
      { key: 'market', label: 'تحليل السوق', pattern: /تحليل السوق|دراسة السوق|السوق/i },
      { key: 'timeline', label: 'الجدول الزمني', pattern: /الجدول الزمني|الخطة الزمنية|مراحل التطوير/i },
      { key: 'financial', label: 'الدراسة المالية', pattern: /الدراسة المالية|التحليل المالي|الجدوى المالية/i },
      { key: 'swot_risks', label: 'تحليل SWOT وتحليل المخاطر', pattern: /تحليل\s*swot|تحليل المخاطر|المخاطر/i },
      { key: 'team', label: 'فريق العمل', pattern: /فريق العمل|فريق التطوير/i },
      { key: 'visual_concept', label: 'التصور البصري', pattern: /قسم\s+التصورات(?:\s+(?:كامل|بالكامل))?|التصورات البصرية|التصور البصري/i },
      { key: 'plans', label: 'المخططات', pattern: /المخططات|المخطط|المساقط|المخطط المعماري/i },
      { key: 'exterior', label: 'التصورات الخارجية', pattern: /التصورات الخارجية|التصور الخارجي|الواجهات/i },
      { key: 'interior', label: 'التصورات الداخلية', pattern: /التصورات الداخلية|التصور الداخلي|التصميم الداخلي/i },
      { key: 'executive_summary', label: 'الملخص التنفيذي', pattern: /الملخص التنفيذي/i }
    ];

    function normalizeTenantSectionCommandText(value) {
      return String(value || '').trim()
        .replace(/[إأآ]/g, 'ا')
        .replace(/ة/g, 'ه')
        .replace(/ى/g, 'ي')
        .replace(/\s+/g, ' ');
    }

    function detectTenantSectionRegenerationRequest(message) {
      const text = String(message || '').trim();
      const normalized = normalizeTenantSectionCommandText(text);
      const isSectionRebuildCommand =
        /(?:اعاده|اعد)\s*(?:توليد|انشاء|بناء|تصميم|تنسيق)/i.test(normalized) ||
        /صمم\s*(?:قسم|القسم)/i.test(normalized);
      if (!text || !isSectionRebuildCommand) return null;
      if (!/(?:قسم|القسم|كامل|بالكامل)/i.test(text)) return null;
      return TENANT_SECTION_REGENERATION_TARGETS.find(item => {
        const normalizedPattern = new RegExp(item.pattern.source.replace(/ة/g, 'ه'), item.pattern.flags);
        return item.pattern.test(text) || normalizedPattern.test(normalized);
      }) || null;
    }

    function tenantSlideMatchesSection(slide, index, sectionKey) {
      const candidates = [slide, tenantSlidePlan?.slides?.[index]].filter(Boolean);
      return candidates.some(candidate => {
        const source = String(candidate.content_source || candidate.contentSource || '').toLowerCase();
        const title = String(candidate.title || '').toLowerCase();
        const type = String(candidate.type || '').toLowerCase();
        if (sectionKey === 'visual_concept') {
          const explicit = String(candidate.section_key || candidate.sectionKey || candidate.section || '').trim();
          return ['plans', 'exterior', 'interior'].includes(explicit) ||
            ['plans', 'exterior', 'interior'].includes(tenantSlideSectionKey(candidate, ''));
        }
        if (sectionKey === 'financial' && (
          source.startsWith('financial_') || source.startsWith('financial:') ||
          source.startsWith('financial_report:') || source.startsWith('financial_summary:') ||
          /الدراسة المالية|التحليل المالي|الجدوى المالية|التدفقات النقدية|مؤشرات العائد|التكاليف والاستثمار|financial|cash ?flow|roi|irr/i.test(title)
        )) return true;
        if (sectionKey === 'location' && (
          type.startsWith('map_') || type === 'site_specs' ||
          ['location_polygon', 'main_roads', 'catchment_areas', 'nearby_landmarks', 'site_analysis', 'location_detail'].includes(source)
        )) return true;
        return tenantSlideSectionKey(candidate, '') === sectionKey;
      });
    }

    const TENANT_SECTION_PLANNER_KEYS = {
      overview: 'basic',
      components: 'basic',
      land: 'land_croquis',
      location: 'location',
      market: 'section-market-study',
      swot_risks: 'section-market-study',
      timeline: 'section-timeline',
      financial: 'section-financial-calc',
      team: 'section-team',
      visual_concept: 'section-visual-concept',
      plans: 'section-visual-concept',
      exterior: 'section-visual-concept',
      interior: 'section-visual-concept',
      executive_summary: 'section-executive-content'
    };

    function tenantSectionPlanMatchesSection(slide, sectionKey) {
      if (!slide || ['cover', 'index', 'closing'].includes(String(slide.type || '').toLowerCase())) return false;
      const explicit = String(slide.section_key || slide.sectionKey || slide.section || '').trim();
      if (sectionKey === 'visual_concept') {
        return ['plans', 'exterior', 'interior'].includes(explicit) ||
          ['plans', 'exterior', 'interior'].includes(tenantSlideSectionKey(slide, ''));
      }
      if (String(slide.type || '').toLowerCase() === 'section_divider') return false;
      return explicit === sectionKey || tenantSlideSectionKey(slide, '') === sectionKey;
    }

    async function requestTenantSectionSlidePlans(sectionKey) {
      const plannerKey = TENANT_SECTION_PLANNER_KEYS[sectionKey];
      if (!plannerKey) throw new Error('القسم غير مدعوم لإعادة التخطيط');
      const response = await requestTenantSlidePlan(tenantProjectData, job => {
        setLiveGenBanner(true, 'إعادة تخطيط قسم ' + (TENANT_PRESENTATION_SECTION_TITLES[sectionKey] || sectionKey),
          (job && job.message) || 'تحليل الصور والبيانات وتحديد عدد الشرائح المناسب', 12);
      }, plannerKey);
      if (!response?.success || !response.plan) {
        throw new Error(response?.error || 'تعذر إعداد خطة القسم الجديدة');
      }
      const slides = (response.plan.slides || []).filter(slide => tenantSectionPlanMatchesSection(slide, sectionKey));
      if (!slides.length) throw new Error('لم تنتج خطة القسم شرائح قابلة للتوليد؛ لم يتم تغيير العرض.');
      return { plan: response.plan, slides };
    }

    function buildTenantSlideRegenerationSnapshot(index) {
      const slideIndex = Number(index);
      const current = Array.isArray(tenantSlidesData) ? tenantSlidesData[slideIndex] : null;
      if (!current || slideIndex < 0 || slideIndex >= tenantSlidesData.length) return null;
      const planned = tenantSlidePlan?.slides?.[slideIndex] || {};
      const snapshot = { ...planned };
      ['title', 'type', 'section_key', 'content_source', 'source_table', 'design_style', 'designStyle',
        'chart_type', 'image_tokens', 'bullets', 'metrics', 'media_only',
        'market_row_start', 'market_row_end', 'index_entries'].forEach(key => {
        const missing = snapshot[key] === undefined || snapshot[key] === null ||
          (Array.isArray(snapshot[key]) && !snapshot[key].length && Array.isArray(current[key]) && current[key].length);
        if (missing && current[key] !== undefined) snapshot[key] = current[key];
      });
      snapshot.title = snapshot.title || current.title || ('شريحة ' + (slideIndex + 1));
      snapshot.type = snapshot.type || current.type || 'content';
      snapshot.design_style = snapshot.design_style || snapshot.designStyle || current.designStyle || 'cards';
      return { slideIndex, current, snapshot };
    }

    async function generateTenantSlideFromSnapshot(snapshot, slideIndex, totalSlides, generationImages, current = {}) {
      if (!snapshot) throw new Error('خطة الشريحة غير موجودة');
      const payload = {
        projectData: slimGenerationProjectData(tenantProjectData),
        slidePlan: { slides: [snapshot] },
        images: generationImages,
        slideIndex: 0,
        _slideNum: Number(slideIndex) + 1,
        _totalSlides: Number(totalSlides) || 1
      };
      // A slide regenerated inside a section-scoped presentation is checked
      // against that section's generation approval, not the full-file gate.
      const scopeMatch = String(tenantProjectData.presentation_scope || '').match(/^section:(.+)$/);
      if (scopeMatch) payload.sectionKey = scopeMatch[1];
      if (tenantPresentationId) payload.presentationId = tenantPresentationId;

      const data = await requestTenantSlideGeneration(payload);
      if (!data?.success || !data.slide?.html || !containsSlideRoot(data.slide.html)) {
        throw new Error(data?.error || 'تعذر إعادة توليد الشريحة');
      }

      const generatedType = data.slide.type || snapshot.type || current.type || 'content';
      const renderedHtml = processSlideHtmlClient(data.slide.html, generatedType);
      if (!renderedHtml || !containsSlideRoot(renderedHtml)) {
        throw new Error('استجابة الشريحة الجديدة غير مكتملة');
      }
      return {
        ...current,
        title: data.slide.title || snapshot.title || current.title,
        type: generatedType,
        html: renderedHtml,
        section_key: data.slide.sectionKey || snapshot.section_key || snapshot.sectionKey || current.section_key || '',
        content_source: data.slide.contentSource || snapshot.content_source || snapshot.contentSource || current.content_source || '',
        source_table: data.slide.sourceTable || snapshot.source_table || snapshot.sourceTable || current.source_table || '',
        index_entries: data.slide.indexEntries || snapshot.index_entries || snapshot.indexEntries || current.index_entries || [],
        designStyle: data.slide.designStyle || snapshot.design_style || snapshot.designStyle || current.designStyle || 'cards',
        bullets: snapshot.bullets || current.bullets || [],
        metrics: snapshot.metrics || current.metrics || []
      };
    }

    async function generateTenantSlideReplacement(index, generationImages) {
      const context = buildTenantSlideRegenerationSnapshot(index);
      if (!context) throw new Error('الشريحة غير موجودة');
      const { slideIndex, current, snapshot } = context;
      return generateTenantSlideFromSnapshot(snapshot, slideIndex, tenantSlidesData.length, generationImages, current);
    }

    async function regenerateTenantSlide(index) {
      if (!hasPermission('create_presentation')) return;
      if (isGeneratingTenantSlides || isRegeneratingTenantSlide) {
        toast('يوجد توليد جارٍ حاليًا');
        return;
      }
      if (hasResumableTenantSlideGeneration()) {
        toast('استكمل التوليد المتوقف قبل إعادة توليد شريحة');
        return;
      }

      const context = buildTenantSlideRegenerationSnapshot(index);
      if (!context) {
        toast('الشريحة غير موجودة');
        return;
      }
      if (!confirm('سيتم إعادة توليد الشريحة «' + context.snapshot.title + '» فقط، مع إبقاء باقي الشرائح كما هي. هل تريد المتابعة؟')) return;

      checkpointPresentationUndo();
      isRegeneratingTenantSlide = true;
      updatePresentationUndoButtons();
      renderTenantSlidesSidebar();
      setLiveGenBanner(true, 'إعادة توليد الشريحة ' + (context.slideIndex + 1) + ' من ' + tenantSlidesData.length,
        'لن تتأثر بقية الشرائح', 35);
      try {
        const previousHtml = tenantSlidesData[context.slideIndex] ? tenantSlidesData[context.slideIndex].html : '';
        tenantSlidesData[context.slideIndex] = await generateTenantSlideReplacement(
          context.slideIndex, buildPresentationGenerationImages());
        tenantSlidesData[context.slideIndex].html = copyWatermarkMarkup(
          previousHtml, tenantSlidesData[context.slideIndex].html);
        tenantProjectData.tenantSlidesData = tenantSlidesData;
        renumberTenantSlides();
        renderTenantSlides();
        selectTenantSlide(context.slideIndex);
        triggerAutoSaveDraft();
        toast('تم إعادة توليد الشريحة ' + (context.slideIndex + 1) + ' فقط');
      } catch (error) {
        console.error('[SLIDE REGENERATE]', error);
        toast(error?.message || 'تعذر إعادة توليد الشريحة');
      } finally {
        isRegeneratingTenantSlide = false;
        checkpointPresentationUndo();
        renderTenantSlidesSidebar();
        setLiveGenBanner(false);
      }
    }

    async function regenerateTenantSection(sectionKey, sectionLabel) {
      if (!hasPermission('create_presentation')) return false;
      if (isGeneratingTenantSlides || isRegeneratingTenantSlide) {
        toast('يوجد توليد جارٍ حاليًا');
        return false;
      }
      if (tenantSlidePlanRequest) {
        toast('يوجد إعداد خطة جارٍ حاليًا');
        return false;
      }
      if (hasResumableTenantSlideGeneration()) {
        toast('استكمل التوليد المتوقف قبل إعادة توليد قسم');
        return false;
      }

      renumberTenantSlides();
      const targetIndexes = tenantSlidesData
        .map((slide, index) => ({ slide, index }))
        .filter(item => sectionKey === 'visual_concept'
          || !['cover', 'index', 'closing', 'section_divider'].includes(String(item.slide?.type || '').toLowerCase()))
        .filter(item => tenantSlideMatchesSection(item.slide, item.index, sectionKey))
        .map(item => item.index);
      if (!targetIndexes.length) {
        toast('لا توجد شرائح لهذا القسم داخل العرض');
        return false;
      }
      const targetNumbers = targetIndexes.map(index => index + 1).join('، ');
      if (sectionKey === 'financial' && typeof validateFinancialStudyBeforeProceed === 'function'
        && !(await validateFinancialStudyBeforeProceed())) return false;
      if (!confirm('سيتم إعادة تخطيط وتوليد قسم «' + sectionLabel + '» من صوره وبياناته الحالية. قد يزيد أو يقل عدد شرائحه، مع إبقاء باقي العرض كما هو. هل تريد المتابعة؟')) return false;

      const previousSlides = tenantSlidesData.slice();
      const previousPlan = tenantSlidePlan;
      const previousProjectData = { ...tenantProjectData };
      checkpointPresentationUndo();
      isRegeneratingTenantSlide = true;
      updatePresentationUndoButtons();
      renderTenantSlidesSidebar();
      try {
        await repairVisualConceptStoredImages();
        persistVisualConceptDraftState();
        const generationImages = buildPresentationGenerationImages();
        const sectionPlan = await requestTenantSectionSlidePlans(sectionKey);
        const plannedSlides = sectionPlan.slides;
        const firstIndex = targetIndexes[0];
        const projectedTotal = tenantSlidesData.length - targetIndexes.length + plannedSlides.length;
        const replacements = [];
        for (let position = 0; position < plannedSlides.length; position += 1) {
          const planSlide = { ...plannedSlides[position] };
          setLiveGenBanner(true, 'إعادة توليد قسم ' + sectionLabel,
            'الشريحة ' + (position + 1) + ' من ' + plannedSlides.length, 20 + Math.round((position / plannedSlides.length) * 65));
          replacements.push({
            slide: await generateTenantSlideFromSnapshot(
              planSlide, firstIndex + position, projectedTotal, generationImages, {})
          });
          // Regenerated section slides start without a watermark; the user
          // enables it per slide from the edit toolbar.
        }

        const targetSet = new Set(targetIndexes);
        const nextSlides = tenantSlidesData.filter((slide, index) => !targetSet.has(index));
        nextSlides.splice(firstIndex, 0, ...replacements.map(item => item.slide));
        tenantSlidesData = nextSlides;
        tenantProjectData.tenantSlidesData = tenantSlidesData;
        renumberTenantSlides();
        renderTenantSlides();
        selectTenantSlide(Math.min(firstIndex, tenantSlidesData.length - 1));
        triggerAutoSaveDraft();
        tenantDesignerMessages.push({
          role: 'assistant',
          content: 'تم إعادة تخطيط وتوليد قسم ' + sectionLabel + ' فقط (' + plannedSlides.length + ' شرائح بدلًا من ' + targetIndexes.length + ')، مع إبقاء باقي العرض كما هو.',
          slides: Array.from({ length: plannedSlides.length }, (_, offset) => firstIndex + offset + 1)
        });
        renderTenantDesignerChat();
        return true;
      } catch (error) {
        console.error('[SECTION REGENERATE]', error);
        tenantSlidesData = previousSlides;
        tenantSlidePlan = previousPlan;
        tenantProjectData = previousProjectData;
        tenantProjectData.tenantSlidesData = tenantSlidesData;
        renderTenantSlides();
        tenantDesignerMessages.push({
          role: 'assistant',
          content: error?.message || 'تعذر إعادة توليد القسم؛ لم يتم استبدال الشرائح القديمة.',
          slides: targetIndexes.map(index => index + 1)
        });
        renderTenantDesignerChat();
        return false;
      } finally {
        isRegeneratingTenantSlide = false;
        checkpointPresentationUndo();
        renderTenantSlidesSidebar();
        setLiveGenBanner(false);
      }
    }

    function buildPresentationGenerationImages() {
      const externalSlots = VISUAL_CONCEPT_EXTERNAL_SLOTS.slice(1);
      const visualMoodboard = externalSlots.map(item => tenantVisualConceptState?.slots?.[item.id]?.approvedImageUrl || tenantVisualConceptState?.slots?.[item.id]?.imageUrl || '');
      const fallbackMoodboard = Array.isArray(tenantCreativeImages?.moodboard) ? tenantCreativeImages.moodboard : [];
      const moodboard = visualMoodboard.some(Boolean)
        ? visualMoodboard
        : fallbackMoodboard.map((image, index) => image || tempMoodboardImages[index] || '');
      const moodboardMeta = externalSlots.map((item, index) => {
        const slot = tenantVisualConceptState?.slots?.[item.id] || {};
        return {
          label: slot.label || visualConceptDefaultSlotLabel(item.id),
          caption: slot.caption || '',
          url: moodboard[index] || ''
        };
      });
      const interiorComponents = visualConceptInteriorComponents().map((component, componentIndex) => {
        const images = [];
        for (let view = 1; view <= VISUAL_CONCEPT_MAX_INTERIOR_IMAGES; view += 1) {
          const slot = tenantVisualConceptState?.slots?.[visualConceptInteriorSlotId(component.id, view)];
          const url = slot?.approvedImageUrl || slot?.imageUrl || '';
          if (url) images.push({
            viewIndex: view,
            url,
            label: slot?.label || component.name,
            caption: slot?.caption || ''
          });
        }
        return {
          id: component.id,
          index: componentIndex + 1,
          name: component.name,
          useType: component.useType,
          builtArea: component.builtArea,
          images
        };
      }).filter(component => component.images.length);
      const interior = interiorComponents.flatMap(component => component.images.map(image => image.url));
      const plansState = typeof visualConceptPlans === 'function' ? visualConceptPlans() : [];
      const plans = plansState.map(plan => plan?.imageUrl || '').filter(Boolean);
      const planMeta = plansState.filter(plan => plan?.imageUrl).map(plan => ({
        title: plan.title || plan.fileName || '',
        description: plan.description || '',
        url: plan.imageUrl
      }));
      const landPhotos = (Array.isArray(tenantProjectData?.land_photos_file_meta)
        ? tenantProjectData.land_photos_file_meta : []).map(photo => ({
          id: photo?.id || '',
          url: durableImageUrl(photo?.imageUrl || photo?.url || (photo?.path ? '/' + String(photo.path).replace(/^\/+/, '') : '')),
          name: photo?.originalName || photo?.name || '',
          description: photo?.description || ''
        }));
      return {
        ...(tenantCreativeImages || {}),
        cover: tenantVisualConceptState?.slots?.cover?.approvedImageUrl || tenantVisualConceptState?.slots?.cover?.imageUrl || tenantCreativeImages?.cover || tempCoverImage || '',
        moodboard,
        moodboard_meta: moodboardMeta,
        interior_components: interiorComponents,
        interior,
        plans,
        plan_meta: planMeta,
        land_photos: landPhotos
      };
    }

    function buildPresentationPlanAssets() {
      const assets = buildPresentationGenerationImages();
      return {
        cover: assets.cover ? 'available' : '',
        moodboard: (assets.moodboard || []).map(image => image ? 'available' : ''),
        moodboard_meta: (assets.moodboard_meta || []).map(item => ({
          label: item.label || '', caption: item.caption || ''
        })),
        interior_components: (assets.interior_components || []).map(component => ({
          ...component,
          images: (component.images || []).map(image => ({ ...image, url: image.url ? 'available' : '' }))
        })),
        plans: (assets.plans || []).map(image => image ? 'available' : ''),
        plan_meta: (assets.plan_meta || []).map(item => ({
          title: item.title || '', description: item.description || ''
        })),
        land_photos: assets.land_photos || [],
        // The planner must know that approved maps are real assets.  Omitting
        // this field made it instruct the model that every map was unavailable,
        // even though the later slide request had the map images in memory.
        map_placeholders: assets.map_placeholders || {},
        map_zooms: assets.map_zooms || {},
        map_centers: assets.map_centers || {}
      };
    }

    let tenantSlidePlanRequest = null;
    function requestTenantSlidePlan(projectData, onProgress, sectionKey = '') {
      if (tenantSlidePlanRequest) return tenantSlidePlanRequest;
      const payload = typeof slimGenerationProjectData === 'function'
        ? slimGenerationProjectData(projectData) : projectData;
      const requestBody = {
        images: buildPresentationPlanAssets()
      };
      if (tenantPresentationId) requestBody.presentationId = tenantPresentationId;
      if (tenantDraftDirty || !tenantPresentationId) {
        // A dirty workspace is authoritative for this turn. The saved presentation is only a
        // fallback before the first local change, so refresh can still discard unsaved work.
        requestBody.projectData = payload;
      }
      if (sectionKey) requestBody.sectionKey = sectionKey;
      tenantSlidePlanRequest = apiWithTimeout('POST', '/api/slide-plan', requestBody)
        .then(async res => {
          if (!(res && res.jobId && !res.plan)) return res;
          const completed = await pollTenantSlidePlanJob(res.jobId, onProgress);
          if (completed?.plan || !res.fallbackPlan) return completed;
          return {
            success: true,
            plan: { ...res.fallbackPlan, source: 'fallback', source_error: completed?.error || 'planner_timeout' },
            planSource: 'fallback'
          };
        })
        .finally(() => { tenantSlidePlanRequest = null; });
      return tenantSlidePlanRequest;
    }
