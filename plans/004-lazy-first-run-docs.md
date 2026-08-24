# Plan 004: Ask at the moment of need, and say so in the docs

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Line numbers in this plan are measured at commit `50239f0`, and they will
> be wrong when you run it.** Plan 001 is a declared dependency and it replaces
> `SKILL.md:82-83`, two lines, with an eight-line block, which moves everything
> below `SKILL.md:83` down by six. Step 1 of this plan then moves the rest
> further. So every replace instruction below names an anchor as well as a
> range: a heading, or the first and last line of the quoted text. **Locate by
> the anchor, and treat the range as a hint.** Re-read the file after every step.
>
> **Drift check (run first)**: `git log --oneline 50239f0..HEAD -- SKILL.md`
> Expect a commit from plan 001. Then confirm each "Current state" excerpt still
> exists verbatim:
>
> ```bash
> grep -n "^## 0\. Preflight" SKILL.md
> grep -n "^## 1\. Resolve the project" SKILL.md
> grep -n "A project with no profile is a new project" SKILL.md
> grep -n "Every url in \`figma_urls\` is an instruction" SKILL.md
> grep -n "^## Install" README.md
> grep -n "^## Set up a project" README.md
> ```
>
> Each must print exactly one line. A missing anchor is a STOP condition. A
> shifted line number is not: that is expected.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: `plans/001-remove-browser-credential-path.md`,
  `plans/002-lazy-secrets-and-one-provider-setup.md`,
  `plans/003-detect-and-init-verbs.md`. This plan documents what those three
  build. Running it first would document behaviour that does not exist.
- **Category**: docs
- **Planned at**: commit `50239f0`, 2026-08-24

## Why this matters

The three plans before this one remove the setup wall from the code. This one
removes it from the routine and the README, which is where an agent and a user
actually read it.

Three instructions still send a first run into a setup phase:

- `SKILL.md:62-67` opens with `$T doctor` as a preflight gate. `doctor` reads
  every profile on disk and every provider, so on a fresh machine its answer is
  a failure, and the agent stops before it has read the ticket.
- `SKILL.md:115-117` sends the agent to hand-write a profile from a 251-line
  reference.
- `README.md:187-199`, the paragraph starting "Then run the wizard", tells the
  user to run the whole wizard right after cloning, which asks for four tokens
  and two organization names.

The wanted first run is: clone the skill, open a project, type "work on 5438",
and answer at most one question, which is the tracker, and then mint the one
token that tracker needs. Everything else is read from the machine or asked
later, at the moment it blocks.

The README also needs an install prompt a user can paste into an agent, so
installing the skill is one paste and not a procedure.

## Current state

### `SKILL.md:62-95`, phase 0

```
## 0. Preflight

```bash
T=~/.claude/skills/agent-ticket-workflow/scripts/tk
$T doctor
```

Exit 0 means every provider answered. Exit 1 prints `projects`, one row per
provider with its own `ok`, and `fix`, one command per gap. A project whose
pull request host is a second provider gets two rows, and `role` names which
one the row read: `tracker` or `host`.

`doctor` reads every profile on disk, so a stale token on a project this run
never touches also exits 1. Stop only when a failing row is the project this run
needs. Then hand the user its `fix` command, usually `scripts/setup.sh
<provider>` run from `~/.claude/skills/agent-ticket-workflow`, because minting a token
is the user's step. Name any other gap once and carry on. A bare ticket id names
no project yet, so re-check the rows against the slug `resolve` returns in step
1.
```

(then the `tk` reads the tokens paragraph, which plan 001 rewrites, then:)

```
Every answer is JSON on stdout. Every failure prints a fixed code under `error`
and a sentence under `message`, so switch on the code, not the prose. Exit 2
means one thing: a ticket matched more than one project and a human must choose.
Everything else is exit 1, a bad command line included.

Three entry points fork here.

- "The tickets assigned to me" goes to batch mode below.
- A ticket that already has an open pull request goes to resume mode below.
- Word that a build reached the test environment goes to Gates below.
```

### `SKILL.md:96-118`, phase 1

```
## 1. Resolve the project

```bash
$T resolve 59644          # id, key, tracker url, or nothing for the current directory
```

The answer holds `slug`, `tracker`, `ticket`, and `notes_path`. Read that
`notes.md` before you touch code. It holds the repo layout, the verify gate, and
the traps for that project.

`config.json` sits beside it in the same directory. Read three fields from it,
`host.base_branch`, `host.branch_pattern`, and `host.commit_subject`, and
expand the patterns yourself. The rest of that file is for `tk`, apart from
`preview.bypass_env`, which step 5 reads on a protected deployment.

Exit 2 answers `slugs` with the candidates. Ask the user which project, then
pass `--slug <slug>` on every verb that follows. `tk resolve` takes no `--slug`,
and it ignores one in silence.

A project with no profile is a new project. Write
`~/.claude/ticket-workflow/projects/<slug>/config.json` and `notes.md` first,
using `references/profiles.md`.
```

### `SKILL.md:132-136`, the Figma bullet of phase 2

```
- Every url in `figma_urls` is an instruction. Pull the frame with
  `$T figma <url> --render /tmp/frame.png --specs` and read `references/figma.md`.
  `--specs` prints resolved values: hex, pixels, font sizes. Mapping a value back
  to a brand design token is your own step, because the Figma variables endpoint
  is Enterprise only.
```

### `README.md:176-232`, install and project setup

```
## Install

Clone into your skills directory. The directory name must match the skill name,
which is the same as the repository name:

```bash
git clone https://github.com/kstulgys/agent-ticket-workflow.git \
  ~/.claude/skills/agent-ticket-workflow
cd ~/.claude/skills/agent-ticket-workflow
```

Then run the wizard. It installs the Superpowers plugin, then walks you through
one provider at a time and writes each token to `secrets.env`:

```bash
scripts/setup.sh
```

Run one step on its own with `scripts/setup.sh superpowers`, or `azure`, `jira`,
`github`, or `figma`.

The wizard asks for your Azure DevOps organization and your Atlassian site,
because no default can be right. Set `AZDO_ORG` and `JIRA_SITE` in the
environment to answer without a prompt.

## Set up a project

Copy an example and edit it:
```

(then the `mkdir`/`cp` block, the paragraph about the slug, the paragraph about
`notes.md`, the paragraph naming the two examples, and a `## Then check it`
block that runs `scripts/tk doctor`. Read the live lines 201-232 before you
replace them.)

### `README.md:234-260`, the verb list and the test count

The verb list at 236-247 has no `detect` and no `init` row. Line 258 says
`388 tests, no network.` The suite at commit `50239f0` runs 447, so that number
is already stale, and plans 002 and 003 raise it again.

### Repo conventions that apply

- ASD-STE100 Simplified Technical English. Short sentences, one idea each,
  active voice, no em dashes, no colons as mid-sentence connectors. Sentence
  case headings.
- `SKILL.md` states a rule, then the reason it exists in one sentence. It names
  no endpoint and no body format (`README.md:136-137`).
- The README is written for a human choosing whether to use the skill.
  `SKILL.md` is written for the agent running it. Do not merge their voices.
- Tables in both files use the `|---|---|` form with no padding.

## Commands you will need

| Purpose  | Command                                          | Expected on success |
|----------|--------------------------------------------------|---------------------|
| Tests    | `python3 -m unittest discover -s tests -t tests` | `OK`                |
| Count    | `python3 -m unittest discover -s tests -t tests 2>&1 \| grep '^Ran '` | the real number to write into the README |
| Verbs    | `python3 scripts/tk`                             | the usage block, for the verb list |

## Scope

**In scope**:

- `SKILL.md` (phase 0, phase 1, and the Figma bullet of phase 2)
- `README.md` (install, first run, verbs, test count)

**Out of scope** (do NOT touch):

- Every other phase of `SKILL.md`. Phases 3 to 7, resume mode, gates, and batch
  mode are unchanged by this work.
- `references/profiles.md` — it stays the full schema reference. `tk init`
  writes a subset, and a user who wants the rest reads this page. Do not trim
  it.
- `references/figma.md`, `references/verification.md`,
  `references/writing-comments.md`.
- Every file under `scripts/` and `tests/`. This plan writes no code. If a doc
  claim turns out to be false, that is a STOP condition, not an edit.

## Git workflow

- Branch: `advisor/004-lazy-first-run-docs`.
- Two commits: one for `SKILL.md`, one for `README.md`.
- Message style from `git log`: a capitalised imperative sentence, no prefix,
  no trailing period. Example in this repo: `Make the documentation match what
  the code does`. Use `Ask for a credential at the moment it blocks` and `Make
  the readme match the first run`.
- Do NOT push and do NOT open a pull request.

## Steps

### Step 1: Replace phase 0 with a start, not a gate

Anchor: the line `## 0. Preflight`. Replace from there through the line that
reads exactly `1.`, which closes the paragraph ending "the slug `resolve`
returns in step". At `50239f0` that is `SKILL.md:62-81`. The next line is blank
and the line after it starts "`tk` reads the tokens itself", which plan 001
rewrote. Leave both. Replace the block with:

````
## 0. Start where the user is

There is no setup gate. The first command is the one that answers the question
the user asked, and a gap answers for itself.

```bash
T=~/.claude/skills/agent-ticket-workflow/scripts/tk
$T resolve 5438
```

Every failure prints a fixed code under `error` and a sentence under `message`,
so switch on the code, not the prose.

| `error` | What it means | Your next step |
|---|---|---|
| none | a profile owns this ticket | step 2 |
| `ambiguous` | two profiles match, exit 2 | ask the user which slug, then pass `--slug` on every verb that follows |
| `unresolved` | no profile owns it | the bootstrap in step 1 |
| `secrets` | a token variable is not set. The message names the variable and the one stage that writes it | run that stage, then repeat the command |
| `http` with 401 or 403 | the token is set and the provider refused it | run that stage again, then repeat the command |
| `profile` | a `config.json` on disk is unreadable. The message names the file | fix that one file |

Every answer is JSON on stdout. Exit 2 means one thing: a ticket matched more
than one project and a human must choose. Everything else is exit 1, a bad
command line included.

Ask for nothing you have not been refused. A run that asks for four tokens
before it reads the ticket spends the user's attention on three providers this
ticket does not touch.

`$T doctor` reads every profile and every provider at once. Run it when a call
fails for a reason no code above explains, or when the user asks what is
configured. It is a diagnostic, and never a first step: on a machine with no
profile yet its answer is a failure, and that failure is not about this ticket.
````

Keep the `tk` reads the tokens paragraph as plan 001 left it. Keep the "Three
entry points fork here" list.

The old file holds the "Every answer is JSON on stdout" paragraph below the `tk`
reads the tokens paragraph. Delete that copy. The block above already carries
it, directly under the table, so leaving both gives the phase two copies.

**Verify**: `grep -c "0\. Preflight" SKILL.md` prints `0`,
`grep -c "diagnostic, and never a first step" SKILL.md` prints `1`, and
`grep -c "Every answer is JSON on stdout" SKILL.md` prints `1`.

### Step 2: Give phase 1 a bootstrap that asks one question

Keep everything from `## 1. Resolve the project` through the paragraph that
ends "and it ignores one in silence" exactly as it is: the heading, the
`resolve` block, the `notes.md` paragraph, the `config.json` paragraph, and the
exit 2 paragraph. At `50239f0` that is `SKILL.md:96-113`.

Anchor: the line `A project with no profile is a new project. Write`. Replace
that paragraph, three lines ending "using `references/profiles.md`.", with the
block below. The blank line before it and the `## 2.` heading after it both
stay.

````
### No profile owns this ticket

This is a new project, and the machine already holds most of what a profile
needs. Read first, ask second.

```bash
$T detect
```

`detect` reads the git remote and the git config in the working directory. It
answers `provider`, `owner`, `repo`, `org`, `project`, `base_branch`, and the
commit identity. A null is a field it could not read, and a null is the only
thing worth a question. It makes no network call and needs no token.

1. The tracker. `detect` names it when the remote is GitHub or Azure DevOps. A
   Jira tracker never appears in a git remote, and neither does a tracker that
   lives apart from the code. So when `provider` is null, or when the id the
   user typed does not look like that provider's ids, ask the user once, with a
   select of three options: GitHub, Azure Boards, Jira. One question, three
   options, no free text.
2. The token, and only when it is missing. Run `scripts/setup.sh <provider>`
   from `~/.claude/skills/agent-ticket-workflow`. That stage opens the
   provider's token page, names the scopes to select, writes the value to
   `secrets.env` itself, and verifies it. You never see the value. Never ask the
   user to paste a token into the chat, and never read one from a browser
   session, a cookie store, or a keyring.
3. The values `detect` left null and the provider needs: the Azure organization
   and project, the Jira site and project key, or the GitHub owner and
   repository. Ask for these together, in one message.
4. Write the profile.

```bash
$T init --slug northwind --tracker azure --ticket 5438 \
    --org https://dev.azure.com/northwind --project "Contoso migration"
```

`init` fills the rest: the id pattern from the ticket you passed, the repo path
and the host block from `detect`, `people.self` from the provider's own account,
and the four buckets. It writes `notes.md` as a stub. It refuses to overwrite a
profile that is already there, and it writes nothing at all when a call fails,
so a missing token means you mint it and run the same command again.

Read the `next` list in its answer. Those are the fields no machine can fill,
and two of them cost a run when they stay empty.

- `notes.md` has no verify gate yet. Ask the user for the commands that prove a
  change in this repo, and write them into the stub before step 4.
- The four buckets hold no states. The first time a ticket needs one, ask the
  user which column their board uses for it, then write it into `config.json`.
  Until then the routing travels in the comment, which is already how this
  routine works on Azure and Jira.
- There is no `deploy_gate`. Ask for the state a tested build reaches the first
  time a ticket gets there.

`references/profiles.md` documents every key, for the fields you add by hand.
````

**Verify**: `grep -n "using .references/profiles.md" SKILL.md` returns
nothing, and `grep -c "tk init" SKILL.md` is at least 1.

### Step 3: Make the Figma token a consequence of a Figma url

Anchor: the line starting `- Every url in \`figma_urls\` is an instruction.`
Replace that bullet, five lines ending "is Enterprise only.", with the block
below. The next bullet starts "- `parent` and `children` matter." and stays.

```
- Every url in `figma_urls` is an instruction. Pull the frame with
  `$T figma <url> --render /tmp/frame.png --specs` and read `references/figma.md`.
  `--specs` prints resolved values: hex, pixels, font sizes. Mapping a value back
  to a brand design token is your own step, because the Figma variables endpoint
  is Enterprise only.
  A ticket with no Figma url needs no Figma token, so this is the first place
  that asks for one. When the call answers `secrets`, run `scripts/setup.sh
  figma`, then repeat it. When it answers `http` with 403, the token is real and
  the file is not shared with the account that minted it, so ask the user to
  share the file or to mint a token on an account that can read it. Never open
  the design in a browser instead.
```

**Verify**: `grep -c "setup.sh figma" SKILL.md` prints `1`.

### Step 4: Rewrite the README install section and add the install prompt

Anchor: the line `## Install`. Replace from there through the paragraph that
ends "to answer without a prompt", which is the `AZDO_ORG` paragraph. At
`50239f0` that is `README.md:176-199`. The next line is blank and the line
after it is `## Set up a project`, which step 5 replaces.

`````
## Install

Clone into your skills directory. The directory name must match the skill name,
which is the same as the repository name:

```bash
git clone https://github.com/kstulgys/agent-ticket-workflow.git \
  ~/.claude/skills/agent-ticket-workflow
```

That is the whole install. There is no setup step, no token to mint yet, and no
config file to write. The skill asks for a credential the first time one is
refused, and for one provider only.

### Or paste this to your agent

```
Install the agent-ticket-workflow skill for me.

1. Clone https://github.com/kstulgys/agent-ticket-workflow into
   ~/.claude/skills/agent-ticket-workflow. The directory name has to be exactly
   agent-ticket-workflow, because the skill name and the directory name must
   match.
2. From that directory, run: python3 -m unittest discover -s tests -t tests
   Tell me the result.
3. Do not mint any token, do not run scripts/setup.sh, and do not write any
   config file or project profile. The skill asks for what it needs when it
   needs it.
4. Then tell me it is ready, and that I start a job by typing: work on <ticket>
```
`````

**Verify**: `grep -c "Or paste this to your agent" README.md` prints `1`, and
`grep -n "scripts/setup.sh$" README.md` returns nothing (no bare wizard run is
recommended any more).

### Step 5: Replace "Set up a project" with the first run

Anchor: the line `## Set up a project`. Replace from there through the
paragraph that ends with the `doctor` explanation, the one whose last sentence
names "a `fix` command per gap". At `50239f0` that is `README.md:201-232`. The
next line is blank and the line after it is `## Verbs`, which step 6 edits.
Write a `## First run` section that says, in the README's voice:

- What the user types: `work on 5438`.
- What the agent does with no profile: reads the git remote, asks for the
  tracker only when the remote cannot name it, runs one wizard stage for that
  provider's token, then writes the profile with `tk init`.
- Which questions are real, and why no machine can answer them: the verify gate
  commands, the board column per bucket, and the state a tested build reaches.
- That the profile lives in `~/.claude/ticket-workflow/projects/<slug>/` and
  nothing about the user's projects is ever committed to this repository. Keep
  that sentence; it exists at `README.md:144-148` today and it is still true.
- That `examples/projects/northwind` and `examples/projects/globex` are worked
  examples for a hand-written profile, and `references/profiles.md` documents
  every key.
- That `scripts/tk doctor` reports what is configured, and
  `scripts/setup.sh <provider>` mints one token, for a user who prefers to set
  a provider up before their first ticket.

Keep the two example paths and the sentence about `notes.md` costing a run. Do
not keep the `mkdir`/`cp` block: `tk init` replaces it.

**Verify**: `grep -n "cp examples/projects" README.md` returns nothing, and
`grep -c "## First run" README.md` prints `1`.

### Step 6: Add the two verbs and fix the test count

Anchor: the fenced block that follows the `## Verbs` heading, `README.md:236-247`
at `50239f0`. Add two rows after the `tk doctor` row. Every existing row puts
its description at column 30, and both new rows land there: `tk detect` is 9
characters plus 21 spaces, and `tk init --slug S --tracker T` is 28 plus 2.

```
tk detect                     what the working directory knows
tk init --slug S --tracker T  write a project profile
```

Then read the real count and write it into the Tests section:

```bash
python3 -m unittest discover -s tests -t tests 2>&1 | grep '^Ran '
```

Replace `388 tests, no network.` with the number that command prints.

**Verify**: `python3 scripts/tk 2>&1 | grep -c "detect\|init"` prints `2`, and
the number in the README matches the `Ran N tests` line exactly.

### Step 7: Read both files end to end

Read `SKILL.md` from phase 0 to the end of phase 2, and `README.md` from the top
to the end of the verb list. Then run every check below. Each one is a command
with an expected result, so none of them is a judgment call.

```bash
# 1. Nothing tells the reader to set up before the first ticket.
#    Expected: no output. Each match is a survivor to fix.
grep -n "scripts/setup\.sh$" README.md
grep -n "Then run the wizard" README.md
grep -n "Preflight" SKILL.md
grep -n "cp examples/projects" README.md

# 2. Every verb the docs name exists and takes the flags they show.
#    Expected: each exits 0 and prints a usage block. Do not add
#    `tk resolve --help` here: that verb reads a bare argument and builds no
#    argparse parser, so it treats --help as a ticket id and answers
#    unresolved with exit 1. That is pre-existing and no doc asks for it.
python3 scripts/tk detect --help
python3 scripts/tk init --help

# 3. Every flag named in the SKILL.md init example is a real flag.
#    Expected: no output.
for f in --slug --tracker --ticket --org --project --site --owner --repo; do
  python3 scripts/tk init --help 2>&1 | grep -q -- "$f" || echo "missing $f"
done

# 4. You added no em dash.
#    Expected: 0. Write the plus in a bracket. A bare '^+' is a quantifier on
#    '^' in some greps, which matches every line and counts the em dash on the
#    line plan 001 removed. README's four remaining em dashes are all in the
#    References list, and they stay.
git diff -U0 50239f0..HEAD -- SKILL.md README.md | grep -c '^[+].*—'

# 5. doctor is named as a diagnostic, never as a first step.
#    Expected: the first line number is greater than the resolve one.
grep -n "doctor" SKILL.md
grep -n '\$T resolve' SKILL.md
```

Check 5 is the one that needs your eyes on two numbers: the first `$T resolve`
in phase 0 must come before the first `doctor` mention. If a `doctor` line sits
above it, phase 0 is still a gate.

### Step 8: Run the gate

```bash
python3 -m unittest discover -s tests -t tests
```

**Verify**: `OK`. This plan changes no code, so the count must match what plan
003 left.

## Test plan

No new tests. The subject is prose, and the repo has no doc test.

The gate is step 7's read plus one check per documented command. Run each
command a changed section names, and confirm the flag exists:

```bash
python3 scripts/tk detect --help
python3 scripts/tk init --help
python3 scripts/tk resolve --help
bash -c 'cd ~/.claude/skills/agent-ticket-workflow 2>/dev/null && scripts/setup.sh nonsense; true'
```

The last one must print the unknown-step message from plan 002 and exit 1,
which proves the stage names the README gives are the names the wizard accepts.
Skip it when the skill is not installed at that path, and say so.

## Done criteria

ALL must hold:

- [ ] `grep -n "0. Preflight" SKILL.md` returns nothing
- [ ] `grep -c "diagnostic, and never a first step" SKILL.md` prints `1`
- [ ] `grep -n "using .references/profiles.md" SKILL.md` returns nothing
- [ ] `grep -c "setup.sh figma" SKILL.md` prints `1`
- [ ] `grep -c "Or paste this to your agent" README.md` prints `1`
- [ ] `grep -n "cp examples/projects" README.md` returns nothing
- [ ] The step 7 check 4 prints `0`: no added line holds an em dash. Use
      `grep -c '^[+].*—'`, never a bare `grep '^+'`
- [ ] The verb list in `README.md` holds a `tk detect` row and a `tk init` row
- [ ] The test count in `README.md` equals the `Ran N tests` line
- [ ] `python3 -m unittest discover -s tests -t tests` prints `OK`
- [ ] `git status --short` lists `SKILL.md` and `README.md` only
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- `tk detect` or `tk init` does not exist, or a flag this plan documents is not
  in its `--help`. That means plan 003 landed differently, and the docs must
  match the code, not the plan.
- The error codes in the step 1 table do not match `cli.error_codes()` at
  `scripts/tk_lib/cli.py:47-76`.
- `scripts/setup.sh <provider>` still asks for more than that provider's
  values. Plan 002 owns that, and documenting the lazy flow over an eager
  wizard would be a false promise.
- Any of the six anchor greps in the header's drift check prints zero lines, or
  more than one. That means the text this plan replaces is gone or duplicated,
  and an anchored replace cannot be aimed. A shifted line number is not a stop
  condition: expect roughly a six-line shift from plan 001.

## Maintenance notes

- The error-code table in phase 0 is the contract between `cli.error_codes()`
  and the routine. A new code in that function needs a row here, or the agent
  will not know what to do with it.
- `references/profiles.md` is now the reference for the fields `tk init` does
  not write, mostly states, people beyond `self`, `deploy_gate`, and `preview`.
  A change to `init`'s defaults changes which half of that page a user still
  needs.
- A reviewer should check one thing above all: no sentence in either file asks
  for a credential before a call has been refused. That is the whole point of
  the four plans.
- Deferred: `references/profiles.md` still opens with "A profile is one
  directory" and describes hand-writing it. Rewriting that page around `tk init`
  is a separate job, and it is not needed for the flow to work.
