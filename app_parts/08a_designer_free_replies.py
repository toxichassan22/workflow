# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Free designer replies: greetings and capability questions answered without
# any model call (moved out of 08 to keep it under the 1,000-line budget).
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _designer_last_reply_was_question(history):
    """True when the assistant's previous turn asked the user something: a
    short follow-up like «اه» or «تمام» is then an answer, not a greeting."""
    for entry in reversed(history if isinstance(history, list) else []):
        if not isinstance(entry, dict) or entry.get('role') != 'assistant':
            continue
        text = str(entry.get('content') or '').strip()
        if not text:
            return False
        return '؟' in text or text.endswith('?')
    return False


_DESIGNER_GREETINGS = frozenset({
    'سلام', 'سلام عليكم', 'السلام عليكم', 'وعليكم السلام', 'مرحبا', 'مرحب',
    'اهلا', 'أهلا', 'اهلين', 'يا هلا', 'هلا', 'هلا والله', 'هاي', 'هاى',
    'ازيك', 'عامل ايه', 'عامل إيه', 'صباح الخير', 'صباح النور',
    'مساء الخير', 'مساء النور', 'شكرا', 'شكرًا', 'تسلم', 'يعطيك العافية',
    'hello', 'hi', 'hey', 'thanks', 'thank you', 'good morning', 'good evening',
})


def _designer_plain_greeting(text):
    """True only when the whole message is a greeting. Confirmation words
    («تمام»، «طيب»، «اه»، «ok»...) are deliberately not greetings: they
    usually mean «نعم، نفّذ ما عرضته» and must reach the planner."""
    cleaned = re.sub(r'[^\w\sء-ي]+', ' ', text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # Squash trailing elongation: «هلاااا» becomes «هلا»، «مرحبااا» becomes «مرحبا».
    cleaned = ' '.join(
        re.sub(r'([اوىيهة])\1+$', r'\1', word) for word in cleaned.split(' '))
    return cleaned in _DESIGNER_GREETINGS


def _designer_chat_free_reply(message, has_attachment=False, history=None):
    """Deterministic no-AI reply for greetings and capability questions.

    These turns used to run the full planner prompt (the whole draft as context) just to
    answer «سلام» or «بتعمل ايه», so the tenant's provider balance moved on a message that
    requested no work. Returning a canned answer here spends zero tokens: no planner call,
    no edit call and no memory call. Returns the reply text, or None when the turn needs
    the planner. A greeting is matched whole-message only, and never while the designer
    is waiting for an answer to its own question.
    """
    if has_attachment:
        return None
    text = normalize_arabic_digits_py(str(message or '').strip().lower())
    if not text:
        return None
    if len(text) > 60:
        return None
    if designer_chat_targets.explicit_slide_numbers(message):
        return None
    if _designer_last_reply_was_question(history):
        return None
    edit_markers = (
        'عدل', 'عدّل', 'غير', 'غيّر', 'احذف', 'امسح', 'ضيف', 'أضف', 'اضف', 'حط', 'ضع',
        'انقل', 'كرر', 'ادمج', 'اقسم', 'جزئ', 'شريحة', 'شريحه', 'سلايد', 'صورة', 'صوره',
        'خريطة', 'خريط', 'شعار', 'لوجو', 'علامة', 'watermark', 'لون', 'خط', 'جدول',
        'صف', 'عمود', 'مخطط', 'رسم',
    )
    if any(marker in text for marker in edit_markers):
        return None
    identity_markers = (
        'اسمك', 'مين انت', 'مين إنت', 'انت مين', 'إنت مين', 'من انت', 'من أنت',
        'انت من', 'إنت من', 'who are you', 'your name', 'what are you',
    )
    if any(marker in text for marker in identity_markers):
        return (
            'أنا Landloom، مساعد التصميم الذكي في المنصة — متخصص في تعديل '
            'وتطوير شرائح عرضك. هذه الرسالة لم تستهلك أي رصيد.'
        )
    if _designer_plain_greeting(text):
        return (
            'أهلاً بك. أخبرني بالتعديل المطلوب على العرض، وسأنفذه مباشرة. '
            'هذه التحية لم تستهلك أي رصيد.'
        )
    help_markers = (
        'بتعمل ايه', 'بتعمل إيه', 'ايه قدراتك', 'إيه قدراتك', 'ممكن تعمل ايه',
        'تقدر تعمل ايه', 'مساعدة', 'مساعده', 'help', 'قدراتك', 'ازاي استخدم',
        'كيف استخدم', 'بتسحب رصيد', 'الرصيد', 'بتكلف',
    )
    if any(marker in text for marker in help_markers):
        return (
            'أنا Landloom، مساعد التصميم لهذا العرض. أنفذ التعديلات على الشرائح المفتوحة فقط، '
            'ولا أقرأ المسودة ولا أستهلك رصيداً إلا بعد طلب تعديل واضح منك. '
            'يمكنك طلب تعديل شريحة، إنشاء شريحة جديدة، أو إرفاق صورة ثم طلب وضعها '
            'في شريحة منفصلة أو داخل شريحة أو كعلامة مائية أو كشعار إضافي.'
        )
    return None
