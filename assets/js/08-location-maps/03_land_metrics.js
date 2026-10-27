    // Derived read-only metrics for the land/croquis section. Every figure comes
    // from the client's approved inputs: the typical-floor coverage is the
    // footprint of a single repeated floor, and the approved floor count includes
    // the ground floor, so a building of N floors has N-1 repeated floors.
    const LAND_COMPUTED_SOURCE_KEYS = new Set(['approved_financial_area', 'approved_floor_area_ratio', 'approved_coverage_ratio', 'approved_typical_floor_coverage', 'approved_floor_count']);

    function landApprovedNumber(key) {
      const input = document.querySelector('#tenantProjectForm [data-key="' + key + '"]');
      const parsed = typeof parseNumber === 'function'
        ? parseNumber(String(input?.value ?? tenantProjectData?.[key] ?? ''))
        : Number(String(input?.value ?? tenantProjectData?.[key] ?? '').replace(/,/g, ''));
      return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
    }

    function landComputedFigures() {
      const area = landApprovedNumber('approved_financial_area');
      const far = landApprovedNumber('approved_floor_area_ratio');
      const coverage = landApprovedNumber('approved_coverage_ratio');
      const typical = landApprovedNumber('approved_typical_floor_coverage');
      const floors = landApprovedNumber('approved_floor_count');
      const repeatedFloors = floors > 1 ? floors - 1 : 0;
      const totalBuiltArea = area * far;
      const buildingArea = area * coverage / 100;
      const typicalFloorArea = area * typical / 100;
      const repeatedFloorsArea = typicalFloorArea * repeatedFloors;
      const usedArea = buildingArea + repeatedFloorsArea;
      const exceeded = totalBuiltArea > 0 && buildingArea > 0 && typicalFloorArea > 0
        && repeatedFloors > 0 && usedArea > totalBuiltArea + 1e-6;
      return {
        area, far, coverage, typical, floors, repeatedFloors,
        totalBuiltArea, buildingArea, typicalFloorArea, repeatedFloorsArea,
        usedArea, exceeded, excess: exceeded ? usedArea - totalBuiltArea : 0
      };
    }

    function formatLandComputedArea(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return '—';
      let text = String(Math.round(Math.abs(number) * 10 * (1 + Number.EPSILON)) / 10);
      if (/[eE]/.test(text)) {
        const [mantissa, exponentText] = text.toLowerCase().split('e');
        const exponent = Number(exponentText);
        const [whole, fraction = ''] = mantissa.split('.');
        const digits = whole + fraction;
        const decimalIndex = whole.length + exponent;
        text = decimalIndex <= 0
          ? '0.' + '0'.repeat(-decimalIndex) + digits
          : decimalIndex >= digits.length
            ? digits + '0'.repeat(decimalIndex - digits.length)
            : digits.slice(0, decimalIndex) + '.' + digits.slice(decimalIndex);
      }
      const [whole, fraction] = text.split('.');
      const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
      return (number < 0 ? '-' : '') + grouped + (fraction ? '.' + fraction : '');
    }

    function landCapacityMessage(figures) {
      return WFT('maps.land_capacity_exceeded',
        'مجموع مساحة الأدوار المتكررة ({repeated} م²) مع مساحة البناء ({building} م²) يتجاوز إجمالي مسطحات البناء ({total} م²) بمقدار {excess} م²',
        {
          repeated: formatLandComputedArea(figures.repeatedFloorsArea),
          building: formatLandComputedArea(figures.buildingArea),
          total: formatLandComputedArea(figures.totalBuiltArea),
          excess: formatLandComputedArea(figures.excess)
        });
    }

    function landCapacityExceeded() {
      return landComputedFigures().exceeded;
    }

    function updateLandComputedMetrics() {
      const box = document.getElementById('landComputedMetrics');
      if (!box) return;
      const figures = landComputedFigures();
      const format = value => value > 0 ? formatLandComputedArea(value) : '—';
      const setMetric = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.textContent = format(value);
        return value > 0;
      };
      const hasAny = setMetric('computedTotalBuiltArea', figures.totalBuiltArea)
        | setMetric('computedCoverageArea', figures.buildingArea)
        | setMetric('computedRepeatedFloorsArea', figures.repeatedFloorsArea)
        | setMetric('computedTypicalFloorArea', figures.typicalFloorArea);
      box.classList.toggle('land-metrics-violated', figures.exceeded);
      const note = document.getElementById('landComputedCapNote');
      if (note) {
        note.textContent = figures.exceeded ? landCapacityMessage(figures) : '';
        note.hidden = !figures.exceeded;
      }
      box.hidden = !hasAny;
    }

    function validateLandCroquisClientFields() {
      const fieldSpecs = [
        { key: 'approved_floor_count', label: 'الأدوار المعتمدة', message: 'يرجى إدخال عدد الأدوار المعتمدة للمشروع وفقًا للاشتراطات التنظيمية.' },
        { key: 'approved_coverage_ratio', label: 'تغطية البناء (%)', message: 'يرجى إدخال نسبة تغطية البناء المعتمدة للأرض وفقًا للاشتراطات التنظيمية.' },
        { key: 'approved_floor_area_ratio', label: 'معامل مسطح البناء المعتمد (FAR)', message: 'يرجى إدخال معامل مسطح البناء المعتمد للمشروع وفقًا للاشتراطات التنظيمية.' },
        { key: 'approved_typical_floor_coverage', label: 'التغطية للطوابق المتكررة (%)', message: 'يرجى إدخال نسبة التغطية المعتمدة للطوابق المتكررة وفقًا للاشتراطات التنظيمية.' },
        { key: 'approved_financial_area', label: 'المساحة المعتمدة للدراسة المالية (م²)', message: 'يرجى إدخال إجمالي المساحة البنائية المعتمدة التي ستُبنى عليها حسابات الدراسة المالية.' }
      ];
      const errors = [];
      for (const spec of fieldSpecs) {
        const input = document.querySelector('#tenantProjectForm [data-key="' + spec.key + '"]');
        const val = input ? String(input.value ?? '').trim() : '';
        const numVal = parseFloat(val.replace(/,/g, ''));
        if (!val || isNaN(numVal) || numVal <= 0) {
          errors.push(spec);
        }
      }
      if (!errors.length) {
        const figures = landComputedFigures();
        if (figures.exceeded) {
          errors.push({
            key: 'approved_typical_floor_coverage',
            label: 'مساحة الأدوار المتكررة',
            message: landCapacityMessage(figures)
          });
        }
      }
      return errors;
    }

    function mountLandComputedMetrics(sectionDiv) {
      if (!sectionDiv) return;
      const computedMetricsField = document.createElement('div');
      computedMetricsField.className = 'tenant-field full';
      computedMetricsField.innerHTML =
        '<div id="landComputedMetrics" class="best-use-metrics" hidden>' +
        '<div><span data-ar-text="إجمالي مسطحات البناء (م²)">إجمالي مسطحات البناء (م²)</span><strong id="computedTotalBuiltArea">—</strong></div>' +
        '<div><span data-ar-text="مساحة البناء (م²)">مساحة البناء (م²)</span><strong id="computedCoverageArea">—</strong></div>' +
        '<div><span data-ar-text="مساحة الأدوار المتكررة (م²)">مساحة الأدوار المتكررة (م²)</span><strong id="computedRepeatedFloorsArea">—</strong></div>' +
        '<div><span data-ar-text="مساحة الدور (م²)">مساحة الدور (م²)</span><strong id="computedTypicalFloorArea">—</strong></div>' +
        '</div>' +
        '<p id="landComputedCapNote" class="land-cap-warning" hidden></p>';
      sectionDiv.appendChild(computedMetricsField);
      const recompute = event => {
        if (LAND_COMPUTED_SOURCE_KEYS.has(event.target?.dataset?.key)) updateLandComputedMetrics();
      };
      sectionDiv.addEventListener('input', recompute);
      sectionDiv.addEventListener('change', recompute);
      updateLandComputedMetrics();
    }
