"""Named task steps, so a progress bar can report what the server is doing.

A percentage nobody measured is worse than no percentage: the client ends up
watching a bar instead of the task. Every plan here is a real sequence the
worker walks, and a step contributes only once the worker enters it — a step
with a known unit count (slides, rows) contributes the share it finished.
Nothing in this module reads the clock, so a slow provider can never make the
bar look further along than the work is.
"""

STEP_PLANS = {
    # The planner is one blocking model call between two local stages; those
    # are the boundaries the worker can actually name.
    'slide_plan': (
        ('inputs', 'تجهيز بيانات المشروع'),
        ('ai', 'تحليل البيانات وبناء الهيكل'),
        ('arrange', 'ترتيب الأقسام والشرائح'),
        ('ready', 'تجهيز خطة العرض'),
    ),
}


def steps(plan_name):
    """The ordered step list a client renders as its checklist."""
    plan = _plan(plan_name)
    return [{'key': key, 'label': label} for key, label in plan]


def payload(plan_name, step_key, detail='', done=None, total=None, complete=False):
    """One job-progress document for the step the worker is on now.

    ``progress`` counts the steps already left plus the finished share of the
    current one. A running job never reports 100 — only ``complete=True`` does,
    so a stale percentage can never look like a finished task.
    """
    plan = _plan(plan_name)
    keys = [key for key, _label in plan]
    if step_key not in keys:
        raise ValueError(f'unknown step {step_key!r} for plan {plan_name!r}')
    index = keys.index(step_key)
    fraction = 1.0 if complete else _fraction(done, total)
    if complete:
        value = 100
    else:
        value = min(99, int(round(((index + fraction) / len(plan)) * 100)))
    return {
        'steps': steps(plan_name),
        'step': step_key,
        'stepLabel': plan[index][1],
        'stepIndex': index,
        'stepTotal': len(plan),
        'progress': value,
        # The client draws a number only for a fraction the server counted.
        # These values are finished steps of a named plan, never the clock.
        'progressMeasured': True,
        'stepDetail': str(detail or ''),
    }


def _plan(plan_name):
    plan = STEP_PLANS.get(plan_name)
    if not plan:
        raise ValueError(f'unknown progress plan {plan_name!r}')
    return plan


def _fraction(done, total):
    try:
        total_value = float(total)
        if total_value <= 0:
            return 0.0
        return max(0.0, min(1.0, float(done) / total_value))
    except (TypeError, ValueError):
        return 0.0
