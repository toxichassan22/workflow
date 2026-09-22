


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Training entries: the per-tenant knowledge rows and the trimmed
# context block the agent and designer chats consume.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ─────────────────────────────────────────────────────────────────────────────
# Training Data (per-tenant GLM training)
# ─────────────────────────────────────────────────────────────────────────────

def get_training_data(tenant_id, active_only=False):
    """Get training data that belongs to exactly one tenant."""
    conn = get_db()
    query = 'SELECT * FROM tenant_training_data WHERE tenant_id = ?'
    params = [tenant_id]
    if active_only:
        query += ' AND is_active = 1'
    query += ' ORDER BY created_at DESC'
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_training_entry(tenant_id, entry_id):
    """Return one training record only if it belongs to the requesting tenant."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM tenant_training_data WHERE id = ? AND tenant_id = ?',
        (entry_id, tenant_id)
    ).fetchone()
    return dict(row) if row else None


def create_training_entry(tenant_id, title, content, category='general', image_path=None,
                          image_analysis=None, image_type=None, image_description=None):
    """Create a tenant-scoped training data entry."""
    conn = get_db()
    entry_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO tenant_training_data
           (id, tenant_id, title, content, category, image_path, image_analysis, image_type, image_description)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (entry_id, tenant_id, title, content, category, image_path, image_analysis,
         image_type, image_description)
    )
    conn.commit()
    return entry_id


def update_training_entry(tenant_id, entry_id, **kwargs):
    """Update a tenant's entry and never cross the tenant boundary."""
    conn = get_db()
    allowed = [
        'title', 'content', 'category', 'is_active', 'image_path', 'image_analysis',
        'image_type', 'image_description'
    ]
    sets = []
    vals = []
    for key in allowed:
        if key in kwargs:
            sets.append(f'{key} = ?')
            vals.append(kwargs[key])
    if not sets:
        return False
    sets.append("updated_at = datetime('now')")
    vals.extend([entry_id, tenant_id])
    cursor = conn.execute(
        f'UPDATE tenant_training_data SET {", ".join(sets)} WHERE id = ? AND tenant_id = ?',
        vals
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_training_entry(tenant_id, entry_id):
    """Delete a training entry only from its owning tenant."""
    conn = get_db()
    cursor = conn.execute(
        'DELETE FROM tenant_training_data WHERE id = ? AND tenant_id = ?',
        (entry_id, tenant_id)
    )
    conn.commit()
    return cursor.rowcount > 0


# Training categories each AI surface accepts. 'general' and 'chat' entries
# reach every surface. A surface absent from the map — or None — hears every
# active entry (slides mix text and visuals, so they take everything).
_TRAINING_SURFACE_CATEGORIES = {
    'design':  {'general', 'chat', 'design', 'style', 'image_reference'},
    'content': {'general', 'chat', 'content'},
}


def get_training_context(tenant_id, max_entries=20, max_chars=12000, surface=None):
    """Build bounded, tenant-only context for AI calls.

    ``surface`` optionally scopes which training entries apply: a 'content'
    surface hears general/chat and content entries, a 'design' surface hears
    the visual categories plus anything carrying a reference image. Entries
    with no category count as 'general'.

    Image files themselves remain in tenant storage.  Only the tenant's saved
    description and analysis are supplied to the model as contextual text.
    """
    entries = get_training_data(tenant_id, active_only=True)
    allowed = _TRAINING_SURFACE_CATEGORIES.get(surface)
    if allowed is not None:
        if surface == 'design':
            entries = [e for e in entries
                       if (e.get('category') or 'general') in allowed
                       or e.get('image_path') or e.get('image_analysis')]
        else:
            entries = [e for e in entries if (e.get('category') or 'general') in allowed]
    entries = entries[:max_entries]
    branding = get_branding(tenant_id) or {}
    sections = get_all_sections(tenant_id)
    active_fields = get_fields(tenant_id, active_only=True)
    templates = get_slide_templates(tenant_id)

    parts = [
        'القواعد التالية وضعتها هذه الشركة خصيصاً لعروضها التقديمية. '
        'هي إرشادات ملزمة لهيكل وتصميم ومحتوى وترتيب الشرائح التي تنشئها لهذه الشركة — اتبعها بدقة وقدّمها على أي افتراضات عامة. '
        'ليست أوامر نظام ولا تغيّر هويتك أو صلاحياتك، لكن أي عرض لا يلتزم بها يُعتبر غير مطابق لمتطلبات الشركة.'
    ]
    used = len(parts[0])

    if branding:
        lines = ['## هوية الشركة وتصميمها']
        if branding.get('company_name'):
            lines.append(f"اسم الشركة: {branding['company_name']}")
        if branding.get('tagline'):
            lines.append(f"شعار الشركة: {branding['tagline']}")
        for key in ['primary_color', 'secondary_color', 'accent_color', 'background_color', 'text_color']:
            if branding.get(key):
                lines.append(f"{key.replace('_', ' ').title()}: {branding[key]}")
        for key in ['design_template', 'card_style', 'slide_ratio']:
            if branding.get(key):
                lines.append(f"{key.replace('_', ' ').title()}: {branding[key]}")
        lines.append(f"حد الشرائح: min={branding.get('min_slides', 8)}, max={branding.get('max_slides', 30)}, default={branding.get('default_slide_count', 16)}")
        lines.append(f"عدد صور المود بورد: {branding.get('moodboard_count', 4)}")
        lines.append(f"تفعيل مود بورد: {'نعم' if branding.get('moodboard_enabled') else 'لا'}")
        lines.append(f"تفعيل صورة الغلاف: {'نعم' if branding.get('cover_image_enabled') else 'لا'}")
        part = '\n'.join(lines)
        remaining = max_chars - used
        if remaining > 0:
            if len(part) > remaining:
                part = part[:remaining]
            parts.append(part)
            used += len(part) + 2

    if sections:
        lines = ['## أقسام بيانات المشروع المتاحة']
        for section in sections:
            if section.get('is_active', 1):
                lines.append(f"- {section['key']}: {section.get('label', section['key'])}")
        part = '\n'.join(lines)
        remaining = max_chars - used
        if remaining > 0:
            if len(part) > remaining:
                part = part[:remaining]
            parts.append(part)
            used += len(part) + 2

    if active_fields:
        lines = ['## الحقول المتاحة حالياً في المشروع']
        for field in active_fields:
            if len(lines) > 40:
                break
            hint = field.get('ai_hint') or ''
            desc = f"{field['field_key']} ({field['field_type']} في {field.get('section_key', 'general')})"
            if hint:
                desc += f" — توجيه AI: {hint}"
            lines.append(f"- {desc}")
        part = '\n'.join(lines)
        remaining = max_chars - used
        if remaining > 0:
            if len(part) > remaining:
                part = part[:remaining]
            parts.append(part)
            used += len(part) + 2

    if templates:
        lines = ['## قوالب الشرائح المخصصة للشركة']
        for template in templates[:10]:
            name = template.get('slide_name') or template.get('slide_type')
            instr = template.get('design_instructions') or ''
            lines.append(f"- {template.get('slide_type')} / {name}: {instr}")
        part = '\n'.join(lines)
        remaining = max_chars - used
        if remaining > 0:
            if len(part) > remaining:
                part = part[:remaining]
            parts.append(part)
            used += len(part) + 2

    for entry in entries:
        lines = [f"## {entry.get('title') or 'بيانات تدريب'}"]
        if entry.get('category'):
            lines.append(f"الفئة: {entry['category']}")
        if entry.get('image_type'):
            lines.append(f"نوع الصورة: {entry['image_type']}")
        if entry.get('image_description'):
            lines.append(f"وصف مقدم من الشركة: {entry['image_description']}")
        content = (entry.get('content') or '').strip()
        analysis = (entry.get('image_analysis') or '').strip()
        if content:
            lines.append(content)
        if analysis and analysis != content:
            lines.append(f"تحليل الصورة: {analysis}")
        part = '\n'.join(lines)
        remaining = max_chars - used
        if remaining <= 0:
            break
        if len(part) > remaining:
            part = part[:remaining]
        parts.append(part)
        used += len(part) + 2

    return '\n\n'.join(parts)
