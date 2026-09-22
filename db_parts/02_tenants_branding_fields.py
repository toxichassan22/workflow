# ─────────────────────────────────────────────────────────────────────────────
# Tenant CRUD
# ─────────────────────────────────────────────────────────────────────────────

def create_tenant(company_name, email, password_hash, subdomain=None, plan='free',
                  account_manager_name=None, username=None, phone=None,
                  credit_balance=0, require_password_change=False):
    """Create a new tenant with branding row and default fields."""
    conn = get_db()
    tenant_id = str(uuid.uuid4())

    conn.execute(
        '''INSERT INTO tenants
           (id, company_name, account_manager_name, username, phone, subdomain, email,
            password_hash, plan, credit_balance, require_password_change, activated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (tenant_id, company_name, account_manager_name, username, phone, subdomain, email,
         password_hash, plan, credit_balance, 1 if require_password_change else 0,
         _utcnow().isoformat())
    )
    conn.execute(
        'INSERT INTO tenant_branding (tenant_id, company_name, primary_color, secondary_color, accent_color, background_color, lock_slide_count) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (tenant_id, company_name, '#3B6E91', '#254B66', '#6DA3C3', '#F4F9FC', 0)
    )
    _seed_default_fields(conn, tenant_id)
    conn.commit()
    return tenant_id


def get_tenant_by_email(email):
    """Fetch a tenant by email."""
    conn = get_db()
    row = conn.execute('SELECT * FROM tenants WHERE email = ?', (email,)).fetchone()
    return dict(row) if row else None


def get_tenant_by_username(username):
    """Fetch a tenant by username."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM tenants WHERE LOWER(username) = LOWER(?)',
        (str(username or '').strip(),)
    ).fetchone()
    return dict(row) if row else None


def get_tenant_by_id(tenant_id):
    """Fetch a tenant by ID."""
    conn = get_db()
    row = conn.execute('SELECT * FROM tenants WHERE id = ?', (tenant_id,)).fetchone()
    return dict(row) if row else None


def get_tenant_by_subdomain(subdomain):
    """Fetch a tenant by subdomain."""
    conn = get_db()
    row = conn.execute('SELECT * FROM tenants WHERE subdomain = ? AND is_active = 1', (subdomain,)).fetchone()
    return dict(row) if row else None


_SLUG_RE = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?')


def _normalize_slug(value):
    """Lowercase a candidate and fold username characters into URL-safe form."""
    slug = re.sub(r'[^a-z0-9-]', '', str(value or '').strip().lower().replace('_', '-').replace('.', '-').replace(' ', '-'))
    slug = re.sub(r'-{2,}', '-', slug).strip('-')
    return slug if slug and _SLUG_RE.fullmatch(slug) else ''


def tenant_slug(tenant):
    """Stable latin slug identifying a company in role-prefixed URLs.

    Prefers the explicit ``subdomain``, then the latin ``username`` (folded to
    URL-safe form). Both are already UNIQUE values. Arabic company names are
    never used: they break URL encoding and every rename would invalidate
    bookmarks. The ``t-<id8>`` fallback keeps tenants without either value
    addressable.
    """
    if not tenant:
        return ''
    for key in ('slug', 'subdomain', 'username'):
        slug = _normalize_slug(tenant.get(key))
        if slug:
            return slug
    tenant_id = str(tenant.get('id') or '').strip()
    return ('t-' + re.sub(r'[^a-z0-9]', '', tenant_id.lower())[:8]) if tenant_id else ''


def get_tenant_by_slug(slug):
    """Resolve a URL slug back to its tenant (subdomain, username, or id fallback)."""
    raw = str(slug or '').strip().lower()
    if not raw:
        return None
    conn = get_db()
    for candidate in dict.fromkeys([raw, _normalize_slug(raw)]):
        if not candidate:
            continue
        row = conn.execute(
            'SELECT * FROM tenants WHERE LOWER(subdomain) = ? AND is_active = 1', (candidate,)
        ).fetchone()
        if row:
            return dict(row)
        row = conn.execute(
            'SELECT * FROM tenants WHERE LOWER(REPLACE(REPLACE(username, ?, ?), ?, ?)) = ? AND is_active = 1',
            ('_', '-', '.', '-', candidate)
        ).fetchone()
        if row:
            return dict(row)
    if raw.startswith('t-'):
        suffix = re.sub(r'[^a-z0-9]', '', raw[2:])
        if suffix:
            row = conn.execute(
                'SELECT * FROM tenants WHERE REPLACE(LOWER(id), ?, ?) LIKE ? AND is_active = 1',
                ('-', '', suffix + '%')
            ).fetchone()
            return dict(row) if row else None
    return None


def get_all_tenants():
    """Fetch all tenants (admin only)."""
    conn = get_db()
    rows = conn.execute('SELECT * FROM tenants ORDER BY created_at DESC').fetchall()
    return [dict(r) for r in rows]


def update_tenant(tenant_id, **fields):
    """Update tenant fields dynamically."""
    conn = get_db()
    allowed = {
        'company_name', 'account_manager_name', 'username', 'phone', 'subdomain',
        'domain', 'email', 'password_hash', 'plan', 'credit_balance', 'is_active',
        'primary_user_id', 'require_password_change', 'settings_json', 'package_id',
        'legal_name', 'commercial_name', 'tax_number', 'cr_number',
        'country', 'region', 'address', 'contact_title', 'trial_ends_at',
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    set_parts = [f'{k} = ?' for k in updates]
    # A new password retires every session token issued under the old one.
    if 'password_hash' in updates:
        set_parts.append('session_version = COALESCE(session_version, 0) + 1')
    set_clause = ', '.join(set_parts)
    values = list(updates.values()) + [tenant_id]
    conn.execute(f'UPDATE tenants SET {set_clause} WHERE id = ?', values)
    if 'is_active' in updates and not updates['is_active']:
        _revoke_password_setup_tokens(conn, tenant_id=tenant_id)
    conn.commit()
    return True


def create_company_with_admin(company_name, manager_name, email, username, phone,
                              password_hash, plan='free', credit_balance=0,
                              is_active=True, require_password_change=False,
                              profile=None, slug=None, package_id=None,
                              trial_days=None):
    """Create a company, its workspace, and its primary company administrator atomically.

    The whole opening file lands in one transaction (t50-05): tenant row with
    the legal profile, the URL slug, branding, default fields, the admin user,
    and the package subscription/trial window.
    A failure anywhere rolls everything back so no half-opened company exists.
    """
    conn = get_db()
    profile = dict(profile or {})
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    normalized_slug = None
    if slug:
        normalized_slug = _normalize_slug(slug)
        if not normalized_slug:
            raise ValueError('invalid_slug')
    now = _utcnow().isoformat()
    trial_ends_at = None
    if trial_days:
        from datetime import timedelta
        trial_ends_at = (_utcnow() + timedelta(days=int(trial_days))).isoformat()
    profile_columns = [c for c in TENANT_COMPANY_PROFILE_FIELDS if profile.get(c)]
    try:
        columns = ['id', 'company_name', 'account_manager_name', 'username', 'phone',
                   'email', 'password_hash', 'plan', 'credit_balance', 'is_active',
                   'primary_user_id', 'require_password_change']
        values = [tenant_id, company_name, manager_name, username.lower(), phone,
                  email.lower(), password_hash, plan, credit_balance,
                  1 if is_active else 0, user_id, 1 if require_password_change else 0]
        if normalized_slug:
            columns.append('slug')
            values.append(normalized_slug)
        if package_id:
            columns.append('package_id')
            values.append(str(package_id))
        if trial_ends_at:
            columns.append('trial_ends_at')
            values.append(trial_ends_at)
        if is_active:
            columns.append('activated_at')
            values.append(now)
        for column in profile_columns:
            columns.append(column)
            values.append(str(profile[column]).strip())
        conn.execute(
            f'INSERT INTO tenants ({", ".join(columns)}) VALUES ({", ".join("?" for _ in columns)})',
            values,
        )
        conn.execute(
            '''INSERT INTO tenant_branding
               (tenant_id, company_name, primary_color, secondary_color, accent_color,
                background_color, lock_slide_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (tenant_id, company_name, '#3B6E91', '#254B66', '#6DA3C3', '#F4F9FC', 0)
        )
        _seed_default_fields(conn, tenant_id)
        conn.execute(
            '''INSERT INTO users
               (id, tenant_id, name, username, phone, email, password_hash, role,
                is_active, require_password_change)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'employee', ?, ?)''',
            (user_id, tenant_id, manager_name, username.lower(), phone, email.lower(),
             password_hash, 1 if is_active else 0, 1 if require_password_change else 0)
        )
        # The primary row is the company's admin identity — it carries every
        # company permission explicitly even though sessions run tenant-direct.
        _grant_all_permissions(conn, user_id)
        if package_id or trial_ends_at:
            conn.execute(
                '''INSERT INTO tenant_subscriptions
                   (id, tenant_id, package_id, status, starts_at, trial_ends_at)
                   VALUES (?, ?, ?, 'active', ?, ?)''',
                (str(uuid.uuid4()), tenant_id, str(package_id) if package_id else None,
                 now, trial_ends_at),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return tenant_id, user_id


def get_tenant_profile_counts(tenant_id):
    """Return company account totals without loading tenant-owned payloads."""
    conn = get_db()
    return {
        'users': conn.execute(
            'SELECT COUNT(*) AS c FROM users WHERE tenant_id = ?', (tenant_id,)
        ).fetchone()['c'],
        'projects': conn.execute(
            'SELECT COUNT(*) AS c FROM project_drafts WHERE tenant_id = ?', (tenant_id,)
        ).fetchone()['c'],
        'presentations': conn.execute(
            'SELECT COUNT(*) AS c FROM presentations WHERE tenant_id = ?', (tenant_id,)
        ).fetchone()['c'],
        'exports': conn.execute(
            'SELECT COUNT(*) AS c FROM exports WHERE tenant_id = ?', (tenant_id,)
        ).fetchone()['c'],
    }


def delete_tenant(tenant_id):
    """Delete a tenant and all related data."""
    conn = get_db()
    conn.execute('DELETE FROM tenants WHERE id = ?', (tenant_id,))
    conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Branding CRUD
# ─────────────────────────────────────────────────────────────────────────────

def get_branding(tenant_id):
    """Get branding settings for a tenant."""
    conn = get_db()
    row = conn.execute('SELECT * FROM tenant_branding WHERE tenant_id = ?', (tenant_id,)).fetchone()
    return dict(row) if row else None


def update_branding(tenant_id, **fields):
    """Update branding settings."""
    conn = get_db()
    allowed = {
        'primary_color', 'secondary_color', 'accent_color', 'background_color', 'text_color',
        'logo_path', 'watermark_path', 'company_name', 'tagline', 'font_family', 'font_arabic',
        'design_template', 'reference_image_path',
        'header_enabled', 'footer_enabled', 'header_height', 'footer_height',
        'card_style', 'slide_ratio', 'moodboard_enabled', 'cover_image_enabled', 'moodboard_count',
        'default_slide_count', 'lock_slide_count', 'min_slides', 'max_slides',
        'default_map_type', 'map_style_overview', 'map_style_landmarks', 'map_style_access', 'map_style_catchment',
        'draw_compass', 'draw_inset', 'font_file_path', 'font_file_data',
        # Company-written rules that ride with every slide-generation prompt.
        'generation_rules',
        # d05: how many days a decided section approval stays valid.
        'section_approval_days',
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False

    # Guard against missing columns on databases that haven't run the latest migration
    existing_cols = {row['name'] for row in conn.execute('PRAGMA table_info(tenant_branding)')}
    updates = {k: v for k, v in updates.items() if k in existing_cols}
    if not updates:
        return False
    updates['updated_at'] = _utcnow().isoformat()
    set_clause = ', '.join(f'{k} = ?' for k in updates)
    values = list(updates.values()) + [tenant_id]
    conn.execute(f'UPDATE tenant_branding SET {set_clause} WHERE tenant_id = ?', values)
    conn.commit()
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Input Fields CRUD
# ─────────────────────────────────────────────────────────────────────────────

FIELD_SECTIONS = [
    {'key': 'basic', 'label': 'معلومات أساسية'},
    {'key': 'location', 'label': 'الموقع والخرائط'},
    {'key': 'land_croquis', 'label': 'الأرض والكروكي'},
    {'key': 'contact', 'label': 'بيانات التواصل'},
    # The widget sections are governable like any field section: revoking one
    # hides it in the form, blocks its writes and strips its blobs from draft
    # responses (ISS-015).
    {'key': 'section-timeline', 'label': 'الجدول الزمني'},
    {'key': 'section-financial-calc', 'label': 'الدراسة المالية والمؤشرات'},
    {'key': 'section-team', 'label': 'فريق العمل'},
    {'key': 'section-market-study', 'label': 'دراسة السوق'},
    {'key': 'section-visual-concept', 'label': 'التصور البصري'},
    {'key': 'section-executive-content', 'label': 'المحتوى التنفيذي'},
]

DEFAULT_FIELD_SECTIONS = {s['key']: True for s in FIELD_SECTIONS}

REMOVED_PREBUILT_FIELDS = {
    'land_image_file', 'regulation_reference_file', 'croquis_file', 'building_permit_file',
    'north_direction', 'croquis_expiry_date', 'subdivision_number',
    'project_goal', 'initial_features', 'initial_strengths',
    'building_ratio_setbacks', 'allowed_uses_restrictions',
    'land_area', 'built_area', 'building_system', 'infrastructure', 'secondary_roads',
}

PREBUILT_FIELDS = [
    {'key': 'project_name', 'label': 'اسم المشروع', 'type': 'text', 'required': True, 'section_key': 'basic', 'ai_hint': 'اسم المشروع الرئيسي', 'sort_order': 1},
    {'key': 'project_type', 'label': 'نوع المشروع الرئيسي', 'type': 'select', 'options': ['سكني', 'تجاري', 'فندقي', 'صناعي ولوجستي'], 'required': True, 'section_key': 'basic', 'ai_hint': 'نوع أو أكثر من الأنواع الرئيسية للمشروع حسب دراسة السوق', 'sort_order': 2},
    {'key': 'project_mixed_components', 'label': 'أنواع المشروع متعدد الاستخدامات', 'type': 'text', 'required': False, 'section_key': 'basic', 'ai_hint': 'الأنواع الرئيسية داخل مشروع متعدد الاستخدامات', 'sort_order': 3},
    {'key': 'project_subtype', 'label': 'الأنواع الفرعية للمشروع', 'type': 'textarea', 'options': [], 'required': False, 'section_key': 'basic', 'ai_hint': 'اختيار نوع فرعي واحد أو أكثر حسب النوع الرئيسي', 'sort_order': 4},
    {'key': 'activity_class', 'label': 'تصنيف النشاط', 'type': 'select', 'options': [], 'required': False, 'section_key': 'basic', 'ai_hint': '', 'sort_order': 5},
    {'key': 'project_idea', 'label': 'فكرة المشروع', 'type': 'textarea', 'required': False, 'section_key': 'basic', 'ai_hint': 'فكرة المشروع كما يدخلها العميل يدويًا', 'sort_order': 6},
    {'key': 'project_level', 'label': 'مستوى المشروع', 'type': 'select', 'options': ['اقتصادي', 'متوسط', 'فوق المتوسط', 'متميز', 'فاخر', 'فائق الفخامة', 'أخرى'], 'required': False, 'section_key': 'basic', 'ai_hint': '', 'sort_order': 7},
    {'key': 'target_audience', 'label': 'الفئة المستهدفة', 'type': 'textarea', 'required': False, 'section_key': 'basic', 'ai_hint': 'الفئة المستهدفة متعددة الاختيارات وتتغير حسب نوع المشروع', 'sort_order': 8},
    {'key': 'project_stage', 'label': 'مرحلة المشروع الحالية', 'type': 'select', 'options': ['فكرة أولية', 'فرصة استثمارية', 'دراسة جدوى', 'تصميم', 'تحت التنفيذ', 'قائم لإعادة التطوير', 'أخرى'], 'required': False, 'section_key': 'basic', 'ai_hint': 'المرحلة الحالية التي يمر بها المشروع', 'sort_order': 9},
    {'key': 'project_logo', 'label': 'شعار المشروع (Logo)', 'type': 'image', 'required': False, 'section_key': 'basic', 'ai_hint': 'صورة شعار المشروع', 'sort_order': 10},
    {'key': 'location_address', 'label': 'رابط موقع الأرض في Google Maps', 'type': 'text', 'required': True, 'section_key': 'location', 'ai_hint': 'رابط Google Maps مباشر لنقطة الأرض؛ يستخدم لتحديد الإحداثيات والبيانات المكانية والاشتراطات المرتبطة بالموقع', 'sort_order': 11},
    {'key': 'land_documents_files', 'label': 'رفع الكروكي ورخصة البناء والمستندات المساندة (حتى 4 ملفات)', 'type': 'file', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'ارفع ملف الكروكي ورخصة البناء وأي مستندات مساندة (صك، خطاب) معًا ليتم تحليلها في طلب AI واحد', 'sort_order': 11},
    {'key': 'plot_number_croquis', 'label': 'رقم القطعة', 'type': 'text', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'رقم قطعة الأرض وحده بدون رقم المخطط أو القسم', 'sort_order': 12},
    {'key': 'plan_number', 'label': 'رقم المخطط', 'type': 'text', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'رقم المخطط وحده كما هو في الصك أو الكروكي', 'sort_order': 13},
    {'key': 'deed_number', 'label': 'رقم الصك أو المرجع', 'type': 'text', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'رقم صك الملكية أو المرجع الرسمي', 'sort_order': 14},
    {'key': 'deed_date', 'label': 'تاريخ الصك', 'type': 'text', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'تاريخ إصدار الصك كما هو مكتوب (هجري أو ميلادي) — ليس تاريخ الكروكي', 'sort_order': 15},
    {'key': 'croquis_land_area', 'label': 'مساحة الأرض حسب الكروكي (م²)', 'type': 'number', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'المساحة الإجمالية للأرض بالمتر المربع حسب الكروكي', 'sort_order': 16},
    {'key': 'approved_financial_area', 'label': 'المساحة المعتمدة للدراسة المالية (م²)', 'placeholder': 'يرجى إدخال إجمالي المساحة البنائية المعتمدة التي ستُبنى عليها حسابات الدراسة المالية.', 'type': 'number', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'يكتبها العميل فقط بعد أي استقطاعات — AI ممنوع من تعبئتها أو تعديلها', 'sort_order': 17},
    {'key': 'boundary_lengths', 'label': 'أطوال الأضلاع وحدود الأرض', 'type': 'textarea', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'ملخص مشتق من جدول الاتجاهات — لا تُعد كتابته يدويًا إن كان الجدول مكتملًا', 'sort_order': 18},
    {'key': 'surrounding_streets', 'label': 'الشوارع المحيطة وعروضها', 'type': 'textarea', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'ملخص مشتق من جدول الاتجاهات — أسماء الشوارع وعروضها', 'sort_order': 19},
    {'key': 'facades_count', 'label': 'عدد الواجهات المطلة على شوارع', 'type': 'number', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'عدد الحدود المطلة على شوارع فقط (1 إلى 4) — الحد المجاور لقطعة ليس واجهة', 'sort_order': 20},
    {'key': 'facades_directions', 'label': 'اتجاهات الواجهات المطلة على شوارع', 'type': 'text', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'اتجاهات الحدود المطلة على شوارع فقط (مثل: شمالية، غربية) — لا تُكتب الاتجاهات الأربعة إلا إن كانت مطلة على أربعة شوارع', 'sort_order': 21},
    {'key': 'building_ratio_coverage', 'label': 'نسبة البناء والتغطية', 'type': 'textarea', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'يملؤه AI من ملفات الأمانة: نسبة البناء، نسبة التغطية، FAR، وعدد الأدوار المرتبط بشريحة مساحة الأرض، بدون ذكر أرقام الصفحات', 'sort_order': 22},
    {'key': 'setbacks', 'label': 'الارتدادات', 'type': 'textarea', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'يملؤه AI من ملفات الأمانة: الارتداد الأمامي والخلفي والجانبيان، أو يوضح أنها غير محددة في المرجع المتاح، بدون ذكر أرقام الصفحات', 'sort_order': 23},
    {'key': 'max_floors_height', 'label': 'الارتفاع أو عدد الأدوار المسموح', 'type': 'textarea', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'عدد الأدوار المسموح بها أو الحد الأقصى للارتفاع بالمتر، مع شرح شريحة الأرض إن وجدت', 'sort_order': 24},
    {'key': 'approved_floor_count', 'label': 'الأدوار المعتمدة', 'placeholder': 'يرجى إدخال عدد الأدوار المعتمدة للمشروع وفقًا للاشتراطات التنظيمية.', 'type': 'number', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'عدد الأدوار الفعلي الذي يعتمده العميل للمبنى — يكتبه العميل فقط ولا يملؤه AI', 'sort_order': 25},
    {'key': 'approved_coverage_ratio', 'label': 'التغطية المعتمدة (%)', 'placeholder': 'يرجى إدخال نسبة التغطية المعتمدة للأرض وفقًا للاشتراطات التنظيمية.', 'type': 'number', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'نسبة التغطية التي يعتمدها العميل للدراسة المالية — يكتبها العميل فقط ولا يملؤها AI', 'sort_order': 26},
    {'key': 'allowed_uses', 'label': 'الاستخدامات المسموحة', 'type': 'textarea', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'قائمة الاستخدامات المسموحة تنظيميًا لهذه الأرض من ملفات الأمانة وجدول التنظيم، بدون كتابة حالة السماح داخل الحقل', 'sort_order': 27},
    {'key': 'regulatory_constraints', 'label': 'القيود التنظيمية', 'type': 'textarea', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'القيود التنظيمية المنطبقة على الموقع والمشروع، بما فيها المواقف والمداخل والمخارج والتحميل والخدمات، بدون ذكر أرقام الصفحات', 'sort_order': 28},
    {'key': 'land_photos', 'label': 'صور الأرض (حتى 4 صور — اختياري)', 'type': 'file', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'صور فوتوغرافية للأرض من العميل مع وصف لكل صورة (لا يحللها AI)', 'sort_order': 29},
    {'key': 'land_and_building_summary', 'label': 'ملخص بيانات الأرض والاشتراطات', 'type': 'textarea', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'يملؤه AI كملخص موثق من ملفات الأمانة يشمل الارتدادات، الاستخدامات، القيود، المواقف، المداخل والمخارج، الفرص، المخاطر والتعارضات، بدون الإحالة إلى أرقام صفحات أو أماكن داخل الملفات', 'sort_order': 30},
    {'key': 'location_lat', 'label': 'خط العرض (Latitude)', 'type': 'text', 'section_key': 'location', 'ai_hint': 'خط العرض للموقع (إختياري)', 'sort_order': 31},
    {'key': 'location_lng', 'label': 'خط الطول (Longitude)', 'type': 'text', 'section_key': 'location', 'ai_hint': 'خط الطول للموقع (إختياري)', 'sort_order': 32},
    {'key': 'city', 'label': 'المدينة', 'type': 'text', 'section_key': 'location', 'ai_hint': 'المدينة المستخرجة تلقائيًا من رابط الموقع والخرائط — لا يكتبها العميل يدويًا', 'sort_order': 33},
    {'key': 'district', 'label': 'الحي', 'type': 'text', 'section_key': 'location', 'ai_hint': 'الحي المستخرج تلقائيًا من رابط الموقع والخرائط — لا يكتبه العميل يدويًا', 'sort_order': 34},
    {'key': 'plot_number', 'label': 'رقم المخطط / القطعة', 'type': 'text', 'section_key': 'location', 'ai_hint': 'رقم المخطط أو القطعة', 'sort_order': 35},
    {'key': 'main_roads', 'label': 'الطرق الرئيسية المحيطة', 'type': 'textarea', 'section_key': 'location', 'ai_hint': 'أسماء الطرق الرئيسية المحيطة بالمشروع وتمثل طرق الوصول إليه', 'sort_order': 40},
    {'key': 'nearby_landmarks', 'label': 'أهم المعالم القريبة', 'type': 'textarea', 'section_key': 'location', 'ai_hint': 'قائمة المعالم القريبة مع أوقات القيادة (مثلاً: ميدان السارية - 1 دقيقة)', 'sort_order': 42},
    {'key': 'city_landmarks', 'label': 'المعالم الرئيسية في المدينة', 'type': 'textarea', 'section_key': 'location', 'ai_hint': 'أهم المعالم الرئيسية في المدينة والمناطق المحيطة', 'sort_order': 43},
    {'key': 'catchment_areas', 'label': 'مناطق نطاق التأثير', 'type': 'textarea', 'section_key': 'location', 'ai_hint': 'المناطق الرئيسية والثانوية المتأثرة بالمشروع', 'sort_order': 44},
    {'key': 'location_data_fetched_at', 'label': 'وقت آخر تحديث بيانات الموقع', 'type': 'text', 'section_key': 'location', 'ai_hint': 'وقت آخر جلب لبيانات الموقع والمعالم بتوقيت السعودية', 'sort_order': 44},
    {'key': 'contact_name', 'label': 'الاسم', 'type': 'text', 'required': False, 'section_key': 'contact', 'ai_hint': 'اسم مسؤول التواصل بالمشروع', 'sort_order': 45},
    {'key': 'contact_position', 'label': 'المنصب', 'type': 'text', 'required': False, 'section_key': 'contact', 'ai_hint': 'المسمى الوظيفي أو المنصب لمسؤول التواصل', 'sort_order': 46},
    {'key': 'contact_email', 'label': 'البريد الإلكتروني', 'type': 'text', 'required': False, 'section_key': 'contact', 'ai_hint': 'البريد الإلكتروني للتواصل', 'sort_order': 47},
    {'key': 'contact_phone', 'label': 'الهاتف', 'type': 'text', 'required': False, 'section_key': 'contact', 'ai_hint': 'رقم هاتف أو جوال التواصل', 'sort_order': 48},
    {'key': 'contact_website', 'label': 'الموقع الإلكتروني', 'type': 'text', 'required': False, 'section_key': 'contact', 'ai_hint': 'رابط الموقع الإلكتروني الرسمي', 'sort_order': 49},
    {'key': 'contact_address', 'label': 'الموقع الجغرافي', 'type': 'text', 'required': False, 'section_key': 'contact', 'ai_hint': 'العنوان الجغرافي أو المقر الرئيسي', 'sort_order': 50},
    {'key': 'contact_social_media', 'label': 'السوشل ميديا (X, LinkedIn, Instagram, TikTok)', 'type': 'textarea', 'required': False, 'section_key': 'contact', 'ai_hint': 'حسابات التواصل الاجتماعي للمشروع أو الشركة', 'sort_order': 51},
]


def _seed_default_fields(conn, tenant_id):
    """Seed pre-built fields for a new tenant (all active by default)."""
    for f in PREBUILT_FIELDS:
        field_id = str(uuid.uuid4())
        conn.execute(
            'INSERT INTO tenant_input_fields (id, tenant_id, field_key, field_label, field_type, field_options, section_key, is_required, is_active, is_custom, sort_order, ai_hint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)',
            (
                field_id, tenant_id, f['key'], f['label'], f['type'],
                json.dumps(f.get('options', []), ensure_ascii=False) if f.get('options') else None,
                f.get('section_key', 'general'),
                1 if f.get('required') else 0,
                1, f.get('sort_order', 0), f.get('ai_hint', '')
            )
        )


def ensure_tenant_prebuilt_fields_active(tenant_id):
    """Re-sync the prebuilt field definitions onto a tenant.

    This runs on every /api/fields call, which is every time the project form opens. It used to
    issue one UPDATE per prebuilt field unconditionally — 39 writes and a commit on every load,
    none of which changed anything in the normal case. It now compares first and writes only what
    actually differs, so a steady-state call performs a single SELECT and no transaction at all.
    """
    if not tenant_id:
        return
    conn = get_db()
    existing_rows = {
        row['field_key']: row for row in
        conn.execute(
            'SELECT id, field_key, field_label, field_type, field_options, section_key, sort_order,'
            ' is_active FROM tenant_input_fields WHERE tenant_id = ?', (tenant_id,)
        ).fetchall()
    }
    dirty = False

    if REMOVED_PREBUILT_FIELDS:
        stale = [key for key in sorted(REMOVED_PREBUILT_FIELDS)
                 if key in existing_rows and existing_rows[key]['is_active']]
        if stale:
            placeholders = ','.join('?' for _ in stale)
            conn.execute(
                f'UPDATE tenant_input_fields SET is_active = 0 WHERE tenant_id = ? AND field_key IN ({placeholders})',
                [tenant_id, *stale]
            )
            dirty = True

    for f in PREBUILT_FIELDS:
        opts_json = json.dumps(f.get('options', []), ensure_ascii=False) if f.get('options') else None
        section = f.get('section_key', 'general')
        order = f.get('sort_order', 0)
        row = existing_rows.get(f['key'])
        if row is None:
            conn.execute(
                'INSERT INTO tenant_input_fields (id, tenant_id, field_key, field_label, field_type, field_options, section_key, is_required, is_active, is_custom, sort_order, ai_hint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?)',
                (
                    str(uuid.uuid4()), tenant_id, f['key'], f['label'], f['type'],
                    opts_json, section,
                    1 if f.get('required') else 0,
                    order, f.get('ai_hint', '')
                )
            )
            print(f'[DB] Migration: added field {f["key"]} to tenant {tenant_id}')
            dirty = True
            continue
        unchanged = (
            row['field_label'] == f['label']
            and row['field_type'] == f['type']
            and (row['field_options'] or None) == opts_json
            and row['section_key'] == section
            and (row['sort_order'] or 0) == order
            and row['is_active']
        )
        if unchanged:
            continue
        conn.execute(
            'UPDATE tenant_input_fields SET field_options = ?, section_key = ?, field_label = ?, field_type = ?, sort_order = ?, is_active = 1 WHERE id = ?',
            (opts_json, section, f['label'], f['type'], order, row['id'])
        )
        dirty = True

    if dirty:
        conn.commit()


def get_fields(tenant_id, active_only=True):
    """Get all input fields for a tenant."""
    conn = get_db()
    if active_only:
        rows = conn.execute(
            'SELECT * FROM tenant_input_fields WHERE tenant_id = ? AND is_active = 1 ORDER BY sort_order, created_at',
            (tenant_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM tenant_input_fields WHERE tenant_id = ? ORDER BY sort_order, created_at',
            (tenant_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_field_by_id(field_id):
    """Get a single field by ID."""
    conn = get_db()
    row = conn.execute('SELECT * FROM tenant_input_fields WHERE id = ?', (field_id,)).fetchone()
    return dict(row) if row else None


def _normalize_options_list(val):
    if not val:
        return []
    if isinstance(val, list):
        res = []
        for item in val:
            if isinstance(item, str):
                parts = [p.strip() for p in re.split(r'[,،;\n]+', item) if p.strip()]
                res.extend(parts)
            elif item is not None:
                res.append(str(item).strip())
        return [r for r in res if r]
    if isinstance(val, str):
        val_str = val.strip()
        if val_str.startswith('[') and val_str.endswith(']'):
            try:
                parsed = json.loads(val_str)
                if isinstance(parsed, list):
                    return _normalize_options_list(parsed)
            except Exception:
                pass
        return [p.strip() for p in re.split(r'[,،;\n]+', val_str) if p.strip()]
    return []


def add_custom_field(tenant_id, field_key, field_label, field_type, field_options=None,
                     is_required=False, placeholder=None, default_value=None, ai_hint=None, sort_order=100, section_key='general'):
    """Add or update a custom field for a tenant."""
    conn = get_db()
    norm_opts = _normalize_options_list(field_options)
    if norm_opts:
        field_type = 'select'
        opts_json = json.dumps(norm_opts, ensure_ascii=False)
    else:
        opts_json = json.dumps(field_options, ensure_ascii=False) if field_options else None

    # Check if a field with same tenant_id and field_key OR same field_label exists
    existing = conn.execute(
        'SELECT id, field_options FROM tenant_input_fields WHERE tenant_id = ? AND (field_key = ? OR LOWER(TRIM(field_label)) = LOWER(TRIM(?)))',
        (tenant_id, field_key, field_label)
    ).fetchone()

    if existing:
        field_id = existing['id']
        if not opts_json and existing['field_options']:
            opts_json = existing['field_options']
            try:
                if json.loads(opts_json):
                    field_type = 'select'
            except Exception:
                pass

        conn.execute(
            'UPDATE tenant_input_fields SET field_key = ?, field_label = ?, field_type = ?, field_options = ?, section_key = ?, is_required = ?, is_active = 1, placeholder = ?, default_value = ?, ai_hint = ? WHERE id = ?',
            (
                field_key, field_label, field_type, opts_json, section_key,
                1 if is_required else 0, placeholder, default_value, ai_hint, field_id
            )
        )
        conn.commit()
        return field_id

    field_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO tenant_input_fields (id, tenant_id, field_key, field_label, field_type, field_options, section_key, is_required, is_active, is_custom, sort_order, placeholder, default_value, ai_hint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?)',
        (
            field_id, tenant_id, field_key, field_label, field_type,
            opts_json,
            section_key, 1 if is_required else 0, sort_order, placeholder, default_value, ai_hint
        )
    )
    conn.commit()
    return field_id


def update_field(field_id, **fields):
    """Update a field."""
    conn = get_db()
    allowed = {'field_key', 'field_label', 'field_type', 'field_options', 'section_key', 'is_required', 'is_active', 'sort_order', 'placeholder', 'default_value', 'ai_hint'}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    if 'field_options' in updates:
        val = updates['field_options']
        norm_opts = _normalize_options_list(val)
        if norm_opts:
            updates['field_options'] = json.dumps(norm_opts, ensure_ascii=False)
            updates['field_type'] = 'select'
        else:
            updates['field_options'] = None

    set_clause = ', '.join(f'{k} = ?' for k in updates)
    values = list(updates.values()) + [field_id]
    conn.execute(f'UPDATE tenant_input_fields SET {set_clause} WHERE id = ?', values)
    conn.commit()
    return True


def delete_field(field_id):
    """Delete a field."""
    conn = get_db()
    conn.execute('DELETE FROM tenant_input_fields WHERE id = ?', (field_id,))
    conn.commit()


def reorder_fields(tenant_id, field_ids):
    """Reorder fields only when every ID belongs to the tenant."""
    conn = get_db()
    placeholders = ','.join('?' for _ in field_ids)
    if not placeholders:
        return True
    owned = conn.execute(
        f'SELECT id FROM tenant_input_fields WHERE tenant_id = ? AND id IN ({placeholders})',
        [tenant_id, *field_ids]
    ).fetchall()
    if len(owned) != len(set(field_ids)):
        return False
    for index, field_id in enumerate(field_ids, start=1):
        conn.execute(
            'UPDATE tenant_input_fields SET sort_order = ? WHERE id = ? AND tenant_id = ?',
            (index, field_id, tenant_id)
        )
    conn.commit()
    return True


def get_custom_sections(tenant_id):
    """Get all custom sections for a tenant."""
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM tenant_custom_sections WHERE tenant_id = ? ORDER BY sort_order, created_at',
        (tenant_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_custom_section(tenant_id, section_key):
    """Get one tenant-owned custom section, if it exists."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM tenant_custom_sections WHERE tenant_id = ? AND section_key = ?',
        (tenant_id, section_key)
    ).fetchone()
    return dict(row) if row else None


def get_all_sections(tenant_id):
    """Get built-in + custom sections for a tenant."""
    custom = get_custom_sections(tenant_id)
    custom_list = [{'key': s['section_key'], 'label': s['section_label'], 'custom': True} for s in custom if s.get('is_active', 1)]
    return FIELD_SECTIONS + custom_list


def add_custom_section(tenant_id, section_key, section_label, sort_order=100):
    """Add a custom section for a tenant."""
    conn = get_db()
    existing = conn.execute(
        'SELECT id FROM tenant_custom_sections WHERE tenant_id = ? AND section_key = ?',
        (tenant_id, section_key)
    ).fetchone()
    if existing:
        return None
    section_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO tenant_custom_sections (id, tenant_id, section_key, section_label, section_icon, sort_order, is_active) VALUES (?, ?, ?, ?, ?, ?, 1)',
        (section_id, tenant_id, section_key, section_label, 'file', sort_order)
    )
    conn.commit()
    return section_id


def update_custom_section(tenant_id, section_key, **updates):
    """Update a custom section."""
    conn = get_db()
    allowed = {'section_label', 'sort_order', 'is_active'}
    sets = []
    vals = []
    for k, v in updates.items():
        db_k = {'label': 'section_label'}.get(k, k)
        if db_k in allowed:
            sets.append(f'{db_k} = ?')
            vals.append(v)
    if not sets:
        return False
    vals.append(_utcnow().isoformat())
    sets.append('updated_at = ?')
    vals.extend([tenant_id, section_key])
    cursor = conn.execute(
        f'UPDATE tenant_custom_sections SET {", ".join(sets)} WHERE tenant_id = ? AND section_key = ?',
        vals
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_custom_section(tenant_id, section_key):
    """Delete a custom section. Fields in it fall back to 'general'."""
    conn = get_db()
    conn.execute(
        'UPDATE tenant_input_fields SET section_key = ? WHERE tenant_id = ? AND section_key = ?',
        ('general', tenant_id, section_key)
    )
    cursor = conn.execute(
        'DELETE FROM tenant_custom_sections WHERE tenant_id = ? AND section_key = ?',
        (tenant_id, section_key)
    )
    conn.commit()
    return cursor.rowcount > 0
