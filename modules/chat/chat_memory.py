"""Shared conversation memory for every assistant chat in the platform.

Three chats used to carry a tiny, fixed slice of the conversation: the plans
popup chat sent the last eight turns, the land chat kept ten, the designer
chat kept ten verbatim turns and folded the rest into a raw text tail, and the
site-plan chat kept four. The result was the same complaint everywhere — the
assistant answered a fresh question, contradicted what the client had just
agreed, and "forgot" what it was supposed to do in the first place.

This module is the single memory contract for those chats:

* the whole conversation travels with the request (bounded by
  ``CHAT_MEMORY_STORED_TURNS``), so a turn is never lost between requests;
* the newest turns stay verbatim inside the model's input window — the budget
  is counted in tokens, not in messages, so a long answer costs less room than
  a short one;
* older turns are folded into a durable digest, and the CLIENT's own words are
  the part that survives folding: an instruction is a contract, an assistant
  reply is disposable. That is what stops the model from contradicting itself;
* the digest is capped, so the request size stays bounded no matter how long
  the session runs.

The module never calls a model. Compaction is mechanical, so a chat turn is
billed for the answer the client asked for and nothing else.
"""

CHAT_MEMORY_STORED_TURNS = 600
CHAT_MEMORY_VERBATIM_TURNS = 60
CHAT_MEMORY_INPUT_TOKEN_BUDGET = 160000
CHAT_MEMORY_DIGEST_CHARS = 40000
# A turn is never cut: the client's own words are a contract, and a silent
# cut loses the end of the request he wrote. The token budget and the digest
# size are the real bounds.
CHAT_MEMORY_TURN_CHARS = 0
CHAT_MEMORY_CLIENT_LINE_CHARS = 40000
CHAT_MEMORY_ASSISTANT_LINE_CHARS = 40000
CHAT_MEMORY_DECISIONS = 40


def estimate_tokens(text):
    """Cheap token estimate.

    Arabic and dense JSON cost roughly three characters per token, English
    closer to four. Three is the conservative middle: an over-estimate keeps
    the request smaller than the window, never larger.
    """
    text = str(text or '')
    if not text:
        return 0
    return max(1, (len(text) + 2) // 3)


def normalize_turns(raw, limit=CHAT_MEMORY_STORED_TURNS):
    """One comparable shape for every turn, whatever the caller stored."""
    turns = []
    for item in (raw if isinstance(raw, list) else []):
        if not isinstance(item, dict):
            # A bare string is not a turn: only the recorded shape is replayed,
            # so a crafted payload cannot smuggle a message in.
            continue
        role = 'assistant' if item.get('role') in ('assistant', 'ai') else 'user'
        content = item.get('content')
        if content is None:
            content = item.get('text')
        content = str(content or '').strip()
        if not content:
            continue
        turn = {'role': role, 'content': (content[:CHAT_MEMORY_TURN_CHARS]
                                          if CHAT_MEMORY_TURN_CHARS else content)}
        slides = item.get('slides') if isinstance(item, dict) and isinstance(item.get('slides'), list) else []
        numbers = []
        for value in slides[:40]:
            text = str(value).strip()
            if text and text not in numbers:
                numbers.append(text)
        if numbers:
            turn['slides'] = numbers
        turns.append(turn)
    if limit and limit > 0:
        turns = turns[-limit:]
    return turns


def merge_turns(stored, incoming):
    """Merge an incoming snapshot into the stored conversation without losing turns.

    The client sends what it has; the server may hold more. Neither side may
    replace the other's history with a shorter copy.
    """
    stored = normalize_turns(stored)
    incoming = normalize_turns(incoming)
    if not stored:
        return incoming
    if not incoming:
        return stored
    if incoming == stored or len(incoming) <= len(stored):
        for start in range(len(stored) - len(incoming) + 1):
            if stored[start:start + len(incoming)] == incoming:
                return stored
    if len(stored) <= len(incoming):
        for start in range(len(incoming) - len(stored) + 1):
            if incoming[start:start + len(stored)] == stored:
                return incoming
    for overlap in range(min(len(stored), len(incoming)), 0, -1):
        if stored[-overlap:] == incoming[:overlap]:
            return stored + incoming[overlap:]
    return stored + incoming


def digest_lines(turns):
    """The folded form of a turn list.

    A client turn keeps far more of its text than an assistant turn: the
    instruction is the contract, the assistant's own wording can be dropped.
    """
    lines = []
    for turn in (turns if isinstance(turns, list) else []):
        if not isinstance(turn, dict):
            continue
        role = 'العميل' if turn.get('role') == 'user' else 'المساعد'
        limit = (CHAT_MEMORY_CLIENT_LINE_CHARS if turn.get('role') == 'user'
                 else CHAT_MEMORY_ASSISTANT_LINE_CHARS)
        text = str(turn.get('content') or '').replace('\n', ' ').strip()
        if not text:
            continue
        slides = turn.get('slides') or []
        scope = ' [شرائح: ' + '، '.join(str(item) for item in slides) + ']' if slides else ''
        lines.append('{0}{1}: {2}'.format(role, scope, text[:limit]))
    return lines


def _trim_to_lines(text, cap):
    """The newest whole lines that fit ``cap`` — a mid-line cut loses meaning."""
    text = str(text or '')
    if len(text) <= cap:
        return text
    lines = text.split('\n')
    kept, total = [], 0
    for line in reversed(lines):
        cost = len(line) + 1
        if kept and total + cost > cap:
            break
        kept.append(line)
        total += cost
    if len(kept) == len(lines):
        return '\n'.join(kept)
    return '…\n' + '\n'.join(reversed(kept))


def fold_turns(turns, memory='', digest_chars=CHAT_MEMORY_DIGEST_CHARS):
    """Fold the oldest turns into the memory digest.

    The digest keeps the client's own words when the cap is tight: an
    assistant line is dropped before an instruction ever is.
    """
    base = str(memory or '').strip()
    lines = digest_lines(turns)
    if not lines:
        return base
    kept, total = [], len(base)
    for line in reversed(lines):
        cost = len(line) + 1
        if total + cost > digest_chars:
            if line.startswith('العميل:') and kept:
                for index, other in enumerate(kept):
                    if other.startswith('المساعد:'):
                        kept.pop(index)
                        total -= len(other) + 1
                        break
                else:
                    continue
            else:
                continue
        kept.append(line)
        total += cost
    kept.reverse()
    merged = '\n'.join([base] + kept) if base else '\n'.join(kept)
    return _trim_to_lines(_dedupe_lines(merged), digest_chars).strip()


def _dedupe_lines(text):
    """Drop a line that already appears — the client sends the memory back with
    the turns it still holds, so the same folded line arrives twice."""
    lines = str(text or '').split('\n')
    seen = {}
    for index, line in enumerate(lines):
        if line.strip():
            seen[line.strip()] = index
    if len(seen) == len([line for line in lines if line.strip()]):
        return text
    keep = set(seen.values())
    return '\n'.join(line for index, line in enumerate(lines) if index in keep)


def build_context(turns, memory='', decisions=None,
                  budget_tokens=CHAT_MEMORY_INPUT_TOKEN_BUDGET):
    """Split a conversation into the part the model reads verbatim and the digest.

    Returns a context dict the caller drops straight into the prompt:
    ``memory`` (the digest), ``decisions`` (what was agreed), ``verbatim``
    (the newest turns), ``folded`` (how many turns the digest absorbed),
    ``estimated_tokens`` (what the prompt will cost) and ``compacted``.
    """
    turns = normalize_turns(turns)
    verbatim, used = [], 0
    for turn in reversed(turns):
        cost = estimate_tokens(turn['content'])
        if used + cost > budget_tokens:
            break
        verbatim.insert(0, turn)
        used += cost
        if len(verbatim) >= CHAT_MEMORY_VERBATIM_TURNS:
            break
    older = turns[:len(turns) - len(verbatim)]
    digest = fold_turns(older, memory)
    return {
        'memory': digest,
        'decisions': normalize_decisions(decisions),
        'verbatim': verbatim,
        'folded': len(older),
        'estimated_tokens': used + estimate_tokens(digest),
        'compacted': bool(older),
    }


def normalize_decisions(decisions):
    """The agreed points, one per line, bounded."""
    if isinstance(decisions, str):
        decisions = [part for part in decisions.split('\n') if part.strip()]
    if not isinstance(decisions, list):
        return []
    seen, cleaned = set(), []
    for item in decisions:
        text = str(item or '').strip()[:400]
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
        if len(cleaned) >= CHAT_MEMORY_DECISIONS:
            break
    return cleaned


def prompt_block(context, heading='## ذاكرة المحادثة'):
    """The prompt section that carries the memory, the agreements and the turns."""
    if not isinstance(context, dict):
        return ''
    parts = []
    memory = str(context.get('memory') or '').strip()
    if memory:
        parts.append(
            heading + ' — ما سبق في هذه المحادثة بالترتيب، التزم به ولا تخالفه '
            'ولا تعِد اقتراحًا رُفض أو غُيّر:\n' + memory)
    decisions = context.get('decisions') or []
    if decisions:
        parts.append('## ما اتُّفق عليه:\n'
                     + '\n'.join('- ' + item for item in decisions))
    verbatim = context.get('verbatim') or []
    if verbatim:
        lines = []
        for turn in verbatim:
            role = 'العميل' if turn.get('role') == 'user' else 'المساعد'
            lines.append('{0}: {1}'.format(role, turn.get('content') or ''))
        parts.append('## آخر الرسائل:\n' + '\n'.join(lines))
    return '\n\n'.join(parts)


def apply_model_memory(context, parsed):
    """Adopt the memory and agreements the model rewrote for the next turn.

    A chat that maintains its own digest does not drift: the model carries the
    agreements forward instead of re-deriving them from the last few turns.
    """
    if not isinstance(context, dict) or not isinstance(parsed, dict):
        return context
    memory = parsed.get('memory')
    if isinstance(memory, str) and memory.strip():
        context['memory'] = memory.strip()[:CHAT_MEMORY_DIGEST_CHARS]
    if 'decisions' in parsed:
        context['decisions'] = normalize_decisions(parsed.get('decisions'))
    return context


def client_turns(raw):
    """The client's own messages — the wishes a distribution prompt must honor."""
    turns = normalize_turns(raw)
    return [turn['content'] for turn in turns if turn['role'] == 'user']
