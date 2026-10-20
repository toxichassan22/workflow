# Raw project packet, signatures and scene-token handling for the Argon site-plan chat.

def _visual_plan_site_context_signature(data):
    project = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    session_fields = {
        'draftId', 'draft_id', 'visual_concept', 'tenantCreativeImages',
        'tenant_creative_images', 'creative_images', 'plans2d',
        'plans_workflow', 'plansWorkflow',
    }
    project = {key: value for key, value in project.items() if key not in session_fields}
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    inputs = {
        'projectData': project,
        'boundary': workflow.get('boundary') if isinstance(workflow.get('boundary'), dict) else {},
        'distribution': workflow.get('distribution') if isinstance(workflow.get('distribution'), dict) else {},
        'distributionNotes': workflow.get('distributionNotes') or '',
        'clientNotes': workflow.get('clientNotes') or '',
    }
    encoded = json.dumps(inputs, sort_keys=True, ensure_ascii=False, default=str,
                         separators=(',', ':'))
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _visual_plan_site_current_components(project, financial):
    source = project.get('project_components_data')
    components = source if isinstance(source, list) else _visual_concept_parse_json(source, None)
    if not isinstance(components, list):
        dynamic_rows = financial.get('dynamicRows') if isinstance(financial.get('dynamicRows'), dict) else {}
        components = dynamic_rows.get('components')
    if not isinstance(components, list):
        components = financial.get('components')
    return copy.deepcopy(components) if isinstance(components, list) else []


def _visual_plan_site_model_analysis(value):
    analysis = _visual_concept_parse_json(value, {})
    if not isinstance(analysis, (dict, list)):
        return {}
    omitted_keys = {
        'rawtext', 'rawresponse', 'rawocrtext', 'ocrtext', 'pagetext',
        'extractiondiagnostics', 'documentprocessing', 'pageimages',
        'originalimage', 'imagedata', 'filedata', 'base64',
    }

    def compact(item, key='', depth=0):
        normalized = re.sub(r'[^a-z0-9]', '', str(key).lower())
        if (normalized in omitted_keys or 'base64' in normalized
                or normalized.endswith(('imagedata', 'filecontent', 'rawbytes'))):
            return None
        if isinstance(item, dict):
            if depth >= 8:
                return None
            result = {}
            for child_key, child in item.items():
                clean_child = compact(child, child_key, depth + 1)
                if clean_child is not None:
                    result[child_key] = clean_child
            return result
        if isinstance(item, list):
            if depth >= 8:
                return []
            return [clean for clean in
                    (compact(child, key, depth + 1) for child in item[:80])
                    if clean is not None]
        if isinstance(item, str) and len(item) > 12000:
            return item[:12000]
        return item

    return compact(analysis)


def _visual_plan_site_boundary_polygon(project, workflow):
    boundary = workflow.get('boundary') if isinstance(workflow.get('boundary'), dict) else {}
    for source in (project.get('survey_coordinates'), project.get('regulation_coordinates'),
                   boundary.get('points')):
        source = _visual_concept_parse_json(source, source)
        if isinstance(source, dict):
            source = (source.get('points') or source.get('survey_coordinates')
                      or source.get('coordinates') or [])
        if not isinstance(source, list):
            continue
        points = []
        for item in source:
            if isinstance(item, dict):
                east = item.get('eastings', item.get('easting', item.get('x')))
                north = item.get('northings', item.get('northing', item.get('y')))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                east, north = item[0], item[1]
            else:
                continue
            east, north = _visual_concept_number(east), _visual_concept_number(north)
            if east is None or north is None:
                points = []
                break
            points.append([east, north])
        if len(points) >= 3:
            return points
    return []


def _visual_plan_site_render_directions(value):
    if isinstance(value, str):
        value = _visual_concept_parse_json(value, [])
    if isinstance(value, dict):
        value = [{'direction': key, **(item if isinstance(item, dict) else {'regulation_text': item})}
                 for key, item in value.items()]
    if not isinstance(value, list):
        return []
    direction_names = {'شمال': 'north', 'الشمال': 'north', 'الشمالي': 'north',
                       'جنوب': 'south', 'الجنوب': 'south', 'الجنوبي': 'south',
                       'شرق': 'east', 'الشرق': 'east', 'الشرقي': 'east',
                       'غرب': 'west', 'الغرب': 'west', 'الغربي': 'west'}
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        direction = str(item.get('direction') or item.get('label') or '').strip()
        direction = direction_names.get(direction, direction.lower())
        if direction not in ('north', 'south', 'east', 'west'):
            continue
        description = ' '.join(str(item.get(key) or '') for key in
                               ('regulation_text', 'regulation', 'text', 'notes', 'uses'))
        street_name = str(item.get('street_name') or item.get('streetName') or '').strip()
        width = _visual_concept_number(item.get('street_width_m') or item.get('street_width')
                                       or item.get('streetWidth'))
        street = bool(item.get('street') or street_name or width is not None
                      or re.search(r'\bstreet\b|\broad\b|شارع|طريق', description, re.IGNORECASE))
        if re.search(r'no\s+(?:street|road)|ليس\s*شارع|لا\s*يوجد\s*شارع', description, re.IGNORECASE):
            street = False
        result.append({'direction': direction, 'street': street,
                       'streetName': street_name, 'streetWidth': width})
    return result


def _visual_plan_site_geometric_facts(polygon, contract=None):
    if not isinstance(polygon, list) or len(polygon) < 3:
        return {}
    n = len(polygon)
    edges = []
    shoelace = 0.0
    for i in range(n):
        p1 = polygon[i]
        p2 = polygon[(i + 1) % n]
        if not (isinstance(p1, (list, tuple)) and isinstance(p2, (list, tuple)) and len(p1) >= 2 and len(p2) >= 2):
            continue
        p1_0, p1_1 = float(p1[0]), float(p1[1])
        p2_0, p2_1 = float(p2[0]), float(p2[1])
        dx = p2_0 - p1_0
        dy = p2_1 - p1_1
        d = math.hypot(dx, dy)
        ang = math.degrees(math.atan2(dy, dx))
        edges.append({'fromPoint': i + 1, 'toPoint': ((i + 1) % n) + 1, 'lengthM': round(d, 2), 'angleDeg': round(ang, 2)})
        shoelace += (p1_0 * p2_1 - p2_0 * p1_1)
    area = abs(shoelace) / 2.0
    valid_points = [p for p in polygon if isinstance(p, (list, tuple)) and len(p) >= 2]
    min_x = min(float(p[0]) for p in valid_points) if valid_points else 0.0
    max_x = max(float(p[0]) for p in valid_points) if valid_points else 0.0
    min_y = min(float(p[1]) for p in valid_points) if valid_points else 0.0
    max_y = max(float(p[1]) for p in valid_points) if valid_points else 0.0
    long_edges = sorted(edges, key=lambda e: e['lengthM'], reverse=True)[:2]
    rotation = long_edges[0]['angleDeg'] if long_edges else 0.0
    return {
        'calculatedShoelaceAreaSqm': round(area, 2),
        'boundaryEdgeDimensions': edges,
        'boundingSpanMeters': {'spanX': round(max_x - min_x, 2), 'spanY': round(max_y - min_y, 2)},
        'principalRotationDeg': round(rotation, 2),
        'recommendedCanvasViewBox': '0 0 1400 840',
        'architecturalZoningDepths': {
            'frontParkingDepthM': 15.0,
            'commercialTowersDepthM': 30.0,
            'residentialAndCourtyardDepthM': 205.0,
            'rearCirculationDrivewayM': 6.5,
            'courtyardAmenities': 'Olympic Swimming Pool (20x40m), 2 Padel Courts, Health Club, Children Playground, Green Landscape'
        }
    }


def _visual_plan_site_prompt_contract(project, workflow):
    approved_area = project.get('approved_financial_area')
    croquis_source = (project.get('croquis_land_area') or project.get('land_area')
                      or project.get('total_area_sqm'))
    approved_area_number = _visual_concept_number(approved_area)
    land_area = approved_area_number if approved_area_number is not None else _visual_concept_number(croquis_source)
    boundary = workflow.get('boundary') if isinstance(workflow.get('boundary'), dict) else {}
    financial = _visual_concept_parse_json(project.get('financial_study_model'), {})
    financial = financial if isinstance(financial, dict) else {}
    components = _visual_plan_site_current_components(project, financial)
    analysis = _visual_plan_site_model_analysis(project.get('land_documents_analysis'))
    analysis = analysis if isinstance(analysis, dict) else {}
    directions = project.get('directions_table') or project.get('directions') or {}
    # The recorded direction in the project data wins. When the croquis text
    # names no main facade, the server resolved one and the plan context
    # carries it — the site plan is drawn against the same facade the
    # geometry used, not against an empty one.
    facade_hint = _visual_plan_frontage_hint(workflow) or {}
    primary_frontage = (project.get('main_facade_direction') or project.get('primary_facade_direction')
                        or project.get('main_frontage_direction')
                        or facade_hint.get('direction') or '')
    building_area = project.get('building_area') or project.get('total_bua') or project.get('total_built_area')
    if not building_area and land_area and project.get('approved_floor_area_ratio'):
        try:
            building_area = round(float(land_area) * float(project.get('approved_floor_area_ratio')), 2)
        except Exception:
            building_area = None

    survey_coords = (project.get('survey_coordinates') or project.get('regulation_coordinates')
                     or boundary.get('points') or [])
    return {
        'projectName': _visual_concept_read(project, 'project_name', 'projectName'),
        # The site plan is drawn in English: an English project name is used
        # when the client recorded one, and an Arabic-only name is left out of
        # the drawing rather than printed in Arabic.
        'projectNameEn': _visual_concept_read(project, 'project_name_en', 'projectNameEn'),
        'projectIdea': _visual_concept_read(project, 'project_idea', 'projectIdea'),
        'approvedFinancialAreaSqm': approved_area_number if approved_area_number is not None else land_area,
        'croquisLandAreaSqm': croquis_source,
        'landAreaSqm': approved_area_number if approved_area_number is not None else land_area,
        'landAreaSource': ('approved_financial_area' if approved_area_number is not None else
                           'croquis_land_area' if croquis_source not in (None, '') else 'not_recorded'),
        'surroundingStreets': project.get('surrounding_streets'),
        'boundaryLengths': project.get('boundary_lengths'),
        'facadesCount': project.get('facades_count'),
        'facadesDirections': project.get('facades_directions'),
        'approvedFloorCount': project.get('approved_floor_count') or project.get('table_floors'),
        'coverageRatio': _visual_concept_read(project, 'approved_coverage_ratio', 'coverage_ratio'),
        'floorAreaRatio': _visual_concept_read(project, 'approved_floor_area_ratio', 'floor_area_ratio'),
        'typicalFloorCoverage': project.get('approved_typical_floor_coverage'),
        'buildingAreaSqm': building_area,
        'surveyCoordinates': survey_coords,
        'directions': directions,
        'setbacks': project.get('setbacks'),
        'primaryFrontage': primary_frontage,
        'landDocumentsAnalysis': analysis,
        'financialComponents': components,
        'distributionRows': workflow.get('distribution', {}).get('rows') or [],
        'distributionNotes': workflow.get('distributionNotes') or '',
        'clientNotes': workflow.get('clientNotes') or '',
    }


def _visual_plan_site_packet(data):
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    project = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    signature = _visual_plan_site_context_signature(data)
    scene = workflow.get('scene') if isinstance(workflow.get('scene'), dict) else None
    prompt_contract = _visual_plan_site_prompt_contract(project, workflow)
    parcel_polygon = _visual_plan_site_boundary_polygon(project, workflow)
    geometry = {'parcels': [{'id': 'parcel_1', 'polygon': parcel_polygon}]} if parcel_polygon else {}
    scene_is_current = bool(scene and scene.get('inputSignature') == signature)
    if (scene_is_current
            and isinstance(scene.get('geometry'), dict)):
        geometry = scene['geometry']
    directions = _visual_plan_site_render_directions(prompt_contract.get('directions'))
    render_contract = {
        'geometry': geometry,
        'directions': directions,
        'primaryFrontage': (scene.get('primaryFrontage') if scene_is_current
                            else prompt_contract.get('primaryFrontage')),
        'projectName': prompt_contract.get('projectName'),
        'projectNameEn': prompt_contract.get('projectNameEn'),
        'landArea': prompt_contract.get('landAreaSqm'),
    }
    context = {'components': prompt_contract.get('financialComponents') or []}
    drawing_layout = None
    if (scene_is_current and isinstance(scene.get('buildings'), list) and len(scene.get('buildings')) > 0):
        try:
            tenant = getattr(g, 'tenant', {})
            tenant = tenant if isinstance(tenant, dict) else {}
            drawing_layout = _visual_plan_site_projected_layout(scene, render_contract, {}, {
                'projectName': render_contract.get('projectName'),
                'developerName': tenant.get('company_name_en') or tenant.get('company_name'),
            })
        except Exception:
            drawing_layout = None
    clean_scene = ({key: value for key, value in scene.items()
                    if key not in ('token', 'inputSignature')} if scene_is_current else None)
    packet = {
        'project': {'name': prompt_contract.get('projectName'), 'idea': prompt_contract.get('projectIdea')},
        'projectName': prompt_contract.get('projectName'),
        'approvedFinancialAreaSqm': prompt_contract.get('approvedFinancialAreaSqm'),
        'surroundingStreets': prompt_contract.get('surroundingStreets'),
        'boundaryLengths': prompt_contract.get('boundaryLengths'),
        'facadesCount': prompt_contract.get('facadesCount'),
        'facadesDirections': prompt_contract.get('facadesDirections'),
        'approvedFloorCount': prompt_contract.get('approvedFloorCount'),
        'coverageRatio': prompt_contract.get('coverageRatio'),
        'floorAreaRatio': prompt_contract.get('floorAreaRatio'),
        'typicalFloorCoverage': prompt_contract.get('typicalFloorCoverage'),
        'buildingAreaSqm': prompt_contract.get('buildingAreaSqm'),
        'surveyCoordinates': prompt_contract.get('surveyCoordinates'),
        'directions': prompt_contract.get('directions'),
        'financialComponents': prompt_contract.get('financialComponents') or [],
        'distributionRows': prompt_contract.get('distributionRows') or [],
        'distributionNotes': prompt_contract.get('distributionNotes') or '',
        'clientNotes': prompt_contract.get('clientNotes') or '',
        'landAndRegulations': prompt_contract,
        'geometricFacts': _visual_plan_site_geometric_facts(parcel_polygon, prompt_contract),
        'existingGeneratedLayout': clean_scene,
        'drawingLayout': drawing_layout,
        'projectMeasurements': {
            'approvedFinancialAreaSqm': prompt_contract.get('approvedFinancialAreaSqm'),
            'landAreaSqm': prompt_contract.get('landAreaSqm'),
            'croquisLandAreaSqm': prompt_contract.get('croquisLandAreaSqm'),
            'landAreaSource': prompt_contract.get('landAreaSource'),
        },
    }
    _visual_plan_report_site_chat_progress(2, 68)
    return packet, render_contract, context, signature


def _visual_plan_site_seal_scene(data, scene, signature):
    sealed = {key: value for key, value in scene.items() if key not in ('token', 'inputSignature')}
    sealed['inputSignature'] = signature
    sealed['token'] = _visual_plan_token(
        'scene', data, signature, {key: value for key, value in sealed.items() if key != 'token'})
    return sealed


def _visual_plan_site_verify_scene(data):
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    scene = workflow.get('scene') if isinstance(workflow.get('scene'), dict) else None
    if not scene:
        return False
    token = scene.get('token')
    signature = scene.get('inputSignature')
    if not token:
        return False
    posted = {key: value for key, value in scene.items() if key != 'token'}
    if (scene.get('version') != VISUAL_PLAN_SCENE_VERSION or not isinstance(signature, str)
            or not _visual_plan_token_matches('scene', data, signature, posted, token)):
        raise visual_plan_geometry.PlanGeometryError(
            'تغيرت بيانات المشهد خارج مسار التعديل.', 'PLANS_SCENE_INVALID')
    return signature == _visual_plan_site_context_signature(data)
