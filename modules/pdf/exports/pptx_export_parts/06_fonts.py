"""Embed the deck font inside the PPTX so the design survives on the client."""

import base64
import json
import os
import struct
from pathlib import Path

import design_templates
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.opc.package import Part
from pptx.opc.packuri import PackURI
from pptx.oxml.ns import qn

_R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
# EOT header layout read from a deck PowerPoint itself saved with embedded
# fonts: panose, charset, italic, weight, fsType, magic, ranges, checksum,
# four reserved longs, then padding1. The names follow the fixed header.
_EOT_HEADER = '<4L10BBBLHH4L2LL4LH'
_EOT_MAGIC = 0x504C
_EOT_VERSION = 0x00020002


def _sfnt_tables(data):
    if len(data) < 12:
        raise ValueError('truncated font')
    version, num_tables = struct.unpack('>IH', data[:6])
    if version not in (0x00010000, 0x4F54544F):  # TrueType / OTTO
        raise ValueError('unsupported sfnt version')
    tables = {}
    for index in range(num_tables):
        start = 12 + index * 16
        tag, _checksum, offset, length = struct.unpack('>4sIII', data[start:start + 16])
        tables[tag] = (offset, length)
    return tables


def _name_records(data, tables):
    if b'name' not in tables:
        return {}
    offset, length = tables[b'name']
    name = data[offset:offset + length]
    if len(name) < 6:
        return {}
    _fmt, count, string_offset = struct.unpack('>HHH', name[:6])
    names = {}
    for index in range(count):
        start = 6 + index * 12
        platform, encoding, language, name_id, size, offset_ = struct.unpack(
            '>HHHHHH', name[start:start + 12])
        if platform != 3 or encoding != 1:
            continue
        if language != 0x0409 and name_id in names:
            continue
        raw = name[string_offset + offset_:string_offset + offset_ + size]
        try:
            names[name_id] = raw.decode('utf-16-be')
        except UnicodeDecodeError:
            continue
    return names


def _to_eot(font_data):
    """Wrap a TrueType font in an uncompressed EOT (PowerPoint's fntdata)."""
    tables = _sfnt_tables(font_data)
    for required in (b'head', b'name', b'OS/2'):
        if required not in tables:
            raise ValueError('missing font table')
    os2_offset, os2_length = tables[b'OS/2']
    os2_format = '>4xH2xH22x10B4L4xH14x2L'
    os2 = struct.unpack(os2_format, font_data[os2_offset:os2_offset + struct.calcsize(os2_format)])
    weight, fs_type = os2[0], os2[1]
    panose = list(os2[2:12])
    unicode_ranges = list(os2[12:16])
    fs_selection = os2[16]
    code_pages = list(os2[17:19])
    head_offset, _head_length = tables[b'head']
    check_sum = struct.unpack('>8xL', font_data[head_offset:head_offset + 12])[0]
    names = _name_records(font_data, tables)
    name_blob = b''
    for name_id in (1, 2, 5, 4):
        # EOT name lengths count the terminating NUL, and each name is
        # followed by a two-byte pad.
        raw = names.get(name_id, '').encode('utf-16-le') + b'\x00\x00'
        name_blob += struct.pack('<H', len(raw)) + raw + b'\x00\x00'
    root_string = b'\x00\x00'
    header_size = struct.calcsize(_EOT_HEADER)
    eot_size = header_size + len(name_blob) + len(root_string) + len(font_data)
    header = struct.pack(
        _EOT_HEADER, eot_size, len(font_data), _EOT_VERSION, 0,
        *panose, 0, 1 if (fs_selection & 1) else 0, weight, fs_type, _EOT_MAGIC,
        *unicode_ranges, *code_pages, check_sum,
        0, 0, 0, 0, 0)
    return header + name_blob + root_string + font_data


def _same_family(left, right):
    def fold(value):
        return ''.join(ch for ch in str(value or '').lower() if ch.isalnum())
    return bool(fold(left)) and fold(left) == fold(right)


def _face_family(data):
    try:
        names = _name_records(data, _sfnt_tables(data))
    except Exception:
        return ''
    return names.get(16) or names.get(1) or ''


def _payload_bytes(value):
    """Font payload -> raw bytes. Accepts base64 or JSON {data, format}."""
    if not value:
        return None
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    text = str(value).strip()
    if not text:
        return None
    if text.startswith('{'):
        try:
            parsed = json.loads(text)
        except ValueError:
            return None
        data = parsed.get('data')
        return base64.b64decode(data) if data else None
    try:
        return base64.b64decode(text)
    except Exception:
        return None


def _read_font_file(path):
    try:
        resolved = design_templates.resolve_font_path(path)
        if not resolved or design_templates._is_lfs_pointer(resolved):
            return None
        with open(resolved, 'rb') as handle:
            return handle.read()
    except Exception:
        return None


def _face_bytes_from_font(font):
    if not font:
        return None
    if font.get('file_data'):
        return _payload_bytes(font['file_data'])
    try:
        source = design_templates._resolve_preset_font_source(
            font.get('source_data') or font.get('font_family'))
    except Exception:
        source = None
    if source and source.get('type') == 'bundled':
        return _payload_bytes(source.get('data'))
    return None


def _weight_map(branding, tenant_id):
    """weight name -> font bytes, preferring the tenant's managed selections."""
    faces = {}
    selections = []
    try:
        selections = design_templates.get_tenant_font_selections(tenant_id) or []
    except Exception:
        selections = []
    for selection in selections:
        if str(selection.get('script') or 'arabic') != 'arabic':
            continue
        weight = str(selection.get('weight') or 'regular')
        data = _payload_bytes(selection.get('custom_font_data'))
        if not data and selection.get('custom_font_path'):
            data = _read_font_file(selection['custom_font_path'])
        if not data and selection.get('font_id'):
            try:
                data = _face_bytes_from_font(
                    design_templates.get_sag_font(selection['font_id']))
            except Exception:
                data = None
        if data:
            faces[weight] = data
    if faces:
        return faces

    branding = branding or {}
    if branding.get('font_file_data'):
        data = _payload_bytes(branding['font_file_data'])
        if data:
            faces['regular'] = data
    if not faces and branding.get('font_file_path'):
        data = _read_font_file(branding['font_file_path'])
        if data:
            faces['regular'] = data
    if faces:
        return faces

    try:
        source = design_templates._resolve_preset_font_source(
            branding.get('font_family') or 'IBM Plex Sans Arabic')
    except Exception:
        source = None
    if source and source.get('type') == 'bundled':
        data = _payload_bytes(source.get('data'))
        if data:
            faces['regular'] = data
    if not faces:
        try:
            bundled = design_templates._load_bundled_fonts()
        except Exception:
            bundled = {}
        light = bundled.get('TheSansArabic-Light')
        bold = bundled.get('TheSansArabic-Bold')
        if light:
            faces['regular'] = _payload_bytes(light[0])
        if bold:
            faces['bold'] = _payload_bytes(bold[0])
    return faces


def _pick(faces, weights):
    for weight in weights:
        if faces.get(weight):
            return faces[weight]
    return None


def embed_fonts(prs, ctx):
    """Add the measured faces as PPTX embedded fonts (best effort, logged)."""
    faces = _weight_map(ctx.branding, ctx.tenant_id)
    regular = _pick(faces, ('regular', 'medium', 'light', 'bold', 'black'))
    bold = _pick(faces, ('bold', 'black', 'medium', 'regular', 'light'))
    if not regular and not bold:
        print("[PPTX] no embeddable font file found; runs reference the family name only")
        return 0
    face_family = _face_family(regular or bold)
    if face_family and not _same_family(face_family, ctx.font_name):
        # A system family (Arial, Tahoma) is a name, not a shipped face: the
        # client machine already has it, and embedding another family under
        # that name would change the design instead of preserving it.
        print(f"[PPTX] '{ctx.font_name}' has no shipped face (found '{face_family}'); "
              f"referencing it by name")
        return 0
    chosen = [('regular', regular), ('bold', bold)]
    try:
        package = prs.part.package
        rels = []
        for index, (style, blob) in enumerate(chosen, 1):
            if not blob:
                continue
            try:
                blob = _to_eot(blob)
            except Exception as exc:
                print(f"[PPTX] skipping embedded {style} face: {exc}")
                continue
            partname = PackURI(f'/ppt/fonts/font{index}.fntdata')
            part = Part(partname, 'application/x-fontdata', package, blob)
            rel_id = prs.part.relate_to(part, RT.FONT)
            rels.append((style, rel_id))
        if not rels:
            return 0
        presentation = prs.part._element
        old = presentation.find(qn('p:embeddedFontLst'))
        if old is not None:
            presentation.remove(old)
        font_list = presentation.makeelement(qn('p:embeddedFontLst'), {})
        embedded = font_list.makeelement(qn('p:embeddedFont'), {})
        font = embedded.makeelement(qn('p:font'), {'typeface': ctx.font_name})
        embedded.append(font)
        for style, rel_id in rels:
            node = embedded.makeelement(qn('p:' + style), {})
            node.set('{%s}id' % _R_NS, rel_id)
            embedded.append(node)
        font_list.append(embedded)
        notes_sz = presentation.find(qn('p:notesSz'))
        if notes_sz is not None:
            notes_sz.addnext(font_list)
        else:
            presentation.append(font_list)
        print(f"[PPTX] embedded font faces={len(rels)} family={ctx.font_name}")
        return len(rels)
    except Exception as exc:
        print(f"[PPTX] font embedding skipped: {exc}")
        return 0
