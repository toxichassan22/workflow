"""Injected collector: turns the rendered slide into a paint list."""

_COLLECTOR_JS = r"""
() => {
  const SLIDE = document.querySelector('.slide');
  if (!SLIDE) return {items: [], warnings: ['no_slide'], raster: ''};
  const base = SLIDE.getBoundingClientRect();
  const items = [];
  const warnings = [];
  let rasterReason = '';
  const num = (v) => { const n = parseFloat(v); return isFinite(n) ? n : 0; };
  const r2 = (v) => Math.round(v * 100) / 100;
  const rectOf = (el) => {
    const r = el.getBoundingClientRect();
    return {x: r2(r.left - base.left), y: r2(r.top - base.top),
            w: r2(r.width), h: r2(r.height)};
  };
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

  function splitLayers(value) {
    const out = []; let depth = 0, quote = null, cur = '';
    for (const ch of value || '') {
      if (quote) { cur += ch; if (ch === quote) quote = null; continue; }
      if (ch === '"' || ch === "'") { quote = ch; cur += ch; continue; }
      if (ch === '(') depth++;
      if (ch === ')') depth--;
      if (ch === ',' && depth === 0) { out.push(cur.trim()); cur = ''; continue; }
      cur += ch;
    }
    if (cur.trim()) out.push(cur.trim());
    return out;
  }
  function urlOf(value) {
    const m = /url\(\s*["']?(.*?)["']?\s*\)/i.exec(value || '');
    return m ? m[1] : '';
  }
  function parseGradient(value) {
    if (!/gradient\(/i.test(value || '')) return null;
    const isRadial = /radial-gradient/i.test(value);
    const start = value.indexOf('(');
    const inner = value.slice(start + 1, value.lastIndexOf(')'));
    const parts = splitLayers(inner);
    let angle = 180;
    const stops = [];
    for (const part of parts) {
      const text = part.trim();
      if (/^-?[\d.]+deg$/.test(text)) { angle = parseFloat(text); continue; }
      if (/^to\s+/i.test(text)) {
        const dir = text.toLowerCase();
        if (dir.indexOf('top') >= 0) angle = 0;
        else if (dir.indexOf('bottom') >= 0) angle = 180;
        else if (dir.indexOf('left') >= 0) angle = 270;
        else if (dir.indexOf('right') >= 0) angle = 90;
        continue;
      }
      if (/^(circle|ellipse|closest|farthest|at\s)/i.test(text)) continue;
      const m = /^(rgba?\([^)]*\)|#[0-9a-fA-F]{3,8})(?:\s+([\d.]+%))?/.exec(text);
      if (m) stops.push({color: m[1], offset: m[2] ? parseFloat(m[2]) / 100 : null});
    }
    if (!stops.length) return null;
    const filled = [];
    stops.forEach((stop, index) => {
      let offset = stop.offset;
      if (offset === null) offset = stops.length === 1 ? 0 : index / (stops.length - 1);
      filled.push({color: stop.color, offset: offset});
    });
    if (filled.length === 1) filled.push({color: filled[0].color, offset: 1});
    // CSS 0deg points up; DrawingML 0deg points right. 180deg(top->bottom)
    // therefore becomes 90deg in PowerPoint.
    const pptAngle = isRadial ? 0 : ((angle - 90) % 360 + 360) % 360;
    return {type: isRadial ? 'radial' : 'linear', angle: pptAngle, stops: filled};
  }
  function parseShadow(value) {
    if (!value || value === 'none') return null;
    const first = splitLayers(value)[0];
    const colorMatch = /(rgba?\([^)]*\)|#[0-9a-fA-F]{3,8})/.exec(first);
    const lengths = (first.match(/-?[\d.]+px/g) || []).map(parseFloat);
    if (lengths.length < 2) return null;
    return {
      color: colorMatch ? colorMatch[1] : 'rgba(0,0,0,0.25)',
      x: lengths[0] || 0, y: lengths[1] || 0,
      blur: lengths.length > 2 ? lengths[2] : 0,
      spread: lengths.length > 3 ? lengths[3] : 0
    };
  }
  function backgroundLayers(cs) {
    const value = cs.backgroundImage || 'none';
    if (!value || value === 'none') return [];
    return splitLayers(value).map((layer) => {
      const url = urlOf(layer);
      if (url) return {kind: 'image', src: url};
      const gradient = parseGradient(layer);
      if (gradient) return {kind: 'gradient', gradient: gradient};
      return {kind: 'unsupported'};
    });
  }
  function radiusToken(cs) {
    const value = (cs.borderRadius || '0px').split('/')[0].trim();
    return value || '0px';
  }
  function bordersOf(cs) {
    const out = [];
    for (const side of ['top', 'right', 'bottom', 'left']) {
      const width = num(cs['border' + cap(side) + 'Width']);
      const style = cs['border' + cap(side) + 'Style'];
      const color = cs['border' + cap(side) + 'Color'];
      if (width > 0 && style !== 'none' && style !== 'hidden') {
        out.push({side: side, width: width, color: color, style: style});
      }
    }
    return out;
  }
  function opacityOf(cs) {
    const value = parseFloat(cs.opacity);
    return isFinite(value) ? Math.max(0, Math.min(1, value)) : 1;
  }
  function unsupportedReason(el, cs) {
    const tag = el.tagName.toLowerCase();
    if (['canvas', 'video', 'iframe', 'object', 'embed'].indexOf(tag) >= 0) return tag;
    if ((cs.filter || 'none') !== 'none') return 'filter';
    if ((cs.backdropFilter || 'none') !== 'none') return 'backdrop-filter';
    if ((cs.mixBlendMode || 'normal') !== 'normal') return 'mix-blend-mode';
    if ((cs.clipPath || 'none') !== 'none') return 'clip-path';
    if ((cs.maskImage || 'none') !== 'none') return 'mask-image';
    if ((cs.backgroundClip || 'border-box') === 'text') return 'background-clip-text';
    if ((cs.writingMode || 'horizontal-tb') !== 'horizontal-tb') return 'writing-mode';
    const transform = cs.transform || 'none';
    if (transform !== 'none') {
      try {
        const m = new DOMMatrixReadOnly(transform);
        if (!m.is2D || Math.abs(m.b) > 0.001 || Math.abs(m.c) > 0.001) return 'transform';
      } catch (error) { return 'transform'; }
    }
    for (const pseudo of ['::before', '::after']) {
      const ps = getComputedStyle(el, pseudo);
      const content = ps.content;
      if (content && content !== 'none' && content !== 'normal'
          && content !== '""' && content !== "''"
          && ps.display !== 'none' && ps.visibility !== 'hidden') {
        return 'pseudo-element';
      }
    }
    const layers = backgroundLayers(cs);
    for (const layer of layers) if (layer.kind === 'unsupported') return 'background-layer';
    if (layers.filter((l) => l.kind === 'image').length + layers.filter((l) => l.kind === 'gradient').length > 2) {
      return 'background-stack';
    }
    return '';
  }

  function textStyle(el, cs, opacity) {
    let color = cs.webkitTextFillColor || cs.color;
    return {
      size: num(cs.fontSize),
      weight: parseInt(cs.fontWeight, 10) || 400,
      italic: cs.fontStyle === 'italic' || cs.fontStyle === 'oblique',
      color: color,
      opacity: opacity,
      align: cs.textAlign,
      direction: cs.direction,
      letter_spacing: num(cs.letterSpacing),
      line_height: num(cs.lineHeight) || (num(cs.fontSize) * 1.35),
      underline: (cs.textDecorationLine || '').indexOf('underline') >= 0,
      strike: (cs.textDecorationLine || '').indexOf('line-through') >= 0,
      baseline: cs.verticalAlign
    };
  }

  function textItemsForNode(node, parent, cs, opacity) {
    const out = [];
    let raw = node.nodeValue || '';
    if (!raw.trim()) return out;
    const range = document.createRange();
    range.selectNodeContents(node);
    const rawRects = Array.from(range.getClientRects())
      .filter((r) => r.width > 0.3 && r.height > 0.3);
    if (!rawRects.length) return out;
    const groups = [];
    for (const rect of rawRects) {
      let group = null;
      for (const candidate of groups) {
        if (Math.abs(candidate.top - rect.top) <= 1.5) { group = candidate; break; }
      }
      if (!group) {
        group = {top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, text: ''};
        groups.push(group);
      } else {
        group.top = Math.min(group.top, rect.top);
        group.bottom = Math.max(group.bottom, rect.bottom);
        group.left = Math.min(group.left, rect.left);
        group.right = Math.max(group.right, rect.right);
      }
    }
    groups.sort((a, b) => (a.top - b.top) || (a.left - b.left));
    const lineText = groups.map(() => '');
    let lastGroup = 0;
    for (let i = 0; i < raw.length; i++) {
      range.setStart(node, i);
      range.setEnd(node, i + 1);
      const charRects = range.getClientRects();
      if (!charRects.length) { lineText[lastGroup] += raw[i]; continue; }
      const cr = charRects[0];
      let best = lastGroup, bestOverlap = -1;
      for (let j = 0; j < groups.length; j++) {
        const overlap = Math.min(groups[j].bottom, cr.bottom) - Math.max(groups[j].top, cr.top);
        if (overlap > bestOverlap) { bestOverlap = overlap; best = j; }
      }
      lastGroup = best;
      lineText[best] += raw[i];
    }
    const style = textStyle(parent, cs, opacity);
    const transform = cs.textTransform;
    for (let j = 0; j < groups.length; j++) {
      let text = lineText[j].replace(/\u00a0/g, ' ');
      if (!text.trim()) continue;
      if (transform === 'uppercase') text = text.toUpperCase();
      else if (transform === 'lowercase') text = text.toLowerCase();
      else if (transform === 'capitalize') text = text.replace(/\b\S/g, (m) => m.toUpperCase());
      const group = groups[j];
      out.push({
        type: 'text', text: text.trim(),
        x: r2(group.left - base.left), y: r2(group.top - base.top),
        w: r2(group.right - group.left), h: r2(group.bottom - group.top),
        style: style
      });
    }
    return out;
  }

  function collectTextNode(node, parent, cs, opacity) {
    for (const item of textItemsForNode(node, parent, cs, opacity)) {
      items.push(item);
    }
  }

  function collectBox(el, cs, opacity) {
    const r = rectOf(el);
    if (r.w <= 0.5 || r.h <= 0.5) return null;
    const layers = backgroundLayers(cs);
    const gradients = layers.filter((l) => l.kind === 'gradient').map((l) => l.gradient);
    const borders = bordersOf(cs);
    const shadow = parseShadow(cs.boxShadow);
    const fill = cs.backgroundColor;
    if (fill === 'rgba(0, 0, 0, 0)' && !gradients.length && !borders.length && !shadow) return null;
    return {
      type: 'box', x: r.x, y: r.y, w: r.w, h: r.h,
      fill: fill, gradients: gradients, radius: radiusToken(cs),
      borders: borders, shadow: shadow, opacity: opacity
    };
  }

  function contentRect(el, cs) {
    const r = el.getBoundingClientRect();
    const pl = num(cs.paddingLeft), pr = num(cs.paddingRight);
    const pt = num(cs.paddingTop), pb = num(cs.paddingBottom);
    const bl = num(cs.borderLeftWidth), br = num(cs.borderRightWidth);
    const bt = num(cs.borderTopWidth), bb = num(cs.borderBottomWidth);
    return {
      x: r2(r.left - base.left + bl + pl), y: r2(r.top - base.top + bt + pt),
      w: r2(Math.max(0, r.width - bl - br - pl - pr)),
      h: r2(Math.max(0, r.height - bt - bb - pt - pb))
    };
  }

  function collectImage(el, cs, opacity) {
    const src = el.currentSrc || el.src || '';
    if (!src) return null;
    const r = contentRect(el, cs);
    return {
      type: 'image', x: r.x, y: r.y, w: r.w, h: r.h, src: src,
      fit: cs.objectFit || 'fill', radius: radiusToken(cs), opacity: opacity,
      natural: {w: el.naturalWidth || 0, h: el.naturalHeight || 0}
    };
  }

  function collectBackgroundImages(el, cs, opacity) {
    const layers = backgroundLayers(cs).filter((l) => l.kind === 'image');
    if (!layers.length) return;
    const r = rectOf(el);
    const sizes = splitLayers(cs.backgroundSize || 'auto');
    const positions = splitLayers(cs.backgroundPosition || '0% 0%');
    layers.forEach((layer, index) => {
      items.push({
        type: 'image', x: r.x, y: r.y, w: r.w, h: r.h, src: layer.src,
        fit: sizes[index] || sizes[0] || 'auto',
        position: positions[index] || positions[0] || '0% 0%',
        radius: radiusToken(cs), opacity: opacity, natural: {w: 0, h: 0},
        background: true
      });
    });
  }

  function collectTableCell(cell) {
    const cs = getComputedStyle(cell);
    const r = rectOf(cell);
    const runs = [];
    const pushRuns = (node, styleCs) => {
      for (const child of node.childNodes) {
        if (child.nodeType === 3) {
          const text = (child.nodeValue || '').replace(/\s+/g, ' ');
          if (text) runs.push({text: text, style: textStyle(node, styleCs, 1)});
        } else if (child.nodeType === 1) {
          const tag = child.tagName.toLowerCase();
          if (tag === 'br') { runs.push({text: '\n'}); continue; }
          if (tag === 'table' || tag === 'style' || tag === 'script') continue;
          pushRuns(child, getComputedStyle(child));
        }
      }
    };
    pushRuns(cell, cs);
    const lines = [];
    const collectLines = (node) => {
      for (const child of node.childNodes) {
        if (child.nodeType === 3) {
          const parentEl = child.parentElement || node;
          const parentStyle = getComputedStyle(parentEl);
          const found = textItemsForNode(child, parentEl, parentStyle, 1);
          for (const item of found) lines.push(item);
        } else if (child.nodeType === 1) {
          const tag = child.tagName.toLowerCase();
          if (['br', 'table', 'style', 'script'].indexOf(tag) >= 0) continue;
          collectLines(child);
        }
      }
    };
    collectLines(cell);
    const overlays = [];
    const collectOverlays = (node) => {
      for (const child of node.children) {
        if (!child || child.nodeType !== 1) continue;
        const tag = child.tagName.toLowerCase();
        if (['table', 'style', 'script', 'br'].indexOf(tag) >= 0) continue;
        const childStyle = getComputedStyle(child);
        if (childStyle.display === 'none' || childStyle.visibility === 'hidden') continue;
        const box = collectBox(child, childStyle, 1);
        if (box) overlays.push(box);
        collectOverlays(child);
      }
    };
    collectOverlays(cell);
    return {
      text: (cell.innerText || '').replace(/\u00a0/g, ' '),
      runs: runs,
      lines: lines,
      overlays: overlays,
      x: r.x, y: r.y, w: r.w, h: r.h,
      colspan: cell.colSpan || 1, rowspan: cell.rowSpan || 1,
      header: cell.tagName.toLowerCase() === 'th',
      fill: cs.backgroundColor,
      padding: [num(cs.paddingTop), num(cs.paddingRight),
                num(cs.paddingBottom), num(cs.paddingLeft)],
      borders: bordersOf(cs),
      align: cs.textAlign,
      vertical: cs.verticalAlign,
      direction: cs.direction,
      style: textStyle(cell, cs, 1)
    };
  }

  function collectTable(table, opacity) {
    const r = rectOf(table);
    const rows = [];
    for (const tr of table.rows) {
      const rowRect = rectOf(tr);
      const cells = [];
      for (const cell of tr.cells) cells.push(collectTableCell(cell));
      rows.push({y: rowRect.y, h: rowRect.h, cells: cells});
    }
    return {type: 'table', x: r.x, y: r.y, w: r.w, h: r.h,
            rows: rows, opacity: opacity};
  }

  function svgPoint(ctm, x, y) {
    return {x: ctm.a * x + ctm.c * y + ctm.e, y: ctm.b * x + ctm.d * y + ctm.f};
  }
  function svgScale(ctm) {
    return Math.sqrt(Math.abs(ctm.a * ctm.d - ctm.b * ctm.c)) || 1;
  }
  function svgGradient(el) {
    if (!el) return null;
    const stops = [];
    for (const stop of el.querySelectorAll('stop')) {
      stops.push({
        offset: stop.getAttribute('offset') || '0',
        color: getComputedStyle(stop).stopColor || stop.getAttribute('stop-color') || '#000'
      });
    }
    if (!stops.length) return null;
    const filled = stops.map((stop, index) => {
      let offset = stop.offset;
      if (String(offset).indexOf('%') >= 0) offset = parseFloat(offset) / 100;
      else offset = parseFloat(offset) || 0;
      return {color: stop.color, offset: Math.max(0, Math.min(1, offset))};
    });
    return {stops: filled, angle: 90};
  }
  function svgFill(el, cs) {
    const raw = cs.fill || '';
    if (raw && raw.indexOf('url(') >= 0) {
      const id = urlOf(raw).replace('#', '');
      const owner = el.ownerSVGElement || document;
      const gradient = owner.getElementById ? owner.getElementById(id) : document.getElementById(id);
      return {gradient: svgGradient(gradient), color: null};
    }
    return {gradient: null, color: raw};
  }
  function collectSvg(svg, opacity) {
    const svgItems = [];
    const walk = (el) => {
      const tag = el.tagName.toLowerCase();
      if (['defs', 'clippath', 'mask', 'lineargradient', 'radialgradient',
           'filter', 'style', 'title', 'desc', 'metadata', 'pattern'].indexOf(tag) >= 0) return;
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') return;
      const elOpacity = opacity * opacityOf(cs);
      if (elOpacity <= 0.01) return;
      const ctm = el.getScreenCTM && el.getScreenCTM();
      if (tag === 'g' || tag === 'svg') {
        for (const child of el.children) walk(child);
        return;
      }
      if (tag === 'text') {
        const hasElementChildren = Array.from(el.children).some((c) =>
          ['tspan', 'textpath'].indexOf(c.tagName.toLowerCase()) >= 0);
        if (hasElementChildren) {
          for (const child of el.children) walk(child);
          if (!el.children.length) { /* fall through */ } else return;
        }
      }
      if (tag === 'tspan' || tag === 'text') {
        const bbox = el.getBoundingClientRect();
        const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
        if (!text || bbox.width < 0.5 || bbox.height < 0.5) return;
        const scale = ctm ? svgScale(ctm) : 1;
        const anchor = (el.getAttribute('text-anchor') || cs.textAnchor || 'start').toLowerCase();
        const fill = svgFill(el, cs);
        svgItems.push({
          type: 'svg-text', text: text,
          x: r2(bbox.left - base.left), y: r2(bbox.top - base.top),
          w: r2(bbox.width), h: r2(bbox.height),
          size: num(cs.fontSize) * scale,
          weight: parseInt(cs.fontWeight, 10) || 400,
          italic: cs.fontStyle === 'italic',
          color: fill.color,
          gradient: fill.gradient,
          anchor: anchor,
          direction: cs.direction,
          opacity: elOpacity
        });
        return;
      }
      if (tag === 'rect') {
        const bbox = el.getBoundingClientRect();
        const fill = svgFill(el, cs);
        svgItems.push({
          type: 'svg-rect', x: r2(bbox.left - base.left), y: r2(bbox.top - base.top),
          w: r2(bbox.width), h: r2(bbox.height),
          radius: num(el.getAttribute('rx') || el.getAttribute('ry') || 0) * (ctm ? svgScale(ctm) : 1),
          fill: fill.color, gradient: fill.gradient,
          stroke: cs.stroke, stroke_width: num(cs.strokeWidth) * (ctm ? svgScale(ctm) : 1),
          dash: cs.strokeDasharray, opacity: elOpacity
        });
        return;
      }
      if (tag === 'line') {
        if (!ctm) return;
        const p1 = svgPoint(ctm, num(el.getAttribute('x1')), num(el.getAttribute('y1')));
        const p2 = svgPoint(ctm, num(el.getAttribute('x2')), num(el.getAttribute('y2')));
        svgItems.push({
          type: 'svg-line',
          x1: r2(p1.x - base.left), y1: r2(p1.y - base.top),
          x2: r2(p2.x - base.left), y2: r2(p2.y - base.top),
          stroke: cs.stroke, stroke_width: num(cs.strokeWidth) * svgScale(ctm),
          dash: cs.strokeDasharray, opacity: elOpacity
        });
        return;
      }
      if (tag === 'circle' || tag === 'ellipse') {
        const bbox = el.getBoundingClientRect();
        const fill = svgFill(el, cs);
        svgItems.push({
          type: 'svg-ellipse',
          x: r2(bbox.left - base.left), y: r2(bbox.top - base.top),
          w: r2(bbox.width), h: r2(bbox.height),
          fill: fill.color, gradient: fill.gradient,
          stroke: cs.stroke, stroke_width: num(cs.strokeWidth) * (ctm ? svgScale(ctm) : 1),
          dash: cs.strokeDasharray, opacity: elOpacity
        });
        return;
      }
      if (tag === 'polyline' || tag === 'polygon') {
        if (!ctm) return;
        const raw = (el.getAttribute('points') || '').trim();
        const nums = raw.split(/[\s,]+/).map(parseFloat).filter((v) => isFinite(v));
        const points = [];
        for (let i = 0; i + 1 < nums.length; i += 2) {
          const p = svgPoint(ctm, nums[i], nums[i + 1]);
          points.push([r2(p.x - base.left), r2(p.y - base.top)]);
        }
        if (points.length < 2) return;
        const fill = svgFill(el, cs);
        svgItems.push({
          type: 'svg-polyline', points: points, closed: tag === 'polygon',
          fill: fill.color, stroke: cs.stroke,
          stroke_width: num(cs.strokeWidth) * svgScale(ctm),
          dash: cs.strokeDasharray, opacity: elOpacity
        });
        return;
      }
      if (tag === 'path') {
        if (!ctm) return;
        const fill = svgFill(el, cs);
        const hasFill = fill.color && fill.color !== 'none' && fill.color !== 'transparent';
        if (hasFill) { rasterReason = 'filled-svg-path'; return; }
        let length = 0;
        try { length = el.getTotalLength(); } catch (error) { return; }
        if (!length) return;
        const step = Math.max(1.5, length / 400);
        const points = [];
        for (let d = 0; d <= length; d += step) {
          const p = el.getPointAtLength(d);
          const q = svgPoint(ctm, p.x, p.y);
          points.push([r2(q.x - base.left), r2(q.y - base.top)]);
        }
        if (points.length < 2) return;
        svgItems.push({
          type: 'svg-polyline', points: points, closed: false,
          fill: null, stroke: cs.stroke,
          stroke_width: num(cs.strokeWidth) * svgScale(ctm),
          dash: cs.strokeDasharray, opacity: elOpacity
        });
        return;
      }
      // Unknown SVG element: walk children so nothing silently disappears.
      for (const child of el.children) walk(child);
    };
    walk(svg);
    return svgItems;
  }

  function walk(el, inheritedOpacity) {
    if (!el || el.nodeType !== 1 || rasterReason) return;
    const tag = el.tagName.toLowerCase();
    if (['script', 'style', 'link', 'meta', 'noscript', 'template',
         'head', 'title'].indexOf(tag) >= 0) return;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    const opacity = inheritedOpacity * opacityOf(cs);
    if (opacity <= 0.01) return;
    const reason = unsupportedReason(el, cs);
    if (reason) { warnings.push(reason); rasterReason = reason; return; }
    if (tag === 'table') { items.push(collectTable(el, opacity)); return; }
    if (tag === 'svg') {
      const box = collectBox(el, cs, opacity);
      if (box && (box.fill !== 'rgba(0, 0, 0, 0)' || box.borders.length)) items.push(box);
      const svgItems = collectSvg(el, opacity) || [];
      for (const item of svgItems) items.push(item);
      return;
    }
    const box = collectBox(el, cs, opacity);
    if (box) items.push(box);
    collectBackgroundImages(el, cs, opacity);
    if (tag === 'img') {
      const image = collectImage(el, cs, opacity);
      if (image) items.push(image);
      return;
    }
    for (const node of el.childNodes) {
      if (node.nodeType === 3) collectTextNode(node, el, cs, opacity);
      else if (node.nodeType === 1) walk(node, opacity);
    }
  }

  walk(SLIDE, 1);
  if (rasterReason) {
    return {items: [], warnings: warnings, raster: rasterReason};
  }
  return {items: items, warnings: warnings, raster: ''};
}
"""
