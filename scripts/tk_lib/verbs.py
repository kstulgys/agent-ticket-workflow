"""Every verb except resolve. Each one loads secrets, resolves, then acts.

The guard and the error shape live in cli, so resolve wears the same ones.
"""
import argparse
import os

from . import cli, config, doctor, figma, gitcmd, secrets

# The arguments each pull request action cannot run without. A missing one used
# to reach the server as the word None: a null description replaced text a
# human wrote, and a route read pullRequests/None/threads.
PR_NEEDS = {"create": ("head", "title", "body_file"),
            "threads": ("pr",),
            "comment": ("pr", "body_file"),
            "attach": ("pr", "file"),
            "describe": ("pr", "body_file")}


def _named(slug, profiles):
    """The profile a slug names, or a refusal that lists every slug on disk.

    A bare key repr tells the reader nothing about what exists.
    """
    if slug not in profiles:
        raise config.Unresolved(f"no profile named {slug}. "
                                f"Known: {', '.join(sorted(profiles))}")
    return profiles[slug]


def _profile(slug=None, arg=None):
    """Returns (profile, values, ticket). It builds no adapter.

    The git verb and the pull request verb take this route. A profile can hold
    a Jira tracker beside a GitHub host, and building the tracker there would
    ask for a Jira token to run work that never touches Jira. An expired Jira
    token would then break git push.
    """
    values = secrets.load()
    profiles = config.load_all()
    if slug:
        return _named(slug, profiles), values, arg
    found = config.resolve(arg, profiles)
    return profiles[found["slug"]], values, found["ticket"]


def _context(arg=None, slug=None):
    """Returns (profile, adapter, ticket, values). Exits 2 when a ticket is ambiguous."""
    profile, values, ticket = _profile(slug, arg)
    return profile, cli.adapter_for(profile, values), ticket, values


class _Broken:
    """An adapter that could not be built. doctor reads the reason from it."""

    def __init__(self, error):
        self._error = error

    def whoami(self):
        raise self._error

    def repo_check(self):
        raise self._error


def _built(build, profile, values):
    """The adapter, or a _Broken that carries why it could not be built.

    A missing token must not stop the other projects, and it must not hide the
    other provider on this one.
    """
    try:
        return build(profile, values)
    except Exception as error:
        return _Broken(error)


def _host_is_second_provider(profile):
    """True when the pull request host needs a check of its own.

    The globex profile is a Jira tracker beside a GitHub host, so its GitHub
    token reaches no check through the tracker. The northwind host is azure-repos
    beside an azure tracker: one organization and one token, so the tracker
    check answers for both.
    """
    host = cli.provider_of((profile.get("host") or {}).get("kind"))
    return bool(host) and host != cli.provider_of(
        (profile.get("tracker") or {}).get("kind"))


@cli.verb("doctor")
@cli.guarded
def _doctor(argv):
    values = secrets.load()
    profiles = config.load_all()
    adapters, hosts = {}, {}
    for slug, profile in profiles.items():
        adapters[slug] = _built(cli.adapter_for, profile, values)
        if _host_is_second_provider(profile):
            hosts[slug] = _built(cli.host_adapter_for, profile, values)
    report = doctor.check(profiles, adapters, hosts)
    cli.emit(report)
    return 0 if report["ok"] else 1


@cli.verb("mine")
@cli.guarded
def _mine(argv):
    parser = argparse.ArgumentParser(prog="tk mine")
    parser.add_argument("--slug", action="append")
    args = parser.parse_args(argv)
    values = secrets.load()
    profiles = config.load_all()
    # Name every slug first, so a typo refuses before any call goes out.
    wanted = [(slug, _named(slug, profiles))
              for slug in (args.slug or sorted(profiles))]
    tickets, failed = [], []
    for slug, profile in wanted:
        try:
            tickets.extend(cli.adapter_for(profile, values).mine())
        # doctor keeps going when one project has no token, and this verb must
        # too. One stale token would otherwise hide the tickets on every other
        # project. failed names what is missing, so no caller reads this list
        # as the whole answer.
        except Exception as error:
            failed.append({"slug": slug, "error": secrets.scrub(str(error))})
    cli.emit({"tickets": tickets, "failed": failed})
    return 1 if failed else 0


@cli.verb("show")
@cli.guarded
def _show(argv):
    parser = argparse.ArgumentParser(prog="tk show")
    parser.add_argument("ticket")
    parser.add_argument("--slug")
    parser.add_argument("--attachments")
    args = parser.parse_args(argv)
    _, adapter, ticket, _ = _context(args.ticket, args.slug)
    if args.attachments:
        os.makedirs(args.attachments, exist_ok=True)
    cli.emit(adapter.show(ticket, attachments_dir=args.attachments))
    return 0


@cli.verb("comment")
@cli.guarded
def _comment(argv):
    parser = argparse.ArgumentParser(prog="tk comment")
    parser.add_argument("ticket")
    parser.add_argument("--slug")
    parser.add_argument("--body-file", required=True)
    args = parser.parse_args(argv)
    _, adapter, ticket, _ = _context(args.ticket, args.slug)
    result = adapter.comment(ticket, cli.read_body(args.body_file))
    cli.emit(result)
    return 0 if result.get("ok") else 1


@cli.verb("state")
@cli.guarded
def _state(argv):
    parser = argparse.ArgumentParser(prog="tk state")
    parser.add_argument("ticket")
    parser.add_argument("--slug")
    parser.add_argument("--bucket")
    parser.add_argument("--gate", action="store_true")
    parser.add_argument("--type", dest="item_type")
    args = parser.parse_args(argv)
    # Both refusals come before the profile read, so a command that cannot run
    # spends no call. The gate is the one state the engine sets on your word,
    # so a command naming a bucket as well is a mistake worth naming.
    if args.gate and args.bucket:
        raise ValueError("pass --bucket <name> or --gate, not both. The gate is "
                         "the one state the engine sets on your word.")
    if not args.gate and not args.bucket:
        raise ValueError("pass --bucket <name> or --gate")
    profile, adapter, ticket, _ = _context(args.ticket, args.slug)
    item_type = args.item_type or adapter.show(ticket)["type"]
    if args.gate:
        result = cli.apply_gate(profile, adapter, ticket, item_type)
    else:
        result = cli.apply_bucket(profile, adapter, ticket, args.bucket, item_type)
    cli.emit(result)
    return 0 if result.get("ok") else 1


@cli.verb("assign")
@cli.guarded
def _assign(argv):
    parser = argparse.ArgumentParser(prog="tk assign")
    parser.add_argument("ticket")
    parser.add_argument("--slug")
    parser.add_argument("--owner", required=True)
    args = parser.parse_args(argv)
    profile, adapter, ticket, _ = _context(args.ticket, args.slug)
    who = cli.person(profile, args.owner) or args.owner
    result = adapter.assign(ticket, who)
    cli.emit(result)
    return 0 if result.get("ok") else 1


@cli.verb("pr")
@cli.guarded
def _pr(argv):
    if not argv:
        raise ValueError(f"pass {', '.join(sorted(PR_NEEDS))}")
    action, rest = argv[0], argv[1:]
    if action not in PR_NEEDS:
        raise ValueError(f"unknown pr action {action}. "
                         f"Known: {', '.join(sorted(PR_NEEDS))}")
    parser = argparse.ArgumentParser(prog=f"tk pr {action}")
    parser.add_argument("--slug")
    parser.add_argument("--pr")
    parser.add_argument("--head")
    parser.add_argument("--base")
    parser.add_argument("--title")
    parser.add_argument("--body-file")
    parser.add_argument("--link", action="append", default=[])
    parser.add_argument("--reviewer")
    parser.add_argument("--reply-to")
    parser.add_argument("--file")
    args = parser.parse_args(rest)
    for name in PR_NEEDS[action]:
        if not getattr(args, name):
            raise ValueError(f"tk pr {action} needs --{name.replace('_', '-')}")
    profile, values, _ = _profile(args.slug)
    # The host owns the pull requests, and it is not always the tracker. The
    # live globex profile is a Jira tracker beside a GitHub host.
    host = cli.host_adapter_for(profile, values)
    body = cli.read_body(args.body_file) if args.body_file else None
    # Every role a host verb names resolves against the host, never against the
    # tracker's people block. A Jira account id is no GitHub login, so the
    # tracker identity filtered no thread here and would name no reviewer.
    if action == "create":
        result = host.pr_create(head=args.head, title=args.title, body=body,
                                base=args.base, links=_links(args.link, profile, values),
                                reviewer=cli.host_person(profile, args.reviewer)
                                or args.reviewer)
    elif action == "threads":
        result = host.pr_threads(args.pr, me=cli.host_self(profile))
    elif action == "comment":
        result = host.pr_comment(args.pr, body, reply_to=args.reply_to)
    elif action == "attach":
        result = host.pr_attach(args.pr, args.file)
    else:
        result = host.pr_describe(args.pr, body)
    cli.emit(result)
    if isinstance(result, dict) and result.get("ok") is False:
        return 1
    return 0


def _link_type(profile, wanted):
    """The profile's own spelling of a work item type a caller named.

    never_link_types compares the exact spelling, so a caller who writes bug
    where the profile writes Bug passes the refusal. The bug then links, it
    completes on merge, and it skips its test pass with no message. That is
    the one harm link_rules exists to stop, so fold the case here, at the one
    place a caller supplied type enters.

    A type the rules never name is a typo, and a typo lands outside
    never_link_types, which is where the harm is. Refuse it.

    A profile that names no type at all carries no rule to bypass, so the
    spelling stands as the caller wrote it.
    """
    rules = profile.get("link_rules") or {}
    known = [str(name) for name in
             list(rules.get("link_types") or []) + list(rules.get("never_link_types") or [])]
    if not known:
        return wanted
    folded = {}
    for name in known:
        folded.setdefault(name.casefold(), set()).add(name)
    group = folded.get(str(wanted).casefold())
    if group is None:
        raise ValueError(
            f"link_rules in profile {profile.get('slug')} names no type {wanted}. "
            f"Known: {', '.join(sorted(set(known)))}")
    if len(group) > 1:
        # One type spelled two ways folds to one key, and the spelling this
        # returns decides whether the work item completes on merge. No rung
        # breaks that tie, so refuse instead of picking one.
        raise ValueError(
            f"link_rules in profile {profile.get('slug')} spells the type "
            f"{wanted} more than one way: {', '.join(sorted(group))}. "
            "Keep one spelling.")
    return next(iter(group))


def _links(items, profile, values):
    """One {"id", "type"} pair per --link value.

    The grammar is <id>:<type>. The refusal rule reads the type, so a wrong
    type links a work item that completes on merge and skips its test pass.
    The caller usually knows the type, and reading it back costs a full work
    item read on Azure, with every comment page. A value with no suffix still
    reads it, because a guess here is worse than one call. A type the server
    answers with is canonical already, so only the suffix needs resolving.
    """
    tracker, out = None, []
    for item in items:
        wid, _, item_type = item.partition(":")
        if item_type:
            item_type = _link_type(profile, item_type)
        else:
            if tracker is None:
                tracker = cli.adapter_for(profile, values)
            item_type = tracker.show(wid)["type"]
        out.append({"id": wid, "type": item_type})
    return out


@cli.verb("figma")
@cli.guarded
def _figma(argv):
    """Figma is not a tracker, so it comes from no profile and no table."""
    parser = argparse.ArgumentParser(prog="tk figma")
    parser.add_argument("url")
    parser.add_argument("--render")
    parser.add_argument("--specs", action="store_true")
    args = parser.parse_args(argv)
    client = figma.Figma(secrets.load())
    out = {}
    if args.render:
        out["render"] = client.render(args.url, args.render)
    if args.specs or not args.render:
        out["specs"] = client.specs(args.url)
    cli.emit(out)
    return 0


@cli.verb("git")
@cli.guarded
def _git(argv):
    if "--" not in argv:
        raise ValueError("usage: tk git --slug <slug> -- <git arguments>")
    split = argv.index("--")
    parser = argparse.ArgumentParser(prog="tk git")
    parser.add_argument("--slug", required=True)
    args = parser.parse_args(argv[:split])
    # _profile, not _context. git reads the host block, and this profile can
    # hold a tracker on another provider whose token has no work here.
    profile, values, _ = _profile(args.slug)
    code = gitcmd.run(profile, values, argv[split + 1:])
    # git answers its own codes, and a fatal error is 128. This CLI documents
    # three codes, so every nonzero git code is an error here.
    return 0 if code == 0 else 1
