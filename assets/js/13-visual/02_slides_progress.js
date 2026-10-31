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
      if (['cover', 'moodboard'].includes(type)) {
        root.querySelectorAll('[data-slide-footer], footer, .slide-footer, [data-slide-counter]').forEach(node => node.remove());
        root.querySelectorAll('div, span, p, b, strong, small').forEach(node => {
          if (node.children.length || !/bottom\s*:/i.test(node.getAttribute('style') || '')) return;
          if (/^\s*\d{1,3}(?:\s*[—–/-]\s*\d{1,3})?\s*$/.test(node.textContent || '')) node.remove();
        });
      } else {
        const counter = String(index).padStart(2, '0') + ' — ' + String(total).padStart(2, '0');
        const counterText = /^\s*\d{1,3}(?:\s*[—–/-]\s*\d{1,3})?\s*$/;
        const separatedText = /^\s*\d{1,3}\s*[—–-]\s*\d{1,3}\s*$/;
        const cornerAnchor = /(?:^|[\s;"'])(?:top|bottom|left|right|inset)\s*:/i;
        const leafOf = node => {
          if (!node.children.length && counterText.test(node.textContent || '')) return node;
          if (node.children.length === 1) {
            const child = node.children[0];
            if (['B', 'STRONG', 'SMALL', 'EM', 'I', 'SPAN'].includes(child.tagName)
                && !child.children.length && counterText.test(child.textContent || '')
                && String(node.textContent || '').trim() === String(child.textContent || '').trim()) return child;
          }
          return null;
        };
        let pairs = Array.from(root.querySelectorAll('[data-slide-counter]'))
          .map(node => ({ owner: node, leaf: leafOf(node) || node }));
        if (!pairs.length && type === 'section_divider') {
          pairs = Array.from(root.querySelectorAll('div, span'))
            .filter(node => /^\s*\d{1,3}\s*[—–-]\s*\d{1,3}\s*$/.test(node.textContent || ''))
            .map(node => ({ owner: node, leaf: node }));
        }
        if (type === 'closing') {
          // A stale closing number may sit at the top edge or wrap its digits in
          // one inline tag — «NN — NN» anywhere is a counter, a bare «NN» only
          // when the element is pinned to a slide corner.
          const claimed = new Set();
          Array.from(root.querySelectorAll('div, span, p, b, strong, small, em, i')).forEach(node => {
            if (node.dataset.slideCounter) return;
            const leaf = leafOf(node);
            if (!leaf || claimed.has(leaf)) return;
            if (separatedText.test(leaf.textContent || '') || cornerAnchor.test(node.getAttribute('style') || '')) {
              claimed.add(leaf);
              pairs.push({ owner: node, leaf });
            }
          });
        }
        if (!pairs.length && type !== 'closing') {
          const footer = root.querySelector('footer, .slide-footer, [data-slide-footer]')
            || Array.from(root.querySelectorAll('footer, div')).find(node => /height:\s*36px/i.test(node.getAttribute('style') || ''));
          if (footer) {
            footer.dataset.slideFooter = '1';
            const candidates = Array.from(footer.querySelectorAll('span, div')).filter(node => counterText.test(node.textContent || ''));
            const counterNode = candidates[candidates.length - 1];
            if (counterNode) pairs.push({ owner: counterNode, leaf: counterNode });
          }
        }
        pairs.forEach(pair => {
          pair.owner.dataset.slideCounter = '1';
          if (type === 'closing') {
            // The brand overlay sits at z-index:1 — keep the counter above it.
            pair.owner.style.zIndex = '20';
            if (!pair.owner.getAttribute('dir')) pair.owner.setAttribute('dir', 'ltr');
          }
          pair.leaf.textContent = counter;
        });
        if (!pairs.length && type === 'closing') {
          const counterEl = document.createElement('div');
          counterEl.dataset.slideCounter = '1';
          counterEl.setAttribute('dir', 'ltr');
          const side = (root.getAttribute('dir') || '').toLowerCase() === 'ltr' ? 'right' : 'left';
          counterEl.style.cssText = 'position:absolute;bottom:34px;' + side + ':48px;z-index:20;font-size:13px;letter-spacing:1px;color:rgba(255,255,255,0.55);';
          counterEl.textContent = counter;
          root.appendChild(counterEl);
        }
      }
      if (type === 'index') {
        const entries = Array.isArray(indexEntries)
          ? indexEntries.filter(entry => entry && entry.section_key)
          : [];
        const preserved = !!(slide.is_custom || slide._designer_keep_html);
        const existingRows = Array.from(root.querySelectorAll('[data-index-section]'));
        if (existingRows.length === 0) {
          if (!preserved && entries.length > 0) {
            return buildTenantIndexSlideHtml(entries, index, total);
          }
        } else if (preserved) {
          // A designer-edited index keeps its own layout: only the page label
          // of rows that still exist is refreshed, rows are never reflowed.
          existingRows.forEach(row => {
            const key = String(row.getAttribute('data-index-section') || '');
            const entry = entries.find(item => String(item.section_key) === key);
            if (!entry) return;
            let page = row.querySelector('[data-index-page]');
            if (!page) {
              page = Array.from(row.querySelectorAll('*')).find(node =>
                !node.children.length && /^\s*\d{1,3}\s*$/.test(node.textContent || ''));
            }
            if (page) page.textContent = String(entry.page || 0).padStart(2, '0');
          });
        } else if (entries.length > 0) {
          // An empty entries list means the section keys are not known yet —
          // never wipe a populated index on that pass. A non-empty list must
          // leave every row in its correct column: patching rows in place used
          // to pile them into one column after a delete or a refresh.
          const rowsByKey = new Map();
          existingRows.forEach(row => {
            const key = String(row.getAttribute('data-index-section') || '');
            if (key && !rowsByKey.has(key)) rowsByKey.set(key, row);
            else row.remove();
          });
          const firstRow = existingRows[0];
          const grid = firstRow?.parentElement?.parentElement;
          const columns = grid ? Array.from(grid.children).filter(node => node.tagName === 'DIV') : [];
          if (grid && columns.length) {
            const templateRow = firstRow.cloneNode(true);
            const ordered = entries.map(entry => {
              let row = rowsByKey.get(String(entry.section_key));
              if (!row) {
                row = templateRow.cloneNode(true);
                row.setAttribute('data-index-section', String(entry.section_key));
                const pageLeaf = row.querySelector('[data-index-page]');
                if (pageLeaf) pageLeaf.setAttribute('data-index-page', String(entry.section_key));
                const titleLeaf = Array.from(row.querySelectorAll('div, span, p')).find(node =>
                  !node.children.length && node !== pageLeaf);
                if (titleLeaf) titleLeaf.textContent = String(entry.title || '');
              }
              let page = row.querySelector('[data-index-page]');
              if (!page) {
                page = Array.from(row.querySelectorAll('*')).find(node =>
                  !node.children.length && /^\s*\d{1,3}\s*$/.test(node.textContent || ''));
              }
              if (page) {
                page.setAttribute('data-index-page', String(entry.section_key));
                page.textContent = String(entry.page || 0).padStart(2, '0');
              }
              return row;
            }).filter(Boolean);
            existingRows.forEach(row => { if (!ordered.includes(row)) row.remove(); });
            const midpoint = Math.ceil(ordered.length / 2);
            let second = columns[1];
            if (!second) {
              second = columns[0].cloneNode(false);
              grid.appendChild(second);
            }
            columns[0].replaceChildren(...ordered.slice(0, midpoint));
            second.replaceChildren(...ordered.slice(midpoint));
          } else {
            entries.forEach(entry => {
              const page = root.querySelector('[data-index-page="' + entry.section_key + '"]');
              if (page) {
                page.dataset.indexPage = entry.section_key;
                page.textContent = String(entry.page).padStart(2, '0');
              }
            });
          }
        }
      }
      return template.innerHTML;
    }

    const FORCED_SECTION_BACKGROUND_RE = /background-image\s*:\s*url\([^)]*\)\s*!important\s*;\s*background-size\s*:\s*cover\s*!important\s*;\s*background-position\s*:\s*center\s+center\s*!important\s*;\s*background-repeat\s*:\s*no-repeat\s*!important\s*;?/gi;

    function slideVisibleWordCount(html) {
      try {
        const doc = new DOMParser().parseFromString(String(html || ''), 'text/html');
        doc.querySelectorAll('style, script').forEach(node => node.remove());
        return String(doc.body ? doc.body.textContent : '').trim().split(/\s+/).filter(Boolean).length;
      } catch (err) {
        return 0;
      }
    }

    /* A stored market/swot content page the server retyped as a divider keeps
       the cover photo forced onto its root. The saved revision is served as-is,
       so the preview must repair every matching slide before rendering. */
    function repairMisclassifiedMarketDivider(slide) {
      if (!slide || typeof slide !== 'object') return slide;
      if (String(slide.type || '').toLowerCase() !== 'section_divider') return slide;
      const section = String(
        slide.section_key || slide.sectionKey || tenantSlideSectionKey(slide, '') || ''
      );
      if (section !== 'market' && section !== 'swot_risks') return slide;
      if (slideVisibleWordCount(slide.html) <= 30) return slide;
      const repaired = { ...slide, type: 'content' };
      delete repaired.design_style;
      repaired.html = String(slide.html || '')
        .replace(FORCED_SECTION_BACKGROUND_RE, '')
        .replace(/<div\b[^>]*data-section-divider-background[^>]*>\s*<\/div>/gi, '');
      return repaired;
    }

    function collapseDuplicateTimelineGantts(slides) {
      let kept = false;
      return slides.filter(slide => {
        const html = String((slide || {}).html || '');
        if (html.indexOf('data-timeline-gantt') === -1) return true;
        // A slide the client duplicated on purpose is their page; only
        // generated duplicates from one plan are collapsed.
        if (kept && !(slide && slide.duplicated_from)) return false;
        kept = true;
        return true;
      });
    }

    function renumberTenantSlides() {
      if (!Array.isArray(tenantSlidesData) || !tenantSlidesData.length) return tenantSlidesData;
      tenantSlidesData = collapseDuplicateTimelineGantts(
        tenantSlidesData.map(repairMisclassifiedMarketDivider)
      );
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
      // The stored divider owns its photo: the element is in the slide's own
      // HTML, and the designer chat may remove it. This used to plant the photo
      // again on every render with a forced declaration, so neither the client
      // nor the chat could drop the background. Now it only follows the current
      // cover image, and only when the slide still carries the element.
      if (!/data-section-divider-background\s*=\s*["']?1/i.test(String(html))) {
        return String(html || '');
      }
      const safeCover = String(coverImage).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
      return String(html).replace(
        /(data-section-divider-background\s*=\s*["']?1["']?[^>]*?background-image\s*:\s*url\()([^)]*)(\))/i,
        (match, head, url, tail) => head + safeCover + tail
      );
    }

    function updateCoverBackgroundHtml(html, coverImage) {
      if (!html || !coverImage) return String(html || '');
      // The stored cover owns its photo as a real element, so the client can
      // delete it and the deletion sticks. Only follow the approved image when
      // that element still exists — never plant it again on every render.
      if (!/data-cover-background\s*=\s*["']?1/i.test(String(html))) {
        return String(html || '');
      }
      const safeCover = String(coverImage).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
      return String(html).replace(
        /(data-cover-background\s*=\s*["']?1["']?[^>]*?background-image\s*:\s*url\()([^)]*)(\))/i,
        (match, head, url, tail) => head + safeCover + tail
      );
    }

    function stripReservedSlideHeaderSpacing(tag) {
      const styleMatch = /style\s*=\s*(["'])([\s\S]*?)\1/i.exec(tag);
      if (!styleMatch) return tag;
      const style = styleMatch[2];
      const px = name => {
        const match = new RegExp('(?:^|[;\\s])' + name + '\\s*:\\s*(-?\\d+(?:\\.\\d+)?)px', 'i').exec(style);
        return match ? parseFloat(match[1]) : null;
      };
      let marginTop = px('margin-top');
      if (marginTop === null) marginTop = px('margin');
      let paddingTop = px('padding-top');
      if (paddingTop === null) paddingTop = px('padding');
      const appendStyle = (source, declaration) => source.replace(
        /style\s*=\s*(["'])([\s\S]*?)\1/i,
        (match, quote, value) => 'style=' + quote + value.replace(/\s*;?\s*$/, ';') + declaration + quote
      );
      let cleaned = tag;
      if (marginTop !== null && marginTop >= 24) cleaned = appendStyle(cleaned, 'margin-top:0!important;');
      if (paddingTop !== null && paddingTop >= 48) cleaned = appendStyle(cleaned, 'padding-top:0!important;');
      return cleaned;
    }

    // Decks stored before the market frame was top-aligned still carry
    // `safe center`, and the stripped model header's margin is still on the
    // first block. The server normalizes both on save/export; the preview
    // must show the same lane.
    function normalizeMarketFrameSpacing(html) {
      if (!html || String(html).indexOf('data-market-auto-fit-content') === -1) return html;
      let cleaned = String(html).replace(
        /<div\b[^>]*\bdata-market-auto-fit-content\s*=\s*["']1["'][^>]*>/gi,
        tag => tag.replace(/justify-content\s*:\s*safe\s+center/gi, 'justify-content:flex-start')
      );
      cleaned = cleaned.replace(
        /(<div\b[^>]*\bdata-market-auto-fit-content\s*=\s*["']1["'][^>]*>\s*)(<[^/!?][^>]*>)/i,
        (match, frameOpen, firstTag) => frameOpen + stripReservedSlideHeaderSpacing(firstTag)
      );
      return cleaned;
    }

    function processSlideHtmlClient(html, slideType) {
      if (!html) return '';
      let cleanHtml = stripSlideFontDeclarations(html);
      cleanHtml = normalizeMarketFrameSpacing(cleanHtml);
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
        cleanHtml = updateCoverBackgroundHtml(cleanHtml, coverImage);
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
      // Zoom is a canvas-level scale: the stage keeps its declared fit width and the
      // visible width is fitWidth x zoom. Deriving both from the slide's own canvas
      // keeps a 4:3 deck undistorted and lets every re-render keep the chosen zoom.
      const declaredWidth = parseFloat(stage.style.getPropertyValue('--stage-w')) || 0;
      let canvasZoom = 0;
      try {
        if (typeof tenantCanvasZoom === 'number' && tenantCanvasZoom > 0) canvasZoom = tenantCanvasZoom;
      } catch (error) { /* the canvas layer loads after this file */ }
      if (!stage.dataset.fitWidth && declaredWidth > 0) stage.dataset.fitWidth = String(declaredWidth);
      const fitWidth = Number(stage.dataset.fitWidth) || declaredWidth || 0;
      if (fitWidth > 0) {
        const stageWidth = fitWidth * (canvasZoom || 1);
        stage.style.setProperty('--stage-w', stageWidth.toFixed(2) + 'px');
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

    /* The scale the slide is actually painted at. The stage variable only
       covers the stage zoom; a slide that carries its own transform (or a
       stored legacy scale) is smaller or larger than that, and every
       selection-handle measurement used the stage scale alone — the boxes
       landed beside the element. Measure the painted width against the
       layout width instead. */
    function slideRenderedScale(stage) {
      const fallback = Number(stage && stage.style.getPropertyValue('--slide-scale')) || 1;
      const slide = stage ? stage.querySelector('.slide') : null;
      if (!slide) return fallback;
      const width = slide.offsetWidth || parseFloat(slide.style.width) || 0;
      if (!width) return fallback;
      const painted = slide.getBoundingClientRect().width;
      const scale = painted / width;
      return isFinite(scale) && scale > 0 ? scale : fallback;
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
          if (parent.closest('[data-slide-live-only="1"]')) return NodeFilter.FILTER_REJECT;
          const tag = parent.tagName;
          if (tag === 'SCRIPT' || tag === 'STYLE') return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        }
      });
      let node;
      while ((node = walker.nextNode())) nodes.push(node);
      return nodes;
    }

    /* A fixed, overflow-hidden frame crops a table resized inside it. Mark that
       frame as the table shape when it wraps just this table; a bare table is
       its own shape. */
    function slideTablePointerBox(table) {
      if (!table || !table.closest) return table;
      const slide = table.closest('.slide');
      const tableRect = table.getBoundingClientRect();
      let node = table.parentElement;
      while (node && node !== slide) {
        const style = window.getComputedStyle(node);
        const clips = /^(hidden|clip)$/.test(style.overflowX)
          || /^(hidden|clip)$/.test(style.overflowY);
        if (clips) {
          const rect = node.getBoundingClientRect();
          const onlyThisTable = node.querySelectorAll('table').length === 1;
          const tight = rect.width > 0 && tableRect.width > 0
            && rect.width <= tableRect.width * 1.5 + 24;
          if (onlyThisTable && tight) return node;
        }
        node = node.parentElement;
      }
      return table;
    }

    function markSlideTablesForPointerEditing(slide) {
      if (!slide || !slide.querySelectorAll) return;
      slide.querySelectorAll('table').forEach(table => {
        if (table.closest('[data-slide-table]')) return;
        slideTablePointerBox(table).setAttribute('data-slide-table', '1');
      });
    }

    function enableSlideInlineEditing(stage, index) {
      const slide = stage.querySelector('.slide');
      if (!slide) return;
      const enabled = hasPermission('create_presentation') && !!slideInlineEditStates[index];
      markSlideTablesForPointerEditing(slide);
      const seen = new Set();
      collectSlideTextNodes(slide).forEach(node => {
        const el = node.parentElement;
        if (!el || seen.has(el)) return;
        seen.add(el);
        // Every table is one shape on a single click, manual or generated; only
        // its cells wait for the double-click handler below.
        if (el.closest && el.closest('[data-slide-table] td, [data-slide-table] th')) return;
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
      if (enabled && typeof bindSlideTableEditing === 'function') bindSlideTableEditing(stage, index);
      // Re-fit the slide when toggling edit mode.
      autoFitSlideContent(stage);
    }

    /* Editor chrome (move/resize handles, the hover delete button) and the
       preview-only cover photo are appended inside the slide. Paths must skip
       them or an edit that changes the text-node count lands on a neighbour. */
    function slidePathIgnores(node) {
      if (!node || node.nodeType !== 1) return false;
      const flag = node.getAttribute ? String(node.getAttribute('data-slide-live-only') || '') : '';
      if (flag === '1') return true;
      const classes = node.classList;
      if (!classes) return false;
      return classes.contains('slide-resize-handle')
        || classes.contains('slide-move-handle')
        || classes.contains('slide-element-delete-btn');
    }

    function slideElementPath(root, element) {
      const path = [];
      let node = element;
      while (node && node !== root) {
        const parent = node.parentElement;
        if (!parent) return null;
        const children = Array.from(parent.children).filter(child => !slidePathIgnores(child));
        const index = children.indexOf(node);
        if (index === -1) return null;
        path.unshift(index);
        node = parent;
      }
      return node === root ? path : null;
    }

    function elementAtSlidePath(root, path) {
      let node = root;
      for (const index of path || []) {
        if (!node || !node.children) return null;
        const children = Array.from(node.children).filter(child => !slidePathIgnores(child));
        node = children[index];
        if (!node) return null;
      }
      return node;
    }
