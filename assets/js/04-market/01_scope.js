/* Market summary scope: city rows with optional district rows. */

    function defaultMarketSummaryScope() {
      const city = String(document.querySelector('#tenantProjectForm [data-key="city"]')?.value ||
        tenantProjectData.city || '').trim();
      return { cities: city ? [{ name: city, districts: [] }] : [] };
    }

    function collectMarketSummaryScope() {
      const cities = [];
      document.querySelectorAll('#marketSummaryScopeCities [data-summary-city]').forEach(card => {
        const name = String(card.querySelector('[data-summary-city-name]')?.value || '').trim();
        const districts = [];
        const seen = new Set();
        card.querySelectorAll('[data-summary-district-name]').forEach(input => {
          const district = String(input.value || '').trim();
          if (district && !seen.has(district) && districts.length < 20) {
            seen.add(district);
            districts.push(district);
          }
        });
        if (name && cities.length < 12) cities.push({ name, districts });
      });
      return { cities };
    }

    function marketSummaryDistrictField(value) {
      const phKey = 'market.summary_scope_district_name';
      return '<div class="market-summary-district" style="display:flex;gap:8px;margin-top:6px">' +
        '<input data-summary-district-name value="' + escapeHtml(value || '') + '"' +
        ' placeholder="' + escapeHtml(WFT(phKey, 'اسم الحي')) + '" data-i18n-ph="' + phKey + '"' +
        ' oninput="persistMarketStudyFromDom()">' +
        '<button type="button" class="btn small danger" data-i18n="market.summary_scope_delete"' +
        ' onclick="deleteMarketSummaryScopeDistrict(this)">' +
        escapeHtml(WFT('market.summary_scope_delete', 'حذف')) + '</button></div>';
    }

    function marketSummaryCityCard(city) {
      const cityKey = 'market.summary_scope_city_name';
      const districtRows = (Array.isArray(city?.districts) ? city.districts : [])
        .map(marketSummaryDistrictField).join('');
      return '<section data-summary-city class="market-block" style="margin-top:8px">' +
        '<div style="display:flex;gap:8px;align-items:end">' +
        '<div style="flex:1"><label data-i18n="market.summary_scope_city">المدينة</label>' +
        '<input data-summary-city-name value="' + escapeHtml(city?.name || '') + '"' +
        ' placeholder="' + escapeHtml(WFT(cityKey, 'اسم المدينة')) + '" data-i18n-ph="' + cityKey + '"' +
        ' oninput="persistMarketStudyFromDom()"></div>' +
        '<button type="button" class="btn small danger" data-i18n="market.summary_scope_delete_city"' +
        ' onclick="deleteMarketSummaryScopeCity(this)">' +
        escapeHtml(WFT('market.summary_scope_delete_city', 'حذف المدينة')) + '</button></div>' +
        '<div data-summary-districts style="margin-top:8px">' + districtRows + '</div>' +
        '<div class="market-actions" style="margin-top:8px"><button type="button" class="btn ghost"' +
        ' data-i18n="market.summary_scope_add_district" onclick="addMarketSummaryScopeDistrict(this)">' +
        escapeHtml(WFT('market.summary_scope_add_district', 'إضافة حي')) + '</button></div></section>';
    }

    function syncMarketSummaryScopeUI() {
      const host = document.getElementById('marketSummaryScopeCities');
      if (host) refreshDynamicI18n(host);
    }

    function renderMarketSummaryScope(scope) {
      const host = document.getElementById('marketSummaryScopeCities');
      if (!host) return;
      const next = (scope && typeof scope === 'object' && !Array.isArray(scope)) ? scope : {};
      let cities = Array.isArray(next.cities) ? next.cities : [];
      if (!cities.length && Array.isArray(next.places)) {
        if (next.mode === 'city') cities = next.places.map(name => ({ name, districts: [] }));
        else if (next.mode === 'district') {
          const projectCity = String(tenantProjectData.city || '').trim();
          if (projectCity) cities = [{ name: projectCity, districts: next.places }];
        }
      }
      if (!cities.length) cities = defaultMarketSummaryScope().cities;
      host.innerHTML = cities.slice(0, 12).map(marketSummaryCityCard).join('');
      if (!host.children.length) host.insertAdjacentHTML('beforeend', marketSummaryCityCard({ name: '', districts: [] }));
      syncMarketSummaryScopeUI();
    }

    function addMarketSummaryScopeCity() {
      const host = document.getElementById('marketSummaryScopeCities');
      if (!host || host.querySelectorAll('[data-summary-city]').length >= 12) return;
      host.insertAdjacentHTML('beforeend', marketSummaryCityCard({ name: '', districts: [] }));
      host.querySelector('[data-summary-city]:last-child [data-summary-city-name]')?.focus();
      syncMarketSummaryScopeUI();
      persistMarketStudyFromDom();
    }

    function addMarketSummaryScopeDistrict(button) {
      const card = button?.closest('[data-summary-city]');
      const host = card?.querySelector('[data-summary-districts]');
      if (!host || host.querySelectorAll('[data-summary-district-name]').length >= 20) return;
      host.insertAdjacentHTML('beforeend', marketSummaryDistrictField(''));
      host.querySelector('[data-summary-district-name]:last-child')?.focus();
      syncMarketSummaryScopeUI();
      persistMarketStudyFromDom();
    }

    function deleteMarketSummaryScopeCity(button) {
      button?.closest('[data-summary-city]')?.remove();
      persistMarketStudyFromDom();
    }

    function deleteMarketSummaryScopeDistrict(button) {
      button?.closest('.market-summary-district')?.remove();
      persistMarketStudyFromDom();
    }
