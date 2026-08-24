"""What a new project needs, and what the working directory already knows.

detect reads the git remote and the git config. init writes the profile. The
two are separate because the first is a question and the second is a decision:
a null field in detect is a value to ask the user for, and nothing else in this
file may invent one.
"""
import json
import os
import re
import subprocess
import urllib.parse

from . import cli, config, doctor

# git answers on stdout and this module reads it, so every call gets a deadline.
# tk runs as a subprocess under an agent, and a git command that waits for a
# credential prompt would hang the whole run with no output.
GIT_TIMEOUT = 10

# The identity key each provider answers with. references/profiles.md:182-185
# names the same three, and doctor.cli.person reads whichever one is present.
IDENTITY_KEY = {"azure": "id", "jira": "accountId", "github": "login"}

# Both lists together are the whole set verbs._link_type accepts, so naming one
# alone would refuse every type in the other. A merge completes every linked
# Azure work item, so a Bug has to be refused.
AZURE_LINK_RULES = {"link_types": ["Task"], "never_link_types": ["Bug"]}

BUCKETS = {"fixable-here": {"state": None, "assignee": "self"},
           "owned-elsewhere": {"state": None, "assignee": None},
           "split": {"state": None, "assignee": "self"},
           "needs-clarification": {"state": None, "assignee": None}}

# Every field a tracker kind cannot be built without, and the flag that carries
# it. detect fills most of them from the remote; a flag covers the rest.
REQUIRED = {"azure": (("--org", "org"), ("--project", "project")),
            "jira": (("--site", "site"), ("--project", "project")),
            "github": (("--owner", "owner"), ("--repo", "repo"))}


def _git_runner(cwd=None):
    """Runs read-only git and answers stdout, or None when git said nothing.

    None is not an error here. A directory outside a repository, a repository
    with no origin, and a git that is not installed are all states a new
    project can be in, and each one is a question for the user.
    """
    def run(args):
        try:
            done = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                                  text=True, timeout=GIT_TIMEOUT, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() or None if done.returncode == 0 else None

    return run


def parse_remote(url):
    """The provider and the coordinates one remote url carries.

    Six forms reach this function, and the differences are not cosmetic: an
    Azure project name arrives percent-escaped over https and bare over ssh,
    and Azure.__init__ quotes the value again, so an escaped one would read as
    a project that does not exist. An unknown host is not a failure. It means
    the host block cannot be filled, and the caller reports that.
    """
    blank = {"provider": None, "owner": None, "repo": None, "org": None,
             "project": None}
    text = str(url or "").strip()
    if not text:
        return dict(blank)
    if text.endswith(".git"):
        text = text[:-len(".git")]
    text = text.rstrip("/")

    ssh = re.match(r"^[^@]+@([^:]+):(.+)$", text)
    if ssh:
        host, path = ssh.group(1), ssh.group(2)
    else:
        parts = urllib.parse.urlsplit(text)
        if not parts.netloc:
            return dict(blank)
        # A userinfo part carries the organization name again on Azure over
        # https. Reading the host with it attached matches no pattern.
        host = parts.netloc.rsplit("@", 1)[-1]
        path = parts.path.lstrip("/")
    segments = [urllib.parse.unquote(part) for part in path.split("/") if part]

    if host.endswith("github.com") and len(segments) >= 2:
        return {"provider": "github", "owner": segments[0],
                "repo": segments[1], "org": None, "project": None}

    if host.endswith("dev.azure.com"):
        # ssh answers v3/<org>/<project>/<repo>. https answers
        # <org>/<project>/_git/<repo>.
        if segments and segments[0] == "v3":
            segments = segments[1:]
        segments = [part for part in segments if part != "_git"]
        if len(segments) >= 3:
            return {"provider": "azure", "owner": None, "repo": segments[2],
                    "org": f"https://dev.azure.com/{segments[0]}",
                    "project": segments[1]}
        return dict(blank)

    if host.endswith("visualstudio.com"):
        segments = [part for part in segments if part != "_git"]
        if len(segments) >= 2:
            return {"provider": "azure", "owner": None, "repo": segments[1],
                    "org": f"https://{host}", "project": segments[0]}
        return dict(blank)

    return dict(blank)


def detect(cwd=None, runner=None):
    """What the working directory knows. It makes no network call.

    Every field this cannot read stays null, because a null is the signal that
    a question is worth asking. Raising instead would make the caller guess
    which field was missing.
    """
    run = runner or _git_runner(cwd)
    root = run(["rev-parse", "--show-toplevel"])
    remote = run(["remote", "get-url", "origin"])
    head = run(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
    parsed = parse_remote(remote)
    base = head.split("/", 1)[-1] if head else None
    return {"root": root or os.path.abspath(cwd or os.getcwd()),
            "remote": remote,
            "provider": parsed["provider"],
            "owner": parsed["owner"],
            "repo": parsed["repo"],
            "org": parsed["org"],
            "project": parsed["project"],
            "base_branch": base,
            "identity": {"name": run(["config", "user.name"]),
                         "email": run(["config", "user.email"])}}


def ticket_patterns(ticket):
    """The match rule one example ticket id implies, or an empty list.

    The digit count is part of the rule. A bare ^[0-9]+$ would claim a three
    digit id that belongs to another tracker, and tk resolve would then exit 2
    on every short id for the rest of the project's life.
    """
    text = str(ticket or "").strip()
    if text.isdigit():
        return [f"^[0-9]{{{len(text)},}}$"]
    key = re.match(r"^([A-Z][A-Z0-9]+)-\d+$", text)
    if key:
        return [f"^{key.group(1)}-[0-9]+$"]
    return []


def _tracker_urls(tracker, org=None, site=None, owner=None, repo=None):
    """The url substrings config.resolve matches a pasted link against."""
    if tracker == "azure":
        # Strip the scheme, never hard-code a host: a legacy remote serves
        # <org>.visualstudio.com, and a profile naming a host the tracker never
        # serves matches no url at all.
        return [re.sub(r"^https?://", "", str(org or "")).rstrip("/")]
    if tracker == "jira":
        return [site] if site else []
    return [f"github.com/{owner}/{repo}"] if owner and repo else []


def _host_block(tracker, detected, owner=None, repo=None):
    """The pull request host, or None when this pair could never push.

    The host comes from the remote, not from the tracker, because a Jira
    tracker beside a GitHub host is a supported pair. The one pair that is not
    supported is an azure-repos host under a tracker that is not azure:
    gitcmd._base_url reads tracker.org to build the push url, and no other
    tracker holds one.
    """
    identity = detected.get("identity") or {}
    common = {"local_path": detected.get("root"),
              "branch_pattern": "feature/{id}-{slug}",
              "commit_subject": "[{id}] {summary}",
              "identity": {"name": identity.get("name"),
                           "email": identity.get("email")}}
    if detected.get("provider") == "github":
        return {"kind": "github",
                "owner": detected.get("owner") or owner,
                "repo": detected.get("repo") or repo,
                "base_branch": detected.get("base_branch") or "main",
                **common}
    if detected.get("provider") == "azure" and tracker == "azure":
        return {"kind": "azure-repos",
                "repo": detected.get("repo") or repo,
                "base_branch": detected.get("base_branch") or "master",
                **common}
    return None


def build(slug, tracker, detected, ticket=None, org=None, project=None,
          site=None, owner=None, repo=None):
    """The profile dict. It writes nothing and makes no call.

    Every value here is either a value the machine read or a null. Nothing
    invents a tracker state name, an assignee, or a deploy gate, because those
    three are the ones a wrong guess writes to a real ticket.
    """
    supplied = {"org": org, "project": project, "site": site, "owner": owner,
                "repo": repo}
    missing = [flag for flag, key in REQUIRED[tracker] if not supplied[key]]
    if missing:
        raise ValueError(
            f"tracker {tracker} needs {', '.join(missing)}. "
            "tk detect could not read it from the git remote, so pass it.")

    if tracker == "azure":
        # api_version is not decoration. Azure.__init__ refuses anything that
        # does not start with 7.1-preview, because a bare 7.1 answers some
        # routes with an empty body.
        tracker_block = {"kind": "azure", "org": org, "project": project,
                         "api_version": "7.1-preview"}
    elif tracker == "jira":
        tracker_block = {"kind": "jira", "site": site, "project": project}
    else:
        tracker_block = {"kind": "github", "owner": owner, "repo": repo}

    profile = {
        "slug": slug,
        "match": {"ticket_patterns": ticket_patterns(ticket),
                  "tracker_urls": _tracker_urls(tracker, org=org, site=site,
                                                owner=owner, repo=repo),
                  "repo_paths": [detected.get("root") or os.getcwd()]},
        "tracker": tracker_block,
        # All four names, every state null. tk state --bucket refuses a name
        # the profile does not define, and a null state leaves the tracker
        # alone, so the routing still travels in the comment until the user
        # names the board's own states.
        "buckets": json.loads(json.dumps(BUCKETS)),
        # An empty dict, not an absent key: init assigns people.self by
        # subscript, and a KeyError there would report a config file problem
        # for a code bug.
        "people": {}}

    host = _host_block(tracker, detected, owner=owner, repo=repo)
    if host:
        profile["host"] = host
    if tracker == "azure":
        profile["link_rules"] = json.loads(json.dumps(AZURE_LINK_RULES))
    return profile


def notes_stub(profile, detected):
    """The notes.md a new project starts with.

    Six headings from the outline in references/profiles.md, each naming what
    to fill and why it costs a run when it is empty.
    """
    host = profile.get("host") or {}
    tracker = (profile.get("tracker") or {}).get("kind")
    lines = [
        f"# {profile['slug']}",
        "",
        "Written by tk init. Every TODO below is a value no machine can read.",
        "",
        "## 1. Repo layout",
        "",
        f"- Repository: {host.get('local_path') or detected.get('root')}",
        f"- Base branch: {host.get('base_branch') or 'TODO: name it'}",
        "- TODO: name the app that serves the area tickets land in.",
        "",
        "## 2. The verify gate",
        "",
        "- TODO: the exact commands, in order, and what a clean run prints.",
        "  This is the field that costs a run when it is empty. With no gate,",
        "  a fix ships on a claim instead of on evidence.",
        "",
        "## 3. Conventions that bite",
        "",
        "- TODO: lint rules, formatter, when to use the language server.",
        "",
        "## 4. Code areas by name",
        "",
        "- TODO: where the forms, the config, and the flows live.",
        "",
        "## 5. Project traps",
        "",
        "- TODO: the four buckets hold no states yet. Ask the user for the",
        "  board's own state names the first time a ticket needs one, then",
        "  write them into buckets in config.json.",
        "- TODO: there is no deploy_gate. Ask for the state a tested build",
        "  reaches, and the word that releases it.",
    ]
    if tracker == "azure":
        lines += [
            "- link_rules names Task and refuses Bug. Those two lists are the",
            "  whole set tk accepts, so User Story, Feature, and Product",
            "  Backlog Item are refused as typos until you add them.",
        ]
    lines += [
        "",
        "## 6. Deep references",
        "",
        "- TODO: relative paths to the docs that matter.",
        "",
    ]
    return "\n".join(lines)


def write(profile, notes, root=None):
    """Writes projects/<slug>/config.json and notes.md. Refuses an overwrite.

    A refusal beats an overwrite. An existing profile holds states and notes a
    human wrote, and this function cannot tell them from a default.
    """
    root = root or config.ROOT
    slug = profile["slug"]
    target = os.path.join(root, "projects", slug)
    config_path = os.path.join(target, "config.json")
    if os.path.exists(config_path):
        raise ValueError(f"profile {slug} already exists at {config_path}. "
                         "Edit it, or pass --slug with another name.")
    os.makedirs(target, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(profile, indent=2, sort_keys=True) + "\n")
    notes_path = os.path.join(target, "notes.md")
    with open(notes_path, "w", encoding="utf-8") as fh:
        fh.write(notes)
    return {"slug": slug, "config_path": config_path, "notes_path": notes_path}


def _next_steps(profile, detected, tracker):
    """The gaps a human still has to close, one sentence each."""
    steps = ["notes.md has no verify gate yet. Ask the user for the commands "
             "that prove a fix, then write them under heading 2.",
             "The four buckets hold no states. Ask the user for the board's "
             "own state names the first time a ticket needs one.",
             "There is no deploy_gate. Ask for the state a tested build "
             "reaches, and the word that releases it."]
    if not profile.get("host"):
        if detected.get("provider") == "azure" and tracker != "azure":
            steps.append(
                "No host block: this directory is an Azure Repos clone and the "
                "tracker is not azure, so the push url has no organization to "
                "read. Add a host block by hand, or run tk git from a clone "
                "whose remote matches the tracker.")
        else:
            steps.append(
                "No host block: this directory has no github or azure remote, "
                "so tk pr and tk git have nowhere to push. Add one by hand.")
    return steps


def init(args, values, client=None, root=None, runner=None):
    """Writes a profile from the directory, the flags, and one whoami call.

    The order is the point. Every call that can fail runs before write, so a
    missing token leaves no profile at all and the retry is the same command.
    Writing first would leave a profile that doctor reports as broken for ever.

    client and runner are the two seams. A test injects both, so no test makes
    a network call and none shells out to git.
    """
    detected = detect(args.path, runner)
    tracker = args.tracker
    org = args.org or (detected["org"] if tracker == "azure" else None)
    project = args.project or (detected["project"] if tracker == "azure" else None)
    owner = args.owner or (detected["owner"] if tracker == "github" else None)
    repo = args.repo or (detected["repo"] if tracker == "github" else None)

    profile = build(args.slug, tracker, detected, ticket=args.ticket, org=org,
                    project=project, site=args.site, owner=owner, repo=repo)

    adapter = cli.adapter_for(profile, values, client)
    who = adapter.whoami()
    key = IDENTITY_KEY[tracker]
    who_id = (who or {}).get("id")
    # A 200 with no id is a real answer on some providers, and doctor treats an
    # unusable people.self exactly as it treats a missing guid. Writing one
    # would produce a profile this repo's own check calls broken.
    if not who_id or doctor._placeholder(who_id):
        raise ValueError(
            f"{tracker} answered no usable account id for the token in "
            "secrets.env, so people.self would be empty. Check the token, "
            "then run tk init again.")
    profile["people"]["self"] = {key: who_id}

    host = profile.get("host") or {}
    if host.get("kind") == "azure-repos":
        ids = adapter.repo_ids(host["repo"])
        if not ids.get("repo_id") or not ids.get("project_id"):
            raise ValueError(
                f"Azure answered no repository and project id for "
                f"{host['repo']}, and the pull request route cannot run "
                "without both. Check the repository name, then run tk init "
                "again.")
        host.update(ids)

    written = write(profile, notes_stub(profile, detected), root)
    return {**written, "self": who, "host": host.get("kind"),
            "next": _next_steps(profile, detected, tracker)}
