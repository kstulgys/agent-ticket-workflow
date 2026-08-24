# Plan 003: Build a project profile from what the machine already knows

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 50239f0..HEAD -- scripts/tk_lib/ tests/`
> If `scripts/tk_lib/cli.py`, `scripts/tk_lib/verbs.py`, `scripts/tk_lib/config.py`,
> or `scripts/tk_lib/azure.py` changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding. On a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED
- **Depends on**: `plans/002-lazy-secrets-and-one-provider-setup.md` (a missing
  token must already name its own stage before a bootstrap can lean on it)
- **Category**: dx
- **Planned at**: commit `50239f0`, 2026-08-24

## Why this matters

`tk` cannot read a ticket without a project profile, and today a human writes
that profile by hand. `SKILL.md:115-117` says so: "A project with no profile is
a new project. Write `~/.claude/ticket-workflow/projects/<slug>/config.json`
and `notes.md` first, using `references/profiles.md`." That reference is 251
lines. It documents an `api_version` that must start with `7.1-preview`, a
`host.kind` that refuses the spelling `azure`, four bucket names that must all
be present, two Azure guids, and an account id per role.

So the user who types "work on 5438" on a fresh machine is sent to write a
50-line JSON file before anything reads the ticket. That is the setup phase
this work removes.

Most of that file is already on the machine. The git remote names the provider,
the owner, the repository, and the Azure organization and project. `git
symbolic-ref` names the base branch. `git config` names the commit identity.
The provider's own API names the user's account id. The ticket the user typed
names the id pattern. This plan adds two verbs: one that reports what the
directory knows, and one that writes the profile from it. What is left to ask
is then two or three values, and each one is a value no machine can know.

## Current state

### The verb table, `scripts/tk_lib/cli.py:7-20`

```python
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
```

### The verb shape to copy, `scripts/tk_lib/verbs.py:131-143`

```python
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
```

Every verb wears `@cli.verb(name)` and `@cli.guarded`. `guarded`
(`scripts/tk_lib/cli.py:79-128`) turns an exception into one JSON line with a
fixed code. The codes are in `error_codes()` at `cli.py:47-76`. The two this
plan relies on: `ValueError` prints `usage`, `OSError` prints `filesystem`.

### Where profiles live, `scripts/tk_lib/config.py:9` and `:33-76`

```python
ROOT = os.path.expanduser("~/.claude/ticket-workflow")
```

`load_all(root=None)` reads `<root>/projects/*/config.json`, refuses a
non-object with `BadProfile`, and sets `profile["_dir"]`. `resolve` is at
`config.py:115-142` and has three rungs: a url by `match.tracker_urls`
substrings at `:117-120`, a ticket by `match.ticket_patterns` with `re.match`
at `:126-128`, and the working directory by `match.repo_paths` at `:137`, which
calls `_by_cwd` at `:91-105` for prefix matching after `os.path.expanduser`.

### Where the adapter gets built, `scripts/tk_lib/cli.py:131-143`

`adapter_for(profile, values, client=None)` takes a profile **dict**, so a
profile that is not on disk yet still builds an adapter. Each adapter exposes
`whoami()`:

- `scripts/tk_lib/azure.py:137-141` → `{"provider", "id", "name"}`, id is a guid
- `scripts/tk_lib/jira.py:93-95` → id is an `accountId`
- `scripts/tk_lib/github.py:104-106` → id is a `login`

`references/profiles.md:182-185` says which key holds an identity per provider:
`id` for Azure, `accountId` for Jira, `login` for GitHub.

### The Azure guids an `azure-repos` host needs, `scripts/tk_lib/azure.py:388-396`

```python
    def _git(self, path, **query):
        """One pull request route. Every git call comes through here.
        ...
        """
        base = f"{self.org}/{self.project}/_apis/git/repositories/{self.host['repo_id']}"
        query["api-version"] = self.GIT_VERSION
        return f"{base}/{path}?{urllib.parse.urlencode(query, safe='$,/')}"
```

`GIT_VERSION = "7.1-preview.1"` (`azure.py:25`). `self.org` is set at
`azure.py:47` and `self.project` at `:48`, already url-quoted. `_get(url)` at
`:112-113` sends the Authorization header. `doctor._profile_gaps`
(`scripts/tk_lib/doctor.py:106-115`) has two branches per key. `if not
host.get(key)` at `:111` reports a guid that is absent, and `_placeholder` at
`:114` reports one that is still the example value. The first branch is the one
that judges `init`: a profile that omits the guids is incomplete by this repo's
own check.

### The link-rule trap, `scripts/tk_lib/verbs.py:269-273`

```python
    rules = profile.get("link_rules") or {}
    known = [str(name) for name in
             list(rules.get("link_types") or []) + list(rules.get("never_link_types") or [])]
    if not known:
        return wanted
```

`link_types` and `never_link_types` together form the known list, and a type in
neither is refused as a typo. So a profile that names only `never_link_types`
would refuse `Task` as well. A default must name both lists or neither.

### Repo conventions that apply

- One module per topic, standard library only, no third-party imports.
  `scripts/tk` puts `scripts/` on `sys.path` and imports `tk_lib`.
- Logic lives in a module; the verb in `verbs.py` is a thin wrapper.
  `doctor.py` holds the check and `verbs.py:91-103` holds its verb. Copy that
  split.
- A function that holds a judgment carries a comment saying why, in the
  imperative prose the rest of the repo uses. See `config.py:91-97`.
- Tests use `tests/helpers.py`: `FakeHttp` queues responses and
  `assert_drained()` fails when a queued response went unused; `tmp_profile`
  writes a profile under a temp root. No test makes a network call or shells
  out to git.
- Test names are sentences. See `tests/test_doctor.py` and
  `tests/test_config.py` for the file shape to copy.

## Commands you will need

| Purpose    | Command                                                          | Expected on success |
|------------|------------------------------------------------------------------|---------------------|
| Compile    | `python3 -m compileall -q scripts`                                | exit 0, no output   |
| Tests      | `python3 -m unittest discover -s tests -t tests`                   | `OK`                |
| One file   | `(cd tests && python3 -m unittest test_bootstrap)`                 | `OK`                |
| Shell lint | `shellcheck scripts/setup.sh`                                      | exit 0, no output   |

451 tests pass after plan 002. This plan adds a test file, so the count rises.
Record the new number and put it in the done criteria you check.

## Scope

**In scope**:

- `scripts/tk_lib/bootstrap.py` (create)
- `scripts/tk_lib/verbs.py` (add two verbs, nothing else)
- `scripts/tk_lib/cli.py` (add two lines to `USAGE`, nothing else)
- `scripts/tk_lib/azure.py` (add one method, `repo_ids`)
- `tests/test_bootstrap.py` (create)

**Out of scope** (do NOT touch):

- `scripts/tk_lib/config.py` — `resolve` and `load_all` already read what
  `init` writes. Do not add a write path here.
- `scripts/tk_lib/gitcmd.py` — it injects a credential. `detect` must never
  use it. `detect` runs plain, read-only git commands with no environment
  changes.
- `scripts/tk_lib/doctor.py` — no change. Its missing-key branch at `:111` is
  the gate that proves `init` filled the guids.
- `scripts/setup.sh` — the token stages are unchanged by this plan.
- `SKILL.md`, `README.md`, `references/profiles.md` — plan 004 documents these
  verbs. Do not write docs here.
- `notes.md` content beyond the stub in step 4. Filling a project's notes is
  the agent's job at run time, not this code's.

## Git workflow

- Branch: `advisor/003-detect-and-init-verbs`.
- Commit per step: `detect` and its tests, then `build` and `write` and theirs,
  then the verbs, then the Azure method.
- Message style from `git log`: a capitalised imperative sentence, no prefix,
  no trailing period. Examples: `Read every page of the assigned ticket list`,
  `Check the profile fields no api call touches`.
- Do NOT push and do NOT open a pull request.

## Steps

### Step 1: Create `scripts/tk_lib/bootstrap.py` with `detect`

`detect` answers what the working directory knows. It makes no network call, it
reads no token, and it never raises for a directory that is not a git
repository. A field it cannot read is `None`, because a null is the signal that
a question is worth asking, and an exception would make the caller guess.

Module head:

```python
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

from . import cli, config

# git answers on stdout and this module reads it, so every call gets a deadline.
# tk runs as a subprocess under an agent, and a git command that waits for a
# credential prompt would hang the whole run with no output.
GIT_TIMEOUT = 10
```

`detect(cwd=None, runner=None)`:

- `runner` is a callable `(args) -> str | None` that returns stdout stripped,
  or `None` when git failed. Default runs
  `subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=GIT_TIMEOUT)`
  and returns `None` on a non-zero exit or `OSError`. Injecting it keeps the
  tests off git.
- Calls, in order: `["rev-parse", "--show-toplevel"]`,
  `["remote", "get-url", "origin"]`,
  `["symbolic-ref", "--short", "refs/remotes/origin/HEAD"]`,
  `["config", "user.name"]`, `["config", "user.email"]`.
- `symbolic-ref` answers `origin/main`. Strip the leading `origin/`. When it
  answers `None`, leave `base_branch` as `None`.
- Returns:

```python
{"root": str | None,          # absolute path, or the cwd when git says nothing
 "remote": str | None,
 "provider": "github" | "azure" | None,
 "owner": str | None,         # github
 "repo": str | None,          # github and azure
 "org": str | None,           # azure, as https://dev.azure.com/<org>
 "project": str | None,       # azure
 "base_branch": str | None,
 "identity": {"name": str | None, "email": str | None}}
```

`parse_remote(url)` is a separate function, because it is the part with the
edge cases. It must read all six forms:

| Remote | provider | owner | org | project | repo |
|---|---|---|---|---|---|
| `https://github.com/acme/site.git` | github | acme | — | — | site |
| `git@github.com:acme/site.git` | github | acme | — | — | site |
| `https://dev.azure.com/northwind/Contoso%20migration/_git/Contoso.migration` | azure | — | `https://dev.azure.com/northwind` | Contoso migration | Contoso.migration |
| `https://northwind@dev.azure.com/northwind/Proj/_git/Repo` | azure | — | `https://dev.azure.com/northwind` | Proj | Repo |
| `git@ssh.dev.azure.com:v3/northwind/Proj/Repo` | azure | — | `https://dev.azure.com/northwind` | Proj | Repo |
| `https://northwind.visualstudio.com/Proj/_git/Repo` | azure | — | `https://northwind.visualstudio.com` | Proj | Repo |

Rules that matter:

- Strip a trailing `.git` and a trailing `/`.
- Unquote a percent-escaped project name with `urllib.parse.unquote`, because
  `tracker.project` reaches `Azure.__init__`, which quotes it again
  (`azure.py:48`). A double-quoted project name reads as a project that does
  not exist.
- Drop a userinfo part (`northwind@`) before reading the host.
- Anything else answers `{"provider": None}` with every other field `None`. A
  GitLab or Bitbucket remote is not a failure here: it means the host block
  cannot be filled, and the caller says so.

**Verify**: after step 5's tests exist,
`python3 -m unittest discover -s tests -t tests -k Detect` prints `OK`. Until
then:

```bash
python3 -c "
import sys; sys.path.insert(0, 'scripts')
from tk_lib import bootstrap
for u in ['https://github.com/acme/site.git',
          'git@ssh.dev.azure.com:v3/northwind/Proj/Repo',
          'https://northwind.visualstudio.com/Proj/_git/Repo',
          'git@gitlab.com:acme/site.git']:
    print(u, '->', bootstrap.parse_remote(u))"
```

Expected: the first three match the table above, the fourth answers a null
provider.

### Step 2: Add `build` to `bootstrap.py`

`build(slug, tracker, detected, ticket=None, org=None, project=None, site=None, owner=None, repo=None)`
returns the profile dict. It writes nothing and makes no call.

Field by field, and the reason for each default:

- `slug`: as given. It is also the directory name, so `config.load_all` keys
  the profile by it and `--slug` finds it.
- `match.ticket_patterns`: from `ticket`.
  - all digits, length N → `[f"^[0-9]{{{N},}}$"]`. Use N, not a bare `+`, so a
    four digit id does not claim a three digit id from another tracker.
  - `^([A-Z][A-Z0-9]+)-\d+$` → `[f"^{key}-[0-9]+$"]` with the key it matched.
  - anything else, or no ticket → `[]`. An empty list is honest: the project
    then resolves by directory only, and `resolve` says so.
- `match.tracker_urls`: for azure, the org url with its scheme stripped,
  `re.sub(r"^https?://", "", org).rstrip("/")`. That yields
  `dev.azure.com/northwind` for a `dev.azure.com` org and
  `northwind.visualstudio.com` for a legacy one, and both are substrings of the
  tracker urls those two hosts serve. Never hard-code `dev.azure.com`: step 1
  reads a `visualstudio.com` remote, and a profile whose `tracker_urls` names a
  host the tracker never serves matches no url at all. For jira, `[site]`. For
  github, `[f"github.com/{owner}/{repo}"]`. `resolve` matches these as
  substrings (`config.py:117-120`).
- `match.repo_paths`: `[detected["root"] or os.getcwd()]`.
- `tracker` per kind:
  - azure: `{"kind": "azure", "org": org, "project": project, "api_version": "7.1-preview"}`.
    `azure.py:41-46` refuses anything that does not start with `7.1-preview`.
  - jira: `{"kind": "jira", "site": site, "project": project}`.
  - github: `{"kind": "github", "owner": owner, "repo": repo}`.
  - Omit `auth_env`. Every adapter defaults it to the right variable, and plan
    002's error names that variable when it is unset. A written default is one
    more thing to keep in step.
- `host`: from `detected["provider"]`, not from the tracker kind, because a Jira
  tracker beside a GitHub host is a supported pair
  (`references/profiles.md:145-150`).
  - detected github → `{"kind": "github", "owner", "repo", "local_path": root,
    "base_branch": detected or "main", "branch_pattern": "feature/{id}-{slug}",
    "commit_subject": "[{id}] {summary}", "identity": detected identity}`.
  - detected azure **and** tracker azure → `{"kind": "azure-repos", "repo",
    "local_path", "base_branch": detected or "master", "branch_pattern",
    "commit_subject", "identity"}`. `repo_id` and `project_id` are filled by
    the verb in step 4, not here.
  - detected azure and tracker **not** azure → omit the host block entirely.
    `gitcmd._base_url` (`gitcmd.py:67-74`) needs `tracker.org` for an
    `azure-repos` host, and a Jira tracker holds none, so such a profile could
    never push. Report the gap instead of writing a profile that fails later.
  - detected provider `None` → omit the host block.
  - Omit `host.auth_env` for the same reason as the tracker block.
- `buckets`: all four names, every `state` null.

```python
{"fixable-here": {"state": None, "assignee": "self"},
 "owned-elsewhere": {"state": None, "assignee": None},
 "split": {"state": None, "assignee": "self"},
 "needs-clarification": {"state": None, "assignee": None}}
```

  All four must exist, because `tk state --bucket` refuses a name the profile
  does not define (`references/profiles.md:154-156`). Every state is null on
  purpose: a null state leaves the tracker's state alone, and an invented state
  name would be refused by the server or, worse, accepted and wrong. The notes
  stub tells the agent to ask the user for the real names.
- `people`: `build` emits `{"people": {}}`, an empty dict and not an absent
  key. Step 4 then assigns `profile["people"]["self"] = {<key>: <id>}` by
  subscript, and an absent key would raise `KeyError`, which `error_codes` maps
  to `profile`, an error that names a config file problem for a code bug. The
  key is `id` for azure, `accountId` for jira, `login` for github.
- `link_rules`: for an azure tracker only,
  `{"link_types": ["Task"], "never_link_types": ["Bug"]}`. Both lists, because
  `verbs._link_type` refuses a type that neither list names. A merge completes
  every linked Azure work item, so a Bug must be refused
  (`references/profiles.md:210-214`). Omit the block for jira and github, where
  a missing block means the type is taken as spelled.
  Say this in the notes stub, because it is a real narrowing: those two lists
  together are the whole set `_link_type` accepts, so `User Story`, `Feature`,
  and `Product Backlog Item` are all refused as typos on a freshly written
  azure profile. The refusal names the type and lists the known ones, so it is
  loud and one edit fixes it. That beats the alternative, which is guessing a
  type list for a board this code has never seen.
- Omit `deploy_gate`, `preview`, and `notes`. `tk state --gate` refuses a
  profile with no `deploy_gate`, which is the honest state until the user names
  the word and the state. `notes` defaults to `notes.md`.

Every value that is still `None` after `build` is a required field nobody
supplied. `build` raises `ValueError` naming the flag, so `guarded` prints
`usage`:

```python
    missing = [flag for flag, value in required if not value]
    if missing:
        raise ValueError(
            f"tracker {tracker} needs {', '.join(missing)}. "
            "tk detect could not read it from the git remote, so pass it.")
```

Required per kind: azure needs `--org` and `--project`; jira needs `--site` and
`--project`; github needs `--owner` and `--repo`.

**Verify**: `python3 -m unittest discover -s tests -t tests -k Build` prints
`OK` once step 5 lands.

### Step 3: Add `write` to `bootstrap.py`

`write(profile, notes, root=None)`:

- `root` defaults to `config.ROOT`, so the tests point it at a temp directory.
- Target `os.path.join(root, "projects", profile["slug"])`.
- Refuse an existing `config.json` with
  `ValueError(f"profile {slug} already exists at {path}. Edit it, or pass --slug with another name.")`.
  A refusal beats an overwrite: the file may hold a human's notes and states.
- `os.makedirs(target, exist_ok=True)`, then write `config.json` as
  `json.dumps(profile, indent=2, sort_keys=True) + "\n"` and `notes.md` as the
  stub text.
- Return `{"slug", "config_path", "notes_path"}`.
- Do not set file modes. The profile holds no secret: `references/profiles.md:17-19`
  says a secret is named in `config.json` and valued in `secrets.env`.

`notes_stub(profile, detected)` returns the stub. Six headings, from the
outline at `references/profiles.md:226-237`, each with one TODO line naming what
to fill and why it matters. Include the two facts the run already knows: the
repo path and the base branch. State plainly that the verify gate is the field
that costs a run when it is empty.

**Verify**: `python3 -m unittest discover -s tests -t tests -k Write` prints
`OK` once step 5 lands.

### Step 4: Register the two verbs in `verbs.py`, and `Azure.repo_ids`

Add to `scripts/tk_lib/azure.py`, beside `repo_check`:

```python
    def repo_ids(self, name):
        """The two guids an Azure Repos host needs, from the repository name.

        Every Azure git route is keyed by host.repo_id, not by the repository
        name (see _git). A profile written from a remote holds the name, so one
        call here turns it into the two guids doctor checks for.
        """
        url = (f"{self.org}/{self.project}/_apis/git/repositories/"
               f"{urllib.parse.quote(name)}?api-version={self.GIT_VERSION}")
        data = self._get(url)
        return {"repo_id": data.get("id"),
                "project_id": (data.get("project") or {}).get("id")}
```

Add to `scripts/tk_lib/verbs.py`, after the `_doctor` verb:

```python
@cli.verb("detect")
@cli.guarded
def _detect(argv):
    """What the working directory knows. It reads no token and no profile."""
    parser = argparse.ArgumentParser(prog="tk detect")
    parser.add_argument("--path")
    args = parser.parse_args(argv)
    cli.emit(bootstrap.detect(args.path))
    return 0
```

`detect` returns 0 even when `provider` is null. A directory with no remote is
a fact the caller acts on, not a failure.

```python
@cli.verb("init")
@cli.guarded
def _init(argv):
    parser = argparse.ArgumentParser(prog="tk init")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--tracker", required=True,
                        choices=("azure", "jira", "github"))
    parser.add_argument("--ticket")
    parser.add_argument("--org")
    parser.add_argument("--project")
    parser.add_argument("--site")
    parser.add_argument("--owner")
    parser.add_argument("--repo")
    parser.add_argument("--path")
    args = parser.parse_args(argv)
    cli.emit(bootstrap.init(args, secrets.load()))
    return 0
```

`bootstrap.init(args, values, client=None, root=None)` does the ordering, and
the order is the point:

1. `detected = detect(args.path)`.
2. Fill each unset argument from `detected`: azure `org`/`project`, github
   `owner`/`repo`. A flag the caller passed always wins.
3. `profile = build(...)`.
4. `adapter = cli.adapter_for(profile, values, client)`, then `who = adapter.whoami()`.
   Put the id under the provider's own key in `profile["people"]["self"]`.
   Refuse to write when the id is null or when `doctor._placeholder` reports it:
   `ValueError` naming the provider. `_profile_gaps` (`doctor.py:96-100`) treats
   an unusable `people.self` exactly as it treats a missing guid, so writing one
   produces a profile that this repo's own check calls broken. A 200 answer with
   no id is a real case on a provider that returns an empty body.
5. When the host kind is `azure-repos`, call `adapter.repo_ids(host["repo"])`
   and merge the two guids into the host block. Refuse to write when either is
   null, with the same shape of error: `ValueError` naming the repository,
   because `doctor` would report the gap anyway and a half-filled host block
   fails at push time.
6. `write(profile, notes_stub(profile, detected), root)` **last**.
7. Emit `{"slug", "config_path", "notes_path", "self": who, "host": kind or None, "next": [...]}`.

Writing last is load-bearing. A missing token raises at step 4, and the machine
is then left with no profile at all, so the agent mints the token and runs the
same command again. A profile written before the call would leave a broken
profile that `doctor` then reports for ever.

`next` is the list of gaps a human must still close, one sentence each. Include
at least: the verify gate in `notes.md` is empty; the four buckets hold no
states; no `deploy_gate`; and, when the host block was omitted, the reason.

Add the import to the `verbs.py` import line and two rows to `cli.USAGE`:

```
  detect                     what the working directory knows
  init --slug S --tracker T  write a project profile
```

Put `detect` and `init` after `doctor` in `USAGE`, so the order matches a first
run.

**Verify**:

```bash
python3 scripts/tk 2>&1 | grep -c "detect\|init"
```

Expected: `2`. Then `python3 scripts/tk detect` in this repository prints JSON
with `"provider": "github"` and this repository's `owner` and `repo`.

### Step 5: Write `tests/test_bootstrap.py`

Model the file on `tests/test_doctor.py` (a class per topic, `FakeHttp` for the
network) and `tests/test_config.py` (a temp root for profiles). Import
`helpers` first, then `from tk_lib import bootstrap`.

A fake git runner replaces git:

```python
def runner_for(answers):
    """A git runner that answers by subcommand. None means git failed."""
    def run(args):
        return answers.get(" ".join(args))
    return run
```

Cases, one test each:

`class TestParseRemote`
1. github https, with and without `.git`
2. github ssh
3. azure https
4. azure https with a percent-escaped project, and the answer is unquoted
5. azure https with a userinfo part
6. azure ssh `v3`
7. `visualstudio.com`
8. a gitlab remote answers a null provider and no other field

`class TestDetect`
9. a full answer set fills every field
10. no `origin` remote leaves `provider` and `remote` null and still answers
    the identity
11. a missing `symbolic-ref` leaves `base_branch` null
12. `origin/main` becomes `main`
13. a directory outside a repository answers nulls and does not raise

`class TestBuild`
14. `5438` becomes `^[0-9]{4,}$`, and `re.match` on it matches `5438` and not `543`
15. `DIST-4471` becomes `^DIST-[0-9]+$`
16. no ticket gives an empty pattern list
17. all four bucket names are present and every state is null
18. an azure tracker gets `api_version` starting `7.1-preview`, and
    `cli.adapter_for` builds an `Azure` from the result without raising
19. an azure tracker gets both link lists; a github tracker gets no
    `link_rules` block
20. a jira tracker beside an azure remote gets no host block
21. a github remote beside a jira tracker gets a github host block
22. a missing required field raises `ValueError` naming the flag

`class TestWrite`
23. the written `config.json` reads back through `config.load_all` with the
    slug as its key
24. `config.resolve("5438", profiles)` picks the written slug
25. `config.resolve(None, profiles, cwd=<repo path>)` picks it by directory
26. a second `write` for the same slug raises `ValueError` and leaves the first
    file byte-for-byte unchanged

`class TestInit`
27. a whoami failure writes nothing: assert the project directory does not
    exist afterwards
28. an `azure-repos` host gets both guids from one call, and
    `FakeHttp.assert_drained()` passes
29. `people.self` holds `login` for github, `accountId` for jira, `id` for
    azure
30. `doctor._profile_gaps(profile)` returns an empty list for the written azure
    profile. Scope this correctly in the test's comment: `_profile_gaps` checks
    three things only, which are every `people` role resolving to a usable and
    non-placeholder id, every bucket `assignee` naming a role the `people` block
    holds, and the two guids on an `azure-repos` host. It reads no `slug`, no
    `match`, no `tracker`, and no bucket `state`, and `_profile_gaps({})`
    returns `[]` as well. So this case proves the three links `build` and `init`
    have to get right between blocks, and it proves nothing about the rest.
31. `cli.adapter_for(profile, {"AZDO_PAT": "x" * 12})` builds an `Azure` from
    the written azure profile without raising. That is the assertion that covers
    what case 30 does not: it runs the `api_version` guard at `azure.py:41-46`
    and the `_need("org")` and `_need("project")` checks at `:47-48`, so a
    tracker block that `build` filled wrongly fails here.
32. `_placeholder` (`doctor.py:72-79`) refuses any id whose characters are all
    the same after hyphens are removed, and `tests/test_doctor.py:248` uses
    `33333333-3333-3333-3333-333333333333` as its identity fixture. Do not copy
    that shape into the fake `whoami` for case 30, or the case fails for a
    reason that has nothing to do with `init`. Use a mixed-digit guid. Write
    this case as the guard: a `whoami` id of all one character makes
    `_profile_gaps` report a placeholder, so `init` refuses to write it.

**Verify**: `python3 -m unittest discover -s tests -t tests` prints `OK`.
Record the new total.

### Step 6: Prove the flow end to end against a temp HOME

No network, so run it against the GitHub tracker of this repository with a
queued response. If you have a real `GH_TOKEN` on the machine, run the real
thing instead and delete the profile afterwards:

```bash
TMPHOME="$(mktemp -d)"
mkdir -p "$TMPHOME/.claude/ticket-workflow"
cp ~/.claude/ticket-workflow/secrets.env "$TMPHOME/.claude/ticket-workflow/" 2>/dev/null \
  && chmod 600 "$TMPHOME/.claude/ticket-workflow/secrets.env"
HOME="$TMPHOME" python3 scripts/tk detect
HOME="$TMPHOME" python3 scripts/tk init --slug scratch --tracker github --ticket 12
HOME="$TMPHOME" python3 scripts/tk resolve 12
cat "$TMPHOME/.claude/ticket-workflow/projects/scratch/config.json"
rm -rf "$TMPHOME"
```

**Verify**, and take one branch, not either:

- With a usable `GH_TOKEN` in the copied `secrets.env`: `init` prints a
  `config_path`, `resolve` answers
  `{"slug": "scratch", "tracker": "github", "ticket": "12", ...}` with exit 0,
  and the JSON holds four buckets, a `people.self.login`, and a github host
  block.
- With no token: `init` answers
  `{"error": "secrets", "message": "GH_TOKEN is not set in secrets.env. Run scripts/setup.sh github to add it."}`
  and `test ! -d "$TMPHOME/.claude/ticket-workflow/projects/scratch"` passes.
  This branch proves the write-last ordering and nothing else, because the run
  stops before `build`. Say so in your report, and then run the tests in step 5
  as the substitute for the first branch. Do not claim the flow is proven end to
  end from this branch alone.

### Step 7: Run the full gate

```bash
python3 -m compileall -q scripts
python3 -m unittest discover -s tests -t tests
shellcheck scripts/setup.sh
```

## Test plan

`tests/test_bootstrap.py` is new and holds the 32 cases in step 5, grouped in
five classes. Structural pattern: `tests/test_doctor.py` for `FakeHttp` and the
class layout, `tests/test_config.py` for a temp profile root.

Three cases carry the most weight, so do not drop them under time pressure:

- case 27, a failed `whoami` writes nothing. It is the ordering guarantee the
  whole retry story rests on.
- case 31, the adapter builds from the written profile. It is the only case that
  judges the tracker block `build` produced, using this repo's own constructor
  guards rather than a hand-written expectation.
- case 30 plus case 32 together, the three cross-block links, with the
  placeholder trap pinned so the case cannot pass for the wrong reason.

No existing test should need an edit. If one does, STOP and report which.

## Done criteria

ALL must hold:

- [ ] `python3 -m unittest discover -s tests -t tests` prints `OK` with 483
      tests: 451 after plan 002, plus the 32 cases in step 5
- [ ] `grep -c "    def test_" tests/test_bootstrap.py` prints `32`
- [ ] `(cd tests && python3 -m unittest test_bootstrap)` prints `OK` with 32
      tests. Do not use `-k Bootstrap`: unittest matches that pattern against
      `module.Class.method`, no name holds a capital `Bootstrap`, and the run
      answers `NO TESTS RAN` with exit 5
- [ ] `python3 scripts/tk detect` in this repository prints
      `"provider": "github"` with this repo's owner and name
- [ ] `python3 scripts/tk init` with no arguments prints
      `{"error": "usage", ...}` and exits 1
- [ ] The step 6 run either writes a profile that `tk resolve` then matches, or
      fails with `secrets` and writes no directory
- [ ] `grep -n "detect\|init" scripts/tk_lib/cli.py` shows both rows in `USAGE`
- [ ] `python3 -m compileall -q scripts` exits 0
- [ ] `git status --short` lists only the five files in Scope
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- `scripts/tk_lib/azure.py:388-396` no longer keys git routes on
  `host['repo_id']`. The `repo_ids` method exists to fill that field, and a
  different key means a different design.
- `verbs._link_type` no longer combines `link_types` and `never_link_types`
  into one known list. The azure `link_rules` default depends on it.
- Any existing test fails after any step.
- `cli.adapter_for` cannot build an adapter from a profile dict that is not on
  disk. Step 4 depends on that.
- Filling `people.self` needs more than one API call per provider. One call is
  the budget; a second means the design is wrong for that provider, so report
  it rather than adding calls.
- A provider needs a field this plan does not name, so a written profile still
  fails `doctor`. Report the field.

## Maintenance notes

- `detect` is deliberately blind to GitLab and Bitbucket. Adding one means a
  `parse_remote` entry and a host kind that `gitcmd.TOKEN_ENV` knows. Do not add
  the remote pattern without the host support.
- Every default in `build` is either a value the machine read or a null. The
  rule to keep: never invent a tracker state name, an assignee, or a deploy
  gate. Those three are the ones a wrong guess writes to a real ticket.
- A bucket with a null `state` is supported, not a crash: `cli.apply_bucket`
  guards with `if bucket.get("state"):`, so `None` never reaches an adapter's
  `state` method, and `references/profiles.md:158` documents it. One consequence
  is worth knowing before someone calls it a bug. `tk state --bucket
  owned-elsewhere` on a freshly written profile still pays a full
  `adapter.show()` call at `verbs.py:179` to read the item type, then answers
  `ok: true` and exits 0 having written no state. That is correct for a profile
  whose routing travels in the comment, and it is the reason plan 004 tells the
  agent to ask for the board's own state names the first time a bucket needs one.
- A reviewer should scrutinise the ordering in `bootstrap.init`. Writing the
  profile before `whoami` would leave a broken profile on every failed first
  run, and the failure would look like a bug in `doctor`.
- Deferred: `init` writes one project at a time and asks nothing. The question
  flow, which asks the user for the tracker and runs the token stage, is prose
  in `SKILL.md` and belongs to plan 004.
