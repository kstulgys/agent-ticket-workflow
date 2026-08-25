"""Read secrets.env. A value never leaves this process in plain text."""
import os
import stat

DEFAULT_PATH = os.path.join(os.path.expanduser("~"), ".claude",
                            "ticket-workflow", "secrets.env")
SETUP = "scripts/setup.sh"
SCRUB = []
# Windows has no POSIX mode. chmod there sets the read-only attribute and
# nothing else, so a file the wizard wrote with chmod 600 reads back as 0o666
# and the check in load refused every file on the platform, with a fix line no
# chmod could carry out. Access to that file is an ACL, which the wizard
# tightens with icacls, and no stdlib call reads one back.
POSIX = os.name == "posix"


class SecretsError(Exception):
    pass


def load(path=None):
    """Every value in secrets.env, or nothing when the file is not there yet.

    An absent file is not a failure. It is the state of a machine that has not
    needed a token yet, and the run that follows may need none. get raises the
    error, because get knows which variable a call wanted and which stage
    writes it. Raising here instead answered every verb with the same sentence,
    so a run whose real gap was a missing project profile reported a missing
    token.

    A file that exists with a wider mode is still a refusal on POSIX. That one
    is a fact about the machine, and no later call can repair it. Windows
    reports a mode this check cannot read, so see POSIX above.
    """
    path = path or DEFAULT_PATH
    if not os.path.exists(path):
        return {}
    if POSIX:
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode != 0o600:
            raise SecretsError(
                f"{path} has mode {oct(mode)}. Run: chmod 600 {path}")
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
        mask(value)
    return values


# The wizard stage that writes each variable. A run needs one provider, so the
# error names one stage, not the whole wizard. A project scoped value such as
# NORTHWIND_BYPASS_HILLCREST matches no prefix, and its error names the bare
# command, because no stage writes it.
STAGES = (("AZDO_", "azure"), ("JIRA_", "jira"), ("GH_", "github"),
          ("FIGMA_", "figma"))


def stage_for(name):
    """The setup stage that writes one variable, or None when none does."""
    return next((stage for prefix, stage in STAGES
                 if str(name).startswith(prefix)), None)


def get(name, values):
    if not values.get(name):
        stage = stage_for(name)
        where = f"{SETUP} {stage}" if stage else SETUP
        raise SecretsError(
            f"{name} is not set in secrets.env. Run {where} to add it.")
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


def mask(value):
    """Adds one more value the scrubber must hide. Returns it unchanged.

    load registers what secrets.env holds. A credential travels in another
    form: Basic and a base64 of the pair. That string is not in the file, so
    the list cannot hold it unless the code that builds it says so.

    A value under eight characters is skipped, because a short one would mask
    ordinary words and a part mask reads as safe when it is not.
    """
    value = str(value)
    if len(value) >= 8 and value not in SCRUB:
        SCRUB.append(value)
    return value
