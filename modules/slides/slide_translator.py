"""Translate an existing deck's text without regenerating a single slide.

The deck is HTML: layout, colours, images, tables and inline emphasis are all
markup, and only the words inside it carry the Arabic. Regenerating the deck in
English costs a full generation and can come back with a different deck, so the
translation runs on the markup itself:

* Text is grouped into runs between block boundaries, so a paragraph split by
  ``<strong>`` is translated as ONE sentence instead of three fragments. Inline
  tags inside a run become ``⟦0⟧`` placeholders and are put back untouched.
* Only text that carries Arabic is sent; numbers, Latin names, image tokens and
  CSS are never translated.
* A translation is accepted only when every placeholder survived exactly once
  and every number in the source is still there. A unit that fails the check
  keeps its Arabic text instead of corrupting the slide.
* The caller supplies the translator callable, so this module never picks a
  model or talks to a provider; the route wires the configured model in.

Public entry point: :func:`translate_slides`.
"""

import copy
import json
import re

AR_RE = re.compile(r'[\u0600-\u06FF]')
TAG_SPLIT_RE = re.compile(r'(<[^>]*>)')
PLACEHOLDER_RE = re.compile(r'⟦(\d+)⟧')
NUMERIC_RE = re.compile(r'\d+(?:[.,]\d+)*')
ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')

# A block boundary ends a sentence: text on either side is translated as its own
# unit. Inline tags (strong, b, span, a, small, sup...) stay inside the unit and
# become placeholders, which is what keeps the emphasis on the right words.
BLOCK_TAGS = {
    'div', 'p', 'section', 'header', 'footer', 'main', 'article', 'aside',
    'nav', 'li', 'ul', 'ol', 'dl', 'dt', 'dd', 'td', 'th', 'tr', 'table',
    'tbody', 'thead', 'tfoot', 'blockquote', 'figcaption', 'figure',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'hr', 'img', 'figure',
}
# Style and script carry code, and an inline SVG is a drawing (map overlays,
# icons): translating inside them would break the page, not the deck text.
SKIP_TAGS = {'style', 'script', 'svg'}
VOID_TAGS = {'br', 'hr', 'img', 'input', 'source', 'meta', 'link', 'wbr'}

MAX_UNITS_PER_CALL = 40
MAX_CHARS_PER_CALL = 5000


def _tag_name(token):
    match = re.match(r'<\s*(/?)\s*([a-zA-Z0-9:-]+)', token)
    if not match:
        return '', False
    return match.group(2).lower(), bool(match.group(1))


def _numbers(text):
    """Every number in a string, digit-only, so 18,500 and 18500 compare equal."""
    normalised = str(text).translate(ARABIC_DIGITS)
    return sorted(re.sub(r'[.,\s]', '', value) for value in NUMERIC_RE.findall(normalised))


def _placeholders(text):
    return sorted(PLACEHOLDER_RE.findall(str(text)))


def _new_unit(start):
    return {'start': start, 'end': start, 'template': [], 'tags': [], 'pieces': []}


def _finish_unit(unit, units):
    template = ''.join(unit['template'])
    if not template.strip() or not AR_RE.search(template):
        return
    unit['template'] = template
    units.append(unit)


def collect_units(html):
    """Split slide HTML into translatable runs, leaving every tag in place.

    Each unit records the token span it covers (``start``/``end``) and the text
    to translate: the source text with ``⟦n⟧`` where an inline tag sat. Anything
    inside ``style``/``script``/``svg`` and text with no Arabic is skipped.
    """
    tokens = TAG_SPLIT_RE.split(html or '')
    units = []
    current = None
    skip_depth = 0
    for index, token in enumerate(tokens):
        if not token:
            continue
        if token.startswith('<'):
            name, closing = _tag_name(token)
            if name in SKIP_TAGS:
                if closing:
                    skip_depth = max(0, skip_depth - 1)
                elif not token.rstrip().endswith('/>'):
                    skip_depth += 1
                if current is not None:
                    _finish_unit(current, units)
                    current = None
                continue
            if skip_depth:
                continue
            if name in BLOCK_TAGS:
                if current is not None:
                    _finish_unit(current, units)
                    current = None
                continue
            if current is None:
                current = _new_unit(index)
            current['template'].append('⟦%d⟧' % len(current['tags']))
            current['tags'].append(token)
            current['end'] = index
            continue
        if skip_depth:
            continue
        if current is None:
            if not AR_RE.search(token):
                continue
            current = _new_unit(index)
        current['template'].append(token)
        current['pieces'].append(index)
        current['end'] = index
    if current is not None:
        _finish_unit(current, units)
    return tokens, units


def _rebuild(tokens, units, translations):
    """Replace each accepted unit's token span with its translated markup."""
    replacements = {}
    for unit, translated in zip(units, translations):
        if not translated:
            continue
        parts = PLACEHOLDER_RE.split(translated)
        rebuilt = []
        for position, part in enumerate(parts):
            if position % 2 == 0:
                rebuilt.append(part)
                continue
            tag_index = int(part)
            if tag_index >= len(unit['tags']):
                rebuilt = None
                break
            rebuilt.append(unit['tags'][tag_index])
        if rebuilt is None:
            continue
        replacements[unit['start']] = (unit['end'], ''.join(rebuilt))
    if not replacements:
        return ''.join(tokens)
    output = []
    index = 0
    while index < len(tokens):
        replacement = replacements.get(index)
        if replacement is None:
            output.append(tokens[index])
            index += 1
            continue
        end, markup = replacement
        output.append(markup)
        index = end + 1
    return ''.join(output)


def _accepted(source, translated):
    """A translation is usable only if it kept the structure and the numbers."""
    if not translated or not str(translated).strip():
        return False
    if _placeholders(translated) != _placeholders(source):
        return False
    if _numbers(translated) != _numbers(source):
        return False
    return str(translated).strip() != str(source).strip()


def _chunks(items, max_items=MAX_UNITS_PER_CALL, max_chars=MAX_CHARS_PER_CALL):
    batch, size = [], 0
    for item in items:
        length = len(item)
        if batch and (len(batch) >= max_items or size + length > max_chars):
            yield batch
            batch, size = [], 0
        batch.append(item)
        size += length
    if batch:
        yield batch


def _translate_batch(texts, translator):
    """Run the caller's translator over one chunk; a failure leaves it Arabic."""
    if not texts:
        return []
    try:
        result = translator(list(texts))
    except Exception as exc:  # a provider failure must not damage the deck
        print(f'[SLIDE TRANSLATE] batch failed: {exc}')
        return [None] * len(texts)
    if not isinstance(result, (list, tuple)) or len(result) != len(texts):
        return [None] * len(texts)
    return list(result)


def translate_html(html, translator):
    """Translate one slide's text; returns (html, stats)."""
    tokens, units = collect_units(html)
    stats = {'units': 0, 'translated': 0, 'skipped': 0}
    if not units:
        return html, stats
    stats['units'] = len(units)
    translations = []
    for batch in _chunks([unit['template'] for unit in units]):
        translations.extend(_translate_batch(batch, translator))
    accepted = []
    for unit, translated in zip(units, translations):
        if _accepted(unit['template'], translated):
            accepted.append(translated)
            stats['translated'] += 1
        else:
            accepted.append(None)
            stats['skipped'] += 1
    return _rebuild(tokens, units, accepted), stats


def _plain(texts, translator):
    """Translate plain strings (slide titles, index entries) in one pass."""
    values = [str(text) for text in texts]
    results = []
    for batch in _chunks(values):
        results.extend(_translate_batch(batch, translator))
    out = []
    for source, translated in zip(values, results):
        out.append(translated if _accepted(source, translated) else None)
    return out


def translate_slides(slides, translator, target_lang='en'):
    """Translate a deck's slides in place-free fashion.

    ``translator`` is ``callable(list_of_strings) -> list_of_strings`` and owns
    the model call. Every slide is copied, so the caller's Arabic deck is never
    mutated. Returns ``(translated_slides, stats)``.
    """
    if target_lang != 'en':
        raise ValueError('unsupported target language: %s' % target_lang)
    translated_slides = copy.deepcopy(slides or [])
    stats = {'slides': 0, 'units': 0, 'translated': 0, 'skipped': 0, 'titles': 0}
    for slide in translated_slides:
        if not isinstance(slide, dict):
            continue
        stats['slides'] += 1
        html = slide.get('html')
        if isinstance(html, str) and html.strip() and AR_RE.search(html):
            slide['html'], slide_stats = translate_html(html, translator)
            for key in ('units', 'translated', 'skipped'):
                stats[key] += slide_stats[key]
        title = slide.get('title')
        if isinstance(title, str) and AR_RE.search(title):
            value = _plain([title], translator)[0]
            if value:
                slide['title'] = value
                stats['titles'] += 1
        entries = slide.get('indexEntries')
        if isinstance(entries, list):
            pending = [
                entry for entry in entries
                if isinstance(entry, dict) and isinstance(entry.get('title'), str)
                and AR_RE.search(entry['title'])
            ]
            if pending:
                values = _plain([entry['title'] for entry in pending], translator)
                for entry, value in zip(pending, values):
                    if value:
                        entry['title'] = value
                        stats['titles'] += 1
    return translated_slides, stats


def deck_has_arabic(slides):
    """True when the deck carries any Arabic text worth translating."""
    return any(
        isinstance(slide, dict) and (
            (isinstance(slide.get('html'), str) and AR_RE.search(slide['html']))
            or (isinstance(slide.get('title'), str) and AR_RE.search(slide['title']))
        )
        for slide in (slides or [])
    )


def translation_prompt():
    """The system prompt the route sends with each batch."""
    return (
        'You are a professional Arabic-to-English translator for real-estate '
        'presentation slides. Translate each item into natural, professional '
        'English suitable for an investment deck. Rules: keep every ⟦n⟧ '
        'placeholder exactly as written and in the same order (they are inline '
        'formatting tags, never translate or renumber them); keep numbers, '
        'percentages, currency, units and proper nouns accurate; never add, '
        'merge, split or explain items; translate every item even when it is a '
        'short label. Return only JSON: '
        '{"items":[{"id":<id>,"text":"<translation>"}]}'
    )


def build_batch_payload(texts):
    """The user message for one batch, as JSON the model can mirror back."""
    return json.dumps(
        {'items': [{'id': index, 'text': text} for index, text in enumerate(texts)]},
        ensure_ascii=False,
    )


def parse_batch_response(content, expected):
    """Map the model's JSON back onto the batch, keeping order and gaps."""
    if not content:
        return [None] * expected
    text = str(content).strip()
    if text.startswith('```'):
        text = re.sub(r'^```[a-zA-Z]*\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
    try:
        data = json.loads(text)
    except ValueError:
        start, end = text.find('{'), text.rfind('}')
        if start == -1 or end <= start:
            return [None] * expected
        try:
            data = json.loads(text[start:end + 1])
        except ValueError:
            return [None] * expected
    items = data.get('items') if isinstance(data, dict) else data
    if not isinstance(items, list):
        return [None] * expected
    out = [None] * expected
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get('id'))
        except (TypeError, ValueError):
            continue
        if 0 <= index < expected:
            value = item.get('text')
            out[index] = value if isinstance(value, str) else None
    return out
