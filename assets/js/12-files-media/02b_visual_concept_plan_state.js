    function visualConceptBoundaryPoints(value) {
      let parsed = value;
      if (typeof value === 'string') {
        try { parsed = JSON.parse(value); } catch (error) { parsed = []; }
      }
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        parsed = parsed.points || parsed.survey_coordinates || parsed.coordinates || [];
      }
      if (!Array.isArray(parsed)) return [];
      const coordinate = value => {
        if (value === null || value === undefined || typeof value === 'boolean' || String(value).trim() === '') return NaN;
        const text = String(value).replace(/[٠-٩]/g, digit => String('٠١٢٣٤٥٦٧٨٩'.indexOf(digit))).replace(/[,٬]/g, '');
        return Number(text);
      };
      return parsed.map((item, index) => {
        const source = Array.isArray(item)
          ? { eastings: item[0], northings: item[1], point: index + 1 }
          : (item && typeof item === 'object' ? item : {});
        return {
          parcel_id: String(source.parcel_id || source.parcelId || '').trim(),
          point: String(source.point || source.point_number || index + 1).trim(),
          eastings: coordinate(source.eastings ?? source.easting ?? source.x),
          northings: coordinate(source.northings ?? source.northing ?? source.y),
          source: String(source.source || '').trim().slice(0, 40)
        };
      }).filter(item => Number.isFinite(item.eastings) && Number.isFinite(item.northings)).slice(0, 60);
    }

    function emptyVisualConceptPlansWorkflow() {
      return {
        status: 'idle',
        verification: { checks: [], issues: [], summary: '', canProceed: false, approved: false },
        boundary: { points: [], referenceUrl: '', approved: false },
        distribution: { rows: [], totals: [], notes: [], checks: [], issues: [], approved: false,
          aiReviewed: false, reviewSignature: '', canProceed: null },
        distributionNotes: '',
        distributionRevision: '',
        conflictChats: { verify: [], distribution: [] },
        clientNotes: '',
        notesReview: { verified: false, canProceed: false, checks: [], issues: [], inputSignature: '', token: '',
          acknowledged: false, ackSignature: '', ackToken: '' },
        scene: null,
        sourceStamp: '',
        prompts: { site: '', uses: '', massing: '' },
        planContext: null,
        viewStage: 'verify',
        promptReady: false,
        promptsError: '',
        jobTodos: [],
        jobError: '',
        siteAssistant: {
          inputSignature: '', summary: '', turns: [], answers: [], pendingQuestion: '',
          readyForGeneration: false, designSpec: null, checkpoints: {}, renderRevision: 0,
          promptTokens: 0, compactionCount: 0, status: 'idle'
        }
      };
    }

    function normalizeVisualConceptPlansWorkflow(raw) {
      let value = raw;
      if (typeof value === 'string') {
        try { value = JSON.parse(value); } catch (error) { value = null; }
      }
      const source = value && typeof value === 'object' ? value : {};
      const empty = emptyVisualConceptPlansWorkflow();
      const verification = source.verification && typeof source.verification === 'object' ? source.verification : {};
      const boundary = source.boundary && typeof source.boundary === 'object' ? source.boundary : {};
      const distribution = source.distribution && typeof source.distribution === 'object' ? source.distribution : {};
      const review = source.notesReview && typeof source.notesReview === 'object' ? source.notesReview : {};
      const chats = source.conflictChats && typeof source.conflictChats === 'object' ? source.conflictChats : {};
      const chatTurns = list => (Array.isArray(list) ? list.slice(-12) : [])
        .map(item => ({
          role: item && item.role === 'assistant' ? 'assistant' : 'user',
          text: String((item && item.text) || '').slice(0, 2000)
        }))
        .filter(item => item.text);
      const prompts = source.prompts && typeof source.prompts === 'object' ? source.prompts : {};
      const scene = source.scene && typeof source.scene === 'object' && source.scene.version === 1 ? source.scene : null;
      const assistant = source.siteAssistant && typeof source.siteAssistant === 'object' ? source.siteAssistant : {};
      const assistantTurns = (Array.isArray(assistant.turns) ? assistant.turns : []).slice(-12).map(item => ({
        role: item?.role === 'assistant' ? 'assistant' : 'user',
        text: String(item?.text || '').slice(0, 4000),
        choices: Array.isArray(item?.choices) ? item.choices.slice(0, 6).map(choice => String(choice).slice(0, 240)) : []
      })).filter(item => item.text);
      const assistantAnswers = (Array.isArray(assistant.answers) ? assistant.answers : []).slice(-100).map(item => ({
        question: String(item?.question || '').slice(0, 800),
        answer: String(item?.answer || '').slice(0, 2000)
      })).filter(item => item.question && item.answer);
      const assistantCheckpoints = assistant.checkpoints && typeof assistant.checkpoints === 'object' ? assistant.checkpoints : {};
      return {
        ...empty,
        status: ['idle', 'verified', 'boundary', 'ready'].includes(source.status) ? source.status : 'idle',
        verification: {
          checks: Array.isArray(verification.checks) ? verification.checks.slice(0, 40) : [],
          issues: Array.isArray(verification.issues) ? verification.issues.slice(0, 30) : [],
          summary: String(verification.summary || '').slice(0, 1600),
          canProceed: Boolean(verification.canProceed),
          approved: Boolean(verification.approved)
        },
        boundary: {
          points: visualConceptBoundaryPoints(boundary.points || boundary.survey_coordinates),
          referenceUrl: durableImageUrl(boundary.referenceUrl || boundary.reference_url),
          approved: Boolean(boundary.approved)
        },
        distribution: {
          rows: (Array.isArray(distribution.rows) ? distribution.rows.slice(0, 60) : []).map((row, index) => ({
            id: String((row && row.id) || 'row_' + (index + 1)).slice(0, 40),
            building: String((row && row.building) || '').slice(0, 160),
            floor_range: String((row && (row.floor_range || row.floorRange)) || '').slice(0, 80),
            component: String((row && row.component) || '').slice(0, 160),
            units_per_floor: (row && row.units_per_floor) ?? '',
            floor_area_sqm: (row && row.floor_area_sqm) ?? '',
            circulation: String((row && row.circulation) || '').slice(0, 400),
            notes: String((row && row.notes) || '').slice(0, 2000)
          })),
          totals: Array.isArray(distribution.totals) ? distribution.totals.slice(0, 60) : [],
          notes: Array.isArray(distribution.notes) ? distribution.notes.slice(0, 12) : [],
          checks: Array.isArray(distribution.checks) ? distribution.checks.slice(0, 40) : [],
          issues: Array.isArray(distribution.issues) ? distribution.issues.slice(0, 30) : [],
          approved: Boolean(distribution.approved),
          aiReviewed: Boolean(distribution.aiReviewed),
          reviewSignature: String(distribution.reviewSignature || '').slice(0, 80),
          canProceed: typeof distribution.canProceed === 'boolean' ? distribution.canProceed : null
        },
        distributionNotes: String(source.distributionNotes || '').slice(0, 1000000),
        distributionRevision: String(source.distributionRevision || '').slice(0, 4000),
        conflictChats: { verify: chatTurns(chats.verify), distribution: chatTurns(chats.distribution) },
        clientNotes: String(source.clientNotes || '').slice(0, 1000000),
        notesReview: {
          verified: Boolean(review.verified), canProceed: Boolean(review.canProceed),
          checks: Array.isArray(review.checks) ? review.checks.slice(0, 30) : [],
          issues: Array.isArray(review.issues) ? review.issues.slice(0, 30) : [],
          inputSignature: String(review.inputSignature || '').slice(0, 64),
          token: String(review.token || '').slice(0, 128),
          acknowledged: Boolean(review.acknowledged),
          ackSignature: String(review.ackSignature || '').slice(0, 64),
          ackToken: String(review.ackToken || '').slice(0, 128)
        },
        scene,
        sourceStamp: String(source.sourceStamp || '').slice(0, 80),
        prompts: {
          site: String(prompts.site || '').slice(0, 64000),
          uses: String(prompts.uses || '').slice(0, 64000),
          massing: String(prompts.massing || '').slice(0, 64000)
        },
        planContext: source.planContext && typeof source.planContext === 'object' ? source.planContext : null,
        viewStage: ['verify', 'boundary', 'generate', 'other'].includes(source.viewStage) ? source.viewStage : 'verify',
        promptReady: Boolean(source.promptReady || (prompts.uses && prompts.massing)),
        promptsError: String(source.promptsError || '').slice(0, 400),
        jobError: String(source.jobError || '').slice(0, 1200),
        jobTodos: (Array.isArray(source.jobTodos) ? source.jobTodos : []).slice(0, 8).map((item, index) => ({
          id: String(item?.id || index + 1).slice(0, 24),
          label: String(item?.label || '').slice(0, 160),
          status: ['pending', 'active', 'done', 'failed'].includes(item?.status) ? item.status : 'pending',
          error: String(item?.error || '').slice(0, 1200)
        })).filter(item => item.label),
        siteAssistant: {
          inputSignature: String(assistant.inputSignature || '').slice(0, 80),
          renderRevision: Math.max(0, Number(assistant.renderRevision) || 0),
          summary: String(assistant.summary || '').slice(0, 40000),
          turns: assistantTurns,
          answers: assistantAnswers,
          pendingQuestion: String(assistant.pendingQuestion || '').slice(0, 800),
          readyForGeneration: Boolean(assistant.readyForGeneration),
          generateRequested: Boolean(assistant.generateRequested),
          designSpec: assistant.designSpec && typeof assistant.designSpec === 'object' ? assistant.designSpec : null,
          checkpoints: Object.fromEntries(['coordinates', 'colors', 'components', 'access', 'landscape', 'legend']
            .filter(name => typeof assistantCheckpoints[name] === 'string')
            .map(name => [name, assistantCheckpoints[name].slice(0, 60000)])),
          promptTokens: Math.max(0, Number(assistant.promptTokens) || 0),
          compactionCount: Math.max(0, Number(assistant.compactionCount) || 0),
          status: ['idle', 'questioning', 'ready', 'generating', 'editing', 'review'].includes(assistant.status)
            ? assistant.status : 'idle'
        }
      };
    }

    function visualConceptWorkflowPlanSeed(definition, workflow) {
      const prompt = workflow?.prompts?.[definition.kind] || '';
      return {
        mode: 'ai', label: definition.label, caption: definition.label, prompt,
        imageUrl: '', approvedImageUrl: '', status: 'pending', chat: [], svgCode: '',
        styleReferenceFileIds: [], styleReferenceNames: [], sourceFileId: '', sourceFileName: ''
      };
    }

    function visualConceptPlansWorkflowState() {
      tenantVisualConceptState = tenantVisualConceptState || normalizeVisualConceptState({});
      tenantVisualConceptState.plansWorkflow = normalizeVisualConceptPlansWorkflow(tenantVisualConceptState.plansWorkflow);
      return tenantVisualConceptState.plansWorkflow;
    }

    let visualConceptPlanScenePending = false;

    function isAdvisoryOrCompliantNotice(text) {
      if (!text || typeof text !== 'string') return false;
      const lower = text.toLowerCase();
      if (text.includes('مطابق') || text.includes('يطابق') || text.includes('لا يوجد تعارض') || text.includes('متوافق') || text.includes('ضمن المسموح')) {
        return true;
      }
      if (lower.includes('tia') || text.includes('دراسة مرورية') || text.includes('دراسة المرور')
          || text.includes('المباني العالية') || text.includes('دليل المباني العالية')
          || text.includes('كود البناء') || text.includes('اشتراطات أمانة') || text.includes('نظام واشتراطات')
          || text.includes('إشعار تنظيمي') || text.includes('ملاحظة تنظيمية')
          || text.includes('متطلب إجرائي') || text.includes('اشتراط إجرائي')
          || text.includes('تأكيد استيفاء') || text.includes('مراجعة بيانات موثقة')) {
        return true;
      }
      return false;
    }

    function visualConceptDistributionRowsStamp(rows) {
      const clean = (Array.isArray(rows) ? rows : []).map(r => ({
        b: String(r?.building || '').trim(),
        f: String(r?.floor_range || '').trim(),
        c: String(r?.component || '').trim(),
        u: String(r?.units_per_floor ?? '').trim(),
        a: String(r?.floor_area_sqm ?? '').trim(),
        s: String(r?.circulation || '').trim()
      }));
      const data = JSON.stringify(clean);
      let first = 2166136261, second = 5381;
      for (let index = 0; index < data.length; index += 1) {
        first = Math.imul(first ^ data.charCodeAt(index), 16777619);
        second = Math.imul(second, 33) ^ data.charCodeAt(index);
      }
      return (first >>> 0).toString(16) + ':' + (second >>> 0).toString(16) + ':' + data.length;
    }

    function visualConceptPlanInputStamp(projectData = tenantProjectData) {
      const workflow = tenantVisualConceptState?.plansWorkflow || emptyVisualConceptPlansWorkflow();
      const keys = ['project_name', 'project_idea', 'city', 'district', 'croquis_land_area',
        'land_area', 'approved_financial_area', 'approved_floor_count', 'approved_coverage_ratio',
        'approved_floor_area_ratio', 'approved_typical_floor_coverage', 'land_and_building_summary', 'regulatory_constraints',
        'north_direction', 'surrounding_streets', 'setbacks', 'building_ratio_setbacks',
        'directions_table', 'survey_coordinates', 'regulation_coordinates', 'facades_directions',
        'boundary_lengths', 'land_documents_analysis', 'project_components_data'];
      const fields = Object.fromEntries(keys.map(key => [key,
        visualConceptPlanCanonicalInput(key, projectData?.[key] ?? '')]));
      const data = JSON.stringify({ fields,
        financialParking: visualConceptPlanFinancialInput(projectData?.financial_study_model),
        boundary: workflow.boundary.points,
        distribution: workflow.distribution.rows });
      let first = 2166136261, second = 5381;
      for (let index = 0; index < data.length; index += 1) {
        first = Math.imul(first ^ data.charCodeAt(index), 16777619);
        second = Math.imul(second, 33) ^ data.charCodeAt(index);
      }
      return (first >>> 0).toString(16) + ':' + (second >>> 0).toString(16) + ':' + data.length;
    }

    function visualConceptPlanCanonicalInput(key, value) {
      let parsed = value;
      if (typeof parsed === 'string') {
        const text = parsed.trim();
        if (text.startsWith('{') || text.startsWith('[')) {
          try { parsed = JSON.parse(text); } catch (error) { /* Keep ordinary text unchanged. */ }
        }
      }
      if (key === 'survey_coordinates' || key === 'regulation_coordinates') {
        // Draft hydration can turn either coordinate source from JSON text into
        // normalized rows. Compare the geometric facts, not formatting or provenance.
        return visualConceptBoundaryPoints(parsed).map(point => ({
          parcel_id: point.parcel_id,
          point: point.point,
          eastings: point.eastings,
          northings: point.northings
        }));
      }
      if (key === 'directions_table' && typeof normalizeSurveyDirections === 'function') {
        parsed = normalizeSurveyDirections(parsed);
      }
      return visualConceptPlanStableInput(parsed, key);
    }

    const VISUAL_CONCEPT_PLAN_NUMERIC_INPUT_WORDS = new Set([
      'area', 'sqm', 'count', 'ratio', 'coverage', 'length', 'width', 'height',
      'setback', 'space', 'spaces', 'unit', 'units', 'easting', 'eastings',
      'northing', 'northings', 'x', 'y', 'latitude', 'longitude', 'lat', 'lng',
      'floor', 'floors', 'basement', 'capacity', 'percent', 'percentage',
      'quantity', 'distance', 'size', 'level', 'amount'
    ]);

    function visualConceptPlanStableInput(value, parentKey = '') {
      if (Array.isArray(value)) return value.map(item => visualConceptPlanStableInput(item, parentKey));
      if (value && typeof value === 'object') {
        return Object.fromEntries(Object.keys(value).sort().map(key =>
          [key, visualConceptPlanStableInput(value[key], key)]));
      }
      if (typeof value !== 'string' || !visualConceptPlanNumericKey(parentKey)) return value;
      const text = value.trim();
      if (!text) return value;
      const number = Number(text);
      return Number.isFinite(number) ? number : value;
    }

    function visualConceptPlanNumericKey(key) {
      const words = String(key || '').replace(/([a-z])([A-Z])/g, '$1 $2')
        .toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
      return words.some(word => VISUAL_CONCEPT_PLAN_NUMERIC_INPUT_WORDS.has(word));
    }

    function visualConceptPlanFinancialInput(value) {
      let model = value;
      if (typeof model === 'string') {
        try { model = JSON.parse(model); } catch (error) { model = null; }
      }
      model = model && typeof model === 'object' && !Array.isArray(model) ? model : {};
      const inputs = model.inputs && typeof model.inputs === 'object' ? model.inputs : {};
      const dynamicRows = model.dynamicRows && typeof model.dynamicRows === 'object' ? model.dynamicRows : {};
      const components = Array.isArray(dynamicRows.components) ? dynamicRows.components
        .filter(row => row && typeof row === 'object' && !Array.isArray(row))
        .slice().sort((left, right) => String(left.id || '').localeCompare(String(right.id || ''))) : [];
      const parkingPlan = model.parkingPlan && typeof model.parkingPlan === 'object'
        && !Array.isArray(model.parkingPlan) ? model.parkingPlan : {};
      // Calculated projections and report tables are rebuilt on draft load. Only
      // the parking inputs and plan affect visual-plan context and its checks.
      return visualConceptPlanStableInput({ basementArea: inputs.basementArea ?? '', components, parkingPlan });
    }

    function invalidateVisualConceptPlanGeneration(workflow, review = true) {
      workflow.promptReady = false;
      workflow.promptsError = '';
      workflow.prompts = { site: '', uses: '', massing: '' };
      workflow.scene = null;
      workflow.sourceStamp = '';
      workflow.siteAssistant = emptyVisualConceptPlansWorkflow().siteAssistant;
      const siteSlot = tenantVisualConceptState?.slots?.plan_site;
      if (siteSlot) {
        siteSlot.chat = [];
        siteSlot.svgCode = '';
        if (siteSlot.imageUrl || siteSlot.approvedImageUrl) {
          siteSlot.approvedImageUrl = '';
          siteSlot.status = 'review';
        }
      }
      if (review) workflow.notesReview = emptyVisualConceptPlansWorkflow().notesReview;
      VISUAL_CONCEPT_PLAN_KINDS.forEach(definition => {
        const slot = tenantVisualConceptState?.slots?.[definition.id];
        if (!slot) return;
        slot.prompt = '';
        slot.imageUrl = slot.imageUrl || slot.approvedImageUrl;
        slot.approvedImageUrl = '';
        slot.status = slot.imageUrl ? 'review' : 'pending';
      });
    }

    function invalidateVisualConceptDistributionReview(workflow) {
      if (!workflow?.distribution) return;
      workflow.distribution.approved = false;
      workflow.distribution.aiReviewed = false;
      workflow.distribution.reviewSignature = '';
      workflow.distribution.checks = [];
      workflow.distribution.issues = [];
      workflow.distribution.canProceed = null;
    }

    function setVisualConceptPlanNotes(value) {
      const workflow = visualConceptPlansWorkflowState();
      const notes = String(value || '').slice(0, 1000000);
      if (workflow.clientNotes === notes) return;
      workflow.clientNotes = notes;
      if (workflow.notesReview) {
        workflow.notesReview.verified = false;
        workflow.notesReview.canProceed = false;
        workflow.notesReview.token = '';
      }
      workflow.promptReady = false;
      workflow.scene = null;
      markVisualConceptDirty();
    }

    function syncVisualConceptPlanInputs(projectData) {
      const workflow = visualConceptPlansWorkflowState();
      const currentStamp = visualConceptPlanInputStamp(projectData);
      const distribution = workflow.distribution;
      // Older saved reviews have no per-review signature. The persisted
      // aiReviewed flag is itself proof that the AI check completed; bind that
      // legacy result to the hydrated inputs once, then invalidate normally on
      // subsequent input changes.
      if (distribution.aiReviewed && !distribution.reviewSignature) {
        distribution.reviewSignature = currentStamp;
      }
      const distributionReviewCurrent = Boolean(distribution.aiReviewed
        && distribution.reviewSignature === currentStamp);
      if (distribution.reviewSignature && !distributionReviewCurrent) {
        invalidateVisualConceptDistributionReview(workflow);
      }
      // sourceStamp belongs to downstream prompt and notes work. A matching
      // distribution review signature is the stronger proof that this saved
      // analysis still describes the hydrated inputs, so a stale legacy
      // sourceStamp must not revoke its review or approval on reload.
      if (!workflow.sourceStamp || workflow.sourceStamp === currentStamp || distributionReviewCurrent) return;
      workflow.distribution.approved = false;
      if (!distributionReviewCurrent) invalidateVisualConceptDistributionReview(workflow);
      workflow.verification = emptyVisualConceptPlansWorkflow().verification;
      workflow.viewStage = 'verify';
      workflow.planContext = null;
      invalidateVisualConceptPlanGeneration(workflow);
    }

    function receiveVisualConceptPlanScene(scene, slotId) {
      if (!scene || scene.version !== 1 || !scene.token) return false;
      const workflow = visualConceptPlansWorkflowState();
      workflow.scene = scene;
      VISUAL_CONCEPT_PLAN_KINDS.forEach(definition => {
        const slot = tenantVisualConceptState?.slots?.[definition.id];
        if (!slot || definition.id === slotId || slot.sceneToken === scene.token) return;
        slot.imageUrl = slot.imageUrl || slot.approvedImageUrl;
        slot.approvedImageUrl = '';
        slot.status = slot.imageUrl ? 'review' : 'pending';
      });
      return true;
    }
