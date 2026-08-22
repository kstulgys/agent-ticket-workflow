# Writing a project profile

A profile is one directory: `~/.claude/ticket-workflow/projects/<slug>/`.

| File | Holds | Read by |
|---|---|---|
| `config.json` | what an API call needs | `tk` |
| `notes.md` | what a decision needs | the agent, after the project resolves |
| anything else | deep reference, reached from `notes.md` | the agent, on demand |

Two rules keep the pair honest.

A fact lives in one file. If `tk` needs it to build a request, it goes in
`config.json`. If you need it to decide what to change, it goes in `notes.md`.
Nothing belongs in both.

A secret never appears in either file. `config.json` names the environment
variable, and `secrets.env` holds the value. Namespace a project secret by slug,
for example `NORTHWIND_BYPASS_HILLCREST`.

You read three keys from `config.json`: `host.base_branch`,
`host.branch_pattern`, and `host.commit_subject`. `tk` reads every other key,
with one exception: `preview.bypass_env`, which `verification.md` reads on a
protected deployment. `tk` reads no key this page leaves out, so an invented key
does nothing.

## An Azure profile

```json
{
  "slug": "northwind",
  "match": {
    "ticket_patterns": ["^[0-9]{5}$"],
    "tracker_urls": ["dev.azure.com/northwind"],
    "repo_paths": ["~/Repositories/Contoso-migration"]
  },
  "tracker": {
    "kind": "azure",
    "org": "https://dev.azure.com/northwind",
    "project": "Contoso migration",
    "api_version": "7.1-preview",
    "auth_env": { "token": "AZDO_PAT" }
  },
  "host": {
    "kind": "azure-repos",
    "repo": "Contoso.migration",
    "repo_id": "<guid>",
    "project_id": "<guid>",
    "local_path": "~/Repositories/Contoso-migration",
    "base_branch": "master",
    "branch_pattern": "feature/{id}-{slug}",
    "commit_subject": "[{id}] {area} | {summary}",
    "identity": { "name": "Example.Dev", "email": "dev@example.com" },
    "auth_env": { "token": "AZDO_PAT" }
  },
  "buckets": {
    "fixable-here": {
      "state": { "Task": "In Progress", "Bug": "Committed" }, "assignee": "self"
    },
    "owned-elsewhere": { "state": null, "assignee": "backend" },
    "split": {
      "state": { "Task": "In Progress", "Bug": "Committed" }, "assignee": "backend"
    },
    "needs-clarification": { "state": null, "assignee": null }
  },
  "people": {
    "self": { "id": "<guid>" },
    "backend": { "id": "<guid>" },
    "reviewer": { "id": "<guid>" }
  },
  "link_rules": {
    "link_types": ["Task"],
    "never_link_types": ["Bug", "Product Backlog Item"]
  },
  "deploy_gate": { "state": { "Bug": "Ready for Test" } },
  "preview": { "bypass_env": "NORTHWIND_BYPASS_{BRAND}" },
  "notes": "notes.md"
}
```

## Matching

| Key | Holds | Default |
|---|---|---|
| `slug` | the project name. Write the directory name here, because `--slug` takes that one | none |
| `match.ticket_patterns` | regular expressions, matched from the start of the id or key | none |
| `match.tracker_urls` | substrings of a tracker url | none |
| `match.repo_paths` | directories this project owns. `~` expands | none |
| `notes` | the notes file name | `notes.md` |
| `preview.bypass_env` | the variable that holds the bypass value for a protected deployment. You expand a `{BRAND}` placeholder with the brand the ticket names, in upper case, so `NORTHWIND_BYPASS_{BRAND}` becomes `NORTHWIND_BYPASS_HILLCREST` | none |

## The tracker block

`tracker.kind` picks the adapter, and it decides the rest of the block.

| `kind` | Also needs | Token variables |
|---|---|---|
| `azure` | `org`, `project`, `api_version` | `auth_env.token`, default `AZDO_PAT` |
| `jira` | `site`, `project` | `auth_env.email` default `JIRA_EMAIL`, `auth_env.token` default `JIRA_TOKEN` |
| `github` | `owner`, `repo` | `auth_env.token`, default `GH_TOKEN` |

`api_version` must start with `7.1-preview`. A point release such as
`7.1-preview.3` is fine, and a bare `7.1` is refused. Azure Boards answers some
routes with a preview error under any other value.

## The host block

The host owns the pull requests, and it is not always the tracker. The globex
profile holds a Jira tracker beside a GitHub host. Write this block for every
project. `tk git` reads the working copy, the credential, and the commit
identity from it, and `host.kind` has no fallback there. Step 6 runs four `tk
git` commands, and a profile that names no `host.kind` answers none of them. A
GitHub tracker with no host block can still open a pull request, because it
holds the owner and the repository already.

| Key | Holds | Kind | Default |
|---|---|---|---|
| `kind` | `azure-repos` or `github`. The spelling `azure` is refused | both | the tracker kind, for a pull request only |
| `local_path` | the working copy `tk git` runs in | both | `.` |
| `base_branch` | the branch a pull request targets | both | `master`, or `main` on GitHub |
| `branch_pattern` | your pattern, such as `feature/{id}-{slug}` | both | none |
| `commit_subject` | your pattern, such as `[{id}] {area} \| {summary}` | both | none |
| `identity.name`, `identity.email` | the author `tk git` commits as. On a GitHub host `identity.name` is also the login `tk pr threads` filters on | both | the git config on disk |
| `auth_env.token` | the token variable `tk git` sends. Name the variable the tracker block names for the same provider | both | `AZDO_PAT`, or `GH_TOKEN` on GitHub |
| `auth_env.user` | the variable that holds the user half of the credential, never the user itself | both | the user is empty, or `x-access-token` on GitHub |
| `repo` | the repository name in the pull request url | azure-repos | none |
| `repo_id`, `project_id` | the two guids every Azure git route needs | azure-repos | none |
| `owner`, `repo` | the GitHub repository | github | none |
| `screenshot_branch` | the branch `tk pr attach` commits an image to | github | `pr-screenshots` |
| `people.<role>` | the host's own identity per role, read like the tracker `people` block. Needed only when the host is another provider than the tracker | both | the tracker `people` block, on one provider only |

An `azure-repos` host also needs `tracker.org`. `tk git` scopes the credential
to that url, so a submodule fetch cannot hand the token to another server.

`tk git` reads the credential from this block. An API call reads it from the
block that names its own provider. The GitHub adapter takes the block whose
`kind` is `github`. An `azure-repos` host takes the tracker block, because that
host also needs `tracker.org` and `tracker.project`, so it always sits beside
its own Azure tracker.

So one provider names one variable in both blocks. Two variables for one
provider split the credential: `tk git` pushes with one token and `tk pr
create` writes with the other, and only one of the two fails when a token dies.

A Jira tracker beside a GitHub host is the case a block order read gets wrong.
The GitHub adapter reads `owner`, `repo`, and `auth_env` from the block whose
`kind` is `github`, so the Jira token stays out of a GitHub call.
That block order holds for identities too. A host verb resolves a role against
the host, so a Jira account id never travels to GitHub as a reviewer or as the
author of a thread. See People below.

## Buckets

`tk state --bucket <name>` applies the bucket's `state` and `assignee`
together. A name the profile does not define is refused, so write all four:
`fixable-here`, `owned-elsewhere`, `split`, and `needs-clarification`.

A `state` of `null` leaves the state alone, and so does an absent one. An
`assignee` role the `people` block does not hold is refused before the write,
because a null assignee clears the field.

`state` takes a different value per tracker.

| Tracker | `state` |
|---|---|
| Azure | a map from work item type to state name, or one name for every type |
| Jira | one status name, or the name of the transition that reaches it. A map from issue type also works |
| GitHub | a label operation, or a map from item type to one operation |

A GitHub label operation reads
`{"add_labels": ["in progress"], "remove_labels": ["triage"], "closed": false}`.
A GitHub issue holds no type field, so the type in such a map is the issue's
first label.

A tag reaches a tracker on GitHub alone, through the bucket's `state` label
operation. Nothing writes a tag on Azure or Jira, so the routing there travels
in the comment. A bucket takes no other key: `tk` reads `state` and `assignee`
and nothing else.

## People and link rules

A role names one identity. `tk` reads `id`, then `accountId`, then `login`, and
it takes the first one it finds. Azure holds a guid under `id`, Jira an account
id under `accountId`, and GitHub a login under `login`. A display name is not an
identity, because two people can share one.

`--owner` names a role on the tracker, and it reads the `people` block.

`--reviewer` and `tk pr threads` name a role on the host, and a host verb
resolves it against the host in this order: `host.people[<role>]` first, then
the `people` block, and that step only when the host and the tracker are one
provider, then `host.identity.name` for the role `self`. Two kinds can be one
provider: `azure-repos` is the host spelling of `azure`. An account identity
therefore always beats `identity.name`, which is a git author name.

So a GitHub host beside a Jira tracker needs `host.identity.name` for `self`,
and `host.people` for any other role a pull request names. The `people` block
there holds Jira account ids, and a Jira account id never equals a GitHub login:
it filters no thread, and as a reviewer it names nobody. An Azure host beside an
Azure tracker needs neither, because the account id in `people` is the identity
that host reads.

Every profile must resolve one of those three for `self`. `tk pr threads`
refuses a profile that resolves none, because a thread the agent wrote could
not be told from a reviewer's, and the verb would answer with its own comments.

`--reviewer` also takes a name the host reads already, such as a GitHub login.
A role the profile does not hold goes to the host as you typed it.

`--link <id>:<type>` compares the type against `link_rules`. A type neither list
names is refused as a typo, and a profile with no `link_rules` takes the type as
you spell it. A merge completes every linked Azure work item, so a bug belongs
in `never_link_types`, and `tk pr create` reports it under `refused`. Spell each
type once, because two spellings of one type are refused as well.

A GitHub host links by issue number, through a phrase in the pull request body.
So an id that is not a number links nothing there. `tk pr create` writes no
phrase for it and reports it under `unlinked`. On the globex profile the tracker
key is a Jira key, so link the GitHub issue number, or link nothing and say so
in the comment.

`tk state --gate` writes `deploy_gate.state`, and it refuses a profile that
holds none. `tk` tests no trigger for that write, so the word that releases it
is prose: name it in `notes.md`.

## notes.md outline

Prose, written for the agent, one file per project.

1. Repo layout, and which app serves the affected area.
2. The verify gate: the exact commands in order, and what a clean run prints.
3. Conventions that bite. Repo lint rules, when to use the language server.
4. Code areas by name. Where the forms, config, and flows live.
5. Project traps. Which portal, which head app, which env var decides. The word
   that releases the deploy gate, when it is not the user saying the build is on
   the test environment.
6. Deep references, by relative path.

## Checking a new profile

```bash
T=~/.claude/skills/ticket-workflow/scripts/tk
TICKET=59644               # a real ticket id or key in this project
$T doctor                  # the token reaches this project, repo included
$T resolve "$TICKET"       # the match rules pick this slug
$T show "$TICKET"          # the shape carries the description and the comments
```

A bare numeric `ticket_patterns` entry collides with every other numeric
tracker. That is expected. `tk resolve` exits 2 and asks, or `repo_paths` breaks
the tie from the working directory.
