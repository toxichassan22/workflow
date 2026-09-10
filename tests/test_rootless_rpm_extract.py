import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from rootless_rpm_extract import (
    decompress_payload,
    extract_rpm,
    parse_cpio_newc,
    rpm_payload_offset,
)

import gzip


def _cpio_entry(name, mode, content):
    name_bytes = name.encode('utf-8') + b'\x00'
    header = b'070701' + b''.join(
        f'{value:08x}'.encode('ascii')
        for value in (0, mode, 0, 0, 1, 0, len(content), 0, 0, 0, 0, len(name_bytes), 0)
    )
    assert len(header) == 110
    blob = header + name_bytes
    blob += b'\x00' * ((4 - (len(blob) % 4)) % 4)
    blob += content
    blob += b'\x00' * ((4 - (len(content) % 4)) % 4)
    return blob


def _cpio_archive(entries):
    blob = b''.join(entries)
    return blob + _cpio_entry('TRAILER!!!', 0, b'')


def _rpm_file(payload):
    lead = b'\xed\xab\xee\xdb' + b'\x00' * 92
    empty_header = b'\x8e\xad\xe8\x01' + struct.pack('>III', 0, 0, 0)
    return lead + empty_header + empty_header + payload


class RootlessRpmExtractTests(unittest.TestCase):
    def test_cpio_newc_round_trip_with_symlink(self):
        archive = _cpio_archive([
            _cpio_entry('usr/lib64/libfoo.so.1.2', 0o100755, b'ELF soilib'),
            _cpio_entry('usr/lib64/libfoo.so', 0o120777, b'libfoo.so.1.2'),
            _cpio_entry('usr/share/doc/x', 0o100644, b'docs'),
        ])
        entries = dict((name, (mode, content)) for name, mode, content in parse_cpio_newc(archive))
        self.assertEqual(entries['usr/lib64/libfoo.so.1.2'][1], b'ELF soilib')
        self.assertEqual(entries['usr/lib64/libfoo.so'][1], b'libfoo.so.1.2')
        self.assertIn('usr/share/doc/x', entries)

    def test_rpm_payload_offset_on_synthetic_package(self):
        payload = gzip.compress(_cpio_archive([_cpio_entry('usr/lib64/a.so', 0o100644, b'data')]))
        package = _rpm_file(payload)
        offset, kind = rpm_payload_offset(package)
        self.assertEqual(kind, 'gzip')
        self.assertEqual(offset, 96 + 16 + 16)
        self.assertEqual(decompress_payload(package, offset, kind)[:6], b'070701')

    def test_extract_rpm_keeps_only_lib64_shared_objects(self):
        archive = _cpio_archive([
            _cpio_entry('usr/lib64/libfoo.so.1.2', 0o100755, b'ELF soilib'),
            _cpio_entry('usr/lib64/libfoo.so', 0o120777, b'libfoo.so.1.2'),
            _cpio_entry('usr/share/doc/x', 0o100644, b'docs'),
            _cpio_entry('../evil/usr/lib64/evil.so', 0o100644, b'evil'),
        ])
        package = _rpm_file(gzip.compress(archive))
        with tempfile.TemporaryDirectory() as tmp_dir:
            rpm_path = os.path.join(tmp_dir, 'foo.rpm')
            with open(rpm_path, 'wb') as handle:
                handle.write(package)
            dest = os.path.join(tmp_dir, 'libs')
            found = extract_rpm(rpm_path, dest)
            self.assertTrue(os.path.isfile(os.path.join(dest, 'usr', 'lib64', 'libfoo.so.1.2')))
            with open(os.path.join(dest, 'usr', 'lib64', 'libfoo.so.1.2'), 'rb') as handle:
                self.assertEqual(handle.read(), b'ELF soilib')
            with open(os.path.join(dest, 'usr', 'lib64', 'libfoo.so'), 'rb') as handle:
                self.assertEqual(handle.read(), b'ELF soilib')
            self.assertFalse(os.path.exists(os.path.join(dest, 'evil')))
            self.assertEqual(len(found), 2)

    def test_unknown_payload_fails_loudly(self):
        with self.assertRaises(ValueError):
            rpm_payload_offset(_rpm_file(b'not-a-compressed-stream!!'))


if __name__ == '__main__':
    unittest.main()
