"""The generation-rules editor behind the AI rules screen.

Split out of the rules/approvals part to keep every file under the line limit.
The stored value is a single text the design prompt appends verbatim, and the
admin agent writes it too, so the screen owns only the block between its two
markers; anything outside them is carried through every save untouched.
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Generation rules (the company's tone sheet behind the AI rules screen)
#
# The stored value is a single text the design prompt appends verbatim, and the
# admin agent writes it too. The screen therefore owns only the block between the
# two markers: any text outside them (typed through the agent) is carried through
# every save untouched, so neither editor can erase the other's work.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GENERATION_RULES_BLOCK_START = 'قواعد المنشأة — بداية'
GENERATION_RULES_BLOCK_END = 'قواعد المنشأة — نهاية'
GENERATION_RULES_MAX_CHARS = 8000
GENERATION_RULES_MAX_TERMS = 40
GENERATION_RULES_MAX_TERM_LENGTH = 60
GENERATION_RULES_MAX_DIRECTIVES = 4000

GENERATION_RULES_TONES = {
    'analytical': 'تحليلي تنفيذي',
    'marketing': 'تسويقي راقٍ',
    'engineering': 'هندسي دقيق',
}

GENERATION_RULES_TONE_SENTENCES = {
    'analytical': 'تحليلي تنفيذي: جمل قصيرة، أرقام مسندة من بيانات المشروع، ولغة مستثمر بلا مبالغة.',
    'marketing': 'تسويقي راقٍ: صياغة إقناعية هادئة تُبرز القيمة دون مبالغة أو وعود.',
    'engineering': 'هندسي دقيق: مصطلحات التخطيط والاشتراطات والمساحات كما وردت في مستندات المشروع.',
}


def _split_generation_rules(raw):
    """Return (text outside the managed block, block body)."""
    text = str(raw or '')
    start = text.find(GENERATION_RULES_BLOCK_START)
    if start == -1:
        return text.strip(), ''
    end = text.find(GENERATION_RULES_BLOCK_END, start)
    if end == -1:
        # An unterminated block is not ours to rewrite: keep it as outside text.
        return text.strip(), ''
    body = text[start + len(GENERATION_RULES_BLOCK_START):end].strip()
    outside = (text[:start] + '\n' + text[end + len(GENERATION_RULES_BLOCK_END):]).strip()
    return outside, body


def _split_terms(value):
    parts = re.split(r'[،,|]', str(value or ''))
    return [part.strip() for part in parts if part.strip()]


def _parse_generation_rules(raw):
    outside, body = _split_generation_rules(raw)
    tone = ''
    approved = []
    banned = []
    directives = []
    in_directives = False
    for line in (body.splitlines() if body else []):
        stripped = line.strip()
        if in_directives:
            directives.append(line)
            continue
        if stripped.startswith('النبرة:'):
            value = stripped.split(':', 1)[1].strip()
            for key, label in GENERATION_RULES_TONES.items():
                if value.startswith(label):
                    tone = key
                    break
        elif stripped.startswith('مصطلحات معتمدة:'):
            approved = _split_terms(stripped.split(':', 1)[1])
        elif stripped.startswith('مصطلحات ممنوعة:'):
            banned = _split_terms(stripped.split(':', 1)[1])
        elif stripped.startswith('توجيهات إضافية'):
            in_directives = True
            tail = stripped.split(':', 1)
            if len(tail) == 2 and tail[1].strip():
                directives.append(tail[1].strip())
    return {
        'tone': tone,
        'approved': approved,
        'banned': banned,
        'directives': '\n'.join(directives).strip(),
        'extra': outside,
    }


def _compose_generation_rules_block(rules):
    lines = [GENERATION_RULES_BLOCK_START]
    tone = rules.get('tone') or ''
    if tone in GENERATION_RULES_TONE_SENTENCES:
        lines.append('النبرة: ' + GENERATION_RULES_TONE_SENTENCES[tone])
    approved = rules.get('approved') or []
    if approved:
        lines.append('مصطلحات معتمدة: ' + '، '.join(approved))
    banned = rules.get('banned') or []
    if banned:
        lines.append('مصطلحات ممنوعة: ' + '، '.join(banned))
    directives = str(rules.get('directives') or '').strip()
    if directives:
        lines.append('توجيهات إضافية للأقسام:')
        lines.append(directives)
    if len(lines) == 1:
        return ''
    return '\n'.join(lines) + '\n' + GENERATION_RULES_BLOCK_END


def _validate_generation_rules_payload(data):
    """Return (rules, error_message). Unknown keys are ignored, not trusted."""
    tone = str(data.get('tone') or '').strip()
    if tone and tone not in GENERATION_RULES_TONES:
        return None, 'نبرة غير معروفة'

    def _terms(key):
        raw = data.get(key) or []
        if not isinstance(raw, list):
            raise ValueError
        terms = []
        for item in raw:
            term = str(item or '').strip()
            if not term:
                continue
            if len(term) > GENERATION_RULES_MAX_TERM_LENGTH:
                return None
            if term not in terms:
                terms.append(term)
        if len(terms) > GENERATION_RULES_MAX_TERMS:
            return None
        return terms

    try:
        approved = _terms('approved')
        banned = _terms('banned')
    except ValueError:
        return None, 'قائمة المصطلحات غير صالحة'
    if approved is None or banned is None:
        return None, 'عدد المصطلحات أو طول المصطلح يتجاوز الحد'

    directives = str(data.get('directives') or '').strip()
    if len(directives) > GENERATION_RULES_MAX_DIRECTIVES:
        return None, 'توجيهات الأقسام أطول من الحد المسموح'

    return {'tone': tone, 'approved': approved, 'banned': banned,
            'directives': directives}, ''


def _generation_rules_payload(rules, raw):
    last_change = db.get_last_ai_rule_change(g.tenant_id, 'set_generation_rules') or {}
    created_at = str(last_change.get('created_at') or '')
    updated_at = created_at.replace(' ', 'T') + 'Z' if created_at else ''
    return {
        'success': True,
        'rules': rules,
        'raw': raw,
        'updatedAt': updated_at,
        'maxChars': GENERATION_RULES_MAX_CHARS,
        'tones': GENERATION_RULES_TONES,
    }


@app.route('/api/ai-rules/generation-rules', methods=['GET'])
@require_permission('ai_rules')
def api_get_generation_rules():
    raw = (db.get_branding(g.tenant_id) or {}).get('generation_rules') or ''
    return jsonify(_generation_rules_payload(_parse_generation_rules(raw), raw))


@app.route('/api/ai-rules/generation-rules/preview', methods=['POST'])
@require_permission('ai_rules')
def api_preview_generation_rules():
    rules, error = _validate_generation_rules_payload(request.json or {})
    if error:
        return jsonify({'error': error}), 400
    block = _compose_generation_rules_block(rules)
    raw = (db.get_branding(g.tenant_id) or {}).get('generation_rules') or ''
    outside, _ = _split_generation_rules(raw)
    composed = (outside + '\n\n' + block).strip() if outside and block else (block or outside)
    return jsonify({'success': True, 'block': block, 'composed': composed})


@app.route('/api/ai-rules/generation-rules', methods=['POST'])
@require_permission('ai_rules')
def api_save_generation_rules():
    rules, error = _validate_generation_rules_payload(request.json or {})
    if error:
        return jsonify({'error': error}), 400

    branding = db.get_branding(g.tenant_id) or {}
    old_raw = str(branding.get('generation_rules') or '')
    outside, _ = _split_generation_rules(old_raw)
    block = _compose_generation_rules_block(rules)
    if outside and block:
        new_raw = outside + '\n\n' + block
    else:
        new_raw = block or outside
    if len(new_raw) > GENERATION_RULES_MAX_CHARS:
        return jsonify({
            'error': 'قواعد التوليد تتجاوز الحد المسموح',
            'error_code': 'RULES_TOO_LONG',
            'maxChars': GENERATION_RULES_MAX_CHARS,
        }), 400

    db.update_branding(g.tenant_id, generation_rules=new_raw)
    if new_raw != old_raw:
        db.log_ai_rule_change(
            tenant_id=g.tenant_id,
            rule_category='company_generation_rules',
            rule_key='set_generation_rules',
            old_value=old_raw,
            new_value=new_raw,
            risk_level='yellow',
            user_id=g.user_id,
            user_name=g.user_name or 'Admin',
        )
    parsed = _parse_generation_rules(new_raw)
    return jsonify(_generation_rules_payload(parsed, new_raw))
