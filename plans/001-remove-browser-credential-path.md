# Plan 001: Remove the browser session path for reading tickets and designs

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 50239f0..HEAD -- SKILL.md README.md scripts/setup.sh scripts/jira-cookies.py references/jira-cookie-fallback.md`
> If any of those files changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding. On a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `50239f0`, 2026-08-24

## Why this matters

The skill ships a second way to read Jira: decrypt the user's live Chrome
cookie database, write the session to a file, then drive `agent-browser`
against the Jira REST API. A session cookie is a full account credential. It is
wider than an API token, no token scope limits it, and it stays valid until the
user signs out. The skill's own doc says so.

The owner's decision is that every ticket read and every design read goes
through `tk` with a token the user minted and stored in `secrets.env`, and
through nothing else. This plan deletes the browser path and every pointer to
it, so no later run can pick it up.

Deleting it also drops the only two third-party Python dependencies the project
names (`secretstorage`, `cryptography`) and removes a second read path from
maintenance.

## Current state

Files in scope, each with its role:

- `scripts/jira-cookies.py` (157 lines) — decrypts Chrome's cookie database
  into `~/.claude/ticket-workflow/jira-state.json`. Nothing imports it. `tk`
  never calls it.
- `references/jira-cookie-fallback.md` (62 lines) — tells the agent to load
  that file into `agent-browser` and make Jira REST calls from a browser tab.
- `SKILL.md:82-83` — points the agent at that reference.
- `SKILL.md:142-145` — tells the agent to open a ticket in the tracker's web
  interface. The phrase "web UI" is split by the line break between 144 and 145.
- `scripts/setup.sh:297-301` — points the user at that reference when a Jira
  token fails to verify.
- `README.md:171-174` — lists the two dependencies and the reference.
- `README.md:262-268` — the references list.
- `README.md:120-131` — the "What it never does" list, where the new rule goes.

The exact text to replace.

`SKILL.md:82-83`:

```
`tk` reads the tokens itself. Leave `secrets.env` closed. When the Atlassian org
blocks an API token, read `references/jira-cookie-fallback.md`.
```

`SKILL.md:142-145` (the last bullet of step 2, "Read the ticket in full"):

```
- An empty list can mean the tracker carries no such key, because the shape
  fills every missing list with `[]`. So an empty `children` on Jira or GitHub
  is not evidence that no child spec exists. Open the parent ticket in the web
  UI on those two trackers before you conclude there is nothing to read.
```

`scripts/setup.sh:297-301` (inside the `if want jira` stage):

```bash
    else
      say "The token did not verify."
      say "If your organization blocks API tokens, read"
      say "references/jira-cookie-fallback.md and use the browser session instead."
    fi
```

`README.md:171-174`:

```
- `curl`, for the setup wizard only.
- `secretstorage` and `cryptography`, for `scripts/jira-cookies.py` only. That
  script is the fallback for an organization that blocks Jira API tokens, and
  `tk` never imports it. See `references/jira-cookie-fallback.md`.
```

`README.md:267-268` (the last two entries of the references list):

```
- `references/figma.md` — reading a design a ticket links to
- `references/jira-cookie-fallback.md` — when an org blocks Jira API tokens
```

Repo conventions that apply here:

- Prose is ASD-STE100 Simplified Technical English. Short sentences, one idea
  each, active voice, no em dashes. Every paragraph in `SKILL.md` follows it.
  Match it.
- A rule in `SKILL.md` states the rule, then the reason it exists in one
  sentence. See `SKILL.md:311-315` for the shape.
- `scripts/setup.sh` prints through `say`, `step`, `note`, and `warn` only. See
  `scripts/setup.sh:58-62`. Never `echo`.

## Commands you will need

| Purpose     | Command                                          | Expected on success        |
|-------------|--------------------------------------------------|----------------------------|
| Compile     | `python3 -m compileall -q scripts`               | exit 0, no output          |
| Tests       | `python3 -m unittest discover -s tests -t tests` | `OK`, 447 tests            |
| Shell lint  | `shellcheck scripts/setup.sh`                    | exit 0, no output          |

447 tests pass at commit `50239f0`. This plan changes no code, so the count
must not move.

## Scope

**In scope** (the only files you may modify or delete):

- `scripts/jira-cookies.py` (delete)
- `references/jira-cookie-fallback.md` (delete)
- `SKILL.md` (two hunks)
- `scripts/setup.sh` (one hunk)
- `README.md` (three hunks)

**Out of scope** (do NOT touch, even though they look related):

- `references/verification.md` — it tells the agent to drive a browser to
  prove a visual change. That is proof of a fix, not reading a ticket. The ban
  in this plan covers reading a ticket or a design. Leave every line of this
  file alone.
- `references/writing-comments.md:6-7` — "How you drove the browser stays in
  your notes" is about the same verification step. Leave it.
- `scripts/tk_lib/http.py:34` — `_AUTH_HEADERS` lists `cookie`. That is a
  scrubber guard that keeps a cookie header out of an error message. It is not
  a browser path. Leave it.
- `scripts/tk_lib/**` — no code change belongs in this plan. The adapters
  already reach a provider through its API with a token.
- `tests/**` — no test references the deleted files. Confirm with the grep in
  step 1, then leave the suite alone.

## Git workflow

- Branch: `advisor/001-remove-browser-credential-path` off `main`.
- One commit. Message style from `git log`: a capitalised imperative sentence,
  no prefix, no trailing period. Examples in this repo: `Delete the unused text
  reader and mark what waits for a verb`, `Make the documentation match what the
  code does`. Use: `Remove the browser session path for reading tickets`.
- Do NOT push and do NOT open a pull request.

## Steps

### Step 1: Confirm no code depends on the two files

```bash
grep -rn "jira-cookies\|jira_cookies\|jira-state\|jira-cookie-fallback" \
  --include='*.py' --include='*.sh' --include='*.yml' . | grep -v '^\./\.git/'
```

**Verify**: the only matches are inside `scripts/jira-cookies.py` itself and
`scripts/setup.sh:300`. If any file under `scripts/tk_lib/` or `tests/`
matches, STOP.

### Step 2: Delete the two files

```bash
git rm scripts/jira-cookies.py references/jira-cookie-fallback.md
```

**Verify**: `test ! -e scripts/jira-cookies.py && test ! -e references/jira-cookie-fallback.md && echo gone` prints `gone`.

### Step 3: Replace the pointer in SKILL.md with the rule

Replace `SKILL.md:82-83` (quoted in "Current state") with:

```
`tk` reads the tokens itself. Leave `secrets.env` closed.

Every ticket read, every ticket write, and every Figma read goes through `tk`,
with a token from `secrets.env`. Never drive a browser to reach a ticket or a
design, and never read a browser session, a cookie store, or a keyring for a
credential. A session cookie is a full account credential, and no token scope
limits it. When a provider refuses to issue API tokens, say so and stop,
because that is the user's to settle with their administrator.
```

**Verify**: `grep -n "jira-cookie" SKILL.md` returns nothing, and
`grep -c "Never drive a browser" SKILL.md` prints `1`.

### Step 4: Replace the web UI instruction in SKILL.md

Replace `SKILL.md:142-145` (quoted in "Current state") with:

```
- An empty list can mean the tracker carries no such key, because the shape
  fills every missing list with `[]`. So an empty `children` on Jira or GitHub
  is not evidence that no child spec exists. Read the description and the
  comments for a ticket id, run `$T show` on the id you find, and when the
  ticket names none, ask the user for the child id. Do not open the tracker in
  a browser to look.
```

**Verify**: `grep -c "Open the parent ticket" SKILL.md` prints `0`. Use that
phrase, not "web UI": in the live file the words "web" and "UI" sit on either
side of a line break at `SKILL.md:144-145`, so `grep "web UI"` never matched
that bullet at all. It matches one other line, `SKILL.md:249`: "`unlinked` is
what the call asked to link and the server did not confirm. Link it in the web
UI, or say so in the comment." That is a human action on a pull request link,
not a ticket read. It is out of scope, and it stays.

Second check: `grep -c "a browser to look" SKILL.md` prints `1`. That phrase,
not "in a browser to look": the replacement text above wraps after "in", so the
longer phrase spans the line break and never matches. It printed `0` at
`50239f0`, so it still discriminates.

### Step 5: Replace the fallback pointer in the wizard

Replace `scripts/setup.sh:297-301` (quoted in "Current state") with:

```bash
    else
      say "The token did not verify. Check the email and the token."
      say "If your organization blocks API tokens, ask an administrator to"
      say "allow one. This tool reads Jira through the API and nothing else."
    fi
```

**Verify**: `shellcheck scripts/setup.sh` exits 0, and
`grep -n "jira-cookie" scripts/setup.sh` returns nothing.

### Step 6: Drop the dependency bullet and the reference line in README.md

Delete the second bullet of `README.md:171-174`, the one that starts
`- \`secretstorage\` and \`cryptography\``. Keep the `curl` bullet above it.

Delete the `references/jira-cookie-fallback.md` line from the references list
at the end of the file. Keep the four lines above it.

**Verify**: `grep -n "secretstorage\|cryptography\|jira-cookie" README.md`
returns nothing.

### Step 7: State the rule in the README's "What it never does" list

`README.md:120-131` is a list of five bullets. Add one bullet, after the
`Merge.` bullet and before the `Invent a behaviour` bullet:

```
- Read a ticket or a design through a browser. Every read is an API call with a
  token you minted, and the token lives in one file that `tk` reads itself. It
  never reads your browser session, your cookie store, or your keyring.
```

**Verify**: `grep -c "Read a ticket or a design through a browser" README.md`
prints `1`. Do not count bullets: step 6 removes two lines that match `^- `
and this step adds one, so the total falls by one.

### Step 8: Run the full gate

```bash
python3 -m compileall -q scripts
python3 -m unittest discover -s tests -t tests
shellcheck scripts/setup.sh
```

**Verify**: compile exits 0, the suite prints `OK` with 447 tests, shellcheck
exits 0.

## Test plan

No new tests. This plan deletes an unreferenced script and edits prose. The
existing suite is the regression gate: it must stay at 447 passing tests,
because nothing under `scripts/tk_lib/` changes.

One extra check stands in for a test, because the harm this plan prevents is a
pointer surviving somewhere:

```bash
grep -rn "agent-browser\|secretstorage\|jira-cookie\|jira-state" . \
  --include='*.md' --include='*.py' --include='*.sh' --include='*.yml' \
  | grep -v '^\./\.git/' | grep -v '^\./plans/'
```

Expected: no output.

## Done criteria

ALL must hold:

- [ ] `test ! -e scripts/jira-cookies.py` and `test ! -e references/jira-cookie-fallback.md`
- [ ] The grep in "Test plan" returns no output
- [ ] `grep -c "Open the parent ticket" SKILL.md` prints `0`, and
      `grep -c "a browser to look" SKILL.md` prints `1`
- [ ] `python3 -m unittest discover -s tests -t tests` prints `OK` with 447 tests
- [ ] `shellcheck scripts/setup.sh` exits 0
- [ ] `python3 -m compileall -q scripts` exits 0
- [ ] `git status --short` lists only the five files named in Scope
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- Any file under `scripts/tk_lib/` or `tests/` imports or names
  `jira-cookies`, `jira_cookies`, or `jira-state`. That would mean the browser
  path is load-bearing, and this plan assumes it is not.
- The text at `SKILL.md:82-83`, `SKILL.md:142-145`, or
  `scripts/setup.sh:297-301` does not match the "Current state" excerpts.
- The test count moves off 447 in either direction.
- You find a third place that reads a browser session for a credential, beyond
  the two files this plan deletes. Report where, do not extend the plan.

## Maintenance notes

- The rule added in step 3 is the one place that states it. A later change that
  adds a provider must not add a browser fallback beside it.
- `references/verification.md` still drives a browser to prove a visual change.
  That boundary is deliberate: read through the API, prove through the browser.
  A reviewer should check that a future edit does not blur it.
- Deferred: `README.md` still tells the user to run the full setup wizard right
  after cloning. Plan 002 and plan 004 change that. Leave it here.
