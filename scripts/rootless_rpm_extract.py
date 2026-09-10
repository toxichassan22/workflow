#!/usr/bin/env python3
"""Extract shared libraries from EL .rpm files without root or rpm tooling.

Shared cPanel hosting has no root, no yum/dnf and often no rpm2cpio/cpio, so
the Chromium system libraries cannot be installed the normal way. This script
side-loads them into a directory in $HOME using the standard library only:

    python3 scripts/rootless_rpm_extract.py pkg1.rpm pkg2.rpm --dest ~/chromium-libs

Only ``usr/lib64/*.so*`` entries (files and symlinks) are extracted; absolute
paths and ``..`` entries are refused. Payload compressions gzip and xz are
handled by the standard library; zstd payloads need ``pip install zstandard``
and fail with that exact hint.

After extraction, point the loader at the directory (staging reads its own
``.env``, which both start_server-staging.sh and deploy-staging.sh export):

    LD_LIBRARY_PATH=/home/landloom/chromium-libs/usr/lib64

then restart with ``start_server-staging.sh --force`` and re-check
``/health?vision=1``. Repeat ``ldd <chrome-headless-shell> | grep 'not found'``
until it is clean, adding the package that owns each still-missing library.
"""

import gzip
import lzma
import os
import stat
import struct
import sys

RPM_LEAD_MAGIC = b'\xed\xab\xee\xdb'
RPM_HEADER_MAGIC = b'\x8e\xad\xe8'
CPIO_NEWC_MAGIC = b'070701'
CPIO_TRAILER = 'TRAILER!!!'


def _read_header(data, offset, pad):
    """Skip one RPM tag header; return the offset just past it.

    Header starts are 8-aligned, so the signature header (which another
    header follows) is padded to 8. The compressed payload follows the
    metadata header immediately with no padding of its own.
    """
    if data[offset:offset + 3] != RPM_HEADER_MAGIC:
        raise ValueError(f'bad rpm header magic at offset {offset}')
    nindex, hsize = struct.unpack_from('>2I', data, offset + 8)
    # hsize already includes the data padding.
    end = offset + 16 + nindex * 16 + hsize
    if end > len(data):
        raise ValueError('rpm header overruns file')
    if pad:
        end += (8 - (end % 8)) % 8
    return end


def _payload_magic_kind(data, offset):
    tail = data[offset:offset + 6]
    if tail[:2] == b'\x1f\x8b':
        return 'gzip'
    if tail[:6] == b'\xfd7zXZ\x00':
        return 'xz'
    if tail[:4] == b'\x28\xb5\x2f\xfd':
        return 'zstd'
    return None


def rpm_payload_offset(data):
    """Return (offset, compressor) of the payload inside raw .rpm bytes."""
    if data[:4] != RPM_LEAD_MAGIC:
        raise ValueError('not an rpm file (bad lead magic)')
    offset = _read_header(data, 96, pad=True)  # signature header, 8-aligned next
    offset = _read_header(data, offset, pad=False)  # metadata header, payload next
    kind = _payload_magic_kind(data, offset)
    if kind is None:
        # A stray pad byte still defeats magic checks, so probe a few bytes
        # back before failing: headers align but the payload need not.
        for back in range(1, 8):
            kind = _payload_magic_kind(data, offset - back)
            if kind is not None:
                offset -= back
                break
    if kind is None:
        raise ValueError(f'unknown rpm payload compression at offset {offset}')
    return offset, kind


def decompress_payload(data, offset, compressor):
    blob = data[offset:]
    if compressor == 'gzip':
        return gzip.decompress(blob)
    if compressor == 'xz':
        return lzma.decompress(blob)
    if compressor == 'zstd':
        try:
            import zstandard
        except ImportError:
            raise RuntimeError(
                'rpm payload uses zstd; run `pip install zstandard` (no root needed) '
                'and retry'
            )
        return zstandard.ZstdDecompressor().decompress(blob)
    raise ValueError(f'unsupported compressor: {compressor}')


def _pad(length):
    return (4 - (length % 4)) % 4


def parse_cpio_newc(data):
    """Yield (name, mode, file_bytes_or_symlink_target) from a newc archive."""
    entries = []
    offset = 0
    end = len(data)
    while offset + 110 <= end:
        if data[offset:offset + 6] != CPIO_NEWC_MAGIC:
            raise ValueError(f'bad cpio magic at offset {offset}')
        fields = struct.unpack('6x' + '8s' * 13, data[offset:offset + 110])
        numbers = [int(field.decode('ascii'), 16) for field in fields]
        (_ino, mode, _uid, _gid, _nlink, _mtime, filesize, _devmaj,
         _devmin, _rdevmaj, _rdevmin, namesize, _check) = numbers
        name_start = offset + 110
        name = data[name_start:name_start + namesize].rstrip(b'\x00').decode('utf-8')
        data_start = name_start + namesize + _pad(110 + namesize)
        content = data[data_start:data_start + filesize]
        if len(content) != filesize:
            raise ValueError(f'truncated cpio entry {name!r}')
        offset = data_start + filesize + _pad(filesize)
        if name == CPIO_TRAILER:
            break
        entries.append((name, mode, content))
    return entries


def _safe_join(dest, name):
    cleaned = name.lstrip('./')
    target = os.path.realpath(os.path.join(dest, cleaned))
    if os.path.commonpath([os.path.realpath(dest), target]) != os.path.realpath(dest):
        raise ValueError(f'refusing to extract outside dest: {name!r}')
    return target


def extract_rpm(path, dest):
    """Extract usr/lib64 shared objects from one .rpm into dest; return paths."""
    with open(path, 'rb') as handle:
        data = handle.read()
    offset, compressor = rpm_payload_offset(data)
    archive = decompress_payload(data, offset, compressor)
    extracted = []
    pending_links = []

    def _write_link(target, link_target):
        try:
            if os.path.islink(target) or os.path.exists(target):
                os.unlink(target)
            os.symlink(link_target, target)
            return True
        except OSError:
            # No-symlink filesystems (Windows dev machines): fall back to a
            # copy of the already-extracted target when it is inside dest.
            resolved = os.path.realpath(os.path.join(os.path.dirname(target), link_target))
            if resolved.startswith(os.path.realpath(dest)) and os.path.isfile(resolved):
                with open(resolved, 'rb') as source:
                    content = source.read()
                with open(target, 'wb') as handle:
                    handle.write(content)
                return True
            return False

    for name, mode, content in parse_cpio_newc(archive):
        cleaned = name.lstrip('./')
        if not (cleaned.startswith('usr/lib64/') or cleaned.startswith('usr/lib/')):
            continue
        base = os.path.basename(cleaned.rstrip('/'))
        if '.so' not in base:
            continue
        if cleaned.endswith('/'):
            continue
        target = _safe_join(dest, cleaned)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if stat.S_ISLNK(mode):
            pending_links.append((target, content.decode('utf-8')))
        elif stat.S_ISREG(mode):
            with open(target, 'wb') as handle:
                handle.write(content)
            os.chmod(target, 0o755 if mode & 0o111 else 0o644)
        else:
            continue
        extracted.append(target)
    for target, link_target in pending_links:
        if not _write_link(target, link_target):
            raise OSError(f'cannot create symlink {target} -> {link_target}')
    return extracted


def main(argv):
    dest = None
    files = []
    args = list(argv)
    while args:
        token = args.pop(0)
        if token == '--dest' and args:
            dest = args.pop(0)
        elif token.startswith('--dest='):
            dest = token.split('=', 1)[1]
        else:
            files.append(token)
    if not files or not dest:
        print(__doc__)
        return 2
    dest = os.path.abspath(os.path.expanduser(dest))
    os.makedirs(dest, exist_ok=True)
    total = 0
    for path in files:
        found = extract_rpm(path, dest)
        print(f'{os.path.basename(path)}: {len(found)} libraries')
        for target in sorted(found):
            print(f'  {os.path.relpath(target, dest)}')
        total += len(found)
    print(f'done: {total} libraries under {dest}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
