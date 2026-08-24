"""Verb table, argument handling, and the one error shape for tk."""
import json
import sys
import urllib.error
from http.client import HTTPException

USAGE = """usage: tk <verb> [options]

verbs:
  doctor                     check every provider and project
  resolve <arg>              id, key, url, or cwd to a project
  mine [--slug S]            tickets assigned to me
  show <ticket>              the normalised ticket shape
  comment <ticket>           post a comment from a file
  state <ticket>             move state by bucket, or apply the deploy gate
  assign <ticket>            assign by role
  pr <create|threads|comment|attach|describe>
  figma <url>                render a frame and print its values
  git --slug S -- <args>     run git with the credential injected
"""

VERBS = {}


def verb(name):
    def register(fn):
        VERBS[name] = fn
        return fn

    return register


def emit(value):
    """JSON to stdout. Every read and every write prints its result."""
    json.dump(value, sys.stdout, indent=2, sort_keys=True, default=str)
    sys.stdout.write("\n")


def read_body(path):
    """Body text comes from a file or stdin, never from argv."""
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def error_codes():
    """Every failure class this CLI answers for, each with its code.

    The import is local, because config imports cli for the verb table. The
    order matters, because URLError, TimeoutError, and ConnectionError are all
    an OSError, and BadProfile and UnicodeDecodeError are both a ValueError.

    guarded derives its except tuple from this table, so the classes it
    catches and the codes it prints cannot drift apart.
    """
    from . import config, http, secrets

    return ((config.Ambiguous, "ambiguous"),
            (config.Unresolved, "unresolved"),
            (secrets.SecretsError, "secrets"),
            (http.HttpError, "http"),
            (config.BadProfile, "profile"),
            (KeyError, "profile"),
            (UnicodeDecodeError, "encoding"),
            (urllib.error.URLError, "network"),
            # IncompleteRead is an HTTPException and nothing else, so it used
            # to escape every entry here and print a traceback with no JSON.
            # RemoteDisconnected and TimeoutError are both an OSError, so they
            # used to report filesystem for a network fault.
            (HTTPException, "network"),
            (TimeoutError, "network"),
            (ConnectionError, "network"),
            (OSError, "filesystem"),
            (RuntimeError, "incomplete"),
            (ValueError, "usage"))


def guarded(fn):
    """Turns every failure below into an exit code and one JSON line.

    Every verb wears this, resolve included. resolve is the first verb the
    engine calls on every run, so a traceback there lands where the agent is
    still working out which project it is in.

    The shape is a fixed code under error and the sentence under message, with
    slugs beside them when a ticket is ambiguous. A caller switches on the
    code.

    Each entry in error_codes comes from a real failure: a bad --render
    directory, a profile that misses a key, a corrupt secrets file, and the
    GitHub page walk at its bound. A reset connection, a truncated body, and a
    request that passes its deadline all report network.

    Exit 2 is for an ambiguous ticket only. It is the one failure a human
    answers. argparse ends the process with 2 for a bad argument, so that code
    is caught here and turned into 1, or a typo would read as an ambiguous
    ticket with no JSON at all.

    The message goes through the scrubber, because an error can quote a url or
    a header that holds a token.
    """

    def wrapper(argv):
        from . import config, secrets

        table = error_codes()
        try:
            return fn(argv)
        except config.Ambiguous as error:
            emit({"error": "ambiguous", "message": secrets.scrub(str(error)),
                  "slugs": error.slugs})
            return 2
        except SystemExit as error:
            # argparse ends the process for --help and for a bad argument. The
            # help path is a success and it printed the usage already.
            if error.code in (None, 0):
                return 0
            emit({"error": "usage",
                  "message": "these arguments are not valid. "
                             "The usage for this verb is on stderr."})
            return 1
        except tuple(kind for kind, _ in table) as error:
            code = next(name for kind, name in table if isinstance(error, kind))
            emit({"error": code, "message": secrets.scrub(str(error))})
            return 1

    return wrapper


def adapter_for(profile, values, client=None):
    """The adapter for one profile. Every verb reaches a tracker through here.

    The import is local, because an adapter imports cli for its verb table.
    """
    from . import azure, github, jira

    kind = (profile.get("tracker") or {}).get("kind")
    table = {"azure": azure.Azure, "jira": jira.Jira, "github": github.GitHub}
    if kind not in table:
        raise ValueError(f"unknown tracker kind {kind}. "
                         f"Known: {', '.join(sorted(table))}")
    return table[kind](profile, values, client)


def host_adapter_for(profile, values, client=None):
    """The adapter that owns the pull requests. It is not always the tracker.

    The live globex profile is a Jira tracker beside a GitHub host, and Jira
    holds no pull request. A pull request verb that took the tracker there
    would call pr_create on a Jira object and raise an AttributeError.

    A profile that declares no host block keeps its pull requests on the
    tracker, so the tracker kind answers for it. That works for a GitHub
    tracker, which holds the owner and the repository already.

    The Azure host has one spelling, azure-repos. This table used to take
    azure as well, and gitcmd takes azure-repos alone, so a profile spelled
    azure opened a pull request and failed every git command. Nothing in
    either message named the other spelling.

    An Azure tracker with no host block reaches the refusal below, and that is
    the better answer. A pull request route needs host.repo_id, so such a
    profile could never open one, and it used to raise a KeyError deep inside
    the git route instead.
    """
    from . import azure, github

    kind = ((profile.get("host") or {}).get("kind")
            or (profile.get("tracker") or {}).get("kind"))
    table = {"azure-repos": azure.Azure, "github": github.GitHub}
    if kind not in table:
        raise ValueError(f"{kind} hosts no pull request. "
                         f"Set host.kind in config.json to one of: "
                         f"{', '.join(sorted(table))}")
    return table[kind](profile, values, client)


def person(profile, role):
    """The identity a role names on the tracker. Each one holds its own key."""
    return _first_id((profile.get("people") or {}).get(role))


def _first_id(who):
    """One identity out of one people entry. Azure, Jira, and GitHub in order."""
    who = who or {}
    return who.get("id") or who.get("accountId") or who.get("login")


def host_names(profile, role):
    """Every name the pull request host can know a role by, the best one first.

    One rule for every host verb. The host is not always the tracker, and the
    people block holds tracker identities. A Jira account id is no GitHub
    login, so a host operation that read people alone compared two identity
    systems: tk pr threads on the live globex profile matched none of my own
    threads and returned them all, and a resume run would answer itself. The
    same read named a Jira account id as a GitHub reviewer.

    host.people is the host's own map, so it wins. The tracker people block
    comes next, and only when the host and the tracker are one provider,
    because then one identity serves both: the Azure host knows me by the
    account id in people.self. host.identity.name is last, because it is the
    git author name, and on the Azure host that name is no account. It is the
    login on GitHub, which is why it is here at all.

    An account identity therefore always beats the author name, and a caller
    that takes one name gets the account. A caller that compares every name,
    such as the thread filter, takes the whole list.
    """
    host = profile.get("host") or {}
    names = [_first_id((host.get("people") or {}).get(role))]
    if provider_of(host.get("kind")) in (
            None, provider_of((profile.get("tracker") or {}).get("kind"))):
        names.append(person(profile, role))
    if role == "self":
        names.append((host.get("identity") or {}).get("name"))
    return [name for name in names if name]


def host_person(profile, role):
    """The one name to send the host for a role, or None when it names none."""
    return next(iter(host_names(profile, role)), None)


def host_self(profile):
    """Every name the host knows me by, and never an empty answer.

    Both adapters read no name as "filter nothing", so an empty answer here
    would hand a resume run its own threads to answer. host.identity.name is
    optional, and gitcmd falls back to the git config on disk for it, so a
    GitHub host profile can carry no name at all and reach this. Refuse it the
    way an unknown bucket role is refused: a run that cannot tell its own
    comments apart must stop, not guess.
    """
    names = host_names(profile, "self")
    if not names:
        raise ValueError(
            f"profile {profile.get('slug')} resolves no identity for itself on "
            "its pull request host, so a thread you wrote cannot be told from a "
            "reviewer's. Add host.identity.name, or host.people.self, or "
            "people.self when the host and the tracker are one provider.")
    return names


def provider_of(kind):
    """The provider one kind belongs to. Two kinds can name one provider.

    azure-repos is the host spelling of azure: one organization, one token, one
    API. doctor compares these names to decide whether a host needs a check of
    its own, and a second azure check on one profile would test the same token
    against the same project twice. host_names compares them to decide whether
    a tracker identity means anything to the host.
    """
    return "azure" if kind == "azure-repos" else kind


def apply_bucket(profile, adapter, ticket, name, item_type=None):
    """Moves one ticket into one bucket. The same shape serves three trackers.

    A bucket names a state, an assignee, or neither. A name the profile does
    not define is an authoring mistake, and doing nothing for it would report
    success over an untouched ticket.
    """
    buckets = profile.get("buckets") or {}
    if name not in buckets:
        raise ValueError(f"unknown bucket {name}. Known: {', '.join(sorted(buckets))}")
    bucket = buckets[name]
    role = bucket.get("assignee")
    who = person(profile, role) if role else None
    if role and not who:
        # person answers None for a role nobody defines, and a None assignee
        # clears the field on Azure and unassigns the issue on Jira. Refuse
        # before the write, the way an unknown bucket name is refused above.
        people = (profile.get("people") or {})
        raise ValueError(
            f"bucket {name} assigns the role {role}, and the people block holds "
            f"no identity for it. Known: {', '.join(sorted(people)) or 'none'}")
    result = {"bucket": name, "ok": True}
    if bucket.get("state"):
        result["state"] = adapter.state(ticket, bucket["state"], item_type=item_type)
        result["ok"] = result["ok"] and bool(result["state"].get("ok"))
    if who:
        result["assign"] = adapter.assign(ticket, who)
        result["ok"] = result["ok"] and bool(result["assign"].get("ok"))
    return result


def apply_gate(profile, adapter, ticket, item_type=None):
    """The one state the engine sets on your word, not on a bucket."""
    gate = (profile.get("deploy_gate") or {}).get("state")
    if not gate:
        raise ValueError("this profile has no deploy_gate state")
    return adapter.state(ticket, gate, item_type=item_type)


def load_verbs():
    from . import config, verbs  # noqa: F401  each module registers its verbs


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        sys.stderr.write(USAGE)
        return 1
    if argv[0] in ("-h", "--help", "help"):
        sys.stdout.write(USAGE)
        return 0
    load_verbs()
    name, rest = argv[0], argv[1:]
    if name not in VERBS:
        sys.stderr.write(f"unknown verb: {name}\n\n{USAGE}")
        return 1
    code = VERBS[name](rest)
    if not isinstance(code, int):
        # sys.exit(None) exits 0. A verb that forgets to return 1 on an error
        # path would report success, so a missing code is an error.
        sys.stderr.write(f"verb gave no exit code: {name}\n")
        return 1
    return code
