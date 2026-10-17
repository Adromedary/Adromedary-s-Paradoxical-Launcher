"""
A small reader for Paradox script (the `key = { ... }` language of common/, events/, history/, gui)
and localisation (.yml) files. It is not a full parser: it finds what the analysis needs, fast.

    blocks(text)          top-level entries: [(key, value_text, line)]  (value is the {...} body or a word)
    defined_keys(text)    names a file defines at its top level (traits, effects, event ids ...)
    inner_keys(body)      keys directly inside one block (for on_action: effect / trigger / events ...)
    identifiers(text)     every word that could be a reference to something defined elsewhere
    loc_keys(text)        localisation keys of a .yml file
"""
import re

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_.:]*")
_KEY_AT = re.compile(r'\s*([A-Za-z0-9_.:@\-]+)\s*(=|\?=|<=|>=|<|>)\s*')
_LOC = re.compile(r'^\s*([A-Za-z0-9_.\-]+):\d*\s*"', re.M)
_COMMENT_FREE = re.compile(r'"[^"\n]*"|#[^\n]*')


def strip_comments(text):
    """Remove # comments (not inside quotes)."""
    if "#" not in text:
        return text
    return _COMMENT_FREE.sub(lambda m: m.group(0) if m.group(0).startswith('"') else "", text)


def blocks(text):
    """Top-level `key = value` entries. Values that are blocks come back as their inner text."""
    text = strip_comments(text)
    out = []
    i, n = 0, len(text)
    line = 1
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch.isspace() or ch == "}":
            i += 1
            continue
        m = _KEY_AT.match(text, i)
        if not m:
            # a stray word or `{` at top level: skip one token
            j = i
            if text[j] == "{":
                j = _skip_block(text, j)
            else:
                while j < n and not text[j].isspace() and text[j] not in "{}":
                    j += 1
            line += text.count("\n", i, j)
            i = max(j, i + 1)
            continue
        key, j = m.group(1), m.end()
        line += text.count("\n", i, j)
        start_line = line
        if j < n and text[j] == "{":
            end = _skip_block(text, j)
            body = text[j + 1:end - 1]
            line += body.count("\n")
            out.append((key, body, start_line))
            i = end
        else:
            k = j
            if k < n and text[k] == '"':
                k = text.find('"', k + 1)
                k = n if k < 0 else k + 1
            else:
                while k < n and not text[k].isspace() and text[k] not in "{}":
                    k += 1
            out.append((key, text[j:k], start_line))
            i = k
    return out


_SPECIAL = re.compile(r'[{}"]')


def _skip_block(text, j):
    """text[j] == '{': index just after the matching '}' (quotes respected). Only visits braces/quotes."""
    depth, q = 0, False
    for m in _SPECIAL.finditer(text, j):
        ch = m.group(0)
        if ch == '"':
            q = not q
        elif not q:
            if ch == "{":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    return m.end()
    return len(text)


_SKIP_KEYS = {"namespace", "on_actions"}


def defined_keys(text):
    """What a script file defines at its top level ({name: line}); @variables and namespace excluded."""
    out = {}
    for key, _, line in blocks(text):
        if key.startswith("@") or key in _SKIP_KEYS:
            continue
        out.setdefault(key, line)
    return out


def inner_keys(body):
    return {k for k, _, _ in blocks(body)}


def identifiers(text):
    """Words in script that may name something defined elsewhere (effects, triggers, events, flags...)."""
    return set(_IDENT.findall(strip_comments(text)))


def loc_keys(text):
    return set(_LOC.findall(text))


_LOC_FULL = re.compile(r'^\s*([A-Za-z0-9_.\-]+):\d*\s*"(.*)"\s*(?:#.*)?$', re.M)


def loc_entries(text):
    """{key: text} of a .yml file."""
    return {k: v for k, v in _LOC_FULL.findall(text)}


def norm(body):
    """Body text with comments and spacing removed, to compare two definitions."""
    return " ".join(strip_comments(body).split())


def namespaces(text):
    return set(re.findall(r"^\s*namespace\s*=\s*([A-Za-z0-9_]+)", text, re.M))


def is_trivial(body):
    """`always = yes/no` style bodies: compatibility hooks, not real content."""
    b = " ".join(strip_comments(body).split())
    return bool(re.fullmatch(r"(always\s*=\s*(yes|no)|value\s*=\s*-?\d+(\.\d+)?|-?\d+(\.\d+)?)?", b))
