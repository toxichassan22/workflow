

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


def _migrate_location_fields(conn):
    """Add missing pre-built location fields to existing tenants and update prebuilt options."""
    existing_tenants = [row['id'] for row in conn.execute('SELECT id FROM tenants').fetchall()]
    for tenant_id in existing_tenants:
        existing_rows = {
            row['field_key']: row for row in
            conn.execute('SELECT id, field_key, section_key, field_options FROM tenant_input_fields WHERE tenant_id = ?', (tenant_id,)).fetchall()
        }
        if REMOVED_PREBUILT_FIELDS:
            placeholders = ','.join('?' for _ in REMOVED_PREBUILT_FIELDS)
            conn.execute(
                f'UPDATE tenant_input_fields SET is_active = 0 WHERE tenant_id = ? AND field_key IN ({placeholders})',
                [tenant_id, *sorted(REMOVED_PREBUILT_FIELDS)]
            )
        for f in PREBUILT_FIELDS:
            opts_json = json.dumps(f.get('options', []), ensure_ascii=False) if f.get('options') else None
            if f['key'] in existing_rows:
                row_id = existing_rows[f['key']]['id']
                conn.execute(
                    'UPDATE tenant_input_fields SET field_options = ?, section_key = ?, field_label = ?, field_type = ?, sort_order = ?, is_active = 1 WHERE id = ?',
                    (opts_json, f.get('section_key', 'general'), f['label'], f['type'], f.get('sort_order', 0), row_id)
                )
                continue
            field_id = str(uuid.uuid4())
            conn.execute(
                'INSERT INTO tenant_input_fields (id, tenant_id, field_key, field_label, field_type, field_options, section_key, is_required, is_active, is_custom, sort_order, ai_hint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?)',
                (
                    field_id, tenant_id, f['key'], f['label'], f['type'],
                    opts_json,
                    f.get('section_key', 'general'),
                    1 if f.get('required') else 0,
                    f.get('sort_order', 0), f.get('ai_hint', '')
                )
            )
            print(f'[DB] Migration: added field {f["key"]} to tenant {tenant_id}')
    conn.commit()


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


def _migrate_font_system(conn):
    """Create central SAG font registry and tenant font overrides."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS sag_fonts (
        id TEXT PRIMARY KEY,
        font_name TEXT NOT NULL,
        font_family TEXT NOT NULL,
        script TEXT NOT NULL,
        weight TEXT NOT NULL,
        style TEXT DEFAULT 'normal',
        source_type TEXT NOT NULL DEFAULT 'preset',
        source_data TEXT,
        file_data TEXT,
        is_active INTEGER DEFAULT 1,
        is_default INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS tenant_font_selections (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        script TEXT NOT NULL,
        weight TEXT NOT NULL,
        font_id TEXT REFERENCES sag_fonts(id) ON DELETE SET NULL,
        custom_font_path TEXT,
        custom_font_data TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        UNIQUE(tenant_id, script, weight)
    );
    CREATE INDEX IF NOT EXISTS idx_sag_fonts_script_weight ON sag_fonts(script, weight);
    CREATE INDEX IF NOT EXISTS idx_tenant_font_selections_tenant ON tenant_font_selections(tenant_id);
    """)
    defaults = [
        ('sag-default-arabic-regular', 'The Sans Arabic', 'The Sans Arabic', 'arabic', 'regular'),
        ('sag-default-arabic-bold', 'The Sans Arabic Bold', 'The Sans Arabic', 'arabic', 'bold'),
        ('sag-default-latin-regular', 'Arial', 'Arial', 'latin', 'regular'),
        ('sag-default-latin-bold', 'Arial Bold', 'Arial', 'latin', 'bold'),
    ]
    for font_id, name, family, script, weight in defaults:
        conn.execute(
            """INSERT OR IGNORE INTO sag_fonts
               (id, font_name, font_family, script, weight, source_type, source_data, is_active, is_default)
               VALUES (?, ?, ?, ?, ?, 'preset', ?, 1, 1)""",
            (font_id, name, family, script, weight, family),
        )
    conn.commit()


def get_sag_fonts(script=None, weight=None, active_only=True):
    conn = get_db()
    query = 'SELECT id, font_name, font_family, script, weight, style, source_type, source_data, is_active, is_default, created_at, updated_at FROM sag_fonts WHERE 1=1'
    params = []
    if active_only:
        query += ' AND is_active = 1'
    if script:
        query += ' AND script = ?'
        params.append(script)
    if weight:
        query += ' AND weight = ?'
        params.append(weight)
    query += ' ORDER BY script, weight, is_default DESC, font_name'
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_sag_font(font_id):
    row = get_db().execute('SELECT * FROM sag_fonts WHERE id = ?', (font_id,)).fetchone()
    return dict(row) if row else None


def create_sag_font(font_name, font_family, script, weight, style='normal', source_type='uploaded', source_data=None, file_data=None):
    font_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        '''INSERT INTO sag_fonts
           (id, font_name, font_family, script, weight, style, source_type, source_data, file_data)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (font_id, font_name, font_family, script, weight, style, source_type, source_data, file_data),
    )
    conn.commit()
    return font_id


def update_sag_font(font_id, **fields):
    allowed = {'font_name', 'font_family', 'is_active', 'is_default'}
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return False
    if updates.get('is_default'):
        current = get_sag_font(font_id)
        if current:
            get_db().execute(
                'UPDATE sag_fonts SET is_default = 0 WHERE script = ? AND weight = ?',
                (current['script'], current['weight']),
            )
    updates['updated_at'] = _utcnow().isoformat()
    clause = ', '.join(f'{key} = ?' for key in updates)
    get_db().execute(f'UPDATE sag_fonts SET {clause} WHERE id = ?', list(updates.values()) + [font_id])
    get_db().commit()
    return True


def get_tenant_font_selections(tenant_id):
    rows = get_db().execute(
        'SELECT * FROM tenant_font_selections WHERE tenant_id = ? ORDER BY script, weight',
        (tenant_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_tenant_font_selection(tenant_id, script, weight):
    row = get_db().execute(
        'SELECT * FROM tenant_font_selections WHERE tenant_id = ? AND script = ? AND weight = ?',
        (tenant_id, script, weight),
    ).fetchone()
    return dict(row) if row else None


def set_tenant_font_selection(tenant_id, script, weight, font_id=None, custom_font_path=None, custom_font_data=None):
    selection_id = str(uuid.uuid4())
    now = _utcnow().isoformat()
    get_db().execute(
        '''INSERT INTO tenant_font_selections
           (id, tenant_id, script, weight, font_id, custom_font_path, custom_font_data, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(tenant_id, script, weight) DO UPDATE SET
           font_id = excluded.font_id,
           custom_font_path = excluded.custom_font_path,
           custom_font_data = excluded.custom_font_data,
           updated_at = excluded.updated_at''',
        (selection_id, tenant_id, script, weight, font_id, custom_font_path, custom_font_data, now, now),
    )
    get_db().commit()
    return selection_id


def delete_tenant_font_selection(tenant_id, script, weight):
    get_db().execute(
        'DELETE FROM tenant_font_selections WHERE tenant_id = ? AND script = ? AND weight = ?',
        (tenant_id, script, weight),
    )
    get_db().commit()


def _migrate_field_sections(conn):
    """Set section_key for existing pre-built fields without one."""
    section_map = {f['key']: f.get('section_key', 'general') for f in PREBUILT_FIELDS}
    rows = conn.execute('SELECT id, field_key FROM tenant_input_fields WHERE section_key IS NULL OR section_key = \'general\'').fetchall()
    for row in rows:
        key = row['field_key']
        if key in section_map:
            conn.execute(
                'UPDATE tenant_input_fields SET section_key = ? WHERE id = ?',
                (section_map[key], row['id'])
            )
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


def _repair_field_options(conn):
    """Repair existing custom fields that have unparsed options or missing select type."""
    try:
        rows = conn.execute("SELECT id, field_type, field_options FROM tenant_input_fields WHERE field_options IS NOT NULL AND field_options != ''").fetchall()
        for row in rows:
            field_id = row['id']
            raw_opts = row['field_options']
            parsed_opts = _normalize_options_list(raw_opts)
            if parsed_opts:
                json_str = json.dumps(parsed_opts, ensure_ascii=False)
                if json_str != raw_opts or row['field_type'] != 'select':
                    conn.execute(
                        "UPDATE tenant_input_fields SET field_options = ?, field_type = 'select' WHERE id = ?",
                        (json_str, field_id)
                    )
        conn.commit()
    except Exception as e:
        print(f"[DB REPAIR ERR] {e}")


def _deduplicate_fields(conn):
    """Remove duplicate fields for same tenant that share label, key, or transliteration, keeping the best one."""
    try:
        ar_map = {
            'ا': 'a', 'أ': 'a', 'إ': 'i', 'آ': 'a', 'ب': 'b', 'ت': 't', 'ث': 'th',
            'ج': 'j', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'dh', 'ر': 'r', 'ز': 'z',
            'س': 's', 'ش': 'sh', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': 'a',
            'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
            'ه': 'h', 'و': 'w', 'ي': 'y', 'ى': 'a', 'ئ': 'y', 'ة': 'a', 'ء': '',
            ' ': '_', 'ـ': '',
        }

        rows = conn.execute('SELECT * FROM tenant_input_fields WHERE is_custom = 1').fetchall()
        by_group = {}
        for r in rows:
            dict_r = dict(r)
            tid = dict_r['tenant_id']
            key_raw = dict_r['field_key'].strip().lower()
            lbl_raw = dict_r['field_label'].strip().lower()

            lbl_trans = ''.join(ar_map.get(ch, ch) for ch in lbl_raw)
            lbl_trans_clean = re.sub(r'[^a-zA-Z0-9]', '', lbl_trans)
            key_clean = re.sub(r'[^a-zA-Z0-9]', '', key_raw)

            if 'license' in key_clean or 'license' in lbl_trans_clean or 'trkhs' in lbl_trans_clean or 'trkhs' in key_clean or 'ترخيص' in lbl_raw:
                group_id = (tid, 'building_license_status')
            else:
                group_id = (tid, key_clean or lbl_trans_clean)

            by_group.setdefault(group_id, []).append(dict_r)

        for (tid, grp), field_list in by_group.items():
            if len(field_list) > 1:
                best = max(field_list, key=lambda f: (1 if f.get('field_options') and f['field_options'] != '[]' else 0, 1 if f.get('field_type') == 'select' else 0, f.get('created_at') or ''))
                for f in field_list:
                    if f['id'] != best['id']:
                        conn.execute('DELETE FROM tenant_input_fields WHERE id = ?', (f['id'],))

            # Ensure building_license_status field has standard Arabic label & correct 6 options
            if grp == 'building_license_status' and field_list:
                best = max(field_list, key=lambda f: (1 if f.get('field_options') and f['field_options'] != '[]' else 0, 1 if f.get('field_type') == 'select' else 0, f.get('created_at') or ''))
                opts = ["مرخص", "قيد الترخيص", "مرخص جزئياً", "غير مرخص", "مرفوض", "لا يحتاج ترخيص"]
                conn.execute(
                    "UPDATE tenant_input_fields SET field_key = 'building_license_status', field_label = 'حالة ترخيص البناء', field_type = 'select', field_options = ?, section_key = 'compliance' WHERE id = ?",
                    (json.dumps(opts, ensure_ascii=False), best['id'])
                )
        conn.commit()
    except Exception as e:
        print(f"[DB DEDUP ERR] {e}")


def _cleanup_accidental_map_fields(conn):
    """Delete custom fields created accidentally when asking AI to add map slides."""
    try:
        conn.execute("""
            DELETE FROM tenant_input_fields 
            WHERE field_key IN ('khryta_alhy_alkaml', 'khryta_altrq_almhyta') 
               OR field_label LIKE '%خريطة الحي%' 
               OR field_label LIKE '%خريطة الطرق%'
        """)
        conn.commit()
    except Exception as e:
        print(f"[DB CLEANUP ERR] {e}")


def _migrate_map_images_presentation_fk(conn):
    """Remove the presentations FK from map_images so draft_* ids can be cached."""
    try:
        if isinstance(conn, sqlite3.PostgresConnection):
            constraints = conn.execute('''
                SELECT tc.constraint_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = current_schema()
                  AND tc.table_name = 'map_images'
                  AND tc.constraint_type = 'FOREIGN KEY'
                  AND kcu.column_name = 'presentation_id'
            ''').fetchall()
            for row in constraints:
                validated = re.fullmatch(r'[A-Za-z0-9_]+', str(row['constraint_name'] or ''))
                if validated:
                    conn.execute(f'ALTER TABLE map_images DROP CONSTRAINT "{validated.group(0)}"')
            conn.commit()
            return
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='map_images'")
        if not cur or not cur.fetchone():
            return
        fks = conn.execute("PRAGMA foreign_key_list(map_images)").fetchall()
        has_fk = any(row['from'] == 'presentation_id' or row[2] == 'presentations' for row in fks)
        if not has_fk:
            return
        conn.executescript("""
            BEGIN TRANSACTION;
            CREATE TABLE map_images_new (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                presentation_id TEXT,
                image_type TEXT NOT NULL,
                file_path TEXT NOT NULL,
                placeholder TEXT NOT NULL,
                metadata_json TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            INSERT INTO map_images_new SELECT * FROM map_images;
            DROP TABLE map_images;
            ALTER TABLE map_images_new RENAME TO map_images;
            CREATE INDEX IF NOT EXISTS idx_mapimages_tenant ON map_images(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_mapimages_pres ON map_images(presentation_id);
            CREATE INDEX IF NOT EXISTS idx_mapimages_type ON map_images(image_type);
            COMMIT;
        """)
        conn.commit()
        print("[DB MIGRATION] map_images presentation_id foreign key removed")
    except Exception as e:
        print(f"[DB MIGRATION ERR] {e}")


def _migrate_project_draft_columns(conn):
    """Add lightweight list metadata to historical project drafts."""
    try:
        cursor = conn.execute("PRAGMA table_info(project_drafts)")
        existing_cols = {row['name'] for row in cursor.fetchall()}
        migrations = {
            'title': "ALTER TABLE project_drafts ADD COLUMN title TEXT",
            'revision': "ALTER TABLE project_drafts ADD COLUMN revision INTEGER DEFAULT 1",
            'data_bytes': "ALTER TABLE project_drafts ADD COLUMN data_bytes INTEGER DEFAULT 0",
            'has_slides': "ALTER TABLE project_drafts ADD COLUMN has_slides INTEGER DEFAULT 0",
            'has_maps': "ALTER TABLE project_drafts ADD COLUMN has_maps INTEGER DEFAULT 0",
        }
        for column, sql in migrations.items():
            if column not in existing_cols:
                conn.execute(sql)
                print(f"[DB MIGRATION] Added project draft column: {column}")
        conn.execute("""
            UPDATE project_drafts
            SET title = COALESCE(NULLIF(title, ''), 'مسودة مشروع بدون عنوان'),
                revision = COALESCE(revision, 1),
                data_bytes = CASE WHEN COALESCE(data_bytes, 0) = 0 THEN length(COALESCE(draft_data, '')) ELSE data_bytes END,
                has_slides = CASE WHEN COALESCE(draft_data, '') LIKE '%tenantSlidesData%' THEN 1 ELSE COALESCE(has_slides, 0) END,
                has_maps = CASE WHEN COALESCE(draft_data, '') LIKE '%map_placeholders%' THEN 1 ELSE COALESCE(has_maps, 0) END
        """)
        conn.commit()
    except Exception as e:
        print(f"[DB DRAFT MIGRATION ERR] {e}")


def _migrate_generation_approval_columns(conn):
    """Add the lifecycle bookkeeping column to historical generation approvals."""
    try:
        cursor = conn.execute("PRAGMA table_info(generation_approvals)")
        existing_cols = {row['name'] for row in cursor.fetchall()}
        if 'prior_status' not in existing_cols:
            conn.execute("ALTER TABLE generation_approvals ADD COLUMN prior_status TEXT")
            print("[DB MIGRATION] Added generation_approvals column: prior_status")
        if 'section_key' not in existing_cols:
            conn.execute("ALTER TABLE generation_approvals ADD COLUMN section_key TEXT")
            print("[DB MIGRATION] Added generation_approvals column: section_key")
        conn.commit()
    except Exception as e:
        print(f"[DB GENERATION MIGRATION ERR] {e}")


def _migrate_point_reservation_columns(conn):
    """Add expiry + the one-active-hold-per-operation index to older DBs."""
    try:
        cursor = conn.execute("PRAGMA table_info(point_reservations)")
        existing_cols = {row['name'] for row in cursor.fetchall()}
        if 'expires_at' not in existing_cols:
            conn.execute("ALTER TABLE point_reservations ADD COLUMN expires_at TEXT")
            print("[DB MIGRATION] Added point_reservations column: expires_at")
        conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS uq_point_reservations_active_op
                        ON point_reservations(generation_approval_id) WHERE status = 'reserved' ''')
        conn.commit()
    except Exception as e:
        print(f"[DB RESERVATION MIGRATION ERR] {e}")


def _migrate_workflow_gate_columns(conn):
    """Columns for the file-gate / generation / archive workflow requirements."""
    additions = (
        ('generation_approvals', (('input_snapshot', 'TEXT'),)),
        ('generation_jobs', (('heartbeat_at', 'TEXT'),)),
        ('final_file_approvals', (('request_hash', 'TEXT'), ('stamped_export_id', 'TEXT'))),
        ('presentation_approvals', (('request_hash', 'TEXT'),)),
        ('presentation_downloads', (('export_id', 'TEXT'),)),
        ('exports', (('content_hash', 'TEXT'), ('regen_policy', 'TEXT'), ('cost_usd', 'REAL DEFAULT 0'))),
        ('project_drafts', (('archived_at', 'TEXT'),)),
        ('presentations', (('archived_at', 'TEXT'),)),
        ('section_versions', (('expires_at', 'TEXT'),)),
        ('tenant_branding', (('section_approval_days', 'INTEGER'),)),
        ('tenant_ledger', (('actor', 'TEXT'), ('reversal_of', 'TEXT'))),
    )
    try:
        for table, cols in additions:
            existing = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}
            for name, definition in cols:
                if name not in existing:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
                    print(f"[DB MIGRATION] Added {table} column: {name}")
        conn.commit()
    except Exception as e:
        print(f"[DB WORKFLOW GATE MIGRATION ERR] {e}")


def _migrate_presentation_revision_schema(conn):
    """Add full snapshots without rewriting historical slides-only backups.

    Run before unrelated optional migrations. Introspection works through the
    SQLite/Postgres shim and avoids failed ALTERs aborting Postgres transactions.
    Revision zero denotes an existing identity whose baseline is captured lazily
    under the same write lock as its first revision-aware save.
    """
    for table, additions in (
        ('presentations', (('revision', 'INTEGER NOT NULL DEFAULT 0'),
                           ('current_revision_id', 'TEXT'), ('creation_key', 'TEXT'))),
        ('change_log', (('revision_id', 'TEXT'), ('previous_revision_id', 'TEXT'))),
    ):
        columns = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}
        for name, definition in additions:
            if name not in columns:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
    conn.execute('''CREATE TABLE IF NOT EXISTS presentation_revisions (
        id TEXT PRIMARY KEY,
        presentation_id TEXT NOT NULL REFERENCES presentations(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL,
        title TEXT NOT NULL,
        project_data TEXT,
        slides_data TEXT,
        slide_count INTEGER NOT NULL,
        draft_id TEXT,
        status TEXT,
        content_hash TEXT NOT NULL,
        user_id TEXT,
        user_name TEXT,
        source TEXT NOT NULL,
        action TEXT NOT NULL,
        summary TEXT NOT NULL,
        details TEXT NOT NULL,
        previous_revision_id TEXT,
        restored_from_revision_id TEXT,
        change_log_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (presentation_id, revision)
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_changelog_revision ON change_log(revision_id)')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_presentation_creation_key ON presentations(tenant_id, creation_key)')


def _migrate_presentation_draft_link(conn):
    try:
        cursor = conn.execute("PRAGMA table_info(presentations)")
        existing_cols = {row['name'] for row in cursor.fetchall()}
        if 'draft_id' not in existing_cols:
            conn.execute("ALTER TABLE presentations ADD COLUMN draft_id TEXT")
            print("[DB MIGRATION] Added presentation draft link")
        rows = conn.execute(
            "SELECT id, project_data FROM presentations WHERE draft_id IS NULL OR draft_id = ''"
        ).fetchall()
        for row in rows:
            try:
                project_data = json.loads(row['project_data'] or '{}')
            except (TypeError, ValueError):
                project_data = {}
            draft_id = project_data.get('draftId') or project_data.get('draft_id') if isinstance(project_data, dict) else None
            if draft_id:
                conn.execute('UPDATE presentations SET draft_id = ? WHERE id = ?', (str(draft_id), row['id']))
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_presentations_tenant_draft '
            'ON presentations(tenant_id, draft_id, updated_at)'
        )
        conn.commit()
    except Exception as e:
        print(f"[DB PRESENTATION MIGRATION ERR] {e}")


def _migrate_project_file_table(conn):
    """Create the project file registry for document uploads on older databases."""
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS project_files (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                draft_id TEXT,
                project_id TEXT,
                file_type TEXT NOT NULL,
                original_name TEXT,
                storage_path TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                file_size INTEGER DEFAULT 0,
                sha256 TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_project_files_tenant ON project_files(tenant_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_project_files_draft ON project_files(tenant_id, draft_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_project_files_hash ON project_files(tenant_id, sha256)')
        conn.commit()
    except Exception as e:
        print(f"[DB FILE MIGRATION ERR] {e}")


def _migrate_branding_columns(conn):
    """Add new columns to tenant_branding if they don't exist."""
    try:
        cursor = conn.execute("PRAGMA table_info(tenant_branding)")
        existing_cols = {row['name'] for row in cursor.fetchall()}
        migrations = {
            'default_slide_count': "ALTER TABLE tenant_branding ADD COLUMN default_slide_count INTEGER DEFAULT 16",
            'lock_slide_count': "ALTER TABLE tenant_branding ADD COLUMN lock_slide_count INTEGER DEFAULT 0",
            'min_slides': "ALTER TABLE tenant_branding ADD COLUMN min_slides INTEGER DEFAULT 8",
            'max_slides': "ALTER TABLE tenant_branding ADD COLUMN max_slides INTEGER DEFAULT 30",
            'default_map_type': "ALTER TABLE tenant_branding ADD COLUMN default_map_type TEXT DEFAULT 'satellite'",
            'moodboard_count': "ALTER TABLE tenant_branding ADD COLUMN moodboard_count INTEGER DEFAULT 4",
            'map_style_overview': "ALTER TABLE tenant_branding ADD COLUMN map_style_overview TEXT DEFAULT 'satellite'",
            'map_style_landmarks': "ALTER TABLE tenant_branding ADD COLUMN map_style_landmarks TEXT DEFAULT 'satellite'",
            'map_style_access': "ALTER TABLE tenant_branding ADD COLUMN map_style_access TEXT DEFAULT 'satellite'",
            'map_style_catchment': "ALTER TABLE tenant_branding ADD COLUMN map_style_catchment TEXT DEFAULT 'satellite'",
            'draw_compass': "ALTER TABLE tenant_branding ADD COLUMN draw_compass INTEGER DEFAULT 1",
            'draw_inset': "ALTER TABLE tenant_branding ADD COLUMN draw_inset INTEGER DEFAULT 1",
            'font_file_path': "ALTER TABLE tenant_branding ADD COLUMN font_file_path TEXT",
            'font_file_data': "ALTER TABLE tenant_branding ADD COLUMN font_file_data TEXT",
            'generation_rules': "ALTER TABLE tenant_branding ADD COLUMN generation_rules TEXT",
            'watermark_path': "ALTER TABLE tenant_branding ADD COLUMN watermark_path TEXT",
        }
        for col, sql in migrations.items():
            if col not in existing_cols:
                conn.execute(sql)
                print(f"[DB MIGRATION] Added column: {col}")
        # Fix rows created during the brief window when lock_slide_count defaulted to 1.
        conn.execute('UPDATE tenant_branding SET lock_slide_count = 0 WHERE lock_slide_count = 1')
        conn.commit()
    except Exception as e:
        print(f"[DB MIGRATION ERR] {e}")


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
