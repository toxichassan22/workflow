/* 11-land-croquis/01a_boundary_dimensions.js — plot dimensions from documented
   boundary lengths, shared global scope, classic scripts in order */

    function surveyBoundaryNumber(value) {
      if (value === null || value === undefined || typeof value === 'boolean') return null;
      const text = String(value)
        .replace(/[٠-٩۰-۹]/g, digit => String('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹'.indexOf(digit) % 10))
        .replace(/[٬,]/g, '').replace('٫', '.').trim();
      if (!text) return null;
      const parsed = Number(text);
      return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
    }

    function surveyDirectionLengthFromText(text) {
      const match = String(text || '').match(
        /(?:بطول|طول(?:\s+(?:الحد|الضلع|الجهة|الجانب))?)\s*[:=\-–—]?\s*([0-9٠-٩۰-۹]+(?:[.,٫][0-9]+)?)\s*(?:متر|أمتار|امتار|م\.?|m\b)/i);
      return match ? surveyBoundaryNumber(match[1]) : null;
    }

    function surveyDirectionCompass(text) {
      const candidate = String(text || '').trim().toLowerCase();
      const words = { north: 'شمال', south: 'جنوب', east: 'شرق', west: 'غرب' };
      const found = Object.keys(words).filter(key =>
        candidate.includes(words[key]) || new RegExp('\\b' + key + '(?:ern)?\\b', 'i').test(candidate));
      return found.length === 1 ? found[0] : '';
    }

    const SURVEY_AXIS_WORDS = { front: 'أمامي|امامي|front', back: 'خلفي|rear|\\bback\\b', side: 'جانب|side' };

    function surveyClauseFigures(clause) {
      // Strict «بطول Nم» figures only when any exist — bare meter figures next
      // to a length phrase are street widths or setbacks, not boundary lengths.
      const phraseRe = /(?:بطول|طول(?:\s+(?:الحد|الضلع|الجهة|الجانب))?)\s*[:=\-–—]?\s*([0-9٠-٩۰-۹]+(?:[.,٫][0-9]+)?)\s*(?:متر|أمتار|امتار|م\.?|m\b)/gi;
      const meterRe = /([0-9٠-٩۰-۹]+(?:[.,٫][0-9]+)?)\s*(?:متر|أمتار|امتار|م\.?|m\b)/gi;
      const scan = re => {
        const found = [];
        let match;
        while ((match = re.exec(clause))) {
          const value = surveyBoundaryNumber(match[1]);
          if (value == null) continue;
          const start = match.index + match[0].indexOf(match[1]);
          found.push({ start, end: start + String(match[1]).length, value });
        }
        return found;
      };
      const phrases = scan(phraseRe);
      return (phrases.length ? phrases : scan(meterRe)).sort((a, b) => a.start - b.start);
    }

    function surveyWordFigures(clause, words) {
      // Each direction/facade mention keeps the first figure after it (before
      // the next mention) — «الشمالي 97م والجنوبي 98م» gives the south 98, not
      // the clause's first figure. A figure before every mention pairs with the
      // first mention instead.
      const mentions = [];
      Object.entries(words).forEach(([key, pattern]) => {
        const re = new RegExp(pattern, 'gi');
        let match;
        while ((match = re.exec(clause))) {
          mentions.push({ start: match.index, end: match.index + match[0].length, key });
        }
      });
      mentions.sort((a, b) => a.start - b.start);
      const figures = surveyClauseFigures(clause);
      const found = {};
      mentions.forEach((mention, index) => {
        if (found[mention.key] != null) return;
        const nxt = index + 1 < mentions.length ? mentions[index + 1].start : clause.length + 1;
        const after = figures.filter(figure => figure.start >= mention.end && figure.start < nxt);
        if (after.length) { found[mention.key] = after[0].value; return; }
        const prv = index ? mentions[index - 1].end : 0;
        const before = figures.filter(figure => figure.end >= prv && figure.end <= mention.start);
        if (before.length) found[mention.key] = before[before.length - 1].value;
      });
      return found;
    }

    function surveyBoundaryLengthsByDirection(source) {
      source = source && typeof source === 'object' ? source : {};
      const lengths = { north: null, south: null, east: null, west: null };
      const offer = (direction, value) => {
        if (direction && lengths[direction] == null && value != null && value > 0) lengths[direction] = value;
      };
      normalizeSurveyDirections(source.directions_table || source.directions).forEach(row =>
        offer(row.direction, surveyBoundaryNumber(row.boundary_length_m)));
      // The «أطوال الأضلاع» summary text — clauses like «الشمالي 72م» or
      // «الشمالي 97م والجنوبي 98م» where each direction keeps its own figure.
      const compassWords = { north: 'شمال', south: 'جنوب', east: 'شرق', west: 'غرب' };
      String(source.boundary_lengths || '').split(/[\n|؛;,،]+/).forEach(clause => {
        Object.entries(surveyWordFigures(clause, compassWords)).forEach(([direction, value]) =>
          offer(direction, value));
      });
      const analysis = typeof source.land_documents_analysis === 'string'
        ? parseStoredLandTable(source.land_documents_analysis)
        : source.land_documents_analysis;
      const parcels = Array.isArray(analysis?.parcels) ? analysis.parcels : [];
      // Only the primary parcel fills gaps — lengths from different plots must
      // never merge into one fabricated shape.
      const primary = parcels[0] && typeof parcels[0] === 'object' ? parcels[0] : null;
      const map = primary && primary.directions && typeof primary.directions === 'object' ? primary.directions : {};
      Object.entries(map).forEach(([key, cell]) => {
        const direction = surveyDirectionCompass(key);
        const value = cell && typeof cell === 'object'
          ? surveyBoundaryNumber(cell.boundary_length_m ?? cell.length_m ?? cell.length)
          : null;
        offer(direction, value);
      });
      return lengths;
    }

    function surveyBoundaryPointsFromDimensions(source) {
      // The documented side lengths describe a rectangle: north/south span the
      // width, east/west the depth. A local origin keeps every coordinate
      // positive so lenient parsers keep all four vertices.
      source = source && typeof source === 'object' ? source : (typeof tenantProjectData !== 'undefined' ? tenantProjectData : {});
      const lengths = surveyBoundaryLengthsByDirection(source);
      const mean = values => {
        const present = values.filter(value => value != null && value > 0);
        return present.length ? present.reduce((sum, value) => sum + value, 0) / present.length : null;
      };
      let width = mean([lengths.north, lengths.south]);
      let depth = mean([lengths.east, lengths.west]);
      if (width == null || depth == null) {
        // «واجهة/خلفية/جانب» phrasing for summaries that never name a compass.
        const axes = {};
        String(source.boundary_lengths || '').split(/[\n|؛;,،]+/).forEach(clause => {
          Object.entries(surveyWordFigures(clause, SURVEY_AXIS_WORDS)).forEach(([axis, value]) => {
            if (axes[axis] == null) axes[axis] = value;
          });
        });
        if (width == null) width = mean([axes.front, axes.back]);
        if (depth == null) depth = axes.side;
      }
      if (!width || !depth) return [];
      const base = 1000;
      return [[0, 0], [width, 0], [width, depth], [0, depth]].map((point, index) => ({
        parcel_id: '', point: String(index + 1),
        eastings: base + point[0], northings: base + point[1], source: 'boundary_lengths'
      }));
    }
