"""Validate designer targets against the workspace seen by the planner."""

import copy
import re


EDIT_TOOLS = {
    'edit_slides', 'edit_design_slide', 'edit_design_slides', 'apply_watermark',
    'remove_watermark', 'apply_image_descriptions', 'insert_team_logo',
    'insert_company_logo_panel', 'insert_canonical_map', 'insert_map',
    'insert_financial_chart', 'update_financial_chart',
}
SINGLE_TOOLS = {
    'duplicate_slide', 'clone_slide', 'split_slide', 'split_dense_slide',
    'generate_image', 'generate_design_image', 'insert_image_into_slide',
}
STRUCTURAL_TOOLS = {
    'delete_slide', 'remove_slide', 'duplicate_slide', 'clone_slide',
    'reorder_slides', 'move_slide', 'split_slide', 'split_dense_slide',
    'merge_slides', 'combine_slides', 'create_slide', 'create_design_slide',
}


class TargetError(ValueError):
    pass


def slide_number(value, count):
    if isinstance(value, bool) or not re.fullmatch(r'\d+', str(value).strip()):
        raise TargetError('رقم الشريحة غير صالح؛ لم يتغير العرض.')
    number = int(value)
    if not 1 <= number <= count:
        raise TargetError(f'رقم الشريحة {number} خارج العرض؛ لم يتغير العرض.')
    return number


def resolve_indexes(params, count, current_index):
    target = params.get('target', params.get('scope', 'current'))
    raw = params.get('indexes', params.get('slideIndexes'))
    if target in ('all', 'كل', 'all_slides', 'presentation'):
        return list(range(count))
    if raw is not None:
        raw = [raw] if isinstance(raw, int) else raw
        if not isinstance(raw, list) or (not raw and target == 'indexes'):
            raise TargetError('لم تصل أرقام الشرائح المستهدفة؛ لم يتغير العرض.')
        if raw:
            return list(dict.fromkeys(slide_number(n, count) - 1 for n in raw))
    if 'slideIndex' in params:
        return [slide_number(params['slideIndex'], count) - 1]
    if target == 'indexes':
        raise TargetError('لم تصل أرقام الشرائح المستهدفة؛ لم يتغير العرض.')
    if target not in ('current', 'auto', None, ''):
        raise TargetError('نطاق الشرائح غير معروف؛ لم يتغير العرض.')
    return [slide_number(current_index + 1, count) - 1]


def explicit_slide_numbers(message):
    text = str(message or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789'))

    # Check for standalone slide specification: e.g. '21', 'رقم 21', 'شريحه 21'
    standalone = re.fullmatch(
        r'\s*(?:(?:ال)?(?:شريح[ةه]|شرايح|شرائح|سلايد[ةهات]*|صفح[ةه]|صفحات|رقم)\s*)?#?\s*(\d+)\s*',
        text, re.I
    )
    if standalone:
        return [int(standalone.group(1))]

    # Handle correction phrasing: e.g. '21 مش 1' or 'انا بقولك 21 مش 1' or 'شريحة 21 مش 1' or '21 بدل 1'
    correction = re.search(
        r'(\d+)\s*(?:مش|مو|ليس|بدل)\s*(?:ال)?(?:شريح[ةه]|سلايد[ةه]?|صفح[ةه]|رقم)?\s*\d+',
        text, re.I
    )
    if correction:
        return [int(correction.group(1))]

    # Negated or contrasting references need conversation-aware interpretation.
    if re.search(r'\b(?:لا|مش|ليس|بدل|عدا|باستثناء|except|not)\b', text, re.I):
        return None
    reference = re.search(r'\b(?:زي|مثل|نفس|مطابق|match|like)\b', text, re.I)
    if reference:
        text = text[:reference.start()]
    matches = re.finditer(
        r'(?:(?:ال)?(?:شريح[ةه]|شرايح|شرائح|سلايد[ةهات]*|صفح[ةه]|صفحات)|slides?|(?:من|في)\s+رقم)\s*(?:رقم\s*)?'
        r'(\d+(?:\s*(?:،|,|و|and|إلى|الى|to|-)\s*\d+)*)', text, re.I)
    numbers = []
    for match in matches:
        chunk = match.group(1)
        pieces = re.split(r'\s*(،|,|و|and|إلى|الى|to|-)\s*', chunk, flags=re.I)
        first = int(pieces[0])
        numbers.append(first)
        for i in range(1, len(pieces), 2):
            end = int(pieces[i + 1])
            if pieces[i].lower() in ('إلى', 'الى', 'to', '-'):
                if end < first or end - first > 500:
                    raise TargetError('نطاق أرقام الشرائح غير صالح؛ لم يتغير العرض.')
                numbers.extend(range(first + 1, end + 1))
            else:
                numbers.append(end)
            first = end
    return list(dict.fromkeys(numbers)) or None


def prepare_actions(actions, payload, message, slides, current_index):
    count = len(slides)
    prepared = copy.deepcopy(actions)
    explicit = payload.get('indexes')
    if payload.get('target') == 'current' or payload.get('scope') == 'current':
        explicit = [slide_number(current_index + 1, count)]
    if explicit:
        if not isinstance(explicit, list):
            raise TargetError('نطاق الشرائح المحدد غير صالح؛ لم يتغير العرض.')
        explicit = [slide_number(n, count) for n in explicit]
    else:
        explicit = explicit_slide_numbers(message)
        if explicit:
            explicit = [slide_number(n, count) for n in explicit]
    force_all = payload.get('target') == 'all' or payload.get('scope') == 'all'
    for action in prepared:
        tool = action.get('tool')
        params = action.get('params')
        if not isinstance(params, dict):
            raise TargetError('معاملات طلب التعديل غير صالحة؛ لم يتغير العرض.')
        targets = []
        if tool in EDIT_TOOLS:
            targets = resolve_indexes(params, count, current_index)
            if explicit and set(targets) != {n - 1 for n in explicit}:
                # A list may be distributed across actions, but never expanded.
                if not set(targets).issubset({n - 1 for n in explicit}):
                    raise TargetError('خطة التعديل لا تطابق الشرائح المحددة؛ لم يتغير العرض.')
            if force_all and not explicit:
                targets = list(range(count))
            params.update(target='indexes', indexes=[i + 1 for i in targets])
        elif tool in SINGLE_TOOLS:
            key = 'slideIndex' if tool in {'generate_image', 'generate_design_image', 'insert_image_into_slide'} else 'slide_number'
            value = params.get(key, current_index + 1)
            params[key] = slide_number(value, count)
            targets = [params[key] - 1]
        elif tool in ('delete_slide', 'remove_slide'):
            raw = params.get('slide_numbers') or [params.get('slide_number', current_index + 1)]
            if not isinstance(raw, list):
                raise TargetError('أرقام الحذف غير صالحة؛ لم يتغير العرض.')
            params['slide_numbers'] = list(dict.fromkeys(slide_number(n, count) for n in raw))
            targets = [n - 1 for n in params['slide_numbers']]
        elif tool in ('merge_slides', 'combine_slides'):
            raw = params.get('slide_numbers') or [params.get('first_slide'), params.get('second_slide')]
            if not isinstance(raw, list) or len(raw) != 2:
                raise TargetError('الدمج يتطلب تحديد شريحتين؛ لم يتغير العرض.')
            params['slide_numbers'] = [slide_number(n, count) for n in raw]
            targets = [n - 1 for n in params['slide_numbers']]
        elif tool in ('reorder_slides', 'move_slide'):
            for key in ('from_index', 'to_index'):
                params[key] = slide_number(params.get(key), count)
            targets = [params['from_index'] - 1]
        action['_original_targets'] = targets
    if explicit:
        edit_actions = [a for a in prepared if a.get('tool') in EDIT_TOOLS]
        if edit_actions and not any(a.get('tool') in STRUCTURAL_TOOLS for a in prepared):
            actual = {i + 1 for a in edit_actions for i in a['_original_targets']}
            if actual != set(explicit):
                raise TargetError('خطة التعديل لا تشمل كل الشرائح المحددة؛ لم يتغير العرض.')
    return prepared


def remap_action(action, original_slides, slides):
    mapped = copy.deepcopy(action)
    tool, params = mapped.get('tool'), mapped['params']

    def position(number):
        original = original_slides[number - 1]
        for index, slide in enumerate(slides):
            if slide is original:
                return index + 1
        raise TargetError('تغيرت شريحة مستهدفة بعملية سابقة؛ لم تُطبق نتيجة جزئية.')

    if tool in EDIT_TOOLS:
        params['indexes'] = [position(n) for n in params['indexes']]
        params.pop('slideIndex', None)
    elif tool in SINGLE_TOOLS:
        key = 'slideIndex' if tool in {'generate_image', 'generate_design_image', 'insert_image_into_slide'} else 'slide_number'
        params[key] = position(params[key])
    elif tool in ('delete_slide', 'remove_slide', 'merge_slides', 'combine_slides'):
        params['slide_numbers'] = [position(n) for n in params['slide_numbers']]
    elif tool in ('reorder_slides', 'move_slide'):
        params['from_index'] = position(params['from_index'])
        params['to_index'] = position(params['to_index'])
    return mapped
