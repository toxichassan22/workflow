import copy
import db
from best_use_contract import ProposalError, decoded, read_object, text, capacity, MAP_TOKENS, digest
from best_use_geometry import number


ARTIFACTS = ('regulations', 'priceScan', 'concepts', 'landDistribution', 'floorDistribution')
DEPENDENCIES = {
    'regulations': (), 'priceScan': ('regulations',),
    'concepts': ('regulations', 'priceScan'),
    'landDistribution': ('regulations', 'priceScan', 'concepts'),
    'floorDistribution': ('regulations', 'priceScan', 'concepts', 'landDistribution'),
}
META = {'id', 'version', 'contentHash', 'inputHash', 'generatedAt', 'approved', 'rejected',
        'approvedAt', 'approvedBy', 'approvedContentHash', 'approvedInputHash', 'inputsChanged'}
EXPLORE_EXCLUDED = {
    'project_name', 'project_type', 'project_subtype', 'project_idea', 'project_level',
    'activity_class', 'target_audience', 'project_language', 'market_study_data',
    'land_documents_analysis', 'land_use_status',
}


SOURCE_FIELDS = (
    'draftId', 'land_documents_files_file_ids', 'croquis_land_area', 'approved_financial_area',
    'approved_coverage_ratio', 'approved_floor_count', 'approved_floor_area_ratio',
    'approved_typical_floor_coverage', 'building_ratio_coverage', 'setbacks', 'max_floors_height',
    'boundary_lengths', 'surrounding_streets', 'survey_coordinates', 'directions_table',
    'location_address', 'location_lat', 'location_lng', 'city', 'district', 'site_analysis', 'main_roads',
    'nearby_landmarks_data', 'city_landmarks_data', 'catchment_areas',
    'location_polygon', 'location_polygon_source', 'plot_number_croquis', 'plan_number', 'zoning_code',
    'allowed_uses', 'land_and_building_summary', 'regulatory_constraints',
)
JSON_FIELDS = {'land_documents_files_file_ids': [], 'survey_coordinates': [], 'directions_table': [],
               'nearby_landmarks_data': [], 'city_landmarks_data': [], 'location_polygon': []}
NUMBER_FIELDS = {'croquis_land_area', 'approved_financial_area', 'approved_coverage_ratio',
                 'approved_floor_count', 'approved_floor_area_ratio', 'approved_typical_floor_coverage',
                 'location_lat', 'location_lng'}


def source_snapshot(project):
    snapshot = {}
    for key in SOURCE_FIELDS:
        value = project.get(key)
        snapshot[key] = (decoded(value, JSON_FIELDS[key]) if key in JSON_FIELDS else
                         number(value) if key in NUMBER_FIELDS else text(value, 30000))
    maps = read_object(read_object(project.get('tenantCreativeImages')).get('map_placeholders'))
    snapshot['maps'] = {key: maps[key] for key in MAP_TOKENS if maps.get(key)}
    # The snapshot must describe the artifact family's inputs, not the live UI
    # toggle — reading best_use_mode here would make every mode switch hash as
    # an input change. Pin it to the explore state's own marker, mirroring the
    # guided side which reads best_use_data.mode.
    snapshot['mode'] = read_object(project.get('best_use_explore_data')).get('mode') or 'explore'
    return db.normalize_generation_input(snapshot)


def source_hash(project):
    return digest(source_snapshot(project))


def prompt_context(project):
    return dict(source_snapshot(project), capacity=capacity(project))


def missing_inputs(project, statuses):
    source = source_snapshot(project)
    missing = []
    if (project.get('best_use_mode') or 'guided') != 'explore':
        missing.append('best_use_mode')
    if not source['land_documents_files_file_ids']:
        missing.append('croquis')
    lat, lng = source['location_lat'], source['location_lng']
    if not source['location_address'] or lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        missing.append('site_location')
    for key in ('land_croquis', 'location'):
        if (statuses or {}).get(key) != 'approved':
            missing.append(key)
    for key in ('croquis_land_area', 'approved_financial_area', 'approved_floor_count', 'approved_floor_area_ratio'):
        value = source[key]
        if value is None or value <= 0 or (key == 'approved_floor_count' and value != int(value)):
            missing.append(key)
    if source['approved_coverage_ratio'] is None or not 0 < source['approved_coverage_ratio'] <= 100:
        missing.append('approved_coverage_ratio')
    if source['approved_floor_count'] and source['approved_floor_count'] > 1 \
            and not (source['approved_typical_floor_coverage'] and source['approved_typical_floor_coverage'] > 0):
        missing.append('approved_typical_floor_coverage')
    if not source['setbacks']:
        missing.append('setbacks')
    if not source['city']:
        missing.append('city')
    # The client-declared regulation fields are the working basis — the croquis
    # may be too old to carry them as text, so each is reported by name.
    for key in ('allowed_uses', 'land_and_building_summary', 'regulatory_constraints',
                'building_ratio_coverage'):
        if not source[key]:
            missing.append(key)
    if not source['directions_table']:
        missing.append('directions_table')
    if not source['site_analysis']:
        missing.append('site_analysis')
    if not missing and capacity(project)['maxBuiltArea'] <= 0:
        missing.append('buildable_area')
    return list(dict.fromkeys(missing))


def content_hash(artifact):
    return digest({key: value for key, value in artifact.items() if key not in META})


def artifact_input(project, name):
    state = read_object(project.get('best_use_explore_data'))
    context = {'sourceHash': source_hash(project), 'artifact': name}
    for dependency in DEPENDENCIES[name]:
        artifact = state.get(dependency) or {}
        context[dependency] = {'id': artifact.get('id'), 'contentHash': artifact.get('contentHash')}
    if name in ('landDistribution', 'floorDistribution'):
        context['selectedConceptId'] = state.get('selectedConceptId')
        context['selectedConceptVersion'] = state.get('selectedConceptVersion')
    return digest(context)


def make_artifact(project, name, payload, artifact_id, previous=None):
    artifact = copy.deepcopy(payload)
    artifact.update(id=artifact_id, version=int((previous or {}).get('version') or 0) + 1,
                    approved=False, rejected=False, inputsChanged=False,
                    inputHash=artifact_input(project, name), generatedAt=db._utcnow().isoformat())
    artifact['contentHash'] = content_hash(artifact)
    return artifact


def current(project, name, visited=None):
    visited = set(visited or ())
    if name in visited:
        return False
    visited.add(name)
    state = read_object(project.get('best_use_explore_data'))
    artifact = state.get(name)
    if not isinstance(artifact, dict) or not artifact.get('id') or artifact.get('rejected'):
        return False
    if any(not current(project, dependency, visited) for dependency in DEPENDENCIES[name]):
        return False
    if name == 'priceScan':
        from best_use_prices import evidence_current
        if not evidence_current(artifact):
            return False
    return (artifact.get('contentHash') == content_hash(artifact)
            and artifact.get('inputHash') == artifact_input(project, name))


def approved(project, name):
    artifact = read_object(project.get('best_use_explore_data')).get(name) or {}
    return (current(project, name) and artifact.get('approved') is True
            and artifact.get('approvedContentHash') == artifact.get('contentHash')
            and artifact.get('approvedInputHash') == artifact.get('inputHash'))


def invalidate(state, names):
    for name in names:
        artifact = state.get(name)
        if isinstance(artifact, dict) and artifact.get('id'):
            artifact.update(approved=False, inputsChanged=True)
            for key in ('approvedAt', 'approvedBy', 'approvedContentHash', 'approvedInputHash'):
                artifact.pop(key, None)


def refresh(project):
    state = read_object(project.get('best_use_explore_data'))
    if state.get('mode') != 'explore':
        return state
    probe = dict(project, best_use_explore_data=state)
    for name in ARTIFACTS:
        artifact = state.get(name)
        if not isinstance(artifact, dict) or not artifact.get('id'):
            continue
        if current(probe, name):
            # inputsChanged is a derived marker, not a verdict: heal it when the
            # hashes verify the artifact is still built on the current inputs.
            artifact['inputsChanged'] = False
        else:
            invalidate(state, (name,))
    project['best_use_explore_data'] = state
    return state


def section_error(project):
    state = read_object(project.get('best_use_explore_data'))
    required = ['priceScan', 'concepts', 'landDistribution', 'floorDistribution']
    if (state.get('regulations') or {}).get('requiresApproval'):
        required.insert(0, 'regulations')
    if any(not isinstance(state.get(name), dict) or not state[name].get('id') for name in required):
        return 'BEST_USE_APPROVAL_REQUIRED'
    if any(not current(project, name) for name in required):
        return 'BEST_USE_INPUTS_CHANGED'
    if any(not approved(project, name) for name in required):
        return 'BEST_USE_APPROVAL_REQUIRED'
    return None


def select_concept(project, concept_id):
    state = read_object(project.get('best_use_explore_data'))
    if not current(project, 'concepts'):
        raise ProposalError('المفاهيم غير متوفرة أو تغيّرت مدخلاتها.')
    concepts = state['concepts']
    if not any(item.get('id') == concept_id for item in concepts.get('items') or []):
        raise ProposalError('المفهوم المختار غير متوفر.')
    if state.get('selectedConceptId') != concept_id or state.get('selectedConceptVersion') != concepts['version']:
        state.update(selectedConceptId=concept_id, selectedConceptVersion=concepts['version'])
        invalidate(state, ('landDistribution', 'floorDistribution'))
    project['best_use_explore_data'] = state
    return state


def selected_concept(project):
    state = read_object(project.get('best_use_explore_data'))
    if not current(project, 'concepts') or state.get('selectedConceptVersion') != state['concepts']['version']:
        return None
    return next((item for item in state['concepts'].get('items') or []
                 if item.get('id') == state.get('selectedConceptId')), None)
