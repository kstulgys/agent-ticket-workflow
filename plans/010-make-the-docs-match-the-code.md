# Plan 010: Make the documentation match what the code does

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 00d0bb2..HEAD -- README.md SKILL.md references examples scripts`
> If any in-scope file changed since this plan was written, compare the "Current
> state" quotes against the live files before you proceed. On a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: `plans/005-fix-the-setup-wizard.md`,
  `plans/008-protect-the-jira-session-file.md`,
  `plans/009-close-the-scrub-gaps.md`. Each changes behaviour this plan
  describes, and 009 edits a different paragraph of the same README.
- **Category**: docs
- **Planned at**: commit `00d0bb2`, 2026-08-23

## Why this matters

In this repository the prose is the product. `SKILL.md` is the routine an agent
executes, so a wrong sentence is wrong behaviour, and `README.md` is the first
thing a person reads before they install anything. Five statements have drifted
from the code. Each one is small and each one costs a real run:

- The stated setup steps leave the user one file short, so phase 1 of the
  routine opens a `notes.md` that was never created.
- Nothing says the `slug` value must equal the directory name, so a copied
  profile answers to two names in different messages.
- The requirements claim no dependencies, which the documented Jira fallback
  contradicts.
- The verb list omits a required argument for `tk git`.
- Step 2 tells the agent to read four keys that two of the three trackers never
  fill, and the shape cannot say the difference, because a missing list and an
  empty list are both `[]`.

## Current state

Quoted from the live files.

```markdown
<!-- README.md:162-167 -->
## Requirements

- Python 3.11 or later. Standard library only, no dependencies, no virtualenv.
- `git`.
- The Superpowers plugin. `scripts/setup.sh` installs it.
- `curl`, for the setup wizard only.
```

`scripts/jira-cookies.py:27-28` imports `secretstorage` and `cryptography`, and
`references/jira-cookie-fallback.md` names both, so the reference page is right
and the README is the drifted one.

The project setup section copies one file:

```bash
mkdir -p ~/.claude/ticket-workflow/projects/myproject
cp examples/projects/northwind/config.json \
  ~/.claude/ticket-workflow/projects/myproject/
```

Against that, `SKILL.md:116` requires both files for a new project, and
`SKILL.md:102-104` tells the agent to read `notes.md` before touching code.
`references/profiles.md:8-9` states the split: `config.json` holds what an API
call needs, `notes.md` holds what a decision needs.

The slug rule lives only in the reference page. `references/profiles.md:89`
documents the `notes` key, and the profile table documents `slug` as the
directory name. The code keys profiles by directory name and never reads the
field:

```python
# scripts/tk_lib/config.py:38-60
    for slug in sorted(os.listdir(base)):
        directory = os.path.join(base, slug)
        ...
        profile["_dir"] = directory
        profiles[slug] = profile
```

So a copied `"slug": "northwind"` survives into every message built from
`profile.get("slug")`, for example `scripts/tk_lib/cli.py:230` and
`scripts/tk_lib/gitcmd.py:28`.

The verb list drops a required argument. `README.md` writes `tk git -- <args>`,
while the CLI requires the slug and its own usage text gets it right:

```python
# scripts/tk_lib/cli.py:18
  git --slug S -- <args>     run git with the credential injected
```

```python
# scripts/tk_lib/verbs.py:342
    parser.add_argument("--slug", required=True)
```

Per-tracker coverage of the ticket shape, read from the three adapters:

| Key | Azure | Jira | GitHub |
|---|---|---|---|
| `parent` | yes, `azure.py:205-217` | yes, `jira.py:157` | no |
| `children` | yes, `azure.py:213-215` | no | no |
| `links` | yes, `azure.py:205-217` | no | no |
| `attachments` | yes, `azure.py:226-240` | yes, `jira.py:168-184` | no, `github.py:126-133` says why |

`shape.ticket` fills every list key with `[]`, so an unsupported key and an empty
one look the same:

```python
# scripts/tk_lib/shape.py:19-23
def ticket(**fields):
    out = {key: fields.get(key) for key in KEYS}
    for key in LIST_KEYS:
        out[key] = list(fields.get(key) or [])
    return out
```

The `notes.md` outline to follow when writing the two examples:

```markdown
<!-- references/profiles.md:226-237 -->
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
```

Writing rules for this repository, which this plan must follow: short sentences,
one idea per sentence, active voice, no em dashes, sentence case headings. Match
the surrounding text.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Tests | `python3 -m unittest discover -s tests -t tests` | ends with `OK` |
| Line width | `awk 'length>80 {print FILENAME":"NR}' README.md SKILL.md` | no output |
| Verb drift | `python3 -c "import sys; sys.path.insert(0,'scripts'); from tk_lib import cli; print(cli.USAGE)"` | prints the usage text to compare against the README |

The repository wraps prose at 80 columns. Keep it.

## Scope

**In scope**:
- `README.md` (Requirements, Set up a project, Verbs)
- `SKILL.md` (step 2 only)
- `examples/projects/northwind/notes.md` (create)
- `examples/projects/globex/notes.md` (create)

**Out of scope** (do NOT touch):
- The README paragraph about tokens at lines 150 to 152. Plan 009 owns it.
- `scripts/tk_lib/shape.py`. Do not make an unsupported key `null`. That would
  change the answer shape, and `tests/test_azure_read.py` asserts the key set
  exactly. Documenting the coverage is the cheap half, and it is the half that
  changes agent behaviour today.
- Any adapter. Adding `children` to Jira, or attachments to GitHub, is a feature,
  not a documentation fix.
- The use cases section and the "What it never does" section. They are accurate.

## Git workflow

- Branch: `advisor/010-make-the-docs-match-the-code`
- Commit per step. Suggested first message:
  `Name the dependency the jira fallback needs`
- Do NOT push and do NOT open a pull request unless the operator asks.

## Steps

### Step 1: Scope the dependency claim to `tk`

In the README Requirements list, keep the first bullet's meaning for `tk` and add
the exception. Target text:

```markdown
- Python 3.11 or later. `tk` itself is standard library only, with no
  dependencies and no virtualenv.
- `git`.
- The Superpowers plugin. `scripts/setup.sh` installs it.
- `curl`, for the setup wizard only.
- `secretstorage` and `cryptography`, for `scripts/jira-cookies.py` only. That
  script is the fallback for an organization that blocks Jira API tokens, and
  `tk` never imports it. See `references/jira-cookie-fallback.md`.
```

**Verify**: `grep -c "secretstorage" README.md` → `1`

### Step 2: Make the project setup produce a working profile

Rewrite the copy block so it takes both files, and add one sentence naming the
`slug` edit. Target shape:

```bash
mkdir -p ~/.claude/ticket-workflow/projects/myproject
cp examples/projects/northwind/config.json \
  examples/projects/northwind/notes.md \
  ~/.claude/ticket-workflow/projects/myproject/
```

Then, in prose under the block:

- The directory name is the project slug. `tk` keys every profile by it.
- Change the `slug` field in `config.json` to that same name. Messages built
  from the profile print that field, so a stale value names a project you do not
  have.
- `notes.md` holds what a decision needs. Phase 1 of the routine reads it before
  it touches code, so an empty one costs a run.

If plan 005 has landed, add one line naming `AZDO_ORG` and `JIRA_SITE` as the
non-interactive path through the wizard, in the Install section beside
`scripts/setup.sh`. Check `scripts/setup.sh` for the exact variable names before
you write them.

**Verify**: `grep -c "notes.md" README.md` → at least `2`

### Step 3: Write the two example notes files

Create `examples/projects/northwind/notes.md` and
`examples/projects/globex/notes.md`, each following the six point outline quoted
above. Keep them short, about 20 to 30 lines. They are examples, so every value
must be obviously fictional and must match the example profile beside it:
northwind is an Azure tracker with an Azure Repos host, globex is a Jira tracker
with a GitHub host.

Write the verify gate section with a real shape, for example a lint command and
a build command in order, and say what a clean run prints. That section is the
one an agent reads every run, so a vague example teaches the wrong habit.

For globex, use point 5 to show a deploy gate word, because
`references/profiles.md:222-224` states that the word which releases the gate
lives in `notes.md`.

**Verify**: `awk 'length>80 {print FILENAME":"NR}' examples/projects/*/notes.md`
→ no output

### Step 4: Correct the verb list

In the README verbs block, change the `tk git` line to match `cli.USAGE`:

```
tk git --slug S -- <args>     git with the credential in the environment
```

Compare the whole block against the usage text with the command in the table
above. Correct any other line that disagrees, and report what you changed.

**Verify**: `grep -c "tk git --slug" README.md` → `1`

### Step 5: State which tracker fills which key

In `SKILL.md` step 2, the bullets about attachments and about `parent` and
`children` are written for every tracker. Add the coverage, in one clause each,
using the table in "Current state" as the source. Keep the existing instruction:
where a tracker does fill the key, the agent must still read it.

Then add one sentence to that step saying an empty list can mean the tracker does
not carry that key at all, so an empty `children` on Jira or GitHub is not
evidence that no child spec exists. Point the reader at the parent ticket in the
web UI for those two trackers.

In the README verb line for `tk show`, replace "the ticket, its comments and its
attachments" with wording that does not promise attachments on every tracker.

**Verify**: `grep -c "children" SKILL.md` → at least `2`
**Verify**: `awk 'length>80 {print FILENAME":"NR}' README.md SKILL.md` → no output

## Test plan

No automated test. This plan changes prose and adds two example files. The gates
are the line width check, the grep counts in each step, and one read of the
finished sections against the code excerpts quoted above.

The Python suite must stay green, because no Python changes:
`python3 -m unittest discover -s tests -t tests` → ends `OK`.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -c "secretstorage" README.md` returns `1`
- [ ] `grep -c "tk git --slug" README.md` returns `1`
- [ ] `test -f examples/projects/northwind/notes.md` and
      `test -f examples/projects/globex/notes.md` both succeed
- [ ] `grep -c "notes.md" README.md` returns at least `2`
- [ ] `awk 'length>80 {print FILENAME":"NR}' README.md SKILL.md examples/projects/*/notes.md` prints nothing
- [ ] `grep -c "No dependencies\|no dependencies, no virtualenv" README.md` returns `0` for the old absolute claim
- [ ] `python3 -m unittest discover -s tests -t tests` exits 0
- [ ] `git status --porcelain` lists only in-scope files
- [ ] the status row for plan 010 in `plans/README.md` is updated

## STOP conditions

Stop and report back, do not improvise, if:

- The wizard variable names in `scripts/setup.sh` are not `AZDO_ORG` and
  `JIRA_SITE`. Plan 005 may have chosen different ones. Use what the code says
  and report the difference.
- `cli.USAGE` and the README verb list disagree on something other than the
  `tk git` line. That is a second drift and a reviewer should see it named
  separately.
- You find a statement in `SKILL.md` that the code contradicts and this plan does
  not list. Report it. Do not fix it here, because `SKILL.md` is the routine and
  an unreviewed edit changes agent behaviour.
- Writing the example `notes.md` needs a real repository layout you do not have.
  Keep it fictional and obviously so.

## Maintenance notes

- The per-tracker table in "Current state" is the thing to re-check whenever an
  adapter gains a key. Documentation is the only place that difference is
  visible, because `shape.ticket` normalises it away.
- `references/profiles.md` was accurate throughout this audit. When the README
  and that page disagree, the page is more likely right.
- A reviewer should read the two new `notes.md` files as an agent would, and ask
  whether the verify gate section would let them prove a change.
