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
        distribution: { rows: [], totals: [], notes: [], checks: [], issues: [], approved: false, aiReviewed: false },
        distributionNotes: '',
        distributionRevision: '',
        conflictChats: { verify: [], distribution: [] },
        clientNotes: '',
        notesReview: { verified: false, canProceed: false, checks: [], issues: [], inputSignature: '', token: '' },
        scene: null,
        sourceStamp: '',
        prompts: { site: '', uses: '', massing: '' },
        planContext: null,
        viewStage: 'verify',
        promptReady: false,
        promptsError: ''
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
            circulation: String((row && row.circulation) || '').slice(0, 400)
          })),
          totals: Array.isArray(distribution.totals) ? distribution.totals.slice(0, 60) : [],
          notes: Array.isArray(distribution.notes) ? distribution.notes.slice(0, 12) : [],
          checks: Array.isArray(distribution.checks) ? distribution.checks.slice(0, 40) : [],
          issues: Array.isArray(distribution.issues) ? distribution.issues.slice(0, 30) : [],
          approved: Boolean(distribution.approved),
          aiReviewed: Boolean(distribution.aiReviewed)
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
          token: String(review.token || '').slice(0, 128)
        },
        scene,
        sourceStamp: String(source.sourceStamp || '').slice(0, 80),
        prompts: {
          site: String(prompts.site || '').slice(0, 64000),
          uses: String(prompts.uses || '').slice(0, 64000),
          massing: String(prompts.massing || '').slice(0, 64000)
        },
        planContext: source.planContext && typeof source.planContext === 'object' ? source.planContext : null,
        viewStage: ['verify', 'boundary', 'generate'].includes(source.viewStage) ? source.viewStage : 'verify',
        promptReady: Boolean(scene && scene.token && (source.promptReady || (prompts.site && prompts.uses && prompts.massing))),
        promptsError: String(source.promptsError || '').slice(0, 400)
      };
    }

    function visualConceptWorkflowPlanSeed(definition, workflow) {
      const prompt = workflow?.prompts?.[definition.kind] || '';
      return {
        mode: 'ai', label: definition.label, caption: definition.label, prompt,
        imageUrl: '', approvedImageUrl: '', status: 'pending', chat: [],
        styleReferenceFileIds: [], styleReferenceNames: [], sourceFileId: '', sourceFileName: ''
      };
    }

    function visualConceptPlansWorkflowState() {
      tenantVisualConceptState = tenantVisualConceptState || normalizeVisualConceptState({});
      tenantVisualConceptState.plansWorkflow = normalizeVisualConceptPlansWorkflow(tenantVisualConceptState.plansWorkflow);
      return tenantVisualConceptState.plansWorkflow;
    }

    let visualConceptPlanScenePending = false;

    function visualConceptPlanInputStamp(projectData = tenantProjectData) {
      const workflow = tenantVisualConceptState?.plansWorkflow || emptyVisualConceptPlansWorkflow();
      const keys = ['project_name', 'project_idea', 'city', 'district', 'croquis_land_area',
        'land_area', 'approved_financial_area', 'approved_floor_count', 'approved_coverage_ratio',
        'approved_floor_area_ratio', 'approved_typical_floor_coverage', 'land_and_building_summary', 'regulatory_constraints',
        'north_direction', 'surrounding_streets', 'setbacks', 'building_ratio_setbacks',
        'directions_table', 'survey_coordinates', 'regulation_coordinates', 'facades_directions',
        'boundary_lengths',
        'land_documents_analysis', 'project_components_data', 'financial_study_model'];
      const fields = Object.fromEntries(keys.map(key => [key, projectData?.[key] ?? '']));
      const data = JSON.stringify({ fields, boundary: workflow.boundary.points,
        distribution: workflow.distribution.rows, distributionNotes: workflow.distributionNotes,
        clientNotes: workflow.clientNotes });
      let first = 2166136261, second = 5381;
      for (let index = 0; index < data.length; index += 1) {
        first = Math.imul(first ^ data.charCodeAt(index), 16777619);
        second = Math.imul(second, 33) ^ data.charCodeAt(index);
      }
      return (first >>> 0).toString(16) + ':' + (second >>> 0).toString(16) + ':' + data.length;
    }

    function invalidateVisualConceptPlanGeneration(workflow, review = true) {
      workflow.promptReady = false;
      workflow.promptsError = '';
      workflow.prompts = { site: '', uses: '', massing: '' };
      workflow.scene = null;
      workflow.sourceStamp = '';
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

    function setVisualConceptPlanNotes(value) {
      const workflow = visualConceptPlansWorkflowState();
      const notes = String(value || '').slice(0, 1000000);
      if (workflow.clientNotes === notes) return;
      workflow.clientNotes = notes;
      workflow.distribution.approved = false;
      invalidateVisualConceptPlanGeneration(workflow);
      markVisualConceptDirty();
    }

    function syncVisualConceptPlanInputs(projectData) {
      const workflow = visualConceptPlansWorkflowState();
      if (!workflow.sourceStamp || workflow.sourceStamp === visualConceptPlanInputStamp(projectData)) return;
      workflow.distribution.approved = false;
      workflow.distribution.aiReviewed = false;
      workflow.verification.approved = false;
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
