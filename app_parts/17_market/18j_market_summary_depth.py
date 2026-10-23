
# ---------------------------------------------------------------------------
# Market summary research depth.
#
# The summary fans out one researcher per (location, group, host). For a
# project with several cities/districts that is the most expensive stage of the
# study, so the client can choose a quick pass that keeps the top-priority
# hosts for every location and caps the total researchers, or the full sweep.
# ---------------------------------------------------------------------------

SUMMARY_RESEARCH_DEPTH_DEFAULT = 'full'
SUMMARY_RESEARCH_QUICK_HOSTS_PER_GROUP = 2
SUMMARY_RESEARCH_QUICK_JOB_CAP = 24
_SUMMARY_RESEARCH_QUICK_VALUES = {'quick', 'fast', 'سريع', 'اقتصادي'}


def summary_research_depth(payload):
    value = str((payload or {}).get('summaryResearchDepth')
                or (payload or {}).get('summary_research_depth') or '').strip().lower()
    return 'quick' if value in _SUMMARY_RESEARCH_QUICK_VALUES else 'full'


def limit_summary_research_jobs(jobs, depth='full'):
    """Keep every job in full mode; cap and prioritize the important sources
    in quick mode. Jobs arrive city-level first, then district-level, with the
    source hosts in catalog priority order."""
    jobs = list(jobs or [])
    if depth != 'quick':
        return jobs
    selected = []
    per_group = {}
    for job in jobs:
        if not job:
            continue
        group = job[0] if len(job) > 0 else {}
        city = job[2] if len(job) > 2 else ''
        district = job[3] if len(job) > 3 else ''
        key = (str(city or ''), str(district or ''),
               str((group or {}).get('key') or ''))
        used = per_group.get(key, 0)
        if used >= SUMMARY_RESEARCH_QUICK_HOSTS_PER_GROUP:
            continue
        per_group[key] = used + 1
        selected.append(job)
        if len(selected) >= SUMMARY_RESEARCH_QUICK_JOB_CAP:
            break
    return selected


def build_summary_research_jobs(payload, source_map, scope_activities_selected,
                                allowed_activity_hosts, scope, depth='full'):
    """One job per location, research group and source host, bounded by depth."""
    jobs = []
    for city_scope in (scope or {}).get('cities') or []:
        locations = [('', city_scope['name'])]
        locations.extend((district, city_scope['name'])
                         for district in city_scope.get('districts') or [])
        for district, city in locations:
            for group in _SUMMARY_RESEARCH_GROUPS:
                for host in source_map.get(group['key']) or []:
                    if scope_activities_selected and not market_study._host_in(
                            host, allowed_activity_hosts):
                        continue
                    if district and host in {'gaca.gov.sa', 'geo.stats.gov.sa'}:
                        continue
                    jobs.append((group, [host], city, district))
    return limit_summary_research_jobs(jobs, depth)
