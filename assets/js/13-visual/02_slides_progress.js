    function renderTenantSlidesProgress(total, done, currentTitle) {
      let bar = document.getElementById('slideGenProgress');
      if (!bar) {
        bar = document.createElement('div');
        bar.id = 'slideGenProgress';
        bar.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:9999;background:#fff;border-bottom:2px solid var(--p);padding:10px 20px;display:flex;align-items:center;gap:12px;box-shadow:0 2px 8px rgba(0,0,0,.1)';
        document.body.appendChild(bar);
      }
      const pct = Math.round((done / total) * 100);
      bar.innerHTML = '<div style="flex:1"><div style="font-weight:700;margin-bottom:4px">جاري توليد الشرائح: ' + done + ' / ' + total + (currentTitle ? ' — ' + escapeHtml(currentTitle) : '') + '</div><div style="height:6px;background:#e0e0e0;border-radius:3px;overflow:hidden"><div style="height:100%;width:' + pct + '%;background:var(--p);transition:width .3s"></div></div></div>';
    }

    function hideSlideProgress() {
      const bar = document.getElementById('slideGenProgress');
      if (bar) bar.remove();
    }

    let activeSlideIndex = 0;
    const slideInlineEditStates = {};
    const slideElementEditStates = {};
    const TENANT_PRESENTATION_SECTION_TITLES = {
      overview: 'نبذة عن المشروع', components: 'مكونات المشروع', land: 'تحليل الأرض',
      location: 'تحليل الموقع الجغرافي', market: 'تحليل السوق', timeline: 'الجدول الزمني',
      financial: 'الدراسة المالية', swot_risks: 'تحليل SWOT وتحليل المخاطر', team: 'فريق العمل',
      visual_concept: 'التصور البصري',
      plans: 'المخططات', exterior: 'التصورات الخارجية', interior: 'التصورات الداخلية',
      executive_summary: 'الملخص التنفيذي', closing: 'الخاتمة'
    };

    function tenantSlideSectionKey(slide, current = '') {
      const explicit = String(slide?.section_key || slide?.sectionKey || slide?.section || '').trim();
      if (TENANT_PRESENTATION_SECTION_TITLES[explicit]) return explicit;
      const type = String(slide?.type || '').toLowerCase();
      if (type === 'closing') return 'closing';
      if (type === 'moodboard') return 'exterior';
      if (type.startsWith('map_') || type === 'site_specs') return 'location';
      const text = [slide?.title, slide?.content_source, slide?.contentSource, slide?.source_table]
        .filter(Boolean).join(' ').toLowerCase();
      const matchers = [
        ['closing', /الخاتمة|الختام|شكرا|شكراً|closing|conclusion|thanks/i],
        ['executive_summary', /الملخص التنفيذي|executive summary/i],
        ['interior', /التصورات? الداخلية|التصميم الداخلي|interior/i],
        ['exterior', /التصورات? الخارجية|المود بورد|mood ?board|واجهات المشروع|exterior|التصور البصري/i],
        ['plans', /المخططات|المخطط|المساقط|مخطط معماري|2d|floor ?plans?/i],
        ['team', /فريق العمل|فريق التطوير|المطور|الاستشاري|team/i],
        ['swot_risks', /swot|نقاط القوة|نقاط الضعف|الفرص والتهديدات|المخاطر|إدارة المخاطر|risk/i],
        ['financial', /الدراسة المالية|التحليل المالي|الجدوى|التدفقات النقدية|الإيرادات|التكاليف|العائد|roi|irr|financial|cash ?flow/i],
        ['timeline', /الجدول الزمني|الخطة الزمنية|مراحل التطوير|مراحل التنفيذ|timeline|schedule/i],
        ['market', /تحليل السوق|دراسة السوق|المنافسين|الطلب السوقي|market|competitor/i],
        ['location', /الموقع الجغرافي|تحليل الموقع|الموقع الاستراتيجي|خريطة|الطرق|المعالم|نطاق التأثير|site|location|map|access|landmarks|catchment/i],
        ['land', /تحليل الأرض|الأرض والاشتراطات|الأرض والكروكي|الكروكي|اشتراطات البناء|حدود الأرض|صور الأرض|land|croquis/i],
        ['components', /مكونات المشروع|الوحدات والمساحات|المكونات|components|units/i],
        ['overview', /نبذة عن المشروع|المشروع والفكرة|فكرة المشروع|نظرة عامة|تعريف المشروع|project overview|project brief/i]
      ];
      return matchers.find(([, pattern]) => pattern.test(text))?.[0] || current || 'overview';
    }

    function buildTenantIndexSlideHtml(indexEntries, slideIndex, totalSlides) {
      const entries = Array.isArray(indexEntries) ? indexEntries : [];
      const midpoint = Math.ceil(entries.length / 2);
      const col1 = entries.slice(0, midpoint);
      const col2 = entries.slice(midpoint);
      const esc = s => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      const makeRows = items => items.map(entry => {
        const secKey = esc(String(entry.section_key || ''));
        const title = esc(String(entry.title || ''));
        const pageNum = String(entry.page || 0).padStart(2, '0');
        return '<div data-index-section="' + secKey + '" style="min-height:48px;display:flex;align-items:center;gap:18px;border-bottom:1px solid rgba(30,41,59,0.30);padding:9px 2px;box-sizing:border-box;">' +
          '<div style="font-size:16px;font-weight:600;flex:1;">' + title + '</div>' +
          '<div data-index-page="' + secKey + '" dir="ltr" style="font-size:16px;font-weight:700;color:var(--accent,#d97706);min-width:34px;text-align:left;">' + pageNum + '</div></div>';
      }).join('');
      const counter = String(slideIndex || 2).padStart(2, '0') + ' — ' + String(totalSlides || 10).padStart(2, '0');
      return '<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;box-sizing:border-box;background:#f8fafc;color:#1e293b;">' +
        '<div style="position:absolute;top:82px;right:52px;left:52px;bottom:58px;box-sizing:border-box;">' +
        '<div style="font-size:30px;font-weight:700;color:var(--primary,#1a4d6f);margin-bottom:24px;">محتويات العرض</div>' +
        '<div style="width:86px;height:3px;background:var(--accent,#d97706);margin-bottom:24px;"></div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:26px 54px;align-items:start;">' +
        '<div>' + makeRows(col1) + '</div>' +
        '<div>' + makeRows(col2) + '</div>' +
        '</div></div>' +
        '<div data-slide-footer="1" style="position:absolute;bottom:20px;left:52px;right:52px;display:flex;justify-content:space-between;align-items:center;font-size:12px;color:#64748b;">' +
        '<div></div>' +
        '<div data-slide-counter="1">' + counter + '</div>' +
        '</div>' +
        '</div>';
    }

    function renumberTenantSlideHtml(slide, index, total, indexEntries) {
      if (!slide?.html) return slide?.html || '';
      const template = document.createElement('template');
      template.innerHTML = String(slide.html);
      const root = template.content.querySelector('.slide');
      if (!root) return slide.html;
      const type = String(slide.type || 'content').toLowerCase();
      if (['cover', 'closing', 'moodboard'].includes(type)) {
        root.querySelectorAll('[data-slide-footer], footer, .slide-footer').forEach(node => node.remove());
      } else {
        const counter = String(index).padStart(2, '0') + ' — ' + String(total).padStart(2, '0');
        let counters = Array.from(root.querySelectorAll('[data-slide-counter]'));
        if (!counters.length && type === 'section_divider') {
          counters = Array.from(root.querySelectorAll('div, span')).filter(node => /^\s*\d{1,3}\s*[—–-]\s*\d{1,3}\s*$/.test(node.textContent || ''));
        }
        if (!counters.length) {
          const footer = root.querySelector('footer, .slide-footer, [data-slide-footer]')
            || Array.from(root.querySelectorAll('footer, div')).find(node => /height:\s*36px/i.test(node.getAttribute('style') || ''));
          if (footer) {
            footer.dataset.slideFooter = '1';
            const candidates = Array.from(footer.querySelectorAll('span, div')).filter(node => /^\s*\d{1,3}(?:\s*[—–/-]\s*\d{1,3})?\s*$/.test(node.textContent || ''));
            const counterNode = candidates[candidates.length - 1];
            if (counterNode) {
              counterNode.dataset.slideCounter = '1';
              counters = [counterNode];
            }
          }
        }
        counters.forEach(node => {
          node.dataset.slideCounter = '1';
          node.textContent = counter;
        });
      }
      if (type === 'index') {
        const existingRows = root.querySelectorAll('[data-index-section]');
        if (existingRows.length === 0 && indexEntries && indexEntries.length > 0) {
          return buildTenantIndexSlideHtml(indexEntries, index, total);
        }
        const activeSections = new Set((indexEntries || []).map(entry => entry.section_key));
        if (activeSections.size > 0) {
          existingRows.forEach(row => {
            if (!activeSections.has(row.dataset.indexSection)) row.remove();
          });
        }
        (indexEntries || []).forEach(entry => {
          let page = root.querySelector('[data-index-page="' + entry.section_key + '"]');
          if (!page) {
            const titleNodes = Array.from(root.querySelectorAll('div, span, p, td, h3, h4')).filter(node =>
              node.children.length === 0 && String(node.textContent || '').trim() === entry.title);
            for (const title of titleNodes) {
              const row = title.closest('[data-index-section]') || title.parentElement;
              if (row) {
                const candidates = Array.from(row.querySelectorAll('*')).filter(n =>
                  n !== title && n.children.length === 0 && /^\s*\d{1,3}\s*$/.test(n.textContent || ''));
                if (candidates.length) {
                  page = candidates[candidates.length - 1];
                  break;
                }
              }
              const sibling = title.nextElementSibling;
              if (sibling && /^\s*\d+\s*$/.test(sibling.textContent || '')) {
                page = sibling;
                break;
              }
            }
          }
          if (page) {
            page.dataset.indexPage = entry.section_key;
            page.textContent = String(entry.page).padStart(2, '0');
          }
        });
      }
      return template.innerHTML;
    }

    function renumberTenantSlides() {
      if (!Array.isArray(tenantSlidesData) || !tenantSlidesData.length) return tenantSlidesData;
      let current = '';
      tenantSlidesData = tenantSlidesData.map(slide => {
        const item = { ...(slide || {}) };
        const type = String(item.type || 'content').toLowerCase();
        if (type === 'cover') item.section_key = 'cover';
        else if (type === 'index') item.section_key = 'index';
        else {
          item.section_key = tenantSlideSectionKey(item, current);
          if (type === 'section_divider') current = item.section_key;
        }
        return item;
      });
      const seen = new Set();
      const indexEntries = [];
      tenantSlidesData.forEach((slide, index) => {
        const type = String(slide.type || '').toLowerCase();
        if (type === 'cover' || type === 'index') return;
        const secKey = String(slide.section_key || '').trim();
        if (!secKey || ['cover', 'index'].includes(secKey)) return;
        if (!TENANT_PRESENTATION_SECTION_TITLES[secKey] || seen.has(secKey)) return;
        seen.add(secKey);
        indexEntries.push({
          section_key: secKey,
          title: TENANT_PRESENTATION_SECTION_TITLES[secKey],
          page: index + 1
        });
      });
      tenantSlidesData = tenantSlidesData.map((slide, index) => {
        const item = { ...slide };
        if (item.type === 'index') item.index_entries = indexEntries;
        item.html = renumberTenantSlideHtml(item, index + 1, tenantSlidesData.length, indexEntries);
        return item;
      });
      // During a paused generation the full plan must remain intact. Rebuilding it from the
      // completed prefix would make the resume button believe there are no remaining slides.
      if (!tenantSlideGenerationCheckpoint?.active) {
        tenantSlidePlan = {
          ...(tenantSlidePlan || {}),
          proposed_count: tenantSlidesData.length,
          slides: tenantSlidesData.map(slide => ({
            title: slide.title || '', type: slide.type || 'content', section_key: slide.section_key || '',
            content_source: slide.content_source || '', source_table: slide.source_table || '',
            index_entries: slide.index_entries || [], design_style: slide.designStyle || slide.design_style || 'cards',
            bullets: slide.bullets || [], metrics: slide.metrics || []
          }))
        };
      }
      return tenantSlidesData;
    }

    // Mirror of design_templates.sanitize_slide_html_for_export(): every export strips the font
    // declarations a slide carries so the company font wins, and the preview must show the same
    // thing — its whole promise is that what you see is what the PDF holds.
    function stripSlideFontDeclarations(html) {
      if (!html) return html;
      let out = String(html).replace(/\sstyle\s*=\s*(["'])([\s\S]*?)\1/gi, (match, quote, value) => {
        let cleaned = value.replace(/\s*font-family\s*:\s*[^;]+;?\s*/gi, '')
          .replace(/;\s*;/g, ';').trim().replace(/^;|;$/g, '');
        return cleaned ? ' style=' + quote + cleaned + quote : '';
      });
      out = out.replace(/<style[^>]*>([\s\S]*?)<\/style>/gi, (match, block) => {
        if (block.indexOf('@font-face') !== -1) return match;
        return '<style>' + block.replace(/\s*font-family\s*:\s*[^;]+;?\s*/gi, '')
          .replace(/;\s*;/g, ';') + '</style>';
      });
      return out;
    }

    function forceSectionDividerBackgroundHtml(html, coverImage) {
      if (!html || !coverImage) return String(html || '');
      const safeCover = String(coverImage).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
      const declaration = "background-image:url('" + safeCover + "')!important;" +
        'background-size:cover!important;background-position:center center!important;' +
        'background-repeat:no-repeat!important;';
      let replaced = false;
      let output = String(html).replace(
        /background(?:-image)?\s*:\s*(?:url\([^)]*\)|none)\s*;?/i,
        () => {
          replaced = true;
          return declaration;
        }
      );
      if (!replaced) {
        const background = '<div data-section-divider-background="1" aria-hidden="true" ' +
          'style="position:absolute;top:0;right:0;left:0;bottom:0;' + declaration + '"></div>';
        output = output.replace(
          /(<div\b[^>]*\bclass=["'][^"']*\bslide\b[^"']*["'][^>]*>)/i,
          '$1' + background
        );
      }
      return output;
    }

    function processSlideHtmlClient(html, slideType) {
      if (!html) return '';
      let cleanHtml = stripSlideFontDeclarations(html);
      const projectData = tenantProjectData || {};
      const logoUrl = (tenantBranding && (tenantBranding.logo_path || tenantBranding.logo || tenantBranding.logo_url)) || '/assets/logo.png';

      cleanHtml = cleanHtml.replace(/##LOGO##/g, logoUrl);

      // 1. Creative Images (Cover & Moodboard)
      const creativeImages = tenantCreativeImages || {};
      const defaultStock = {
        cover: '/uploads/luxury_skyscraper_cover.png',
        moodboard: [
          '/uploads/moodboard_exterior.png',
          '/uploads/moodboard_materials.png',
          '/uploads/moodboard_interior.png',
          '/uploads/moodboard_urban_lifestyle.png'
        ]
      };
      const coverImage = creativeImages.cover || creativeImages.mainImageData || defaultStock.cover;
      const userMoodboard = Array.isArray(creativeImages.moodboard) && creativeImages.moodboard.filter(Boolean).length > 0
        ? creativeImages.moodboard
        : (Array.isArray(creativeImages.moodboardImages) && creativeImages.moodboardImages.filter(Boolean).length > 0
          ? creativeImages.moodboardImages
          : []);

      const moodboardImages = [];
      for (let i = 0; i < 16; i++) {
        moodboardImages.push(userMoodboard[i] || defaultStock.moodboard[i % 4]);
      }

      cleanHtml = cleanHtml.replace(/#*IMAGE_COVER#*/gi, coverImage);
      cleanHtml = cleanHtml.replace(/#*COVER_IMAGE#*/gi, coverImage);
      cleanHtml = cleanHtml.replace(/#*MAIN_IMAGE#*/gi, coverImage);
      cleanHtml = cleanHtml.replace(/#*PROJECT_IMAGE_COVER#*/gi, coverImage);

      for (let idx = 0; idx < 16; idx++) {
        const mbUrl = moodboardImages[idx];
        const num = idx + 1;
        const mbReg = new RegExp('#*MOODBOARD_IMAGE_' + num + '#*', 'gi');
        const projReg = new RegExp('#*PROJECT_IMAGE_' + num + '#*', 'gi');
        cleanHtml = cleanHtml.replace(mbReg, mbUrl).replace(projReg, mbUrl);
      }

      // Component-Specific Interior Placeholders
      const interiorCompsList = Array.isArray(creativeImages.interior_components) ? creativeImages.interior_components : [];
      interiorCompsList.forEach((comp, cIdx) => {
        const cNum = cIdx + 1;
        const cImgs = Array.isArray(comp.images) ? comp.images : [];
        cImgs.forEach((imgItem, jIdx) => {
          const jNum = jIdx + 1;
          const url = (typeof imgItem === 'object' && imgItem !== null) ? (imgItem.url || '') : String(imgItem || '');
          if (url) {
            const reg1 = new RegExp('#*INTERIOR_COMP_' + cNum + '_(?:IMG|IMAGE)_' + jNum + '#*', 'gi');
            const reg2 = new RegExp('#*INTERIOR_C' + cNum + '_(?:IMG|IMAGE)_' + jNum + '#*', 'gi');
            const reg3 = new RegExp('#*INTERIOR_' + cNum + '_' + jNum + '#*', 'gi');
            cleanHtml = cleanHtml.replace(reg1, url).replace(reg2, url).replace(reg3, url);
          }
        });
      });

      // Flat Interior Placeholders
      const interiorImagesList = Array.isArray(creativeImages.interior) ? creativeImages.interior : [];
      for (let idx = 0; idx < 16; idx++) {
        const intUrl = interiorImagesList[idx] || '';
        const num = idx + 1;
        const intReg = new RegExp('#*INTERIOR_IMAGE_' + num + '#*', 'gi');
        cleanHtml = cleanHtml.replace(intReg, intUrl);
      }
      cleanHtml = cleanHtml.replace(/#*INTERIOR_(?:COMP_\d+_(?:IMG|IMAGE)_\d+|C\d+_(?:IMG|IMAGE)_\d+|\d+_\d+|IMAGE_\d+|\d+)#*/gi, '');

      // 2D Plans Placeholders
      const plansImagesList = Array.isArray(creativeImages.plans) ? creativeImages.plans : [];
      for (let idx = 0; idx < 16; idx++) {
        const planUrl = plansImagesList[idx] || '';
        const num = idx + 1;
        const planReg1 = new RegExp('#*PLAN_IMAGE_' + num + '#*', 'gi');
        const planReg2 = new RegExp('#*2D_PLAN_' + num + '#*', 'gi');
        cleanHtml = cleanHtml.replace(planReg1, planUrl).replace(planReg2, planUrl);
      }
      cleanHtml = cleanHtml.replace(/#*(?:PLAN_IMAGE|2D_PLAN)_\d+#*/gi, '');

      // Map Placeholders
      if (creativeImages.map_placeholders && typeof creativeImages.map_placeholders === 'object') {
        Object.entries(creativeImages.map_placeholders).forEach(([token, url]) => {
          if (url) {
            const reg = new RegExp(token.replace(/#/g, '\\#'), 'g');
            cleanHtml = cleanHtml.replace(reg, url);
          }
        });
      }

      // 2. Data Placeholders
      const projectLogoMetaPath = projectData.project_logo_file_meta?.path
        ? ('/' + String(projectData.project_logo_file_meta.path).replace(/^\/+/, '')) : '';
      const projectLogoUrl = projectData.project_logo || projectLogoMetaPath
        || (projectData.project_logo_file_id ? '/api/project-files/' + encodeURIComponent(projectData.project_logo_file_id) : '');
      const replacements = {
        'PROJECT_NAME': projectData.project_name || projectData.projectName || projectData.name || '',
        'PROJECT_TYPE': projectData.project_type || projectData.projectType || '',
        'land_area': projectData.croquis_land_area || projectData.approved_financial_area || projectData.total_area_sqm || projectData.landArea || '',
        'location_address': projectData.location_address || projectData.location || projectData.address || '',
        'location_lat': projectData.location_lat || '',
        'location_lng': projectData.location_lng || '',
        'altsnyf_altkhtyty': projectData.altsnyf_altkhtyty || projectData.zoning || '',
        'nsba_albna__far': projectData.nsba_albna__far || projectData.far || '',
        'plot_number': projectData.plot_number || projectData.plotNumber || '',
        'budget': projectData.budget || projectData.total_cost || '',
        'noi': projectData.noi || projectData.annual_profit || '',
        'roi': projectData.roi || '',
        'alqrma_almdafa_almtwqaa__cap_rate': projectData.cap_rate || projectData.capRate || '',
        'nsba_alashgal_almtwqaa': projectData.occupancy_rate || '',
        'PROJECT_LOGO': projectLogoUrl
      };

      Object.entries(replacements).forEach(([key, val]) => {
        if (val) {
          const regExact = new RegExp('##' + key + '##', 'g');
          const regLower = new RegExp('##' + key.toLowerCase() + '##', 'g');
          const regUpper = new RegExp('##' + key.toUpperCase() + '##', 'g');
          cleanHtml = cleanHtml.replace(regExact, val).replace(regLower, val).replace(regUpper, val);
        }
      });

      Object.entries(projectData).forEach(([k, v]) => {
        if (v && (typeof v === 'string' || typeof v === 'number')) {
          const regExact = new RegExp('##' + k + '##', 'gi');
          cleanHtml = cleanHtml.replace(regExact, String(v));
        }
      });

      // Map files are already complete marked images from the location section.
      // The preview must fetch that exact file again after a replacement, even when
      // a server-side edit reused the same URL and the browser still has the old
      // bytes in its image cache.
      cleanHtml = cleanHtml.replace(
        /(?:\/uploads\/maps\/|\/api\/map-images\/)[^"'\s)]+/gi,
        url => withCacheBust(url)
      );

      // Cover and divider slides auto-inject fallback if model omitted ##IMAGE_COVER##
      if (coverImage && slideType === 'section_divider') {
        cleanHtml = forceSectionDividerBackgroundHtml(cleanHtml, coverImage);
      } else if (coverImage && (slideType === 'cover' || cleanHtml.includes('class="slide cover"') || cleanHtml.includes("class='slide cover'"))) {
        if (!cleanHtml.includes(coverImage) && !cleanHtml.includes('background-image')) {
          const bgDiv = '<div aria-hidden="true" style="position:absolute;inset:0;z-index:0;background-image:url(\'' + coverImage.replace(/'/g, "\\'") + '\');background-size:cover;background-position:center;"></div>';
          cleanHtml = cleanHtml.replace(/(<div[^>]*class=["']slide[^"']*["'][^>]*>)/i, '$1' + bgDiv);
        }
      }

      // Moodboard slide auto-inject fallback if images exist but tokens weren't placed
      if (slideType === 'moodboard' && moodboardImages.length) {
        const hasAnyImage = moodboardImages.some(img => img && cleanHtml.includes(img));
        if (!hasAnyImage) {
          const cols = moodboardImages.length <= 2 ? '1fr 1fr' : '1fr 1fr';
          const rows = moodboardImages.length <= 2 ? '1fr' : '1fr 1fr';
          const tiles = moodboardImages.map(img => '<div style="background-image:url(\'' + img.replace(/'/g, "\\'") + '\');background-size:cover;background-position:center;"></div>').join('');
          cleanHtml = '<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#171717;color:#fff;font-family:Arial,sans-serif;box-sizing:border-box;padding:42px;"><div style="display:flex;align-items:center;justify-content:space-between;height:52px;margin-bottom:20px;"><div style="font-size:30px;font-weight:700;">لوحة الإلهام (Moodboard)</div><div style="width:170px;height:4px;background:#C2A176;"></div></div><div style="height:560px;display:grid;grid-template-columns:' + cols + ';grid-template-rows:' + rows + ';gap:8px;">' + tiles + '</div></div>';
        }
      }

      // Heal pre-gray watermarks for display (mirror of the server-side
      // normalization): a saved overlay keeps its old filter until the next
      // save persists the healed one.
      cleanHtml = cleanHtml.replace(
        /(<div\b[^>]*\bdata-slide-watermark=["']true["'][^>]*>[\s\S]*?<img\b[^>]*style="[^"]*?)filter\s*:\s*[^;"]+/gi,
        '$1filter:grayscale(100%) brightness(0) invert(53.3%)'
      );

      cleanHtml = cleanHtml.replace(/##[a-zA-Z0-9_]+##/g, '');
      return cleanHtml;
    }

    function tenantSlideCanvasDimensions(slide) {
      const ratio = String((tenantBranding && tenantBranding.slide_ratio) || '16:9').trim();
      const defaultHeight = ratio === '4:3' ? 960 : 720;
      const parsePx = value => {
        const match = String(value || '').trim().match(/^([0-9]+(?:\.[0-9]+)?)px$/i);
        return match ? Number(match[1]) : 0;
      };
      const width = parsePx(slide && slide.style && slide.style.width) || 1280;
      const height = parsePx(slide && slide.style && slide.style.height) || defaultHeight;
      return {
        width: width > 0 ? width : 1280,
        height: height > 0 ? height : defaultHeight
      };
    }

    function autoFitSlideContent(stage) {
      if (!stage) return null;
      const slide = stage.querySelector('.slide');
      if (!slide) return null;

      const canvas = tenantSlideCanvasDimensions(slide);

      slide.style.boxSizing = 'border-box';
      slide.style.width = canvas.width + 'px';
      slide.style.height = canvas.height + 'px';

      // Keep the stage in sync when a slide is inserted after the initial refit. Generated
      // slides can use a taller canvas, while the old stage kept the skeleton's 16:9 height.
      const stageWidth = parseFloat(stage.style.getPropertyValue('--stage-w')) || 0;
      if (stageWidth > 0) {
        stage.style.setProperty('--stage-h', (stageWidth * canvas.height / canvas.width).toFixed(2) + 'px');
        stage.style.setProperty('--slide-scale', (stageWidth / canvas.width).toFixed(4));
      }

      // The stage already scales the complete slide canvas. A second scale on an
      // arbitrary content wrapper made some previews shorter than the exported slide,
      // which left a large blank area and could move the heading outside the viewport.
      // Keep the generated layout intact and only remove the legacy mutations that this
      // function used to write into saved slide HTML.
      slide.querySelectorAll('*').forEach(el => {
        el.style.boxSizing = 'border-box';
        const transform = String(el.style.transform || '').trim();
        const transformOrigin = String(el.style.transformOrigin || '').trim();
        const width = String(el.style.width || '').trim();
        const maxWidth = String(el.style.maxWidth || '').trim();
        const isLegacyAutoFit = /^scale\(0?\.\d+\)$/.test(transform)
          && transformOrigin === 'top right'
          && (/%$/.test(width) || /%$/.test(maxWidth));
        if (isLegacyAutoFit) {
          el.style.removeProperty('transform');
          el.style.removeProperty('transform-origin');
          if (/%$/.test(width)) el.style.removeProperty('width');
          if (/%$/.test(maxWidth)) el.style.removeProperty('max-width');
        }
      });
      return canvas;
    }

    function slideParseCssColor(value) {
      const match = /rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)/.exec(String(value || '').trim());
      if (!match) return null;
      return { r: +match[1], g: +match[2], b: +match[3], a: match[4] === undefined ? 1 : +match[4] };
    }

    function slideColorContrast(fg, bg) {
      const lum = c => {
        const f = v => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
        return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
      };
      const l1 = lum(fg), l2 = lum(bg);
      return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    }

    const SLIDE_READABLE_COLORS = [
      { css: '#1e293b', rgb: { r: 30, g: 41, b: 59 } },
      { css: '#0f172a', rgb: { r: 15, g: 23, b: 42 } },
      { css: '#334155', rgb: { r: 51, g: 65, b: 85 } },
      { css: '#ffffff', rgb: { r: 255, g: 255, b: 255 } },
    ];

    // The solid surface under el, or null when the text sits on an image or a
    // gradient — an indeterminate surface must never be "repaired".
    function slideTextSurface(el, slideRoot) {
      let node = el;
      while (node && node.nodeType === 1) {
        const style = getComputedStyle(node);
        if (style.backgroundImage && style.backgroundImage !== 'none') return null;
        const bg = slideParseCssColor(style.backgroundColor);
        if (bg && bg.a > 0.05) return bg;
        if (node === slideRoot) break;
        node = node.parentElement;
      }
      return { r: 255, g: 255, b: 255, a: 1 };
    }

    function slideTextOverMedia(el, slideRoot) {
      let node = el;
      while (node && node !== slideRoot && node.nodeType === 1) {
        const position = getComputedStyle(node).position;
        if (position === 'absolute' || position === 'fixed') {
          const scope = node.parentElement;
          return Boolean(node.querySelector('img,video,canvas,svg,picture') ||
            (scope && scope.querySelector('img,video,canvas,svg,picture')));
        }
        node = node.parentElement;
      }
      return false;
    }

    // Repair text that computed styles leave unreadable — e.g. a <style>-block
    // rule painting white table cells on the white canvas, which the server-side
    // audit cannot always see. The inline !important color wins over the rule.
    function repairSlideTextContrast(stage) {
      const slideRoot = stage && stage.querySelector ? stage.querySelector('.slide') : null;
      if (!slideRoot || typeof getComputedStyle !== 'function') return;
      [slideRoot, ...slideRoot.querySelectorAll('*')].forEach(el => {
        let hasText = false;
        for (const child of el.childNodes) {
          if (child.nodeType === 3 && child.nodeValue.trim()) { hasText = true; break; }
        }
        if (!hasText) return;
        const fg = slideParseCssColor(getComputedStyle(el).color);
        if (!fg || fg.a <= 0.05) return;
        const surface = slideTextSurface(el, slideRoot);
        if (!surface || slideColorContrast(fg, surface) >= 4.5) return;
        if (slideTextOverMedia(el, slideRoot)) return;
        const readable = SLIDE_READABLE_COLORS.find(c => slideColorContrast(c.rgb, surface) >= 4.5);
        el.style.setProperty('color', (readable || SLIDE_READABLE_COLORS[0]).css, 'important');
      });
    }

    function collectSlideTextNodes(root) {
      const nodes = [];
      if (!root) return nodes;
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
        acceptNode(node) {
          if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
          const parent = node.parentElement;
          if (!parent) return NodeFilter.FILTER_REJECT;
          if (parent.closest('.slide-resize-handle, .slide-move-handle, .slide-element-delete-btn')) return NodeFilter.FILTER_REJECT;
          const tag = parent.tagName;
          if (tag === 'SCRIPT' || tag === 'STYLE') return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        }
      });
      let node;
      while ((node = walker.nextNode())) nodes.push(node);
      return nodes;
    }

    function enableSlideInlineEditing(stage, index) {
      const slide = stage.querySelector('.slide');
      if (!slide) return;
      const enabled = hasPermission('create_presentation') && !!slideInlineEditStates[index];
      const seen = new Set();
      collectSlideTextNodes(slide).forEach(node => {
        const el = node.parentElement;
        if (!el || seen.has(el)) return;
        seen.add(el);
        if (enabled) {
          if (el.hasAttribute('contenteditable')) return;
          el.setAttribute('contenteditable', 'plaintext-only');
          el.setAttribute('spellcheck', 'false');
          el.classList.add('slide-editable');
          el.title = 'اضغط للتعديل المباشر على النص (Esc للخروج)';
          el.addEventListener('mousedown', stopEditEvent);
          el.addEventListener('click', stopEditEvent);
          el.addEventListener('keydown', onInlineEditKey);
          el.addEventListener('paste', onInlineEditPaste);
          el.addEventListener('focus', onSlideEditableFocus);
          el.addEventListener('blur', () => commitSlideInlineEdit(stage, index, el));
        } else {
          el.removeAttribute('contenteditable');
          el.removeAttribute('spellcheck');
          el.classList.remove('slide-editable');
          el.removeAttribute('title');
          el.removeEventListener('mousedown', stopEditEvent);
          el.removeEventListener('click', stopEditEvent);
          el.removeEventListener('keydown', onInlineEditKey);
          el.removeEventListener('paste', onInlineEditPaste);
          el.removeEventListener('focus', onSlideEditableFocus);
        }
      });
      // Re-fit the slide when toggling edit mode.
      autoFitSlideContent(stage);
    }

    function slideElementPath(root, element) {
      const path = [];
      let node = element;
      while (node && node !== root) {
        const parent = node.parentElement;
        if (!parent) return null;
        path.unshift(Array.prototype.indexOf.call(parent.children, node));
        node = parent;
      }
      return node === root ? path : null;
    }

    function elementAtSlidePath(root, path) {
      let node = root;
      for (const index of path || []) {
        if (!node || !node.children || !node.children[index]) return null;
        node = node.children[index];
      }
      return node;
    }

    /* A static "shape": a block with its own visible surface (background,
       image, border or shadow). These are the cards and panels behind texts
       in flow layouts. Outline is deliberately ignored: hover and selection
       outlines must never make an element look like a shape. */
    function slideNodeIsVisualShape(node, style) {
      if (!node || !style) return false;
      const bg = String(style.backgroundColor || '').trim().toLowerCase();
      if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') return true;
      const bgImg = String(style.backgroundImage || '').trim().toLowerCase();
      if (bgImg && bgImg !== 'none') return true;
      const borderW = parseFloat(style.borderTopWidth) || 0;
      const borderStyle = String(style.borderTopStyle || '').trim().toLowerCase();
      if (borderW > 0 && borderStyle && borderStyle !== 'none') return true;
      const shadow = String(style.boxShadow || '').trim().toLowerCase();
      if (shadow && shadow !== 'none') return true;
      return false;
    }

    /* Watermark-aware target: geometry ops (frame/move/resize) use the logo img
       itself, while overlay-level ops (opacity/layer/delete) walk back up via
       watermarkOverlayOf(). */
    function watermarkOverlayOf(node) {
      if (!node || !node.closest) return null;
      return node.closest('[data-slide-watermark="true"], .slide-watermark');
    }

    function slideDragTarget(slide, source) {
      if (!slide || !source || source === slide) return null;
      if (source.closest && source.closest('.slide-resize-handle, .slide-move-handle, .slide-element-delete-btn')) return null;
      if (source.closest && source.closest('[contenteditable]')) return null;
      if (source.closest && source.closest('[data-slide-textbox], [data-slide-imagebox]')) {
        const box = source.closest('[data-slide-textbox], [data-slide-imagebox]');
        if (box && slide.contains(box)) return box;
      }
      if (source.closest && source.closest('.presentation-chrome-logo')) return null;
      /* Watermark layer: selectable in edit mode so it can be dragged,
         restacked or deleted per slide. In normal view it stays
         click-through via pointer-events:none. */
      if (source.closest) {
        const watermark = source.closest('[data-slide-watermark="true"], .slide-watermark');
        if (watermark && slide.contains(watermark)) {
          // The overlay is a full-slide inset:0 layer; selecting it stretched
          // the edit frame over the whole slide. Handles must hug the logo img.
          const logo = watermark.querySelector('img');
          return (logo && watermark.contains(logo)) ? logo : watermark;
        }
      }
      let node = source.nodeType === 1 ? source : source.parentElement;
      while (node && node !== slide) {
        const style = window.getComputedStyle(node);
        if (node.matches('[data-company-logo-placement], [data-team-logo-placement], img:not(.presentation-chrome-logo)')
          || style.position === 'absolute') {
          if (node.tagName === 'IMG' && node.parentElement && node.parentElement !== slide
            && node.parentElement.hasAttribute
            && (node.parentElement.hasAttribute('data-slide-imagebox')
              || node.parentElement.hasAttribute('data-canonical-map'))) {
            return node.parentElement;
          }
          return node;
        }
        /* Flow-layout shapes: the deepest block with its own visible surface
           wins, so an inner card is picked over a full-slide wrapper. Managed
           chrome (header/footer/counters) is never a shape. The walk stops
           before the slide root, which can never be selected. */
        if (!node.closest('[data-slide-header], [data-slide-footer], header, footer')
          && node.matches('div, section, aside, figure, table, ul')
          && slideNodeIsVisualShape(node, style)) {
          return node;
        }
        node = node.parentElement;
      }
      return null;
    }

    function findSlideRawTarget(rawRoot, target, path) {
      if (!rawRoot) return null;
      const placement = target ? (target.getAttribute('data-company-logo-placement')
        || target.getAttribute('data-team-logo-placement')) : null;
      if (placement) {
        const attr = target.hasAttribute('data-company-logo-placement')
          ? 'data-company-logo-placement' : 'data-team-logo-placement';
        const safePlacement = String(placement).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
        const byPlacement = rawRoot.querySelector('[' + attr + '="' + safePlacement + '"]');
        if (byPlacement) return byPlacement;
      }
      return elementAtSlidePath(rawRoot, path);
    }

    function commitSlideElementMove(stage, index, target, path, dx, dy) {
      const slideData = tenantSlidesData[index];
      if (!slideData || !slideData.html || (!dx && !dy)) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      if (!rawRoot) return;
      const rawTarget = findSlideRawTarget(rawRoot, target, path);
      if (!rawTarget) return;

      pushSlideEditHistory(index);
      const nextX = (Number(target.dataset.manualTranslateX) || 0) + dx;
      const nextY = (Number(target.dataset.manualTranslateY) || 0) + dy;
      const transform = 'translate(' + Math.round(nextX) + 'px, ' + Math.round(nextY) + 'px)';
      target.dataset.manualTranslateX = String(Math.round(nextX));
      target.dataset.manualTranslateY = String(Math.round(nextY));
      target.style.transform = transform;
      rawTarget.dataset.manualTranslateX = String(Math.round(nextX));
      rawTarget.dataset.manualTranslateY = String(Math.round(nextY));
      rawTarget.style.transform = transform;
      slideData.html = rawRoot.outerHTML;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      toast('تم تحريك العنصر وحفظ موضعه في الشريحة');
    }

    function commitSlideElementDelete(stage, index, target, path) {
      const slideData = tenantSlidesData[index];
      if (!slideData || !slideData.html) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      if (!rawRoot) return;
      const rawTarget = findSlideRawTarget(rawRoot, target, path);
      if (!rawTarget || !rawTarget.parentElement) return;
      // Deleting the logo must remove the whole watermark overlay,
      // not leave an empty full-slide layer behind.
      const deleteTarget = watermarkOverlayOf(rawTarget) || rawTarget;
      if (!deleteTarget.parentElement) return;
      pushSlideEditHistory(index);
      deleteTarget.parentElement.removeChild(deleteTarget);
      slideData.html = rawRoot.outerHTML;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      const session = slideEditSessions[index];
      if (session) session.sel = null;
      triggerAutoSaveDraft();
      refreshSingleSlideCard(index);
      toast('تم حذف العنصر من الشريحة');
    }

    function enableSlideElementDragging(stage, index) {
      const slide = stage.querySelector('.slide');
      if (!slide) return;
      const enabled = hasPermission('create_presentation') && !!slideElementEditStates[index];
      slide.classList.toggle('slide-element-editing', enabled);
      if (!enabled) return;
      let activeDeleteBtn = null;
      function removeDeleteBtn() {
        if (activeDeleteBtn) { activeDeleteBtn.remove(); activeDeleteBtn = null; }
      }
      stage.addEventListener('mouseover', function handleSlideHover(event) {
        if (!enabled) return;
        if (slideElementDragActive) return;
        removeDeleteBtn();
        const target = slideDragTarget(slide, event.target);
        if (!target) return;
        const path = slideElementPath(slide, target);
        if (!path) return;
        target.classList.add('slide-element-editable');
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'slide-element-delete-btn';
        btn.textContent = 'حذف';
        btn.addEventListener('pointerdown', function(e) { e.stopPropagation(); e.preventDefault(); });
        btn.addEventListener('click', function(e) {
          e.stopPropagation();
          e.preventDefault();
          removeDeleteBtn();
          commitSlideElementDelete(stage, index, target, path);
        });
        // A selected watermark target is the logo img itself (a void element),
        // so the hover button docks on its overlay instead of throwing.
        const btnHost = (target.tagName === 'IMG' && target.parentElement) ? target.parentElement : target;
        btnHost.appendChild(btn);
        activeDeleteBtn = btn;
      });
      stage.addEventListener('mouseout', function handleSlideHoverOut(event) {
        if (!enabled) return;
        const related = event.relatedTarget;
        if (activeDeleteBtn && (!related || (!activeDeleteBtn.contains(related) && !activeDeleteBtn.parentElement?.contains(related)))) {
          const target = slideDragTarget(slide, event.target);
          if (target) target.classList.remove('slide-element-editable');
          removeDeleteBtn();
        }
      });
      stage.addEventListener('pointerdown', function handleSlidePointerDown(event) {
        if (event.button !== 0) return;
        if (slideElementDragActive) return;
        const target = slideDragTarget(slide, event.target);
        if (!target) return;
        const path = slideElementPath(slide, target);
        if (!path) return;
        event.preventDefault();
        event.stopPropagation();
        slideElementDragActive = true;
        const scale = Number(stage.style.getPropertyValue('--slide-scale')) || 1;
        const startX = event.clientX;
        const startY = event.clientY;
        const startTranslateX = Number(target.dataset.manualTranslateX) || 0;
        const startTranslateY = Number(target.dataset.manualTranslateY) || 0;
        let moved = false;
        target.classList.add('slide-element-editable');
        target.setPointerCapture?.(event.pointerId);

        const handlePointerMove = moveEvent => {
          const dx = (moveEvent.clientX - startX) / scale;
          const dy = (moveEvent.clientY - startY) / scale;
          if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
          target.style.transform = 'translate(' + Math.round(startTranslateX + dx) + 'px, ' + Math.round(startTranslateY + dy) + 'px)';
        };
        const finish = endEvent => {
          const dx = (endEvent.clientX - startX) / scale;
          const dy = (endEvent.clientY - startY) / scale;
          target.releasePointerCapture?.(event.pointerId);
          target.removeEventListener('pointermove', handlePointerMove);
          target.removeEventListener('pointerup', finish);
          target.removeEventListener('pointercancel', finish);
          target.classList.remove('slide-element-editable');
          slideElementDragActive = false;
          if (moved) commitSlideElementMove(stage, index, target, path, dx, dy);
          selectSlideElement(stage, index, target, path);
        };
        target.addEventListener('pointermove', handlePointerMove);
        target.addEventListener('pointerup', finish);
        target.addEventListener('pointercancel', finish);
      });
      stage.addEventListener('click', function handleSlideEditClick(event) {
        if (!getSlideEditSession(index)) return;
        if (event.target.closest('.slide-element-selected, .slide-resize-handle, .slide-move-handle, .slide-element-delete-btn')) return;
        if (event.target.closest && event.target.closest('[contenteditable]')) return;
        const session = slideEditSessions[index];
        if (session && session.sel) {
          const slideEl = stage.querySelector('.slide');
          const selected = slideEl ? elementAtSlidePath(slideEl, session.sel.path) : null;
          if (selected && (selected === event.target || selected.contains(event.target))) return;
        }
        if (slideDragTarget(slide, event.target)) return;
        clearSlideElementSelection(stage);
        if (session) session.sel = null;
        syncSlideElementToolbar(index);
      });
      stage.addEventListener('keydown', function handleSlideEditKey(event) {
        if (event.key !== 'Delete' && event.key !== 'Backspace') return;
        const ae = document.activeElement;
        if (ae && (ae.isContentEditable || /^(INPUT|TEXTAREA|BUTTON|SELECT)$/.test(ae.tagName))) return;
        if (!getSlideEditSession(index)) return;
        event.preventDefault();
        event.stopPropagation();
        deleteSelectedSlideElement(index);
      });
    }