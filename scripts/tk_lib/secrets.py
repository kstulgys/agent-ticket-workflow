"""Read secrets.env. A value never leaves this process in plain text."""
import os
import stat

DEFAULT_PATH = os.path.expanduser("~/.claude/ticket-workflow/secrets.env")
SETUP = "scripts/setup.sh"
SCRUB = []


class SecretsError(Exception):
    pass


def load(path=None):
    path = path or DEFAULT_PATH
    if not os.path.exists(path):
        raise SecretsError(f"no secrets file at {path}. Run {SETUP} to create it.")
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode != 0o600:
        raise SecretsError(f"{path} has mode {oct(mode)}. Run: chmod 600 {path}")
    values = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            # Strip one matching outer pair only. Stripping every quote
            # character would hold a value the file does not contain, and then
            # scrub would mask the wrong string.
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
    for value in values.values():
        if len(value) >= 8 and value not in SCRUB:
            SCRUB.append(value)
    return values


def get(name, values):
    if not values.get(name):
        raise SecretsError(f"{name} is not set in secrets.env. Run {SETUP} to add it.")
    return values[name]


def scrub(text):
    text = str(text)
    # Mask the longest value first. When one secret contains another, replacing
    # the shorter one first leaves the edges of the longer one in the output. A
    # part mask is worse than no mask, because it looks safe. The sort lives
    # here, not in load, so the order holds even if a caller appends to SCRUB.
    for value in sorted(SCRUB, key=len, reverse=True):
        text = text.replace(value, "***")
    return text
