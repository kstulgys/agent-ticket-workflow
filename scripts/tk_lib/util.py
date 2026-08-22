"""Small helpers with no provider knowledge."""
import os
import re
import unicodedata

_LINE_END = re.compile(r"\r\n?")
_BLANK_LINES = re.compile(r"\n{2,}")
_HOLE = re.compile(r"\{(\w+)\}")
FALLBACK_NAME = "attachment"


def one_line_ending(text):
    """Turns CRLF and a lone CR into LF.

    A caller that splits a body into blocks needs this first. Text lifted from
    an Azure comment carries CRLF, and a CRLF body never splits on a blank line.
    """
    return _LINE_END.sub("\n", text or "")


def _one_break(text):
    """One line ending, one newline per break, and no whitespace at the edges."""
    return _BLANK_LINES.sub("\n", one_line_ending(text)).strip()


def readback_ok(sent, stored):
    """True when the server stored what we sent.

    Whitespace at the two edges is free. The line ending is free too, because
    Azure can return CRLF for a body we sent with LF. A false failure there
    makes the agent post the comment again, and a duplicate comment costs more
    than a missed near miss. The count of newlines at one break is free for the
    same reason: a rendered comment comes back as HTML, and two paragraphs
    there hold one newline where we sent two. No comment means anything
    different because of its blank line count. Every other whitespace
    difference is a mismatch, so a lost paragraph, a truncation, an added
    character, and a changed inner space all still fail.
    """
    return _one_break(sent) == _one_break(stored)


def slugify(text, words=5):
    """Lowercase words joined by a dash. Returns an empty string when none survive.

    An accented letter loses the accent and keeps its word whole. A Dutch title
    is the normal case here, so a word like Financiele must not split in two and
    spend two of the word slots.
    """
    plain = unicodedata.normalize("NFKD", (text or "").lower())
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    parts = [p for p in re.sub(r"[^a-z0-9]+", "-", plain).split("-") if p]
    return "-".join(parts[:words])


def expand(pattern, **values):
    """Fills every {name} hole in one pass. An unknown hole stays as it is.

    One pass means a value that holds a brace hole is never rewritten by a later
    key, so the result does not depend on the argument order.
    """
    def fill(match):
        key = match.group(1)
        return str(values[key]) if key in values else match.group(0)

    return _HOLE.sub(fill, pattern or "")


def safe_name(name):
    """One file name from a name the provider owns.

    Treat the name as untrusted input. basename drops any directory part, so an
    absolute name cannot write outside the target and a name holding .. cannot
    walk out of it. A backslash counts as a separator, because a Windows client
    can send one. A dot name is not a file name, so it falls back too.
    """
    plain = os.path.basename(str(name or "").replace("\\", "/")).strip()
    return FALLBACK_NAME if plain in ("", ".", "..") else plain


def free_path(target, name):
    """A path under target that no file holds yet.

    Two attachments on one ticket often share a name. Without the number the
    second download overwrites the first, and both records then point at the
    same bytes with nothing to say one went missing.
    """
    stem, ext = os.path.splitext(name)
    path = os.path.join(target, name)
    count = 1
    while os.path.exists(path):
        path = os.path.join(target, f"{stem}-{count}{ext}")
        count += 1
    return path


def name_set(value):
    """Casefolded names from one name or from many. None gives an empty set.

    One person has more than one name on one server. A pull request host knows
    me by a login, and the profile that names it also holds a tracker account
    id. So a caller passes every name that means the same person, and the
    comparison accepts any one of them. Case is free, because a login is not
    case sensitive and a profile can spell it either way.
    """
    many = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
    return {str(item).casefold() for item in many if item}
