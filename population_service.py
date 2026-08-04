"""Optional BigQuery-backed population density lookup.

The service intentionally returns no estimate when the dataset or query is not configured.
"""

import json
import os
import time

import jwt
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.environ.get(
    'BIGQUERY_CREDENTIALS_FILE',
    os.path.join(BASE_DIR, 'BigQuery API.json'),
)
TOKEN_SCOPE = 'https://www.googleapis.com/auth/bigquery'
_TOKEN_CACHE = {'value': None, 'expires_at': 0}


def _credentials():
    try:
        with open(CREDENTIALS_PATH, 'r', encoding='utf-8') as source:
            data = json.load(source)
        required = ('client_email', 'private_key', 'token_uri')
        if not all(data.get(key) for key in required):
            return None
        return data
    except (OSError, ValueError):
        return None


def _access_token(credentials):
    now = int(time.time())
    if _TOKEN_CACHE['value'] and _TOKEN_CACHE['expires_at'] - 60 > now:
        return _TOKEN_CACHE['value']
    assertion = jwt.encode(
        {
            'iss': credentials['client_email'],
            'scope': TOKEN_SCOPE,
            'aud': credentials['token_uri'],
            'iat': now,
            'exp': now + 3600,
        },
        credentials['private_key'],
        algorithm='RS256',
    )
    response = requests.post(
        credentials['token_uri'],
        data={'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': assertion},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    _TOKEN_CACHE.update(value=payload['access_token'], expires_at=now + int(payload.get('expires_in', 3600)))
    return payload['access_token']


def _query_text(project_id):
    configured = os.environ.get('BIGQUERY_POPULATION_QUERY', '').strip()
    if configured:
        return configured
    dataset = os.environ.get('BIGQUERY_POPULATION_DATASET', '').strip()
    table = os.environ.get('BIGQUERY_POPULATION_TABLE', '').strip()
    if not dataset or not table:
        return ''
    geometry_column = os.environ.get('BIGQUERY_POPULATION_GEOMETRY_COLUMN', 'geometry').strip()
    density_column = os.environ.get('BIGQUERY_POPULATION_DENSITY_COLUMN', 'population_density').strip()
    return (
        f'SELECT `{density_column}` AS population_density '
        f'FROM `{project_id}.{dataset}.{table}` '
        f'WHERE ST_CONTAINS(`{geometry_column}`, ST_GEOGPOINT(@lng, @lat)) LIMIT 1'
    )


def get_population_density(lat, lng):
    credentials = _credentials()
    if not credentials:
        return {'available': False, 'reason': 'BigQuery credentials are not configured'}
    project_id = os.environ.get('BIGQUERY_PROJECT_ID') or credentials.get('project_id')
    query = _query_text(project_id)
    if not project_id or not query:
        return {'available': False, 'reason': 'BigQuery population dataset/query is not configured'}
    try:
        token = _access_token(credentials)
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        body = {
            'query': query,
            'useLegacySql': False,
            'parameterMode': 'NAMED',
            'queryParameters': [
                {'name': 'lat', 'parameterType': {'type': 'FLOAT64'}, 'parameterValue': {'value': str(float(lat))}},
                {'name': 'lng', 'parameterType': {'type': 'FLOAT64'}, 'parameterValue': {'value': str(float(lng))}},
            ],
        }
        response = requests.post(
            f'https://bigquery.googleapis.com/bigquery/v2/projects/{project_id}/queries',
            headers=headers,
            json=body,
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get('jobComplete') and payload.get('jobReference', {}).get('jobId'):
            job_id = payload['jobReference']['jobId']
            location = payload['jobReference'].get('location')
            for _ in range(12):
                time.sleep(1)
                params = {'location': location} if location else {}
                poll = requests.get(
                    f'https://bigquery.googleapis.com/bigquery/v2/projects/{project_id}/queries/{job_id}',
                    headers=headers,
                    params=params,
                    timeout=30,
                )
                poll.raise_for_status()
                payload = poll.json()
                if payload.get('jobComplete'):
                    break
        if payload.get('errors'):
            return {'available': False, 'reason': 'BigQuery query failed'}
        rows = payload.get('rows') or []
        if not rows:
            return {'available': False, 'reason': 'No population density row found'}
        value = (rows[0].get('f') or [{}])[0].get('v')
        if value in (None, ''):
            return {'available': False, 'reason': 'Population density value is empty'}
        return {
            'available': True,
            'value': value,
            'unit': os.environ.get('BIGQUERY_POPULATION_UNIT', 'نسمة/كم²'),
            'source': 'Google BigQuery',
        }
    except Exception:
        return {'available': False, 'reason': 'BigQuery population lookup failed'}
