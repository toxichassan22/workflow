import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auth
import db


def _make_args(db_path, backup_dir, old_email='old-admin@example.test',
               new_email='owner@newcompany.test', new_company='New Admin Co',
               new_password='StrongPass12345', dry_run=False, yes=True):
    return Namespace(
        old_admin_email=old_email,
        new_admin_email=new_email,
        new_company_name=new_company,
        new_admin_password=new_password,
        db_path=db_path,
        backup_dir=backup_dir,
        dry_run=dry_run,
        yes=yes,
    )


class SuperAdminMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_db_path = db.DB_PATH
        cls.db_path = os.path.join(cls.temp_dir.name, 'migrate-test.db')
        cls.backup_dir = os.path.join(cls.temp_dir.name, 'backups')
        db.DB_PATH = cls.db_path
        # Late import so the script resolves BASE_DIR correctly; import function only.
        from scripts.migrate_super_admin import run_migration as _run
        cls.run_migration_fn = staticmethod(_run)

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def setUp(self):
        # Fresh DB per test.
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        for suffix in ('-wal', '-shm', '-journal'):
            try:
                os.remove(self.db_path + suffix)
            except OSError:
                pass
        db.init_db()
        self.old_id = str(uuid.uuid4())
        con = sqlite3.connect(self.db_path)
        con.execute(
            "INSERT INTO tenants (id, company_name, email, password_hash, plan, is_admin, is_active)"
            " VALUES (?,?,?,?, 'enterprise',1,1)",
            (self.old_id, 'Client Real Company', 'old-admin@example.test',
             auth.hash_password('OldAdmin12345')),
        )
        con.execute(
            'INSERT INTO tenant_branding (tenant_id, company_name) VALUES (?,?)',
            (self.old_id, 'Client Real Company'),
        )
        for i in range(2):
            con.execute(
                'INSERT INTO users (id, tenant_id, name, email, password_hash, role, is_active)'
                ' VALUES (?,?,?,?,?,?,1)',
                (str(uuid.uuid4()), self.old_id, f'User{i}',
                 f'user{i}@example.test', auth.hash_password('UserPass12345'), 'employee'),
            )
        for i in range(3):
            con.execute(
                'INSERT INTO project_drafts (id, tenant_id, user_id, title, draft_data, status)'
                ' VALUES (?,?,?,?,?,?)',
                (str(uuid.uuid4()), self.old_id, f'tenant-admin:{self.old_id}',
                 f'Project {i}', json.dumps({'project_name': f'P{i}'}, ensure_ascii=False), 'draft'),
            )
        con.execute(
            'INSERT INTO presentations (id, tenant_id, title, project_data, slides_data, slide_count)'
            ' VALUES (?,?,?,?,?,?)',
            (str(uuid.uuid4()), self.old_id, 'Demo', '{}', '[]', 0),
        )
        con.execute(
            'INSERT INTO project_files (id, tenant_id, file_type, storage_path, mime_type, sha256)'
            ' VALUES (?,?,?,?,?,?)',
            (str(uuid.uuid4()), self.old_id, 'cover', '/tmp/x.png', 'image/png', 'abc'),
        )
        con.commit()
        con.close()

    def _query(self, sql, params=()):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute(sql, params).fetchall()]
        finally:
            con.close()

    def test_dry_run_makes_no_changes(self):
        code = self.run_migration_fn(_make_args(self.db_path, self.backup_dir, dry_run=True, yes=False))
        self.assertEqual(code, 0)
        tenants = self._query('SELECT email, is_admin FROM tenants')
        self.assertEqual(len(tenants), 1)
        self.assertEqual(tenants[0]['email'], 'old-admin@example.test')
        self.assertEqual(
            self._query('SELECT COUNT(*) c FROM users')[0]['c'], 2)
        self.assertEqual(
            self._query('SELECT COUNT(*) c FROM project_drafts')[0]['c'], 3)

    def test_migration_preserves_projects_and_empties_users(self):
        code = self.run_migration_fn(_make_args(self.db_path, self.backup_dir))
        self.assertEqual(code, 0)
        tenants = {r['email']: r for r in self._query('SELECT * FROM tenants')}
        self.assertIn('old-admin@example.test', tenants)
        self.assertIn('owner@newcompany.test', tenants)
        old = tenants['old-admin@example.test']
        new = tenants['owner@newcompany.test']
        # Same old id, demoted, still active, locked login.
        self.assertEqual(old['id'], self.old_id)
        self.assertEqual(old['is_admin'], 0)
        self.assertEqual(old['is_active'], 1)
        self.assertIsNone(old['primary_user_id'])
        self.assertEqual(new['is_admin'], 1)
        self.assertEqual(new['plan'], 'enterprise')
        # Projects preserved under old id, none under new.
        old_counts = self._query(
            'SELECT (SELECT COUNT(*) FROM project_drafts WHERE tenant_id=?) drafts,'
            ' (SELECT COUNT(*) FROM presentations WHERE tenant_id=?) presentations,'
            ' (SELECT COUNT(*) FROM users WHERE tenant_id=?) users,'
            ' (SELECT COUNT(*) FROM project_files WHERE tenant_id=?) files',
            (self.old_id, self.old_id, self.old_id, self.old_id))[0]
        self.assertEqual(old_counts['drafts'], 3)
        self.assertEqual(old_counts['presentations'], 1)
        self.assertEqual(old_counts['users'], 0)
        self.assertEqual(old_counts['files'], 1)
        self.assertEqual(
            self._query('SELECT COUNT(*) c FROM project_drafts WHERE tenant_id=?',
                        (new['id'],))[0]['c'], 0)
        # Passwords: old invalidated, new works.
        self.assertFalse(auth.verify_password('OldAdmin12345', old['password_hash']))
        self.assertTrue(auth.verify_password('StrongPass12345', new['password_hash']))
        # Backup was written.
        self.assertTrue(os.path.isdir(self.backup_dir))
        self.assertTrue(any(Path(self.backup_dir).iterdir()))
        # Isolation: new tenant cannot read old drafts by tenant scoping.
        cross = self._query(
            'SELECT id FROM project_drafts WHERE tenant_id=? AND id IN'
            ' (SELECT id FROM project_drafts WHERE tenant_id=?)',
            (new['id'], self.old_id))
        self.assertEqual(cross, [])

    def test_validation_rejects_bad_input(self):
        # Short password.
        code = self.run_migration_fn(_make_args(
            self.db_path, self.backup_dir, new_password='short1'))
        self.assertEqual(code, 1)
        # Same email.
        code = self.run_migration_fn(_make_args(
            self.db_path, self.backup_dir,
            old_email='same@example.test', new_email='same@example.test'))
        self.assertEqual(code, 1)
        # Missing old tenant.
        code = self.run_migration_fn(_make_args(
            self.db_path, self.backup_dir, old_email='missing@example.test'))
        self.assertEqual(code, 1)

    def test_new_email_conflict_is_rejected(self):
        con = sqlite3.connect(self.db_path)
        con.execute(
            "INSERT INTO tenants (id, company_name, email, password_hash, plan, is_admin, is_active)"
            " VALUES (?,?,?,?, 'free',0,1)",
            (str(uuid.uuid4()), 'Other', 'owner@newcompany.test',
             auth.hash_password('OtherPass12345')),
        )
        con.commit()
        con.close()
        code = self.run_migration_fn(_make_args(self.db_path, self.backup_dir))
        self.assertEqual(code, 1)

    def test_old_tenant_must_be_admin(self):
        con = sqlite3.connect(self.db_path)
        con.execute('UPDATE tenants SET is_admin=0 WHERE id=?', (self.old_id,))
        con.commit()
        con.close()
        code = self.run_migration_fn(_make_args(self.db_path, self.backup_dir))
        self.assertEqual(code, 1)


if __name__ == '__main__':
    unittest.main()
