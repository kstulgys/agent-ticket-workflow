"""One check per provider, and one per project."""
from . import cli, secrets

SETUP = "scripts/setup.sh"
# The provider whose token carries a scope per API area. Its project check
# reads a work item, so its fix line, and no other, names that scope.
AZURE = "azure"


def check(profiles, adapters, hosts=None):
    """Reads every provider, then reads every project through it.

    Two calls per project, because they fail apart. A token can name the right
    account and still read no ticket: an Azure PAT is scoped per project and
    per API area, a Jira token needs browse permission, and a GitHub token
    needs the organization to authorize it under single sign on. Each one
    passes the account call, so only the project call proves access. Each
    adapter reads the data a run needs there, not a route beside it.

    hosts holds the pull request host of a project whose host is a second
    provider, and it gets a row of its own. Without it the GitHub token on the
    globex profile reached no check here, and a dead token first showed up at
    tk pr create, which is the moment this verb comes before.
    """
    providers, projects, fix = {}, [], []
    if not profiles:
        return {"ok": False, "providers": {}, "projects": [],
                "fix": ["no project profiles found. Create "
                        "~/.claude/ticket-workflow/projects/<slug>/config.json"]}
    for slug, profile in profiles.items():
        # The provider, never the kind. azure-repos is the host spelling of
        # azure, and the raw word broke three places: setup.sh refuses it, so
        # the one command this verb hands the user would not run, and providers
        # split one provider over two keys, which stops the summary from
        # folding two rows of one provider into one answer.
        units = [("tracker", cli.provider_of((profile.get("tracker") or {})
                                             .get("kind")),
                  adapters.get(slug))]
        if (hosts or {}).get(slug) is not None:
            units.append(("host", cli.provider_of((profile.get("host") or {})
                                                  .get("kind")),
                          hosts[slug]))
        for role, kind, adapter in units:
            row = _row(slug, role, kind, adapter, fix)
            # A profile with no tracker.kind is the broken setup this verb
            # exists to find. None is no sort key beside a string, so cli.emit
            # would write a part of the document and then raise where nothing
            # catches it.
            key = kind or "unknown"
            # One failing project makes its provider false. Two projects can
            # share a provider, and the last answer must never overwrite an
            # earlier failure. A summary that reads true above a failing
            # project is worse than no doctor, because this verb exists to
            # answer whether a run will work before it touches a real ticket.
            providers[key] = bool(row.get("ok")) and providers.get(key, True)
            projects.append(row)
        # A row only when there is something to report. Every provider row
        # answers for a token, and this one answers for the file, so a row
        # saying nothing is wrong would add a line per project to every clean
        # report. The fix list is the actionable half, and it names the slug.
        gaps = _profile_gaps(profile)
        if gaps:
            projects.append({"slug": slug, "role": "profile", "provider": None,
                             "ok": False, "error": "; ".join(gaps)})
            for gap in gaps:
                fix.append(f"{slug}: {gap}. Edit config.json.")
    return {"ok": all(row.get("ok") for row in projects),
            "providers": providers, "projects": projects, "fix": sorted(set(fix))}


def _placeholder(value):
    """True when a value is an example placeholder, not a real identity.

    The example profiles ship a guid whose hex digits are all one character,
    and a copied profile keeps it. A real Azure identity is never one repeated
    digit, so this shape is safe to refuse.
    """
    digits = str(value or "").replace("-", "")
    return len(digits) >= 8 and len(set(digits)) == 1


def _profile_gaps(profile):
    """Every profile field no API call reads. It makes no network call.

    doctor reads two routes per project, and neither looks at a bucket role, a
    people identity, or a repository guid. So a profile copied from the examples
    and never edited passed green here, and the failure arrived later at tk pr
    create as a 404 on a placeholder guid, which reads as a permissions problem.

    An absent optional block passes, because a tracker only project is valid. A
    block that is present with a missing required key fails.
    """
    gaps = []
    people = profile.get("people") or {}
    for role in sorted(people):
        who = cli.person(profile, role)
        if not who:
            gaps.append(f"people.{role} holds no id, accountId, or login")
        elif _placeholder(who):
            gaps.append(f"people.{role} still holds the example placeholder id")
    for name in sorted(profile.get("buckets") or {}):
        role = ((profile.get("buckets") or {}).get(name) or {}).get("assignee")
        if role and role not in people:
            gaps.append(f"buckets.{name} assigns the role {role}, and the "
                        "people block holds no entry for it")
    host = profile.get("host") or {}
    # Only this host kind needs the two guids, and it is the kind that gets no
    # row of its own, because it shares its token with the tracker.
    if host.get("kind") == "azure-repos":
        for key in ("repo_id", "project_id"):
            if not host.get(key):
                gaps.append(f"host.{key} is missing, and the pull request "
                            "route cannot run without it")
            elif _placeholder(host.get(key)):
                gaps.append(f"host.{key} still holds the example placeholder guid")
    # host.local_path is deliberately not checked here. Every gap above is a
    # fact about the file, so this answer does not change with the machine. A
    # path that is not cloned yet is a normal state during setup, and tk git
    # already fails on it with an error that names the directory.
    return gaps


def _row(slug, role, kind, adapter, fix):
    """One provider row. It appends the fix line for the gap it finds."""
    row = {"slug": slug, "role": role, "provider": kind}
    try:
        who = adapter.whoami()
        row.update(ok=True, name=who.get("name"), id=who.get("id"))
    # whoami can fail as an HttpError, a SecretsError, or a socket error, and
    # every one of them means the same thing to the reader: this provider is
    # not usable yet.
    except Exception as error:
        # This report goes to stdout. No exception reachable here carries a
        # token today, so the scrubber is the second line of defence.
        row.update(ok=False, error=secrets.scrub(error))
        fix.append(f"{SETUP} {kind}" if kind else
                   f"{slug}: the profile names no {role}.kind. "
                   "Add it to config.json.")
    if row.get("ok"):
        # Every adapter holds repo_check, so this call has no name test in
        # front of it. A test here would skip the check in silence for an
        # adapter that lost the method.
        try:
            repo = adapter.repo_check()
        # repo_check catches HttpError alone, so a reset connection or a
        # profile missing a key escapes it. One project must not take down a
        # report that already holds the rows that passed.
        except Exception as error:
            repo = {"ok": False, "error": secrets.scrub(error)}
        if not repo.get("ok"):
            row.update(ok=False, repo_error=repo.get("error"))
            line = (f"{slug}: the {kind} token reached the API but not the "
                    "project data. Authorize it for the organization under "
                    "single sign-on, or scope it to this project.")
            if kind == AZURE:
                # One next step per row. A Jira or GitHub token has no Work
                # Items scope to set, so that sentence on their row sends the
                # reader to mint a credential their provider has no word for.
                line += (" This check reads a work item, so an Azure PAT also "
                         "needs the Work Items scope.")
            fix.append(line)
    return row
