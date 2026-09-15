"""Encrypted database backup (t63).

Produces a consistent copy of the application database, compresses it,
encrypts it with AES-256-GCM and registers the run in ``backup_history``
so the platform can report RPO compliance from the ops dashboard.

Usage:
    python scripts/backup_db.py [--kind full|pre-deploy|manual]

Environment:
    BACKUP_ENCRYPTION_KEY  hex or base64 32-byte key — required
    BACKUP_DIR             destination directory (default: ./backups)
    DATABASE_URL           postgres URL; without it the SQLite DB_PATH is used
    DB_PATH                SQLite file override (same default as db.py)

Restore a produced artifact with scripts/restore_check.py.
"""

import argparse
import base64
import gzip
import hashlib
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402


def _load_key():
    raw = os.environ.get('BACKUP_ENCRYPTION_KEY', '').strip()
    if not raw:
        raise SystemExit('BACKUP_ENCRYPTION_KEY is not set')
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        key = base64.b64decode(raw)
    if len(key) != 32:
        raise SystemExit('BACKUP_ENCRYPTION_KEY must decode to exactly 32 bytes')
    return key


def _dump_database(work_dir):
    """Return a path to a consistent plaintext dump inside work_dir."""
    database_url = os.environ.get('DATABASE_URL', '').strip()
    if database_url.startswith(('postgres://', 'postgresql://')):
        target = Path(work_dir) / 'dump.dump'
        subprocess.run(
            ['pg_dump', '--format=custom', '--file', str(target), database_url],
            check=True,
        )
        return target
    target = Path(work_dir) / 'backup.sqlite3'
    import sqlite3
    source = sqlite3.connect(db.DB_PATH)
    try:
        dest = sqlite3.connect(str(target))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    return target


def _encrypt(plaintext_path, key, out_path):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    payload = gzip.compress(Path(plaintext_path).read_bytes(), compresslevel=9)
    ciphertext = AESGCM(key).encrypt(nonce, payload, None)
    # Layout: 12-byte nonce || ciphertext+tag
    Path(out_path).write_bytes(nonce + ciphertext)
    return out_path


def main():
    parser = argparse.ArgumentParser(description='Encrypted database backup')
    parser.add_argument('--kind', default='manual',
                        choices=('full', 'pre-deploy', 'manual'))
    args = parser.parse_args()

    key = _load_key()
    backup_dir = Path(os.environ.get('BACKUP_DIR', str(ROOT / 'backups')))
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    out_path = backup_dir / f'manafe-{args.kind}-{stamp}.enc'

    with tempfile.TemporaryDirectory() as work_dir:
        dump_path = _dump_database(work_dir)
        _encrypt(dump_path, key, out_path)

    blob = Path(out_path).read_bytes()
    digest = hashlib.sha256(blob).hexdigest()

    from flask import Flask
    app = Flask(__name__)
    with app.app_context():
        row = db.record_backup(
            kind=args.kind, path=str(out_path), size_bytes=len(blob),
            sha256=digest, encrypted=True,
        )
    print(f"backup recorded: {row['id']} -> {out_path} ({len(blob)} bytes, sha256 {digest[:16]}...)")


if __name__ == '__main__':
    main()
