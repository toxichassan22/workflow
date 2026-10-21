"""Number formatting helpers that preserve all supplied decimal places.

`format_precise_number` keeps every decimal digit a value carries. It is the
right helper for audit output (cost, balance, usage) where a digit may not be
invented or dropped.

The presentation layer is different: a number that reaches a slide must read
exactly like the number the client approved on screen. The financial study
screen rounds half-up to the hundredth (`roundFinancialHundredth` in
`assets/js/09-financial/01_financial_format.js`) and groups the thousands with
a comma (`formatExactSystemNumber`). These helpers are the server twin of that
contract, so the deck and the screen can never drift apart.
"""

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# A number that already carries thousands separators: `923,938,343` (US style),
# `923.938.343` (European style) or the mixed `923.938,343`. A single dot group
# without a comma (`12.345`) is a decimal, not a thousands separator — reading
# it as one would multiply the value by a thousand.
_GROUPED_NUMBER_RE = re.compile(
    r'(?<![\d.,٫٬])('
    r'-?\d{1,3}(?:,\d{3})+(?:\.\d+)?'   # US style: 923,938,343 and 1,234.56
    r'|-?\d{1,3}(?:\.\d{3})+(?:,\d+)'    # mixed: 923.938,343
    r'|-?\d{1,3}(?:\.\d{3}){2,}'         # European: 923.938.343
    r')(?![\d.,٫٬])'
)


def format_precise_number(value, grouped=True):
    """Format a numeric value without reducing its decimal precision."""
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            return ''
        text = format(number, 'f')
    except (InvalidOperation, TypeError, ValueError):
        return ''

    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    if Decimal(text) == 0:
        text = '0'
    sign = '-' if text.startswith('-') else ''
    unsigned = text[1:] if sign else text
    whole, separator, fraction = unsigned.partition('.')
    if grouped:
        whole = f'{int(whole or 0):,}'
    return sign + whole + (separator + fraction if separator else '')


def round_half_up(value, digits=2):
    """Round a number half-up to `digits` decimals.

    `Decimal.quantize` with ROUND_HALF_UP is the rounding the financial screen
    applies, so a value that leaves the browser keeps the very same digits when
    it reaches a slide. Returns ``None`` for a value that is not a number.
    """
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite():
        return None
    exponent = Decimal(1).scaleb(-int(digits))
    try:
        return number.quantize(exponent, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        # A value too large for the requested exponent (1e30 with two decimals)
        # keeps its own precision instead of raising.
        return number


def format_financial_number(value, digits=2, grouped=True):
    """Format a value the way the financial study screen shows it.

    Half-up rounding to the hundredth plus comma thousands separators — the
    exact twin of `resultMoney` / `resultPercent` in the browser.
    """
    rounded = round_half_up(value, digits)
    if rounded is None:
        return ''
    text = format(rounded, 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    if Decimal(text) == 0:
        text = '0'
    sign = '-' if text.startswith('-') else ''
    unsigned = text[1:] if sign else text
    whole, separator, fraction = unsigned.partition('.')
    if grouped:
        whole = f'{int(whole or 0):,}'
    return sign + whole + (separator + fraction if separator else '')


def format_millions(value, digits=2):
    """Format a value that is already expressed in millions."""
    return format_financial_number(value, digits=digits)


def sar_in_millions(value, digits=2):
    """Format a SAR amount in millions — the unit the financial charts use."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return ''
    if not number.is_finite():
        return ''
    return format_financial_number(number / Decimal(10) ** 6, digits=digits)


def _split_grouped_number(raw):
    """Split a written number into its integer digits and its fraction digits."""
    sign = ''
    text = raw
    if text.startswith('-'):
        sign, text = '-', text[1:]
    comma = text.rfind(',')
    dot = text.rfind('.')
    if comma >= 0 and dot >= 0:
        # Both separators present: the last one is the decimal separator.
        decimal_at = max(comma, dot)
        integer_part = text[:decimal_at]
        fraction = text[decimal_at + 1:]
    elif comma >= 0:
        if re.fullmatch(r'\d{1,3}(?:,\d{3})+', text):
            integer_part, fraction = text, ''
        else:
            integer_part, fraction = text[:comma], text[comma + 1:]
    elif dot >= 0:
        if re.fullmatch(r'\d{1,3}(?:\.\d{3}){2,}', text):
            integer_part, fraction = text, ''
        else:
            integer_part, fraction = text[:dot], text[dot + 1:]
    else:
        integer_part, fraction = text, ''
    digits = re.sub(r'\D', '', integer_part)
    return sign, digits, re.sub(r'\D', '', fraction)


def normalize_grouped_number_text(text):
    """Rewrite a number that already carries thousands separators.

    `923,938,343` stays `923,938,343` and `923.938,343` becomes `923,938,343`.
    Every decimal digit is kept — this only fixes the grouping, never the value.
    """
    def replace(match):
        raw = match.group(1)
        sign, digits, fraction = _split_grouped_number(raw)
        if not digits:
            return raw
        grouped = f'{int(digits):,}'
        return sign + grouped + (f'.{fraction}' if fraction else '')

    return _GROUPED_NUMBER_RE.sub(replace, str(text or ''))
