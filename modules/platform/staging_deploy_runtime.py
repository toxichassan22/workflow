import json
import os
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


_CODE_SUFFIXES = {'.py', '.js', '.css'}
_PROTECTED_DIRS = {'uploads', 'outputs', 'venv', '.venv', '.git', '.deploy_backups', '.deploy_runs'}
_REQUEST_ID = re.compile(r'[A-Za-z0-9_-]{1,80}\Z')


def _read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _code_path(value):
    if not isinstance(value, str) or '\\' in value or ':' in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        return None
    if any(part in _PROTECTED_DIRS for part in path.parts) or path.suffix not in _CODE_SUFFIXES:
        return None
    return path.as_posix()


def archive_code(app_dir, paths):
    root = Path(app_dir).resolve()
    backup = root / '.deploy_backups' / uuid.uuid4().hex
    if not backup.resolve().is_relative_to(root):
        raise ValueError('Unsafe deployment backup directory')
    archived = []
    for value in sorted(set(paths)):
        relative = _code_path(value)
        if not relative:
            continue
        source = root / relative
        if not source.exists() and not source.is_symlink():
            continue
        if source.is_symlink() or not source.resolve().is_relative_to(root):
            raise ValueError(f'Unsafe obsolete code path: {relative}')
        if not source.is_file():
            continue
        destination = backup / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.replace(destination)
        archived.append(relative)
    if archived:
        print(f'Archived {len(archived)} obsolete code files in {backup.relative_to(root)}', flush=True)
    return archived


def app_part_paths(parts_dir):
    root = Path(parts_dir)
    groups = {}
    for path in root.rglob('*.py'):
        if '__pycache__' not in path.parts:
            groups.setdefault(path.name, []).append(path)
    chosen, legacy = [], []
    for name, paths in sorted(groups.items()):
        nested = [path for path in paths if path.parent != root]
        if len(nested) > 1:
            raise ValueError(f'Duplicate grouped app part: {name}')
        selected = nested[0] if nested else paths[0]
        chosen.append(str(selected))
        legacy.extend(path.relative_to(root.parent).as_posix()
                      for path in paths if path != selected)
    marker = _read_json(root.parent / '.deployed_commit')
    if legacy and marker.get('source') == 'github-staging':
        archive_code(root.parent, legacy)
    return chosen


def _tracked_files(repo_dir, revision, required=False):
    result = subprocess.run(['git', '-C', str(repo_dir), 'ls-tree', '-rz', '--name-only', revision],
                            capture_output=True, check=False)
    if result.returncode:
        if required:
            raise RuntimeError('Cannot read the target deployment file inventory')
        return set()
    return {path for item in result.stdout.decode('utf-8').split('\0')
            if (path := _code_path(item))}


def prepare_runtime(repo_dir, app_dir):
    root = Path(app_dir).resolve()
    current = _tracked_files(repo_dir, 'HEAD', required=True)
    inventory = _read_json(root / '.deploy_inventory.json')
    previous = {path for item in inventory.get('files', []) if (path := _code_path(item))}
    marker = _read_json(root / '.deployed_commit')
    old_commit = str(marker.get('deployed_commit') or marker.get('commit') or '')
    if re.fullmatch(r'[0-9a-fA-F]{7,40}', old_commit):
        previous.update(_tracked_files(repo_dir, old_commit))
    for path in current:
        parts = PurePosixPath(path).parts
        if len(parts) == 3 and parts[0] == 'modules':
            previous.add(parts[-1])
        for index, part in enumerate(parts[:-1]):
            if part == 'app_parts' or part.endswith('_parts'):
                flat = PurePosixPath(*parts[:index + 1], parts[-1]).as_posix()
                if flat != path:
                    previous.add(flat)
    archived = archive_code(root, previous - current)
    _write_json(root / '.deploy_inventory.json', {'files': sorted(current)})
    return archived


def sanitize_error(text, environment=None):
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', str(text or ''))
    matches = re.findall(r'^(?:[\w.]+(?:Error|Exception):[^\n]*|ERROR[: ][^\n]*|fatal:[^\n]*|error:[^\n]*)',
                         text, re.MULTILINE | re.IGNORECASE)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    summary = matches[-1] if matches else (lines[-1] if lines else '')
    environment = os.environ if environment is None else environment
    sensitive = sorted((str(value) for key, value in environment.items()
                        if value and re.search(r'KEY|TOKEN|PASS|SECRET|CREDENTIAL|URL', key, re.IGNORECASE)),
                       key=len, reverse=True)
    for value in sensitive:
        summary = summary.replace(value, '[redacted]')
    summary = re.sub(r'https?://\S+', '[redacted-url]', summary)
    summary = re.sub(r'(?i)\bbearer\s+[A-Za-z0-9._~-]+', 'Bearer [redacted]', summary)
    summary = re.sub(r'\bsk-(?:or-v1-)?[A-Za-z0-9_-]{12,}', '[redacted]', summary)
    summary = re.sub(r'(?i)\b(password|secret|token|api[_-]?key)[\"\']?\s*[:=]\s*'
                     r'(?:\"[^\"]*\"|\'[^\']*\'|[^\s,;}]+)', r'\1=[redacted]', summary)
    summary = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', summary)
    return ' '.join(summary.split())[:800]


def claim_request(app_dir, request_id):
    if not _REQUEST_ID.fullmatch(request_id):
        raise ValueError('Invalid deployment request ID')
    path = Path(app_dir) / '.deploy_runs' / (request_id + '.claim')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    os.close(descriptor)
    return True


def read_status(app_dir, request_id=''):
    root = Path(app_dir)
    if request_id:
        if not _REQUEST_ID.fullmatch(request_id):
            raise ValueError('Invalid deployment request ID')
        return _read_json(root / '.deploy_runs' / (request_id + '.json'))
    return _read_json(root / '.deploy_status')


def write_status(app_dir, commit, status, step, exit_code=0, request_id='', log_path=None, error=''):
    if status not in {'queued', 'running', 'deployed', 'failed'}:
        raise ValueError('Invalid deployment status')
    if request_id and not _REQUEST_ID.fullmatch(request_id):
        raise ValueError('Invalid deployment request ID')
    previous = read_status(app_dir, request_id)
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    started = previous.get('started_at') if previous.get('commit') == commit else None
    value = {'commit': commit, 'request_id': request_id, 'status': status, 'step': step,
             'exit_code': int(exit_code), 'started_at': started or now, 'updated_at': now,
             'finished_at': now if status in {'deployed', 'failed'} else None}
    if status == 'failed':
        if log_path and not error:
            try:
                with open(log_path, 'rb') as handle:
                    handle.seek(0, os.SEEK_END)
                    handle.seek(max(0, handle.tell() - 16000))
                    error = handle.read().decode('utf-8', errors='replace')
            except OSError:
                error = ''
        value['error'] = sanitize_error(error) or f'Deployment failed at {step} (exit {exit_code})'
    root = Path(app_dir)
    if request_id:
        _write_json(root / '.deploy_runs' / (request_id + '.json'), value)
    _write_json(root / '.deploy_status', value)
    return value
