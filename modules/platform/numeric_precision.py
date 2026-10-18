"""Number formatting helpers that preserve all supplied decimal places."""

from decimal import Decimal, InvalidOperation


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
