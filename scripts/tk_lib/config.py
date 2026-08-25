"""Profiles on disk, and the rules that pick one."""
import json
import os
import re
import sys

from . import cli

ROOT = os.path.join(os.path.expanduser("~"), ".claude", "ticket-workflow")

_URL_TICKET = (
    re.compile(r"_workitems/edit/([0-9]+)"),
    re.compile(r"/browse/([A-Z][A-Z0-9]*-[0-9]+)"),
    re.compile(r"/issues/([0-9]+)"),
    re.compile(r"/pull/([0-9]+)"),
)


class Ambiguous(Exception):
    def __init__(self, slugs):
        self.slugs = sorted(slugs)
        super().__init__("several projects match: " + ", ".join(self.slugs))


class Unresolved(Exception):
    pass


class BadProfile(ValueError):
    """A profile on disk that this tool cannot read."""


def load_all(root=None):
    base = os.path.join(root or ROOT, "projects")
    profiles = {}
    if not os.path.isdir(base):
        return profiles
    for slug in sorted(os.listdir(base)):
        directory = os.path.join(base, slug)
        # A file here is not a profile, so it is not a gap to report. Every
        # verb loads these profiles, so one stray file would print the same
        # warning on every invocation.
        if not os.path.isdir(directory):
            continue
        path = os.path.join(directory, "config.json")
        if not os.path.exists(path):
            # The skip stays, but it is no longer silent. A profile that fails
            # to load stops competing for its ticket pattern. That can turn a
            # refusal into a confident wrong answer.
            sys.stderr.write(f"skipped {directory}, it holds no config.json\n")
            continue
        with open(path, encoding="utf-8") as fh:
            try:
                profile = json.load(fh)
            except ValueError as error:
                # The default message gives no file name, and a person with
                # several profiles cannot tell which file to repair.
                raise BadProfile(f"{path} is not valid JSON: {error}") from error
        if not isinstance(profile, dict):
            # Valid JSON is not a valid profile. A list or a string clears the
            # guard above and then crashes on the assignment below, and a
            # traceback is the one answer this CLI promises never to give.
            raise BadProfile(
                f"{path} holds {type(profile).__name__}, not an object. "
                "A profile is a JSON object. See references/profiles.md.")
        for block in ("match", "tracker", "host", "buckets", "people",
                      "link_rules", "deploy_gate", "preview"):
            if block in profile and not isinstance(profile[block], dict):
                # doctor reads tracker.kind outside its own guard, so a string
                # here takes down the whole report rather than one row.
                raise BadProfile(
                    f"{path} has {block} as {type(profile[block]).__name__}, "
                    "not an object. See references/profiles.md.")
        profile["_dir"] = directory
        profiles[slug] = profile
    return profiles


def _match(profile):
    return profile.get("match") or {}


def _ticket_from_url(url):
    for pattern in _URL_TICKET:
        found = pattern.search(url)
        if found:
            return found.group(1)
    return None


def _holds(root, cwd):
    """True when cwd is root itself or sits under it.

    normcase folds the separator and the case, abspath names the drive, and
    both drop a trailing separator. A profile carries C:/repos/app while
    getcwd answers C:\\repos\\App, so the plain string compare this replaces
    matched the repository root and no directory inside it: every run from a
    subdirectory on Windows resolved to no project. A repo_paths entry written
    with ~ missed even the root, because expanduser keeps the separators the
    profile used. resolve hands cwd through abspath already, so doing the same
    to root is what keeps the two comparable.
    """
    root = os.path.normcase(os.path.abspath(os.path.expanduser(root)))
    cwd = os.path.normcase(os.path.abspath(cwd))
    return cwd == root or cwd.startswith(root + os.sep)


def _by_cwd(profiles, cwd):
    """Slugs whose repo paths hold the directory. One hit per profile.

    A profile can list a parent path and a child path. Two hits for one slug
    would read as a tie between a project and itself, and no rung could break
    it. The url rung counts one hit per profile, so this agrees with it.
    """
    hits = []
    for slug, profile in profiles.items():
        if any(_holds(path, cwd)
               for path in _match(profile).get("repo_paths", [])):
            hits.append(slug)
    return hits


def _result(slug, profile, ticket):
    return {"slug": slug,
            "tracker": (profile.get("tracker") or {}).get("kind"),
            "ticket": ticket,
            "notes_path": os.path.join(profile["_dir"], profile.get("notes", "notes.md"))}


def resolve(arg, profiles, cwd=None):
    cwd = os.path.abspath(cwd or os.getcwd())
    if arg and "://" in arg:
        hits = [slug for slug, profile in profiles.items()
                if any(fragment in arg
                       for fragment in _match(profile).get("tracker_urls", []))]
        if len(hits) > 1:
            raise Ambiguous(hits)
        if hits:
            return _result(hits[0], profiles[hits[0]], _ticket_from_url(arg))
        raise Unresolved(f"no profile matches the url {arg}")
    if arg:
        hits = [slug for slug, profile in profiles.items()
                if any(re.match(p, arg) for p in _match(profile).get("ticket_patterns", []))]
        if len(hits) > 1:
            narrowed = [slug for slug in _by_cwd(profiles, cwd) if slug in hits]
            hits = narrowed or hits
        if len(hits) > 1:
            raise Ambiguous(hits)
        if hits:
            return _result(hits[0], profiles[hits[0]], arg)
        raise Unresolved(f"no profile matches the ticket {arg}")
    hits = _by_cwd(profiles, cwd)
    if len(hits) > 1:
        raise Ambiguous(hits)
    if hits:
        return _result(hits[0], profiles[hits[0]], None)
    raise Unresolved(f"no profile matches the directory {cwd}")


@cli.verb("resolve")
@cli.guarded
def _resolve_verb(argv):
    # cli.guarded writes every error here: a fixed code under "error" and the
    # sentence under "message". A caller switches on the code. This verb had
    # its own two branches, so a corrupt config.json printed a traceback where
    # every other verb printed the profile code.
    cli.emit(resolve(argv[0] if argv else None, load_all()))
    return 0
