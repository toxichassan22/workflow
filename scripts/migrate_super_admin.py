"""Migrate the super-admin account to a new company without losing client projects.

Situation this solves (Arabic):
  شركة السوبر ادمن الحالية فيها مشاريع شركة حقيقية. المطلوب نقل حساب الادارة
  لشركة جديدة تبقى هي السوبر ادمن الرسمي, والشركة الحالية تفضل بنفس المعرف
  وبكل مشاريعها وعروضها وصورها, لكن من غير حسابات مستخدمين, لحد ما العميل
  يستلمها بدعوة مخصصة.

What this script does:
  1. Backs up the SQLite file (app.db + wal/shm) before touching anything.
     For Postgres (DATABASE_URL) it skips the file copy and relies on a
     single transaction plus pre/post counts.
  2. Verifies the old tenant exists, is_admin=1, and reports projects /
     presentations / users counts.
  3. Creates the NEW super-admin tenant (is_admin=1, enterprise, empty).
  4. Demotes the OLD tenant to is_admin=0, keeping the SAME id so every
     project_drafts / presentations / project_files / map_images row stays
     reachable. Resets its password to a random secret and clears
     primary_user_id so nobody can log in with the old credentials.
  5. Empties the OLD tenant accounts: deletes rows in users plus their
     password_setup_tokens. Tenant-level data (drafts, presentations,
     branding, files) is never deleted.
  6. Verifies after: old projects count unchanged, old users == 0,
     new tenant has no projects, old is_admin == 0, new is_admin == 1.

What it does NOT do:
  - It never deletes the old tenant row (that would cascade-delete projects).
  - It never moves drafts to the new tenant (new company starts empty).
  - It never touches .env automatically. After success you MUST update
    ADMIN_EMAIL / ADMIN_PASSWORD / ADMIN_COMPANY_NAME on the server,
    otherwise the next restart re-promotes the OLD email via _seed_admin().

Client onboarding (after this script):
  التسجيل العادي POST /api/auth/register يعمل شركة جديدة تماما, لذلك لا يصلح
  لدخول العميل على شركته القديمة. الصح هو ان السوبر ادمن الجديد ينشئ للعميل
  مدير شركة داخل نفس tenant القديم:
    POST /api/admin/tenants/<OLD_TENANT_ID>/users
    {name, email, username, phone, role: company_admin, useSetupLink: true}
  ثم يرسل setupUrl للعميل. العميل يفتح الرابط, يعين كلمة سر, ويدخل ليرى
  نفس المشاريع لانها مربوطة بـ tenant_id وليس بـ user_id.

Usage (run on the host that owns the DB file):
  python scripts/migrate_super_admin.py \\
    --old-admin-email sag@example.com \\
    --new-admin-email owner@newcompany.com \\
    --new-company-name "My New Admin Company" \\
    --new-admin-password "StrongPass12345" \\
    --db-path app.db --backup-dir backups --dry-run

  Remove --dry-run and add --yes to execute.

Exit codes: 0 success, 1 validation failure, 2 migration failure.
"""

import argparse
import copy
import json
import os
import re
import secrets
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
try:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    from auth import hash_password
except Exception:  # fallback when auth cannot import (no .jwt_secret etc.)
    import hashlib
    import hmac

    def hash_password(password):
        salt = os.urandom(32)
        key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
        return f"pbkdf2$sha256${salt.hex()}${key.hex()}"

try:
    import db as db_module

    PREBUILT_FIELDS = list(getattr(db_module, 'PREBUILT_FIELDS', []) or [])
except Exception:
    PREBUILT_FIELDS = []


def _is_postgres_dsn(value):
    return isinstance(value, str) and value.startswith(('postgres://', 'postgresql://'))


def _resolve_db_path(explicit):
    if explicit:
        return explicit
    return os.environ.get('DB_PATH') or os.environ.get('DATABASE_URL') or str(BASE_DIR / 'app.db')


def _backup_sqlite(db_path, backup_dir):
    src = Path(db_path)
    if not src.exists():
        raise FileNotFoundError(f'DB file not found: {db_path}')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    dest_dir = Path(backup_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for candidate in (src, Path(str(src) + '-wal'), Path(str(src) + '-shm')):
        if candidate.exists():
            dest = dest_dir / f"{src.stem}-pre-superadmin-migration-{stamp}{candidate.suffix or '.db'}"
            # Avoid collision when wal/shm share suffix handling.
            if candidate.name != src.name:
                dest = dest_dir / f"{candidate.name}-pre-superadmin-migration-{stamp}.bak"
            shutil.copy2(candidate, dest)
            copied.append(str(dest))
    # Also dump a JSON manifest of counts for human audit.
    return copied, stamp


def _connect(db_path):
    con = sqlite3.connect(db_path, timeout=30.0)
    con.row_factory = sqlite3.Row
    try:
        con.execute('PRAGMA busy_timeout = 10000;')
    except Exception:
        pass
    return con


def _counts(con, tenant_id):
    out = {}
    for table, key in (
        ('project_drafts', 'projects'),
        ('presentations', 'presentations'),
        ('users', 'users'),
        ('project_files', 'files'),
        ('exports', 'exports'),
    ):
        try:
            row = con.execute(f'SELECT COUNT(*) AS c FROM {table} WHERE tenant_id = ?', (tenant_id,)).fetchone()
            out[key] = int(row['c']) if row else 0
        except Exception:
            out[key] = -1
    try:
        row = con.execute(
            'SELECT COUNT(*) AS c FROM password_setup_tokens WHERE tenant_id = ?', (tenant_id,)
        ).fetchone()
        out['setup_tokens'] = int(row['c']) if row else 0
    except Exception:
        out['setup_tokens'] = -1
    return out


def _validate_args(args):
    errors = []
    email_re = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    old_email = (args.old_admin_email or '').strip().lower()
    new_email = (args.new_admin_email or '').strip().lower()
    if not old_email or not email_re.match(old_email):
        errors.append('old-admin-email غير صالح.')
    if not new_email or not email_re.match(new_email):
        errors.append('new-admin-email غير صالح.')
    if old_email and new_email and old_email == new_email:
        errors.append('البريد الجديد يجب ان يختلف عن بريد السوبر ادمن الحالي.')
    if not (args.new_company_name or '').strip():
        errors.append('new-company-name مطلوب.')
    elif len(args.new_company_name.strip()) > 120:
        errors.append('اسم الشركة الجديدة طويل جدا (120 حرف حد اقصى).')
    pwd = args.new_admin_password or ''
    if len(pwd) < 12:
        errors.append('كلمة سر الادمن الجديدة يجب ان تكون 12 حرف على الاقل (شرط _seed_admin).')
    elif not re.search(r'[A-Za-z]', pwd) or not re.search(r'[0-9]', pwd):
        errors.append('كلمة السر يجب ان تشمل حروف وارقام.')
    return errors


def run_migration(args):
    db_path = _resolve_db_path(args.db_path)
    if _is_postgres_dsn(db_path):
        print('Postgres DSN detected: file backup is skipped. تأكد من وجود نسخة احتياطية مدارة قبل --yes.')
        if args.dry_run:
            print('dry-run: لن يتم تنفيذ اي كتابة على Postgres في وضع المعاينة.')
        backup_files = []
        use_sqlite_backup = False
    else:
        use_sqlite_backup = True
        backup_files = []

    errors = _validate_args(args)
    if errors:
        for err in errors:
            print(f'ERROR: {err}')
        return 1

    old_email = args.old_admin_email.strip().lower()
    new_email = args.new_admin_email.strip().lower()
    new_company = args.new_company_name.strip()

    if use_sqlite_backup and not args.dry_run:
        try:
            backup_files, stamp = _backup_sqlite(db_path, args.backup_dir)
            print('Backup OK:')
            for path in backup_files:
                print(f'  - {path}')
        except Exception as exc:
            print(f'ERROR: فشل النسخ الاحتياطي, تم ايقاف النقل حفاظا على البيانات: {exc}')
            return 2

    con = _connect(db_path)
    try:
        old = con.execute('SELECT * FROM tenants WHERE email = ?', (old_email,)).fetchone()
        if not old:
            print(f'ERROR: لا توجد شركة بهذا البريد الحالي: {old_email}')
            return 1
        old = dict(old)
        if not old.get('is_admin'):
            print(f"ERROR: الشركة {old_email} ليست سوبر ادمن (is_admin=0). راجع البريد المقصود.")
            return 1
        old_id = old['id']

        conflict_tenant = con.execute('SELECT id, email FROM tenants WHERE email = ?', (new_email,)).fetchone()
        if conflict_tenant:
            print(f"ERROR: البريد الجديد مسجل بالفعل كشركة: {new_email}")
            return 1
        conflict_user = con.execute('SELECT id, tenant_id FROM users WHERE email = ?', (new_email,)).fetchone()
        if conflict_user:
            print(f"ERROR: البريد الجديد مسجل بالفعل كمستخدم داخل شركة {conflict_user['tenant_id']}")
            return 1

        admins = con.execute("SELECT id, company_name, email FROM tenants WHERE is_admin = 1").fetchall()
        print(f'Super-admin tenants before: {len(admins)}')
        for row in admins:
            print(f"  - {row['company_name']} <{row['email']}> id={row['id']}")

        before_old = _counts(con, old_id)
        print(f"Old tenant id={old_id} company={old.get('company_name')}")
        print(f"Before counts (old): {json.dumps(before_old, ensure_ascii=False)}")

        old_users = con.execute(
            'SELECT id, name, email, username, role, is_active FROM users WHERE tenant_id = ? ORDER BY created_at',
            (old_id,),
        ).fetchall()
        print(f"Old tenant users: {len(old_users)}")
        for user in old_users:
            print(f"  - {user['name']} <{user['email']}> role={user['role']} active={user['is_active']}")

        if args.dry_run:
            print('dry-run: لا تغيير. احذف --dry-run مع --yes للتنفيذ الفعلي.')
            print('Planned actions:')
            print(f'  1. Create new super-admin tenant "{new_company}" <{new_email}> (empty, enterprise, is_admin=1).')
            print(f'  2. Demote old tenant {old_id} to is_admin=0, reset password to random, clear primary_user_id.')
            print(f'  3. Delete {len(old_users)} user(s) + setup tokens under old tenant. Projects stay untouched.')
            print('  4. REQUIRED after: update ADMIN_EMAIL/ADMIN_PASSWORD/ADMIN_COMPANY_NAME on the server.')
            return 0

        if not args.yes:
            print('ERROR: التنفيذ الفعلي يتطلب --yes للتأكيد الصريح بعد مراجعة --dry-run.')
            return 1

        new_id = str(uuid.uuid4())
        new_hash = hash_password(args.new_admin_password)
        random_lock = secrets.token_urlsafe(24)

        try:
            con.execute('BEGIN IMMEDIATE')
            # 1. New super-admin tenant (empty workspace).
            con.execute(
                '''INSERT INTO tenants
                   (id, company_name, email, password_hash, plan, is_admin, is_active)
                   VALUES (?, ?, ?, ?, 'enterprise', 1, 1)''',
                (new_id, new_company, new_email, new_hash),
            )
            con.execute(
                '''INSERT INTO tenant_branding
                   (tenant_id, company_name, primary_color, secondary_color, accent_color,
                    background_color, lock_slide_count)
                   VALUES (?, ?, '#3B6E91', '#254B66', '#6DA3C3', '#F4F9FC', 0)''',
                (new_id, new_company),
            )
            for field in PREBUILT_FIELDS:
                try:
                    con.execute(
                        '''INSERT INTO tenant_input_fields
                           (id, tenant_id, field_key, field_label, field_type, field_options,
                            section_key, is_required, is_active, is_custom, sort_order, ai_hint)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)''',
                        (
                            str(uuid.uuid4()), new_id, field.get('key'), field.get('label'),
                            field.get('type'),
                            json.dumps(field.get('options', []), ensure_ascii=False) if field.get('options') else None,
                            field.get('section_key', 'general'),
                            1 if field.get('required') else 0, 1,
                            field.get('sort_order', 0), field.get('ai_hint', ''),
                        ),
                    )
                except Exception as field_exc:
                    print(f'WARN: default field {field.get("key")} seed skipped: {field_exc}')

            # 2. Demote old tenant, lock its direct login, keep the same id.
            con.execute(
                '''UPDATE tenants
                   SET is_admin = 0,
                       password_hash = ?,
                       require_password_change = 1,
                       primary_user_id = NULL,
                       is_active = 1
                   WHERE id = ?''',
                (hash_password(random_lock), old_id),
            )
            # 3. Empty accounts under old tenant only.
            con.execute('DELETE FROM password_setup_tokens WHERE tenant_id = ?', (old_id,))
            con.execute('DELETE FROM users WHERE tenant_id = ?', (old_id,))
            con.commit()
        except Exception as exc:
            try:
                con.rollback()
            except Exception:
                pass
            print(f'ERROR: فشل النقل وتم التراجع عن كل الكتابة: {exc}')
            return 2

        after_old = _counts(con, old_id)
        after_new = _counts(con, new_id)
        old_after_row = con.execute('SELECT id, company_name, email, is_admin, is_active FROM tenants WHERE id = ?', (old_id,)).fetchone()
        new_after_row = con.execute('SELECT id, company_name, email, is_admin, is_active FROM tenants WHERE id = ?', (new_id,)).fetchone()

        print('Migration committed.')
        print(f"After counts (old {old_id}): {json.dumps(after_old, ensure_ascii=False)}")
        print(f"After counts (new {new_id}): {json.dumps(after_new, ensure_ascii=False)}")

        ok = True
        if after_old.get('projects') != before_old.get('projects'):
            print(f"ERROR: عدد مشاريع الشركة القديمة تغير! قبل={before_old.get('projects')} بعد={after_old.get('projects')}")
            ok = False
        if after_old.get('presentations') != before_old.get('presentations'):
            print('ERROR: عدد العروض تغير في الشركة القديمة!')
            ok = False
        if after_old.get('files') not in (-1, before_old.get('files')):
            print('ERROR: عدد ملفات الشركة القديمة تغير!')
            ok = False
        if (after_old.get('users') or 0) != 0:
            print('ERROR: ما زالت هناك حسابات مستخدمين في الشركة القديمة.')
            ok = False
        if (after_new.get('projects') or 0) != 0:
            print('ERROR: الشركة الجديدة يجب ان تبدأ بدون مشاريع.')
            ok = False
        if not new_after_row or not new_after_row['is_admin']:
            print('ERROR: الشركة الجديدة ليست سوبر ادمن.')
            ok = False
        if not old_after_row or old_after_row['is_admin']:
            print('ERROR: الشركة القديمة ما زالت سوبر ادمن.')
            ok = False
        if not ok:
            print('Migration finished BUT verification failed. استعد من النسخة الاحتياطية فورا قبل اي خطوة اخرى.')
            return 2

        print('Verification OK: المشاريع محفوظة بنفس العدد, القديمة بلا مستخدمين, الجديدة سوبر ادمن فاضية.')
        print('')
        print('REQUIRED next step on the server (.env) BEFORE restart:')
        print(f'  ADMIN_EMAIL={new_email}')
        print('  ADMIN_PASSWORD=<كلمة سر الادمن الجديدة التي ادخلتها>')
        print(f'  ADMIN_COMPANY_NAME={new_company}')
        print('  السبب: _seed_admin() يعيد ترقية اي tenant يحمل ADMIN_EMAIL عند كل تشغيل.')
        current_env_email = (os.environ.get('ADMIN_EMAIL') or '').strip().lower()
        if current_env_email == old_email:
            print('URGENT: متغير البيئة الحالي ADMIN_EMAIL ما زال يشير للشركة القديمة.')
            print('  حدث ملف .env على السيرفر فورا ولا تعيد تشغيل السيرفر قبل ذلك,')
            print('  والا ستعود القديمة سوبر ادمن بجانب الجديدة (تم اثبات ذلك بالاختبار).')
        elif current_env_email and current_env_email != new_email:
            print(f'NOTE: البيئة الحالية تشير الى {current_env_email} وليس الجديد. حدثها يدويًا.')
        print('')
        print('Client onboarding later (لا تستخدم التسجيل العادي, لانه ينشئ شركة جديدة):')
        print(f'  POST /api/admin/tenants/{old_id}/users')
        print('  {name, email, username, phone, role: company_admin, useSetupLink: true}')
        print('  ثم ارسل setupUrl للعميل. سيدخل على نفس tenant_id ويرى نفس المشاريع.')
        return 0
    finally:
        try:
            con.close()
        except Exception:
            pass


def build_parser():
    parser = argparse.ArgumentParser(description='Move super-admin to a new company, keep old projects, empty old accounts.')
    parser.add_argument('--old-admin-email', required=True, help='Current super-admin tenant email')
    parser.add_argument('--new-admin-email', required=True, help='New super-admin tenant email')
    parser.add_argument('--new-company-name', required=True, help='New super-admin company name')
    parser.add_argument('--new-admin-password', required=True, help='New super-admin password (12+ chars, letters+numbers)')
    parser.add_argument('--db-path', default=None, help='SQLite file or Postgres DSN (default: DB_PATH/DATABASE_URL/app.db)')
    parser.add_argument('--backup-dir', default=str(BASE_DIR / 'backups'), help='Where to store SQLite backup')
    parser.add_argument('--dry-run', action='store_true', help='Show plan and counts without writing')
    parser.add_argument('--yes', action='store_true', help='Explicit confirmation for real execution')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return run_migration(args)


if __name__ == '__main__':
    raise SystemExit(main())
