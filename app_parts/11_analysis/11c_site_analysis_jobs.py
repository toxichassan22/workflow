# Site analysis as a job.
#
# The analysis spends Google Maps calls — Places, Geocoding, Roads — and the
# request used to hold them open: the browser waited on a call it could not
# interrupt, and a user who spotted the wrong pin only found out when the
# whole sweep was over. The work now runs in a job the stop button can
# reach, and the answer is fetched from the persisted job.
#
# The tests keep the synchronous path unless they ask for the background one,
# exactly like the other queued operations.

_SITE_ANALYSIS_JOB_NAMESPACE = '.site_analysis_jobs'
_SITE_ANALYSIS_JOB_TIMEOUT_SECONDS = 900


def _site_analysis_result(data, project_data, lat, lng, source):
    """The paid half of the site analysis: the Maps calls behind the fields."""
    site_maps_ctx = maps_service.maps_usage_ctx('site', g.tenant_id, data=data)
    with maps_service.maps_usage_scope(site_maps_ctx):
        fields, nearby_items, nearby_matrix, city_items, city_matrix, roads, polygon, diagnostics = _collect_site_fields(
            project_data, g.tenant_id, lat, lng
        )
    fields.setdefault('location_polygon_source', 'none')
    return {
        'success': True,
        'fields': fields,
        'mapPlaceholders': {},
        'mapsDeferred': True,
        'landmarks': nearby_items,
        'landmarksMatrix': nearby_matrix,
        'cityLandmarks': city_items,
        'roads': roads,
        'zooms': {},
        'lat': lat,
        'lng': lng,
        'source': source,
        'boundary': {
            'status': 'verified_building' if polygon else 'needs_review',
            'estimated': False,
            'manual_edit_available': True,
        },
        'warning': None,
        'landmarksWarning': diagnostics.get('nearby_landmarks_error') or diagnostics.get('nearby_landmarks_warning'),
        'cityLandmarksWarning': diagnostics.get('city_landmarks_error') or diagnostics.get('city_landmarks_warning'),
    }


def _site_analysis_job_worker(flask_app, tenant_id, data, job_id):
    """Run the site sweep off the request so the stop button can reach it."""
    with flask_app.test_request_context('/api/site-analysis-jobs/' + job_id, method='POST', json=data):
        # The stop button reaches this analysis through the run registry; the
        # thread dies with the worker, so the handle cannot leak.
        run_control.bind_run(job_id, tenant_id)
        g.tenant_id = tenant_id
        g.user_id = data.get('actor', {}).get('user_id') if isinstance(data.get('actor'), dict) else None
        g.user_name = data.get('actor', {}).get('user_name') if isinstance(data.get('actor'), dict) else None
        g.user_role = data.get('actor', {}).get('user_role') if isinstance(data.get('actor'), dict) else None
        g.is_admin = False
        g.user_permissions = {}
        g.tenant = db.get_tenant_by_id(tenant_id)
        _write_job(_SITE_ANALYSIS_JOB_NAMESPACE, tenant_id, job_id, {
            'status': 'running',
            'success': True,
            'message': 'جاري جلب بيانات الموقع والطرق والمعالم...',
        })
        try:
            project_data = clean_project_data(data.get('projectData', {}))
            address = project_data.get('location_address') or project_data.get('location') or ''
            link = address if isinstance(address, str) and address.startswith('http') else (
                project_data.get('location_maps_link') or project_data.get('maps_link')
            )
            coords = maps_service.extract_coords_from_maps_link(link) if link else None
            if coords:
                lat, lng = coords['lat'], coords['lng']
                source = 'maps_link'
            else:
                lat = maps_service._extract_coordinate(
                    project_data.get('location_lat') or project_data.get('locationLat') or
                    project_data.get('latitude') or project_data.get('lat')
                )
                lng = maps_service._extract_coordinate(
                    project_data.get('location_lng') or project_data.get('locationLng') or
                    project_data.get('longitude') or project_data.get('lng')
                )
                source = 'existing_coordinates'
            if lat is None or lng is None:
                raise ValueError('لا توجد إحداثيات للموقع')
            result = _site_analysis_result(data, project_data, lat, lng, source)
            if run_control.current_run_cancelled():
                _write_job(_SITE_ANALYSIS_JOB_NAMESPACE, tenant_id, job_id,
                           {**run_control.cancelled_job_patch(),
                            'message': 'تم إيقاف تحليل الموقع'})
                return
            _write_job(_SITE_ANALYSIS_JOB_NAMESPACE, tenant_id, job_id, {
                'status': 'completed',
                'success': True,
                'message': 'اكتمل تحليل الموقع',
                'result': result,
            })
        except Exception as exc:
            print(f'[SITE ANALYSIS JOB FAILED] {exc}')
            cancelled = run_control.current_run_cancelled()
            _write_job(_SITE_ANALYSIS_JOB_NAMESPACE, tenant_id, job_id, {
                'status': 'cancelled' if cancelled else 'failed',
                'success': False,
                'error': run_control.CANCELLED_MESSAGE if cancelled else f'تعذر تحليل الموقع: {exc}',
                'error_code': run_control.CANCELLED_ERROR_CODE if cancelled else 'SITE_ANALYSIS_FAILED',
            })


@app.route('/api/site-analysis-jobs/<job_id>', methods=['GET'])
@require_permission('create_presentation')
def api_site_analysis_job(job_id):
    """The state of a queued site analysis."""
    if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', str(job_id or '')):
        return jsonify({'success': False, 'error': 'معرف مهمة غير صالح'}), 400
    job = _read_job(_SITE_ANALYSIS_JOB_NAMESPACE, g.tenant_id, job_id)
    if not job:
        return jsonify({
            'success': False,
            'status': 'not_found',
            'error': 'المهمة غير موجودة أو انتهت صلاحيتها',
            'failureReason': 'job_not_found',
        }), 404
    # A stop is reported from the moment it lands; the worker publishes its own
    # terminal cancelled state when it reaches its next checkpoint.
    if (str(job.get('status') or '') in ('queued', 'running')
            and run_control.is_run_cancelled(job_id, g.tenant_id)):
        job = {**job, **run_control.cancelled_job_patch()}
    return jsonify(job)
