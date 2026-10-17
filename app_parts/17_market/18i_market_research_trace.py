"""Tenant-scoped JSONL audit trail for market research browser activity."""

import json as _market_trace_json
import os as _market_trace_os
import re as _market_trace_re
import threading as _market_trace_threading


_MARKET_TRACE_SECRET_KEY = _market_trace_re.compile(
    r'(?:password|passwd|secret|token|authorization|cookie|api.?key|email|phone|mobile|card|cvv|otp)',
    _market_trace_re.I)
_MARKET_TRACE_SECRET_VALUE = _market_trace_re.compile(
    r'(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+|([?&](?:token|key|secret|signature|auth)=)[^&\s]+'
)
_MARKET_TRACE_EMAIL = _market_trace_re.compile(
    r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', _market_trace_re.I)
_MARKET_TRACE_PHONE = _market_trace_re.compile(
    r'(?<!\d)(?:(?:\+?966|0)5\d{8})(?!\d)')
_MARKET_TRACE_MAX_BYTES = 256 * 1024 * 1024


def _market_trace_sanitize(value, key='', depth=0):
    if _MARKET_TRACE_SECRET_KEY.search(str(key or '')):
        return '[redacted]'
    if depth > 8:
        return '[depth limited]'
    if isinstance(value, dict):
        return {str(item_key)[:120]: _market_trace_sanitize(item, str(item_key), depth + 1)
                for item_key, item in list(value.items())[:80]}
    if isinstance(value, (list, tuple)):
        return [_market_trace_sanitize(item, key, depth + 1) for item in value[:50]]
    if isinstance(value, str):
        cleaned = _MARKET_TRACE_SECRET_VALUE.sub(
            lambda match: (match.group(1) or match.group(2) or '') + '[redacted]', value)
        cleaned = _MARKET_TRACE_EMAIL.sub('[redacted email]', cleaned)
        cleaned = _MARKET_TRACE_PHONE.sub('[redacted phone]', cleaned)
        return cleaned[:12000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:1000]


def _market_research_trace_path(tenant_id, job_id):
    return _market_trace_os.path.join(
        _market_job_dir(tenant_id), f'{str(job_id)}.research.jsonl')


def _market_research_trace_writer(tenant_id, job_id):
    """Append sanitized browser actions and observations for one market job."""
    path = _market_research_trace_path(tenant_id, job_id)
    _market_trace_os.makedirs(_market_trace_os.path.dirname(path), exist_ok=True)
    lock = _market_trace_threading.Lock()
    trace_full = False

    def write(event):
        nonlocal trace_full
        if not isinstance(event, dict):
            return
        record = _market_trace_sanitize(event)
        line = _market_trace_json.dumps(record, ensure_ascii=False, default=str) + '\n'
        with lock:
            if trace_full:
                return
            try:
                existing_bytes = (_market_trace_os.path.getsize(path)
                                  if _market_trace_os.path.exists(path) else 0)
                if existing_bytes + len(line.encode('utf-8')) > _MARKET_TRACE_MAX_BYTES:
                    marker = _market_trace_json.dumps({
                        'event': 'trace_limit_reached', 'limit_bytes': _MARKET_TRACE_MAX_BYTES,
                    }, ensure_ascii=False) + '\n'
                    with open(path, 'a', encoding='utf-8') as handle:
                        handle.write(marker)
                        handle.flush()
                    trace_full = True
                    return
                with open(path, 'a', encoding='utf-8') as handle:
                    handle.write(line)
                    handle.flush()
            except OSError as exc:
                trace_full = True
                print(f'[MARKET SUMMARY] research trace write failed: {exc}')

    return write
