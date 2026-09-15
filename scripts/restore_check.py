"""Restore-verify a backup produced by scripts/backup_db.py (t63).

Decrypts the artifact into a scratch directory and runs an integrity check on
the result — ``PRAGMA integrity_check`` for SQLite dumps, ``pg_restore --list``
for Postgres custom-format dumps. Marks the backup row as restore-tested so the
ops dashboard can show the last verified restore.

Usage:
    python scripts/restore_check.py backups/manafe-full-20250101-120000.enc \
        [--backup-id <row id>]

Environment:
    BACKUP_ENCRYPTION_KEY  same key used at backup time — required
"""

import argparse
import base64
import gzip
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_key():
    raw = __import__('os').environ.get('BACKUP_ENCRYPTION_KEY', '').strip()
    if not raw:
        raise SystemExit('BACKUP_ENCRYPTION_KEY is not set')
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        key = base64.b64decode(raw)
    if len(key) != 32:
        raise SystemExit('BACKUP_ENCRYPTION_KEY must decode to exactly 32 bytes')
    return key


def _decrypt(artifact_path, key, work_dir):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    blob = Path(artifact_path).read_bytes()
    nonce, ciphertext = blob[:12], blob[12:]
    payload = gzip.decompress(AESGCM(key).decrypt(nonce, ciphertext, None))
    # A SQLite file starts with its magic header; anything else is a pg dump.
    if payload[:16] == b'SQLite format 3\x00':
        target = Path(work_dir) / 'restored.sqlite3'
    else:
        target = Path(work_dir) / 'restored.dump'
    target.write_bytes(payload)
    return target


def _verify(restored_path):
    if restored_path.suffix == '.sqlite3':
        conn = sqlite3.connect(str(restored_path))
        try:
            result = conn.execute('PRAGMA integrity_check').fetchone()
        finally:
            conn.close()
        if not result or result[0] != 'ok':
            raise SystemExit(f'integrity_check failed: {result}')
        return 'sqlite integrity_check: ok'
    listing = subprocess.run(
        ['pg_restore', '--list', str(restored_path)],
        check=True, capture_output=True, text=True,
    )
    if 'TABLE' not in listing.stdout.upper():
        raise SystemExit('pg_restore listing contained no tables')
    return 'postgres archive listing: ok'


def main():
    parser = argparse.ArgumentParser(description='Verify an encrypted backup restores cleanly')
    parser.add_argument('artifact', help='path to the .enc backup artifact')
    parser.add_argument('--backup-id', default=None,
                        help='backup_history row id to mark restore-tested')
    args = parser.parse_args()

    key = _load_key()
    with tempfile.TemporaryDirectory() as work_dir:
        restored = _decrypt(args.artifact, key, work_dir)
        verdict = _verify(restored)
    print(verdict)

    if args.backup_id:
        import db
        from flask import Flask
        app = Flask(__name__)
        with app.app_context():
            row = db.mark_backup_restore_tested(args.backup_id, note=verdict)
        print(f"restore test recorded: {row['id']}" if row else 'backup row not found')


if __name__ == '__main__':
    main()
