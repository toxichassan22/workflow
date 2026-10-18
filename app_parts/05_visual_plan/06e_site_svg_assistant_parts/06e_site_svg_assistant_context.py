# Raw project packet, signatures and scene-token handling for the Argon site-plan chat.

def _visual_plan_site_context_signature(data):
    project = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    project = {key: value for key, value in project.items()
               if key not in ('draftId', 'draft_id')}
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


def _visual_plan_site_prompt_contract(project, workflow):
    approved_area = project.get('approved_financial_area')
    croquis_source = (project.get('croquis_land_area') or project.get('land_area')
                      or project.get('total_area_sqm'))
    approved_area_number = _visual_concept_number(approved_area)
    land_area = approved_area_number if approved_area_number is not None else croquis_source
    area_source = ('approved_financial_area' if approved_area_number is not None else
                   'croquis_land_area' if croquis_source not in (None, '') else 'not_recorded')
    distribution = workflow.get('distribution') if isinstance(workflow.get('distribution'), dict) else {}
    rows = distribution.get('rows') if isinstance(distribution.get('rows'), list) else []
    boundary = workflow.get('boundary') if isinstance(workflow.get('boundary'), dict) else {}
    financial = _visual_concept_parse_json(project.get('financial_study_model'), {})
    financial = financial if isinstance(financial, dict) else {}
    dynamic_rows = financial.get('dynamicRows') if isinstance(financial.get('dynamicRows'), dict) else {}
    components = project.get('project_components_data')
    if not isinstance(components, list):
        components = dynamic_rows.get('components')
    if not isinstance(components, list):
        components = financial.get('components')
    components = components if isinstance(components, list) else []
    directions = project.get('directions_table') or project.get('directions') or {}
    analysis = _visual_concept_parse_json(project.get('land_documents_analysis'), {})
    analysis = analysis if isinstance(analysis, dict) else {}
    parcels = analysis.get('parcels') if isinstance(analysis.get('parcels'), list) else []
    document_parcel = parcels[0] if parcels and isinstance(parcels[0], dict) else {}
    primary_frontage = (project.get('main_facade_direction') or project.get('primary_facade_direction')
                        or project.get('main_frontage_direction') or '')
    return {
        'projectName': _visual_concept_read(project, 'project_name', 'projectName'),
        'projectIdea': _visual_concept_read(project, 'project_idea', 'projectIdea'),
        'city': project.get('city'),
        'district': project.get('district'),
        'locationAddress': _visual_concept_read(project, 'location_address', 'locationAddress'),
        'landAreaSqm': land_area,
        'landAreaSource': area_source,
        'approvedFinancialAreaSqm': approved_area,
        'croquisLandAreaSqm': croquis_source,
        'coverageRatio': _visual_concept_read(project, 'approved_coverage_ratio', 'coverage_ratio'),
        'floorAreaRatio': _visual_concept_read(project, 'approved_floor_area_ratio', 'floor_area_ratio'),
        'floorCount': _visual_concept_read(project, 'approved_floor_count', 'table_floors'),
        'approvedFloorCount': project.get('approved_floor_count'),
        'typicalFloorCoverage': project.get('approved_typical_floor_coverage'),
        'openArea': project.get('open_area'),
        'boundaryLengths': project.get('boundary_lengths'),
        'surveyCoordinates': (project.get('survey_coordinates') or project.get('regulation_coordinates')
                             or boundary.get('points') or []),
        'boundaryPoints': boundary.get('points') or [],
        'directions': directions or document_parcel.get('directions_table') or {},
        'setbacks': project.get('setbacks') or document_parcel.get('setbacks'),
        'surroundingStreets': project.get('surrounding_streets'),
        'facadesCount': project.get('facades_count'),
        'facadesDirections': project.get('facades_directions'),
        'primaryFrontage': primary_frontage,
        'northDirection': project.get('north_direction'),
        'allowedUses': project.get('allowed_uses'),
        'regulatoryConstraints': project.get('regulatory_constraints') or document_parcel.get('regulatory_constraints'),
        'landBrief': project.get('land_and_building_summary') or document_parcel.get('summary'),
        'landDocumentsAnalysis': analysis,
        'financialComponents': components,
        'distributionRows': rows,
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
    if (scene and scene.get('inputSignature') == signature
            and isinstance(scene.get('geometry'), dict)):
        geometry = scene['geometry']
    directions = _visual_plan_site_render_directions(prompt_contract.get('directions'))
    render_contract = {
        'geometry': geometry,
        'directions': directions,
        'primaryFrontage': scene.get('primaryFrontage') if scene else prompt_contract.get('primaryFrontage'),
        'projectName': prompt_contract.get('projectName'),
        'landArea': prompt_contract.get('landAreaSqm'),
    }
    context = {'components': prompt_contract.get('financialComponents') or []}
    drawing_layout = None
    if (scene and isinstance(scene.get('buildings'), list)
            and scene.get('inputSignature') == signature):
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
                    if key not in ('token', 'inputSignature')} if scene else None)
    packet = {
        'project': {'name': prompt_contract.get('projectName'), 'idea': prompt_contract.get('projectIdea')},
        'landAndRegulations': prompt_contract,
        'sourceProjectData': project,
        'sourceDistribution': workflow.get('distribution') if isinstance(workflow.get('distribution'), dict) else {},
        'sourceBoundary': workflow.get('boundary') if isinstance(workflow.get('boundary'), dict) else {},
        'existingGeneratedLayout': clean_scene,
        'program': {},
        'drawingLayout': drawing_layout,
        'financialComponents': prompt_contract.get('financialComponents') or [],
        'distributionRows': prompt_contract.get('distributionRows') or [],
        'distributionNotes': prompt_contract.get('distributionNotes') or '',
        'clientNotes': prompt_contract.get('clientNotes') or '',
        'projectMeasurements': {key: prompt_contract.get(key) for key in (
            'landAreaSqm', 'landAreaSource', 'approvedFinancialAreaSqm', 'croquisLandAreaSqm')},
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
