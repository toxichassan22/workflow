"""Enforce source boundaries on market-study researcher output."""


def _summary_source_url_allowed(url, hosts):
    host = market_study._source_host(url)
    host = str(host or '').lower().removeprefix('www.')
    for allowed in hosts or []:
        allowed = str(allowed or '').lower().removeprefix('www.')
        if host == allowed or host.endswith('.' + allowed):
            return True
    return False


def _summary_restrict_research_result(parsed, hosts):
    """Keep only structured findings that cite the researcher's assigned host."""
    if not isinstance(parsed, dict):
        return {}, 0
    filtered = 0
    output = {'group': str(parsed.get('group') or '')}
    url_keys = {'coverage': 'url', 'findings': 'source_url', 'sources': 'url'}
    for key, url_key in url_keys.items():
        rows = parsed.get(key) if isinstance(parsed.get(key), list) else []
        allowed_rows = []
        for row in rows:
            if (not isinstance(row, dict)
                    or not _summary_source_url_allowed(row.get(url_key), hosts)):
                filtered += 1
                continue
            allowed_rows.append(row)
        output[key] = allowed_rows
    gaps = parsed.get('coverage_gaps')
    output['coverage_gaps'] = ([str(gap)[:1000] for gap in gaps
                                if str(gap).strip()]
                               if isinstance(gaps, list) else [])
    output['filtered_outside_source_rows'] = filtered
    return output, filtered
