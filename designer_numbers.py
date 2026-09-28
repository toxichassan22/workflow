"""Numeric facts for the designer chat's preservation gates.

Every check that decides «the result dropped a number» — edit/redesign/rewrite
verification, the condensing-restructure facts check, the request and
superseded-value excusals — reads numbers through this module, so the gates
can never disagree about what a number is.

A number is an atom inside ONE visible text node: «9/2027» is the atoms 9 and
2027, «1,250,000.50» is 1250000.5 and «٢٠٢٧» is 2027. Text nodes are never
glued together and whitespace never joins digits. The old reader joined the
slide text with spaces and let a number run across whitespace, so a table cell
«إلى 9/2027» followed by a cell «5» read as the pseudo-number «9/20275». The
moment a redesign moved those cells apart the pseudo-number «vanished», the
task was rejected for dropping a value that never existed on the slide, and
the retry — told to restore «9/20275» — could not possibly comply.

Pure Python, no Flask: unit-testable on its own.
"""

import re
from collections import Counter

DIGIT_TRANS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬٪', '01234567890123456789.,%')
# A run of digits joined only by «.» or «,» — «/», «:», dashes, spaces and
# every other character end the run, so dates and ranges split into atoms.
_RUN = re.compile(r'\d+(?:[.,]\d+)*')
# A separator is a thousands group only when exactly three digits follow it:
# «5,000,000» and «٥٬٠٠٠٬٠٠٠» fold alike while «100.5» and «12,5» stay decimal.
_GROUP_SEP = re.compile(r'(?<=\d)[.,](?=\d{3}(?!\d))')
# «م2»/«كم2»/«m2»/«م3» carry a unit exponent, not a value: «م²» (no ASCII
# digit) must compare equal, so the exponent is masked with a same-length
# non-digit — offsets stay aligned for atom_contexts.
_UNIT_EXPONENT = re.compile(r'(?<=[\u0645mM])[23](?!\d)')


def _digits(text):
    return _UNIT_EXPONENT.sub('\u00b2', str(text or '').translate(DIGIT_TRANS))


def _unpad(digits):
    """Zero padding is cosmetic on a one- or two-digit field («المرحلة 01»,
    «09/2027»); on a longer run it is part of the value — «0111» and
    «0551234567» are phone numbers that must keep their leading zero."""
    return (digits.lstrip('0') or '0') if len(digits) <= 2 else digits


def _atoms_of_run(run):
    compact = _GROUP_SEP.sub('', run).replace(',', '.')
    pieces = compact.split('.')
    if len(pieces) > 2:
        # «27.09.2026» — a dotted date or version, not one value.
        return [_unpad(piece) for piece in pieces if piece]
    whole = _unpad(pieces[0])
    if len(pieces) == 2:
        fraction = pieces[1].rstrip('0')
        return [f'{whole}.{fraction}' if fraction else whole]
    return [whole]


def number_atoms(text):
    """Normalized numeric atoms of one text node, in reading order."""
    atoms = []
    for match in _RUN.finditer(_digits(text)):
        atoms.extend(_atoms_of_run(match.group(0)))
    return atoms


def count_atoms(texts):
    """Multiset of atoms over separate text nodes — never across them."""
    counts = Counter()
    for text in texts or ():
        counts.update(number_atoms(text))
    return counts


_BARE_NODE_CHARS = 16


def _squash(text):
    return ' '.join(str(text or '').split())


def atom_contexts(texts, atoms, radius=28):
    """``[(atom, snippet)]``: for each atom, the first text node carrying it,
    trimmed around the value — so a retry can say where the value lived, in
    the surface form the slide shows («1,250,000» for the atom 1250000).

    A bare node — a table cell holding only «5» — says nothing about where it
    sat, so its neighbours join it: «إلى 9/2027 | 5 | الإنشاء».
    """
    wanted = list(dict.fromkeys(str(atom).strip() for atom in atoms or () if str(atom).strip()))
    nodes = [str(text or '') for text in texts or ()]
    found = {}
    for index, raw in enumerate(nodes):
        if len(found) == len(wanted):
            break
        # _digits maps one character to one character, so match offsets in
        # the normalized text slice the original text exactly.
        for match in _RUN.finditer(_digits(raw)):
            for atom in _atoms_of_run(match.group(0)):
                if atom not in wanted or atom in found:
                    continue
                start = max(0, match.start() - radius)
                end = min(len(raw), match.end() + radius)
                snippet = ('…' if start else '') + _squash(raw[start:end]) + ('…' if end < len(raw) else '')
                if len(_squash(raw)) < _BARE_NODE_CHARS:
                    before = _squash(nodes[index - 1])[-radius:] if index else ''
                    after = _squash(nodes[index + 1])[:radius] if index + 1 < len(nodes) else ''
                    snippet = ' | '.join(part for part in (before, snippet, after) if part)
                found[atom] = snippet
    return [(atom, found.get(atom, '')) for atom in wanted]


__all__ = ['DIGIT_TRANS', 'atom_contexts', 'count_atoms', 'number_atoms']
