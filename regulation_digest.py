# -*- coding: utf-8 -*-
"""Deterministic Jeddah building-regulation digest.

Loads the verified knowledge base in ``rules/`` (built from اشتراطات1.pdf and
اشتراطات2.pdf) and selects the regulation block that applies to a parcel from
``site_facts`` — zoning code, area, street type — without sending the source
PDFs through a model again.

Two products come out of ``build_regulation_digest``:

* ``fields`` — numeric values safe to write into the analysis output
  (setbacks, coverage, FAR, floors, parking).  Values that carry a documented
  conflict in the source documents are intentionally left out so nothing
  unverified is force-filled.
* ``text`` — a compact Arabic block injected into the final analysis prompt so
  the model narrates from the same verified numbers instead of re-reading
  hundreds of pages.
"""
import json
import os
import re

_RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rules')
_CACHE = {}

_AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')


def _load(name):
    if name not in _CACHE:
        with open(os.path.join(_RULES_DIR, name), encoding='utf-8') as fh:
            _CACHE[name] = json.load(fh)
    return _CACHE[name]


def _num(value):
    if value is None:
        return None
    text = str(value).translate(_AR_DIGITS)
    match = re.search(r'(\d+(?:[.,]\d+)?)', text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(',', '.'))
    except ValueError:
        return None


def normalize_zoning_code(code):
    """Normalize a zoning code from a croquis to a lookup key."""
    if not code:
        return ''
    text = str(code).translate(_AR_DIGITS)
    text = re.sub(r'\s+', ' ', text).strip()
    lookup = _load('index.json')['lookup']
    for key in sorted(lookup, key=len, reverse=True):
        norm_key = re.sub(r'\s+', ' ', key.translate(_AR_DIGITS)).strip()
        if text == norm_key:
            return key
    # Prefix match for codes like "ت ح" vs "ت ح1" or extra annotations.
    for key in sorted(lookup, key=len, reverse=True):
        norm_key = re.sub(r'\s+', ' ', key.translate(_AR_DIGITS)).strip()
        if text.startswith(norm_key) or norm_key.startswith(text):
            return key
    return ''


def _area_band_contains(band, area):
    """Does ``area`` fall inside a band string like '400-600', '5000+', '<400'?"""
    if area is None or band in (None, 'all', 'any', 'جميع المساحات'):
        return band in ('all', 'any', 'جميع المساحات')
    band = str(band).translate(_AR_DIGITS).replace(' ', '')
    if band.startswith('<'):
        return area < _num(band[1:])
    if band.endswith('+'):
        return area >= _num(band[:-1])
    if '-' in band:
        lo, hi = band.split('-', 1)
        return _num(lo) <= area < _num(hi)
    return False


def _street_band_matches(row_width, width):
    if row_width in (None, 'any', 'all'):
        return True
    if width is None:
        return False
    w = str(row_width).translate(_AR_DIGITS)
    if w.startswith('<'):
        return width < _num(w[1:])
    if w.endswith('m+'):
        return width >= _num(w[:-2])
    if '-' in w:
        lo, hi = w.replace('m', '').split('-', 1)
        return _num(lo) <= width < _num(hi)
    return False


def _select_row(rows, area, street_width=None):
    """Pick the building-table row matching area (and street width when present)."""
    candidates = [
        row for row in rows
        if _area_band_contains(row.get('area_m2') or row.get('area'), area)
        and _street_band_matches(row.get('street_width'), street_width)
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    if area is None:
        return None
    # Narrowest matching band wins when several overlap.
    def band_width(row):
        band = str(row.get('area_m2') or row.get('area') or '').translate(_AR_DIGITS)
        if '-' in band:
            lo, hi = band.replace(' ', '').split('-', 1)
            return (_num(hi) or 0) - (_num(lo) or 0)
        return float('inf')
    return sorted(candidates, key=band_width)[0]


def _select_row_with_common(rows, area, street_width=None):
    """Like ``_select_row`` but when no single row wins, still returns the
    fields every matching row agrees on (e.g. ت ر١: coverage is 60% in all
    rows even when the street width is unknown)."""
    row = _select_row(rows, area, street_width)
    if row:
        return row, []
    loose = [
        r for r in rows
        if _area_band_contains(r.get('area_m2') or r.get('area'), area)
    ]
    if not loose:
        return None, []
    common = {}
    for key in ('coverage', 'far', 'floors', 'max_floors', 'max_height_m'):
        values = [r.get(key) for r in loose]
        if all(v is not None for v in values) and len(set(values)) == 1:
            common[key] = values[0]
    return common or None, loose


def _zone_text(zone_key, zone, row, extras):
    """Render the applicable rules as a compact Arabic block for the prompt."""
    lines = [f'كود المنطقة: {zone_key} — {zone.get("name", "")}']
    if zone.get('uses'):
        lines.append('الاستعمالات: ' + '، '.join(zone['uses']))
    if row:
        if row.get('coverage') is not None:
            lines.append(f"نسبة البناء: {row['coverage']}%")
        if row.get('floors') is not None:
            lines.append(f"عدد الطوابق: {row['floors']}")
        if row.get('far') is not None:
            lines.append(f"معامل مسطح البناء: {row['far']}")
        if row.get('max_floors') is not None:
            lines.append(f"أقصى عدد للطوابق: {row['max_floors']}")
        if row.get('max_height_m') is not None:
            lines.append(f"أقصى ارتفاع: {row['max_height_m']}م")
    for line in extras:
        lines.append(line)
    return '\n'.join(lines)


def _fmt_setbacks(sb, zone_kind):
    parts = [f'ارتداد أمامي على الشارع الرئيسي ≥{sb["front_main_street_m"]["ground"]}م']
    if sb['front_main_street_m'].get('with_parking_inside'):
        parts.append(f'و≥{sb["front_main_street_m"]["with_parking_inside"]}م عند توفير المواقف داخل الارتداد')
    if sb['front_main_street_m'].get('with_parking_in_setback'):
        parts.append('ومواقف السيارات ضمن الارتداد الأمامي بعمق ≥5.5م')
    parts.append(f'شوارع جانبية ≥{sb["side_streets_m"]}م')
    parts.append(f'ممرات مشاة ≥{sb["pedestrian_paths_m"]}م')
    neighbor = sb.get('neighbor_m') or {}
    if 'normal' in neighbor:
        parts.append(f'جار ≥{neighbor["normal"]}م' + (f' و{neighbor["with_balconies"]}م عند الشرفات' if neighbor.get('with_balconies') else ''))
    elif '≤5_floors' in neighbor:
        parts.append('جار حسب الارتفاع: ≤٥ طوابق ٢م، ٦-٨ طوابق ٣م، ٩-١٢ طابق ٤م، وأكثر حسب دليل المباني العالية')
    return '؛ '.join(parts)


def build_regulation_digest(site_facts):
    """Select the applicable regulation block from verified rules JSON.

    Returns a dict::

        {
          'matched': bool,
          'zone_key': str,
          'special_plan_required': bool,
          'fields': {'setbacks': str, 'coverage_ratio': str, ...},   # safe to force-fill
          'text': str,       # Arabic block for the analysis prompt
          'conflicts': [..],
          'sources': [..],
          'notes': [..],
        }
    """
    site_facts = site_facts or {}
    digest = {
        'matched': False, 'zone_key': '', 'special_plan_required': False,
        'fields': {}, 'text': '', 'conflicts': [], 'sources': [], 'notes': [],
    }
    zones = _load('zones.json')['zones']
    general = _load('general.json')

    code = normalize_zoning_code(site_facts.get('zoning_code'))
    if not code:
        digest['notes'].append('لم يُتعرف على كود التنظيم من حقائق الموقع')
        return digest
    zone_key = _load('index.json')['lookup'].get(code, {}).get('zone')
    zone = zones.get(zone_key or '')
    if not zone:
        digest['notes'].append(f'كود التنظيم «{code}» لا يطابق أي منطقة موثقة')
        return digest
    digest['matched'] = True
    digest['zone_key'] = zone_key
    digest['special_plan_required'] = bool(zone.get('special_plan_required'))
    if zone.get('source'):
        digest['sources'].extend(zone['source'])

    area = _num(site_facts.get('area_sqm'))
    width = _num(site_facts.get('street_width_m'))
    building_type = str(site_facts.get('building_type') or site_facts.get('land_use') or '')
    extras, fields = [], {}

    if digest['special_plan_required']:
        extras.append('هذه المنطقة لها تنظيم خاص معتمد — لا تُطبق عليها الجداول العامة؛ يجب الرجوع للتنظيم المعتمد للمنطقة.')
        if zone.get('table'):
            extras.append('جدول المنطقة الخاصة (إن انطبق): ' + json.dumps(zone['table'], ensure_ascii=False))
        digest['text'] = _zone_text(zone_key, zone, None, extras)
        digest['text'] += '\n\nالقواعد العامة المشتركة تبقى نافذة ما لم يتعارض معها التنظيم الخاص.'
        return digest

    row, note_lines = None, []

    if zone_key == 'س ف':
        bs = zone['building_system']
        row = {'coverage': bs['coverage_ground_max']['value'], 'floors': bs['max_floors'], 'far': None}
        fields['setbacks'] = _fmt_setbacks(zone['setbacks'], 'فيلات')
        fields['coverage_ratio'] = '75% للدورين الأرضي والأول شاملاً الملاحق الأرضية'
        fields['building_ratio'] = 'طابقين + ملحق علوي ≤70% من مساحة الطابق الأسفل'
        fields['max_floors_height'] = 'أقصى ارتفاع للمبنى 15م'
        fields['parking_requirements'] = zone['parking']['rule_master_table']
        fields['allowed_uses'] = 'سكني فيلات'
        digest['conflicts'].append({'field': 'parking', 'detail': zone['parking']['conflict']})
        digest['conflicts'].append({'field': 'floor_height', 'detail': bs['floor_height_m']['conflict']})
        extras += [
            f"الارتدادات: {fields['setbacks']}",
            f"الملحق الأرضي: {bs['ground_annex']['value']}% من مساحة الأرض ضمن النسبة الكلية",
            'تعارض موثق في معدل مواقف الفيلات بين بند اللائحة (موقف/250م²) والجدول العام (موقفان ≤500م² +1/150م²) — يُعرض للمراجعة.',
        ]

    elif zone_key == 'س ع':
        bs = zone['building_system']
        row = {'coverage': bs['coverage_ground_max']['value'], 'floors': bs['max_floors'], 'far': None}
        fields['setbacks'] = _fmt_setbacks(zone['setbacks'], 'عمائر')
        fields['coverage_ratio'] = '65% للطابق الأرضي و75% للطوابق المتكررة'
        fields['building_ratio'] = '٤ طوابق سكنية + طابق مواقف + ملحق علوي ≤70%'
        fields['max_floors_height'] = 'حتى 23م لأربعة أدوار شاملاً دروة الملحق (شكل اللائحة يطبع 22م — تعارض موثق)'
        fields['parking_requirements'] = zone['parking']['rate']
        fields['allowed_uses'] = 'سكني عمائر'
        digest['conflicts'].append({'field': 'setback_parking_depth', 'detail': zone['setbacks']['front_main_street_m']['with_parking_in_setback']})
        extras += [
            f"الارتدادات: {fields['setbacks']}",
            'لا يسمح بالملاصقة مع الجار ولا بالبناء داخل الارتدادات.',
            'طابق مواقف واحد لا يحتسب من عدد الطوابق ولا من المعامل.',
        ]

    elif zone_key == 'س ف ع':
        is_villa = 'فيل' in building_type or 'فيلا' in building_type
        base = 'فيلات' if is_villa else 'عمائر'
        variant = zone['building_system'][base]
        row = {'coverage': 75 if is_villa else 65, 'floors': 'طابقين', 'far': None}
        ref = zones['س ف'] if is_villa else zones['س ع']
        fields['setbacks'] = _fmt_setbacks(ref['setbacks'], base)
        fields['coverage_ratio'] = ('75% للدورين' if is_villa else '65% أرضي / 75% متكرر')
        fields['building_ratio'] = f'طابقين بنظام {base}'
        fields['parking_requirements'] = ref['parking'].get('rate') or ref['parking'].get('rule_master_table', '')
        fields['allowed_uses'] = f'سكني {base} (طابقين)'
        extras += [
            f"يُطبق نظام {base} كاملاً بحد أقصى طابقين: {variant}",
            f"الارتدادات: {fields['setbacks']}",
        ]
        if not is_villa and 'فيل' not in building_type:
            extras.append('إن كان المبنى فيلا تُطبق نسب الفيلات (75%)، وإن كان عمارة تُطبق نسب العمائر (65%/75%).')

    elif zone_key in ('ت ح١', 'ت ح٢', 'ت ر١', 'ت ب', 'ت خ', 'حيازات صغيرة', 'بحر الطيب', 'شارع ٦٥م'):
        if zone_key == 'ت ر١':
            row, loose = _select_row_with_common(zone['building_table']['rows'], area, width)
            if loose and row and 'floors' not in row:
                note_lines.append('عرض الشارع غير معروف — نسبة البناء والمعامل العام محسومان، وعدد الطوابق يعتمد على عرض الشارع (راجع الجدول).')
        elif zone_key == 'ت ب':
            bs = zone['building_system']
            row = {'coverage': bs['coverage'], 'floors': bs['floors'], 'far': bs['far']}
            fields['max_floors_height'] = f"{bs['floors']} طابق، أرضي ≤{bs['coverage_ground_max']}% وأول ≤{bs['coverage_first_max']}%"
            fields['parking_requirements'] = 'حسب معدل الاستخدام (جدول المواقف العام)'
        elif zone_key == 'ت خ':
            plan = str(site_facts.get('plan_type') or building_type)
            rows = zone['building_table']['rows']
            row = _select_row(rows, None) if not plan else next(
                (r for r in rows if ('عمائر' in r['plan_type'] and 'عمائر' in plan)
                 or ('فيلات' in r['plan_type'] and 'فيل' in plan)
                 or ('صناعية' in r['plan_type'] and 'صناع' in plan)), None)
            if row:
                fields['max_floors_height'] = f"{row['floors']} طوابق بحد أقصى {row['max_height_m']}م"
        elif zone_key == 'حيازات صغيرة':
            row = _select_row(zone['tiers'], area)
        elif zone_key in ('بحر الطيب', 'شارع ٦٥م'):
            table = zone.get('table') or zone.get('table_service_street')
            row = _select_row(table, area) if table else None
        else:  # ت ح١ / ت ح٢
            row = _select_row(zone['building_table']['rows'], area)
            if row and zone_key == 'ت ح١':
                note_lines.append('سقوف الارتفاع: ٦٠٠–١٠٠٠م² حد ١٠ طوابق؛ ١٠٠٠–٣٠٠٠م² حد ١٢ طابق؛ ٣٠٠٠م²+ بلا حد مع دليل المباني العالية.')

        if row:
            if row.get('coverage') is not None:
                fields['coverage_ratio'] = f"{row['coverage']}%"
            if row.get('far') is not None:
                fields['floor_area_ratio'] = str(row['far'])
            if row.get('floors') is not None:
                fields['building_ratio'] = f"{row['floors']} طوابق بنسبة {row.get('coverage', '—')}% ومعامل {row.get('far', '—')}"
                fields['table_floors'] = str(row['floors'])
            if row.get('max_floors') is not None:
                fields['max_floors_height'] = f"أقصى {row['max_floors']} طوابق"
        else:
            note_lines.append('تعذر اختيار شريحة المساحة/عرض الشارع — أدرج الجدول كاملاً للمراجعة.')
            extras.append('جدول المنطقة كاملاً: ' + json.dumps(
                (zone.get('building_table') or {}).get('rows') or zone.get('table') or zone.get('tiers') or [],
                ensure_ascii=False))

        if zone.get('commercial_depth_m'):
            extras.append(f"العمق التجاري لهذا التصنيف: {zone['commercial_depth_m']}م من حد الشارع.")
        sb = general['setbacks_general']['street_setbacks'].get('تجاري متنوع')
        if sb:
            fields['setbacks'] = (
                f"ارتداد أمامي ≥{sb['main_street_m']}م كحد بناء (و{sb['with_parking_m']}م عند توفير المواقف داخله)؛ "
                f"باقي الشوارع ≥{sb['other_streets_m']}م؛ "
                'جار حسب الارتفاع: ≤٥ طوابق ٢م، ٦-٨ ٣م، ٩-١٢ ٤م، وأكثر بدليل المباني العالية')
            extras.append(f"الارتدادات: {fields['setbacks']}")
        fields['parking_requirements'] = fields.get('parking_requirements') or 'موقف/25م² للمحلات والمعارض على المحاور والشوارع التجارية؛ مكاتب إدارية جديدة موقف/25م²'
        fields['allowed_uses'] = '، '.join(zone.get('uses') or [])

    elif zone_key in ('ص١', 'ص٢', 'ص٣'):
        extras.append(f"الفصل عن المناطق الأخرى: {json.dumps(zone.get('separation') or zone.get('rules'), ensure_ascii=False)}")
        if zone_key == 'ص١':
            use = 'ورش' if 'ورش' in building_type else 'مستودعات'
            if use == 'مستودعات':
                wh = zone['warehouses']
                row = _select_row(wh['table_24'], area)
                extras.append(f"مستودعات: حد أدنى للمساحة {json.dumps(wh['min_area_m2'], ensure_ascii=False)}؛ مبنى خدمات ≤{wh['service_building']}")
            else:
                wk = zone['workshops']
                row = _select_row(wk['table_27'], area)
                extras.append(f"ورش: تغطية ≤{wk['max_coverage']}%؛ ارتدادات {json.dumps(wk['setbacks'], ensure_ascii=False)}")
        fields['allowed_uses'] = '، '.join(zone.get('uses') or [])

    elif zone_key in ('سكن جماعي', 'خ٣', 'ق', 'ت م', 'م م'):
        if zone_key == 'خ٣':
            bs = zone['building_system']
            row = bs.get('سكنية_عمارات') if 'عمائر' in building_type else bs.get('سكنية_فيلات')
        elif zone_key == 'م م':
            fields['floor_area_ratio'] = 'حسب موقع المشروع: محاور رئيسة 7.0، ثانوية 6.0، شوارع رئيسة 5.0، محلية عمائر 4.2، محلية فيلات 3.6'
            digest['conflicts'].append({'field': 'far_marine', 'detail': zone['far_table']['بحرية']['conflict']})
            extras.append('مساحات الحد الأدنى حسب المنطقة: ' + json.dumps(zone['area_thresholds'], ensure_ascii=False))
        elif zone_key == 'سكن جماعي':
            extras.append('مواقع السكن الجماعي: ' + '؛ '.join(zone['site_rules']))
            fields['parking_requirements'] = zone['parking']
        elif zone_key == 'ق':
            extras.append('شروط الموقع: ' + '؛ '.join(zone['site_rules']))
            extras.append('نظام البناء: ' + zone['building_system'])
        else:
            extras.append('قواعد المنطقة المركزية: ' + json.dumps(zone['rules'], ensure_ascii=False))
        fields['allowed_uses'] = '، '.join(zone.get('uses') or [])

    else:
        extras.append('لا يوجد جدول رقمي معياري لهذا الكود — راجع تفاصيل المنطقة في المصدر.')
        fields['allowed_uses'] = '، '.join(zone.get('uses') or [])

    # Small-holdings override: <400م² parcels in >2-floor zones take the tiers.
    if area is not None and area < 400 and zone_key not in ('س ف', 'حيازات صغيرة', 'بحر الطيب', 'ت ب'):
        tiers = zones['حيازات صغيرة']['tiers']
        tier = _select_row(tiers, area)
        if tier and tier.get('floors'):
            fields['coverage_ratio'] = f"{tier['coverage']}%"
            fields['floor_area_ratio'] = str(tier['far'])
            fields['building_ratio'] = f"{tier['floors']} طوابق بنظام الحيازات الصغيرة"
            fields['max_floors_height'] = f"أقصى {tier['floors']} طوابق (نظام الحيازات الصغيرة)"
            fields['table_floors'] = str(tier['floors'])
            extras.append(f"مساحة <٤٠٠م²: يُطبق نظام الحيازات الصغيرة — {tier['floors']} طوابق، {tier['coverage']}%، معامل {tier['far']}.")

    digest['fields'] = {k: v for k, v in fields.items() if v not in (None, '', [])}
    digest['text'] = _zone_text(zone_key, zone, row, extras + note_lines)
    if general.get('conflicts'):
        relevant = [c['topic'] for c in general['conflicts']]
        digest['text'] += '\n\nتعارضات موثقة بين اللائحة والوثيقة تخص هذه المنطقة قد تظهر في الحقول: ' + '؛ '.join(relevant[:4])
    return digest


def digest_prompt_block(digest):
    """The text injected into the final analysis prompt."""
    if not digest.get('matched'):
        return ''
    lines = [
        'قواعد الاشتراطات الموثقة المطبقة على هذه القطعة (من قاعدة بيانات الأنظمة المتحقق منها — المصدر الوحيد للقيم الرقمية):',
        digest['text'],
    ]
    if digest.get('special_plan_required'):
        lines.append('تنبيه إلزامي: هذه المنطقة ذات تنظيم خاص؛ لا تطبق الجداول العامة واذكر الحاجة للتنظيم المعتمد.')
    if digest.get('conflicts'):
        lines.append('تعارضات موثقة يجب إظهارها للمستخدم ولا تُحسم من عندك: '
                     + json.dumps(digest['conflicts'], ensure_ascii=False))
    lines.append('استخدم هذه القيم حرفياً في الحقول الرقمية (نسبة البناء، المعامل، الطوابق، الارتدادات، المواقف) ولا تستبدلها بقيم أخرى.')
    return '\n'.join(lines)
