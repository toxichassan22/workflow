def _visual_concept_plan_model(context, regulations):
    """One derived concept distribution shared by all three plan prompts —
    bands in fixed stack order, tower on the uncapped sector, low block on the
    floor-capped sector, parking below grade, service on the roof."""
    components = [item for item in context.get('components') or []
                  if isinstance(item, dict) and item.get('name')]
    if not components:
        return None
    below, roof, bands, open_uses = [], [], [], []
    for index, item in enumerate(components):
        order, category = _visual_concept_plan_use_category(item)
        entry = (order, index, item, category)
        pool = financial_parking.parking_area_pool(item)
        if category == 'parking' and (pool == 'basement' or not item.get('parkingLocation')):
            below.append(entry)
        elif category == 'service':
            roof.append(entry)
        elif category == 'landscape' or category == 'parking' and pool == 'surface':
            open_uses.append(entry)
        else:
            bands.append(entry)
    bands.sort(key=lambda row: (row[0], row[1]))

    groups = []
    for _order, _index, item, category in bands:
        if groups and groups[-1][0] == category:
            groups[-1][1].append(item)
        else:
            groups.append((category, [item]))

    hints = _visual_concept_plan_sector_hints(regulations)
    capped = [hint for hint in hints if hint.get('cap')]
    low_sector = min(capped, key=lambda hint: hint['cap']) if capped else None
    # The high-rise axis is the sector recorded with no height cap; a sector that
    # simply has no cap recorded still outranks the floor-capped low block.
    explicit_open = [hint for hint in hints
                     if hint.get('uncapped') and hint is not low_sector]
    open_hints = [hint for hint in hints
                  if not hint.get('cap') and hint is not low_sector]
    high_sector = (explicit_open or open_hints or [None])[0]

    street_dirs, _other_dirs, sea_dir = _visual_concept_plan_direction_scan(context)

    floor_count = _visual_concept_number(context.get('floor_count'))
    floor_count = int(floor_count) if floor_count else 0
    floors, ranges = [], []
    if floor_count and groups:
        areas = []
        for _category, items in groups:
            area = 0.0
            for part in items:
                area += (_visual_concept_number(part.get('builtArea'))
                         or _visual_concept_number(part.get('unitArea')) or 0.0)
            areas.append(area)
        total_area = sum(areas) or 1.0
        raw = [area / total_area * floor_count for area in areas]
        floors = [max(1, int(value)) for value in raw]
        remainder = floor_count - sum(floors)
        order = sorted(range(len(groups)), key=lambda i: raw[i] - int(raw[i]), reverse=True)
        index = 0
        while remainder > 0 and order:
            floors[order[index % len(order)]] += 1
            remainder -= 1
            index += 1
        while remainder < 0 and any(count > 1 for count in floors):
            for i in sorted(range(len(groups)), key=lambda i: floors[i], reverse=True):
                if remainder >= 0:
                    break
                if floors[i] > 1:
                    floors[i] -= 1
                    remainder += 1
        start = 1
        for count in floors:
            end = start + count - 1
            lo = 'G' if start == 1 else str(start)
            ranges.append(f'{lo}-{end}' if end > start else lo)
            start = end + 1

    bands_out = []
    for position, (category, items) in enumerate(groups):
        label = _VISUAL_PLAN_USE_LABEL.get(category, 'Amenities')
        if position > 0 and len(items) == 1:
            # A band label becomes callout text in the drawing, so it must stay
            # English: a recorded Arabic name the lexicon cannot map falls back to
            # the use category label — the name itself still reaches the prompt as
            # data inside the component brief.
            name = _visual_concept_plan_component_en(
                _visual_concept_plan_sanitize_text(items[0].get('name')))
            if name and not re.search(r'[\u0600-\u06FF]', name):
                label = name
        bands_out.append({
            'category': category,
            'label': label,
            'items': items,
            'floors': floors[position] if position < len(floors) else 0,
            'range': ranges[position] if position < len(ranges) else '',
            'color': _visual_concept_plan_use_color(
                context, _VISUAL_PLAN_USE_LABEL.get(category, 'Amenities')),
        })

    main_dir, res_dir, svc_dir = _visual_concept_plan_entry_dirs(street_dirs, sea_dir, high_sector)
    has_residential = any(band['category'] == 'residential' for band in bands_out)
    block_label = (f"{low_sector['direction'].title()} Block"
                   if low_sector and low_sector.get('direction') else 'Low Block')
    blocks = []
    if low_sector:
        blocks.append({
            'label': block_label,
            'cap': low_sector.get('cap') or 0,
            'direction': low_sector.get('direction') or '',
            'use': 'Residential' if has_residential else 'Low-rise',
            'color': _visual_concept_plan_use_color(context, 'Residential') or 'soft-blue',
            'bands': [],
        })
    return {
        'bands': bands_out,
        'below': below,
        'roof': roof,
        'open_uses': open_uses,
        'high_sector': high_sector,
        'low_sector': low_sector,
        'blocks': blocks,
        'floor_count': floor_count,
        'main_dir': main_dir,
        'res_dir': res_dir,
        'svc_dir': svc_dir,
        'sea_dir': sea_dir,
        'has_residential': has_residential,
        'block_label': block_label,
    }


def _visual_concept_plan_distribution_spec(context, model, regulations):
    """The shared APPROVED DISTRIBUTION MODEL block — same shape the bench used."""
    name = _visual_concept_text(context.get('project_name'), 160) or 'the project'
    place = _visual_concept_plan_place_en(context)
    lines = [f"- Project: '{name}'" + (f' — {place}.' if place else '.')]

    points = context.get('boundary_points') or []
    parcel = (f'an irregular {len(points)}-vertex plot' if len(points) >= 3 else 'a plot')
    area = _visual_concept_plan_sanitize_text(context.get('land_area')
                                              or regulations.get('croquis_land_area'))
    if area:
        parcel += f' (~{area} m²)'
    lines.append(f'- Parcel: {parcel}. Where an outline reference image is attached it is the '
                 'TRUE surveyed parcel outline — trace it exactly, same vertices and '
                 'proportions. North is up.')

    edge_bits, neighbor_dirs = [], []
    sea_dir = model['sea_dir'] if model else ''
    for item in context.get('directions') or []:
        text = _visual_concept_plan_sanitize_text(item.get('regulation_text'))
        key = _visual_concept_plan_direction_key(item.get('direction'))
        if not text or not key:
            continue
        if re.search(r'neighbor|adjacent|propert|مجاور|جار', text, flags=re.IGNORECASE):
            neighbor_dirs.append(key)
            continue
        bit = f'{key} edge faces {_visual_concept_plan_edge_english(text)}'
        if key == sea_dir:
            bit += ' — this is the sea-frontage side'
        edge_bits.append(bit)
    if sea_dir:
        edge_bits.sort(key=lambda bit: 0 if bit.startswith(sea_dir + ' edge') else 1)
    if neighbor_dirs:
        edge_bits.append(' and '.join(neighbor_dirs) + ' edges touch neighboring plots')
    if edge_bits:
        lines.append('- Edges: ' + '; '.join(edge_bits) + '.')

    if model and model['high_sector'] and model['low_sector']:
        lines.append(
            f"- Two zoning zones: the {model['high_sector']['direction'].upper()} part is a "
            f"high-rise axis — the tall tower stands there; the "
            f"{model['low_sector']['direction'].upper()} part is low-rise, "
            f"max {model['low_sector']['cap']} floors.")

    setbacks = _visual_concept_plan_setback_en(_visual_concept_plan_sanitize_text(
        context.get('setbacks') or regulations.get('setbacks')
        or regulations.get('building_ratio_setbacks')))
    if setbacks:
        lines.append(f'- Setback envelope: {setbacks} — shown as a dashed inner line.')

    if model:
        tower_dir = model['high_sector']['direction'] if model['high_sector'] else ''
        if model.get('from_distribution'):
            tower = 'a mixed-use building'
        else:
            tower = (f"a {model['floor_count']}-storey mixed-use tower"
                     if model['floor_count'] else 'a mixed-use tower')
        if tower_dir:
            tower += f' on the {tower_dir} part'
        band_phrases = []
        last = len(model['bands']) - 1
        for position, band in enumerate(model['bands']):
            if len(band['items']) == 1 and position > 0:
                item = band['items'][0]
                bits = []
                if item.get('units') not in (None, ''):
                    units = str(item['units']).strip()
                    bits.append(f"{units} {'unit' if units in ('1', '1.0') else 'units'}")
                area = item.get('builtArea') or item.get('unitArea')
                if area not in (None, ''):
                    bits.append(f'{area} m²')
                briefs = '; '.join(bits)
            else:
                briefs = '; '.join(_visual_concept_plan_component_brief(i)
                                   for i in band['items'])
            article = 'an' if band['label'][:1].lower() in 'aeiou' else 'a'
            if position == 0:
                storey = f"{band['floors']}-storey " if band['floors'] else ''
                if model.get('from_distribution'):
                    noun = 'ground band'
                else:
                    noun = ('podium base' if len(model['bands']) > 1
                            and (band['floors'] or 0) <= 8 else 'base')
                phrase = f"{article} {storey}{band['label']} {noun}"
            elif position == last:
                phrase = f"{article} {band['label']} top band"
            else:
                phrase = f"{article} {band['label']} band"
            band_phrases.append(phrase + (f' ({briefs})' if briefs else ''))
        if band_phrases:
            tower += ' — ' + ', '.join(band_phrases[:-1]) + (
                f', and {band_phrases[-1]}' if len(band_phrases) > 1 else band_phrases[0])
        masses = [f'(1) {tower}']
        for index, block in enumerate(model.get('blocks') or [], 2):
            cap_text = f"{block['cap']}-storey " if block.get('cap') else 'low-rise '
            on_part = f" on the {block['direction']} part" if block.get('direction') else ''
            masses.append(f"({index}) a {cap_text}{block.get('use') or 'mixed-use'} "
                          f"'{block['label']}'{on_part}")
        if model.get('below'):
            masses.append(f"({len(masses) + 1}) {_financial_parking_basement_levels(model)}-level basement parking across the parcel — "
                          'drawn only in the floor-distribution stack')
        lines.append('- Approved masses: ' + '; '.join(masses) + '.')
        open_bits = []
        if model['sea_dir']:
            open_bits.append(f"along the {model['sea_dir']} edge")
        block_labels = [block['label'] for block in model.get('blocks') or [] if block.get('label')]
        if block_labels:
            open_bits.append('around ' + ', '.join(f"the '{label}'" for label in block_labels))
        lines.append('- Open areas: landscaping '
                     + (' and '.join(open_bits) if open_bits
                        else 'on the remaining open ground inside the setback envelope') + '.')
        entries = []
        if model['main_dir']:
            entries.append(f"main lobby entry on the {model['main_dir']} side")
        if model['res_dir'] and model['svc_dir'] and model['svc_dir'] != model['res_dir']:
            entries.append(f"residential entry on the {model['res_dir']} street")
            entries.append(f"service entry on the {model['svc_dir']} street")
        elif model['res_dir']:
            entries.append(f"residential and service entries on the {model['res_dir']} street")
        elif model['main_dir']:
            entries.append('residential and service entries beside the main lobby entry')
        if entries:
            lines.append('- Entries: ' + '; '.join(entries) + '.')
    else:
        lines.append('- No approved building masses are recorded; keep the parcel a neutral '
                     'regulated-development field.')

    parking_brief = _financial_parking_visual_brief(context)
    if parking_brief:
        lines.append(parking_brief)
    colors = '; '.join(f"{item['use']} = {item['color']}"
                       for item in context.get('colors') or [] if item.get('use'))
    if colors:
        lines.append(f'- FIXED color code, identical in every drawing: {colors}.')
    lines.append('- All text in the image English only. Bottom-right caption: '
                 "'ILLUSTRATIVE REFERENCE - NOT TO SCALE'.")
    return 'APPROVED DISTRIBUTION MODEL — render exactly this, invent nothing:\n' + '\n'.join(lines)


def _visual_concept_plan_site_body(context, model, regulations):
    parts = [
        "DRAWING REQUESTED — 'CONCEPTUAL SITE PLAN': a simplified flat 2D site plan, top-down "
        'orthographic view on a white background, same pastel style and fixed color code. The '
        'attached reference image is the TRUE surveyed parcel outline — trace it exactly, same '
        'vertices and proportions, as a dark navy outline. Inside it draw the dashed setback '
        'envelope, then the approved footprints: ']
    if model:
        high_dir = model['high_sector']['direction'] if model['high_sector'] else ''
        podium_color = model['bands'][0]['color'] if model['bands'] else 'soft-teal'
        crown_color = (model['bands'][-1]['color'] if model['bands'] else '') or 'soft-blue'
        # Same podium heuristic the spec uses: a short first band under a taller
        # stack is a podium base; otherwise the tower sits on the ground directly.
        # An approved-distribution model names no podium — its bands are floors.
        has_podium = (not model.get('from_distribution')
                      and len(model['bands']) > 1 and (model['bands'][0]['floors'] or 0) <= 8)
        building_name = next((str(item.get('building') or '')
                              for band in model['bands'] for item in band.get('items') or []
                              if item.get('building')), '')
        mass_label = _visual_concept_plan_building_en(building_name)
        if model.get('from_distribution'):
            footprints = [f"the building zone" + (f' on the {high_dir} part' if high_dir else '')
                          + f" ({(podium_color + ' ') if podium_color else ''}footprint "
                            f"labeled '{mass_label}')"]
        elif has_podium:
            footprints = [f"the podium+tower zone" + (f' on the {high_dir} part' if high_dir else '')
                          + f' ({podium_color} podium footprint with a smaller {crown_color} tower '
                            "footprint inside it labeled 'Tower')"]
        else:
            footprints = [f"the tower zone" + (f' on the {high_dir} part' if high_dir else '')
                          + f" ({crown_color} tower footprint labeled 'Tower')"]
        for block in model.get('blocks') or []:
            cap_text = f"{block['cap']}-storey " if block.get('cap') else ''
            on_part = f" on the {block['direction']} part" if block.get('direction') else ''
            footprints.append(f"the {cap_text}{block.get('color') or 'muted'} "
                              f"'{block['label']}' footprint{on_part}")
        for component in context.get('components') or []:
            if component.get('parkingPlanId') and component.get('parkingLocation') == 'surface':
                footprints.append(f"a light-grey Surface Parking area of {component.get('builtArea')} m² for {component.get('units')} spaces including aisles")
        footprints.append('pale-green landscaping filling the rest')
        if model.get('below'):
            pocket_dir = model['svc_dir'] or model['res_dir']
            footprints.append('a light-grey service/parking pocket'
                              + (f' on the {pocket_dir} part' if pocket_dir else ''))
        parts.append(', '.join(footprints) + '. ')
        entries = []
        if model['main_dir']:
            entries.append(f"'Main Entry' on the {model['main_dir']}")
        if model['res_dir']:
            entries.append(f"'Residential Entry' on the {model['res_dir']}")
        if model['svc_dir'] and model['svc_dir'] not in (model['main_dir'], model['res_dir']):
            entries.append(f"'Service Entry' on the {model['svc_dir']}")
        elif model['res_dir']:
            entries.append(f"'Service Entry' beside it")
        parts.append('Streets: label each recorded street and open-space strip on its edge with '
                     'its recorded name and width, each neighboring plot "Neighbor"'
                     + (', and a pale-cyan "Sea" band beyond the waterfront edge'
                        if model['sea_dir'] else '')
                     + '. Entry arrows: '
                     + ('; '.join(entries) if entries
                        else 'the recorded entries on their recorded edges')
                     + '. ')
    else:
        parts.append('keep the parcel a neutral regulated-development field — no approved '
                     'building masses are recorded, so draw no tower, podium, block, entry arrow, '
                     'or parking layout, and note "Approved building footprints not recorded." ')
    parts.append(
        'North arrow pointing up. Bottom-left legend with the fixed color chips plus "Parcel '
        'Boundary" and "Setback Envelope" line keys. Top-left title "CONCEPTUAL SITE PLAN". Flat '
        'cartographic style, muted colors, no photorealism, no satellite imagery. Only verified '
        'labels — no invented dimensions.')
    return ''.join(parts)


def _visual_concept_plan_uses_body(context, model, regulations):
    parts = [
        "DRAWING REQUESTED — 'VERTICAL PROGRAM DISTRIBUTION': a clean vertical stacked-floor "
        'diagram of the approved distribution on a white background, same pastel style and fixed '
        'color code. ']
    if model:
        stacks = []
        tower_bits = []
        below_count = _financial_parking_basement_levels(model)
        if below_count:
            tower_bits.append(f"{below_count} light-grey 'Basement Parking' level"
                              + ('s' if below_count > 1 else '')
                              + " below a dark navy 'Ground Level' line")
        else:
            tower_bits.append("a dark navy 'Ground Level' line at the base")
        for band in model['bands']:
            color = band['color'] or 'muted'
            count = band['floors']
            rng = _visual_concept_plan_floor_label_en(band['range'])
            if count and rng:
                tower_bits.append(f"{count} {color} '{band['label']} ({rng})' bands")
            else:
                tower_bits.append(f"{color} '{band['label']}' bands")
        if model['roof']:
            tower_bits.append("a thin grey 'Roof & Services' cap")
        if model.get('from_distribution'):
            tower_name = 'building'
        else:
            tower_name = (f"{model['floor_count']}-storey tower" if model['floor_count']
                          else 'mixed-use tower')
        stacks.append('Left stack — the ' + tower_name + ', bands bottom to top exactly: '
                      + ', '.join(tower_bits) + '.')
        for position, block in enumerate(model.get('blocks') or []):
            side = 'Right' if not position else f"Side stack {position + 1}"
            if block.get('bands'):
                block_bits = []
                for band in block['bands']:
                    band_text = (f"{band['floors']} {band['color'] or 'muted'} '{band['label']}"
                                 + (f" ({_visual_concept_plan_floor_label_en(band['range'])})'"
                                    if band.get('range') else "'")
                                 + ' bands')
                    block_bits.append(band_text)
                stacks.append(f"{side} stack — the '{block['label']}': "
                              + ', '.join(block_bits)
                              + ' above its own ground line.')
            else:
                cap = block.get('cap') or 0
                stacks.append(f"{side} stack — the {cap or 'low'}-storey '{block['label']}': "
                              f"{cap or 'several'} {block.get('color') or 'muted'} "
                              f"'{block.get('use') or block['label']} (G-{cap})' bands above the "
                              'same ground line'
                              + (' with its own light-grey parking band below' if below_count else '')
                              + '.')
        count_word = {1: 'ONE stack. ', 2: 'TWO stacks side by side. '}.get(
            len(stacks), f'{len(stacks)} stacks side by side. ')
        parts.append(count_word + ' '.join(stacks) + ' ')
    else:
        parts.append('No distribution is recorded; draw one generic stack per recorded component '
                     'with no labeled floors. ')
    parts.append(
        'English callout labels with dotted leader lines per band group. Bottom-left legend with '
        'the fixed color chips for the uses present. Top-left title "VERTICAL PROGRAM '
        'DISTRIBUTION". Flat infographic style, crisp readable English labels, no photorealism, '
        'no people, no furniture. Only the approved floor counts — no invented floors.')
    return ''.join(parts)


def _visual_concept_plan_massing_body(context, model, regulations):
    parts = [
        "DRAWING REQUESTED — 'CONCEPTUAL MASSING': a clean conceptual 3D massing diagram in a "
        'flat pastel architectural style on a white background. Isometric view from a high '
        'corner' + (
            f", rotated so the {model['main_dir']} edge faces front-left"
            if model and model['main_dir'] else '')
        + '. The attached reference image is the TRUE surveyed parcel outline — the parcel plate '
        'must match its exact shape and proportions. ']
    if model:
        high_dir = model['high_sector']['direction'] if model['high_sector'] else ''
        tiers = []
        last = len(model['bands']) - 1
        for position, band in enumerate(model['bands']):
            color = band['color'] or 'muted'
            noun = _VISUAL_PLAN_USE_LABEL.get(band['category'], 'Amenities').lower()
            if position == 0:
                storey = f"{band['floors']}-storey " if band['floors'] else ''
                if model.get('from_distribution'):
                    base_noun = 'ground band'
                else:
                    base_noun = ('podium base' if len(model['bands']) > 1
                                 and (band['floors'] or 0) <= 8 else 'base')
                tiers.append(f'{color} {storey}{base_noun}')
            elif position == last:
                tiers.append(f'{color} {noun} crown')
            else:
                tiers.append(f'{color} {noun} band')
        if model.get('from_distribution'):
            tower_name = 'building'
        else:
            tower_name = (f"{model['floor_count']}-storey tower" if model['floor_count'] else 'tower')
        parts.append(
            'On it, extrude only the approved masses as simple matte boxes with thin white '
            'horizontal floor lines and dark navy outlines: the ' + tower_name
            + (f' on the {high_dir} part' if high_dir else '')
            + ', shown as one volume banded by use (' + ', '.join(tiers) + ')')
        for block in model.get('blocks') or []:
            cap_text = f"{block['cap']}-storey " if block.get('cap') else 'low '
            on_part = f" on the {block['direction']} part" if block.get('direction') else ''
            parts.append(f" plus the separate {cap_text}{block.get('color') or 'muted'} "
                         f"'{block['label']}'{on_part}")
        parts.append('. Pale-green landscaping with round trees fills the open areas')
        if model['sea_dir']:
            parts.append(f"; a pale-cyan 'Sea' band runs beyond the {model['sea_dir']} edge")
        callouts = [band['label'] + (' Podium' if i == 0 and not model.get('from_distribution')
                                     and len(model['bands']) > 1
                                     and (band['floors'] or 0) <= 8 else '')
                    for i, band in enumerate(model['bands'])]
        callouts += [block['label'] for block in model.get('blocks') or [] if block.get('label')]
        parts.append('. English callout labels on dotted leader lines: '
                     + ', '.join(f"'{label}'" for label in callouts)
                     + '. Edge labels: each recorded street and neighbor named with its '
                     'recorded name and width. ')
    else:
        parts.append('No approved masses are recorded — do not extrude speculative volumes; show '
                     'a restrained dashed development field labeled "Approved building footprints '
                     'not recorded." ')
    parts.append(
        'Bottom-left legend with the fixed color chips. Top-left title "CONCEPTUAL MASSING". Flat '
        'vector look, muted pastel palette, dark navy text, no photorealism, no people, no cars, '
        'no shadows. Do not add room detail, furniture, facades or any element not in the '
        'approved model.')
    return ''.join(parts)


def _visual_concept_plan_drawing_prompt(kind, context, model=None):
    context = context if isinstance(context, dict) else {}
    regulations = context.get('regulations') if isinstance(context.get('regulations'), dict) else {}
    if model is None:
        model = _visual_concept_plan_model(context, regulations)
    spec = _visual_concept_plan_distribution_spec(context, model, regulations)
    body = {
        'site': _visual_concept_plan_site_body,
        'uses': _visual_concept_plan_uses_body,
        'massing': _visual_concept_plan_massing_body,
    }.get(kind, _visual_concept_plan_massing_body)(context, model, regulations)
    return (_visual_concept_plan_prompt_header(kind, context) + spec + '\n' + body)


def _visual_concept_plan_prompt_templates(context, model=None):
    return {
        definition['kind']: _visual_concept_plan_drawing_prompt(definition['kind'], context, model=model)
        for definition in VISUAL_CONCEPT_PLAN_DEFINITIONS
    }
