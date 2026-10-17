/* Market project snapshot helpers, loaded after 05-market-competitors.js. */

    function collectMarketProjectData() {
      const data = { ...(tenantProjectData || {}) };
      document.querySelectorAll('#tenantProjectForm [data-key]').forEach(input => {
        const key = input.dataset && input.dataset.key;
        const type = input.dataset && input.dataset.type;
        if (!key || type === 'image' || type === 'pdf' || type === 'file') return;
        if (input.value !== undefined && input.value !== '') data[key] = input.value;
      });
      return data;
    }
