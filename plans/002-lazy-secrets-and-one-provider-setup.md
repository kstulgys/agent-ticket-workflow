# Plan 002: Make a missing token one provider's question, not a wizard gate

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 50239f0..HEAD -- scripts/tk_lib/secrets.py scripts/setup.sh tests/test_secrets.py`
> If any of those files changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding. On a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none. Plan 001 also edits `scripts/setup.sh`, but a different
  hunk: 001 changes the Jira stage at lines 297-301, this plan changes lines
  156-172 and 343-363. Either order works. Run them on one branch if you want
  to avoid a merge.
- **Category**: dx
- **Planned at**: commit `50239f0`, 2026-08-24

## Why this matters

A user clones the skill, opens a project, and types "work on 5438". The routine
resolves the project, then reads the ticket. That second call is the wall.

Measured at commit `50239f0`, against a temp `HOME` that holds one GitHub
profile and no `secrets.env`:

```
$ tk resolve 5438
{"slug": "scratch", "ticket": "5438", "tracker": "github", ...}

$ tk show 5438
{"error": "secrets",
 "message": "no secrets file at .../secrets.env. Run scripts/setup.sh to create it."}

$ tk doctor
{"error": "secrets",
 "message": "no secrets file at .../secrets.env. Run scripts/setup.sh to create it."}
```

Two things are wrong with that answer. It names the whole wizard, which asks
for an Azure organization, an Azure PAT, an Atlassian site, a Jira token, a
GitHub token, and a Figma token, in that order. Five of those six values are
for providers this ticket never touches. And it names no variable, so neither
the user nor the agent learns that the one missing value is `GH_TOKEN`.

`tk doctor` fails the same way, which is worse than it looks: the diagnostic
that exists to report a per-provider gap cannot run on the machine that has
every gap.

The wanted answer to both commands is one sentence:
`GH_TOKEN is not set in secrets.env. Run scripts/setup.sh github to add it.`

Two changes get there. `secrets.load` stops treating an absent file as fatal,
so the run reaches the call that knows which variable it wanted. And
`secrets.get` names the one wizard stage that writes that variable.

## Current state

### `scripts/tk_lib/secrets.py:1-43`

```python
"""Read secrets.env. A value never leaves this process in plain text."""
import os
import stat

DEFAULT_PATH = os.path.expanduser("~/.claude/ticket-workflow/secrets.env")
SETUP = "scripts/setup.sh"
SCRUB = []


class SecretsError(Exception):
    pass


def load(path=None):
    path = path or DEFAULT_PATH
    if not os.path.exists(path):
        raise SecretsError(f"no secrets file at {path}. Run {SETUP} to create it.")
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode != 0o600:
        raise SecretsError(f"{path} has mode {oct(mode)}. Run: chmod 600 {path}")
    values = {}
```

(lines 21-37 parse the file and register every value with `mask`; they do not
change.)

```python
def get(name, values):
    if not values.get(name):
        raise SecretsError(f"{name} is not set in secrets.env. Run {SETUP} to add it.")
    return values[name]
```

### Which calls the raise blocks, and which it does not

Four call sites load secrets before they do anything else: `verbs.py:39`
(`_profile`), `verbs.py:94` (`_doctor`), `verbs.py:112` (`_mine`), and
`verbs.py:325` (`_figma`). Two of them carry the whole first run.

`scripts/tk_lib/verbs.py:31-44`, the route `show`, `comment`, `state`,
`assign`, `pr`, and `git` all take:

```python
def _profile(slug=None, arg=None):
    """Returns (profile, values, ticket). It builds no adapter.
    ...
    """
    values = secrets.load()
    profiles = config.load_all()
    if slug:
        return _named(slug, profiles), values, arg
    found = config.resolve(arg, profiles)
    return profiles[found["slug"]], values, found["ticket"]
```

`scripts/tk_lib/verbs.py:91-103`, the doctor verb:

```python
@cli.verb("doctor")
@cli.guarded
def _doctor(argv):
    values = secrets.load()
    profiles = config.load_all()
    adapters, hosts = {}, {}
    for slug, profile in profiles.items():
        adapters[slug] = _built(cli.adapter_for, profile, values)
```

`resolve` is the exception, and it matters. Its verb lives in
`scripts/tk_lib/config.py:145-153` and calls `load_all()` only, never
`secrets.load()`. So `tk resolve` already works on a fresh machine, and the
error the user meets comes one call later, from `tk show`.

After this plan, `_doctor` gains a behaviour worth pinning. `_built`
(`verbs.py:66-75`) catches a build failure and returns a `_Broken` adapter, and
`doctor._row` (`doctor.py:123-138`) catches whatever `whoami` raises and appends
`setup.sh <provider>` as the fix line. With `load` answering `{}` instead of
raising, `tk doctor` on a machine with no token stops failing whole and starts
reporting one row per provider, each naming its own stage. Step 6 checks that.

Each adapter reads its own variable through `get`, so `get` is the one place
that knows which provider a run actually needs:

- `scripts/tk_lib/azure.py:38-39` — `secrets.get(auth.get("token", "AZDO_PAT"), values)`
- `scripts/tk_lib/figma.py:73` — `secrets.get("FIGMA_TOKEN", values)`
- `scripts/tk_lib/gitcmd.py:35` — `secrets.get(auth.get("token") or TOKEN_ENV[kind], values)`
- `scripts/tk_lib/jira.py` and `scripts/tk_lib/github.py` do the same for
  `JIRA_EMAIL`, `JIRA_TOKEN`, and `GH_TOKEN`.

### `scripts/setup.sh:156-172`

```bash
# Run one step with setup.sh superpowers, azure, jira, github, or figma. Run all
# five with no argument.

WANT="${*:-superpowers azure jira github figma}"
want() { [[ " $WANT " == *" $1 "* ]]; }

for provider in "$@"; do
  case "$provider" in
    superpowers|azure|jira|github|figma) ;;
    *)
      warn "Unknown step: $provider"
      say "Use superpowers, azure, jira, github, or figma."
      say "No argument runs all five."
      exit 1
      ;;
  esac
done
```

### `scripts/setup.sh:343-363`, the closing stage

```bash
stage "Lock the file and run the check"
chmod 600 "$ENV_FILE"
say "Wrote $ENV_FILE with mode 600."
say "tk doctor checks every provider, not only the one you set up now."
say "A gap in another provider is a separate fix, not a fault of this run."
TK="$(dirname "$0")/tk"
if [[ ! -x "$TK" ]]; then
```

(lines 349-354 handle a missing `tk`; lines 356-362 run `tk doctor` and print
its exit code.) Read the live file for the exact body before you edit it.

`tk doctor` answers `{"ok": false, "fix": ["no project profiles found. ..."]}`
when no profile exists (`scripts/tk_lib/doctor.py:26-29`). On a fresh machine
that prints a failure directly after a token was saved and verified, which
reads as "your setup failed" when the token is fine.

### Repo conventions that apply

- A module docstring states what the file is for. Every function that holds a
  judgment carries a comment that says why, not what. See
  `scripts/tk_lib/secrets.py:57-66` for the shape.
- Errors name the next action. Every existing message ends in a command the
  reader can run.
- Test names are sentences: `test_get_names_the_missing_variable_and_the_setup_script`.
  Match that in `tests/test_secrets.py`.
- The wizard prints through `say`, `step`, `note`, and `warn` only
  (`scripts/setup.sh:58-62`). Never `echo`.

## Commands you will need

| Purpose    | Command                                              | Expected on success   |
|------------|------------------------------------------------------|-----------------------|
| Compile    | `python3 -m compileall -q scripts`                   | exit 0, no output     |
| Tests      | `python3 -m unittest discover -s tests -t tests`     | `OK`                  |
| One file   | `python3 -m unittest discover -s tests -t tests -k Secrets` | `OK`            |
| Shell lint | `shellcheck scripts/setup.sh`                        | exit 0, no output     |

447 tests pass at commit `50239f0`. This plan replaces one test and adds four,
so the expected count after it is 451.

## Scope

**In scope**:

- `scripts/tk_lib/secrets.py`
- `scripts/setup.sh`
- `tests/test_secrets.py`

**Out of scope** (do NOT touch):

- `scripts/tk_lib/verbs.py` — `_profile` keeps calling `secrets.load()` first.
  After this plan that call returns `{}` on a fresh machine and the run
  continues to `config.resolve`, which is the point. Do not reorder it.
- `scripts/tk_lib/doctor.py` — its "no project profiles found" answer is
  correct for a diagnostic. The guard added in step 5 lives in the wizard, not
  here.
- Every adapter under `scripts/tk_lib/` — they already read their own variable
  through `secrets.get`. Do not add a provider name to any call site.
- `SKILL.md` and `README.md` — plan 004 rewrites the flow they describe.

## Git workflow

- Branch: `advisor/002-lazy-secrets-and-one-provider-setup` off the branch that
  holds plan 001, or off `main` if 001 already landed there.
- Commit per step group: one commit for the `secrets.py` change with its tests,
  one for the wizard.
- Message style from `git log`: a capitalised imperative sentence, no prefix,
  no trailing period. Examples: `Give every request a deadline and name every
  transport failure`, `Make the first wizard run work`. Use `Name the one setup
  stage a missing token needs` and `Ask for one provider at a time`.
- Do NOT push and do NOT open a pull request.

## Steps

### Step 1: Let an absent secrets file answer with no values

In `scripts/tk_lib/secrets.py`, replace the missing-file raise in `load` with a
return of an empty dict. Keep the mode guard exactly as it is: a file that
exists with a wider mode is still a refusal.

Target shape:

```python
def load(path=None):
    """Every value in secrets.env, or nothing when the file is not there yet.

    An absent file is not a failure. It is the state of a machine that has not
    needed a token yet, and the run that follows may need none. get raises the
    error, because get knows which variable a call wanted and which stage
    writes it. Raising here instead answered every verb with the same sentence,
    so a run whose real gap was a missing project profile reported a missing
    token.

    A file that exists with a wider mode is still a refusal. That one is a
    fact about the machine, and no later call can repair it.
    """
    path = path or DEFAULT_PATH
    if not os.path.exists(path):
        return {}
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode != 0o600:
        raise SecretsError(f"{path} has mode {oct(mode)}. Run: chmod 600 {path}")
    ...
```

Leave lines 21-37 (the parse loop and the `mask` registration) unchanged.

**Verify**: `python3 -c "import sys; sys.path.insert(0, 'scripts'); from tk_lib import secrets; print(secrets.load('/nonexistent/secrets.env'))"`
prints `{}`.

### Step 2: Name the one stage that writes the missing variable

Add a variable-prefix to stage map beside `SETUP`, and use it in `get`.

Target shape:

```python
# The wizard stage that writes each variable. A run needs one provider, so the
# error names one stage, not the whole wizard. A project scoped value such as
# NORTHWIND_BYPASS_HILLCREST matches no prefix, and its error names the bare
# command, because no stage writes it.
STAGES = (("AZDO_", "azure"), ("JIRA_", "jira"), ("GH_", "github"),
          ("FIGMA_", "figma"))


def stage_for(name):
    """The setup stage that writes one variable, or None when none does."""
    return next((stage for prefix, stage in STAGES
                 if str(name).startswith(prefix)), None)


def get(name, values):
    if not values.get(name):
        stage = stage_for(name)
        where = f"{SETUP} {stage}" if stage else SETUP
        raise SecretsError(
            f"{name} is not set in secrets.env. Run {where} to add it.")
    return values[name]
```

**Verify**: `python3 -m unittest discover -s tests -t tests -k Secrets` runs.
One existing test fails at this point: `test_missing_file_names_the_setup_script`.
Step 3 replaces it. Do not delete it before step 3.

### Step 3: Replace and extend the secrets tests

In `tests/test_secrets.py`, replace this test (lines 50-53):

```python
    def test_missing_file_names_the_setup_script(self):
        with self.assertRaises(secrets.SecretsError) as cm:
            secrets.load("/nonexistent/secrets.env")
        self.assertIn("setup.sh", str(cm.exception))
```

with:

```python
    def test_a_missing_file_answers_with_no_values(self):
        # A machine with no token yet is a normal state. Raising here answered
        # every verb with a missing token, including a run whose real gap was
        # that no project profile exists.
        self.assertEqual(secrets.load("/nonexistent/secrets.env"), {})
```

Keep `test_refuses_a_mode_other_than_600` exactly as it is.

Add four tests to the same class:

```python
    def test_get_names_the_azure_stage_for_an_azure_variable(self):
        with self.assertRaises(secrets.SecretsError) as cm:
            secrets.get("AZDO_PAT", {})
        self.assertIn("setup.sh azure", str(cm.exception))

    def test_get_names_the_stage_for_every_provider_prefix(self):
        for name, stage in (("JIRA_TOKEN", "jira"), ("GH_TOKEN", "github"),
                            ("FIGMA_TOKEN", "figma")):
            with self.subTest(name=name):
                with self.assertRaises(secrets.SecretsError) as cm:
                    secrets.get(name, {})
                self.assertIn(f"setup.sh {stage}", str(cm.exception))

    def test_get_names_the_bare_command_for_a_project_value(self):
        # A project scoped value such as a preview bypass has no stage. Naming
        # one would send the reader to a stage that never writes it.
        with self.assertRaises(secrets.SecretsError) as cm:
            secrets.get("NORTHWIND_BYPASS_HILLCREST", {})
        self.assertIn("setup.sh", str(cm.exception))
        self.assertNotIn("setup.sh azure", str(cm.exception))

    def test_an_empty_value_reads_as_missing(self):
        # The old behaviour, pinned. A key with no value is a half-finished
        # setup, and treating it as present sends an empty credential.
        with self.assertRaises(secrets.SecretsError):
            secrets.get("GH_TOKEN", {"GH_TOKEN": ""})
```

Keep `test_get_names_the_missing_variable_and_the_setup_script` as it is: it
still passes and it pins the variable name in the message.

**Verify**: `python3 -m unittest discover -s tests -t tests` prints `OK` with
451 tests.

### Step 4: Make the wizard ask for one provider at a time

In `scripts/setup.sh`, change the default stage list and the help text.

Replace the comment at lines 156-157 and the default at line 159:

```bash
# Run one step with setup.sh superpowers, azure, jira, github, or figma. Name
# several to run several: setup.sh azure github.
#
# A bare run does the Superpowers stage only. A token stage has to be named,
# because a run needs one provider and the other three questions are noise. The
# skill runs the stage the provider a ticket lives on needs, when it needs it.

WANT="${*:-superpowers}"
```

Replace the last line of the unknown-step message (line 168):

```bash
      say "No argument runs the superpowers step only."
```

**Verify**: `shellcheck scripts/setup.sh` exits 0. Then
`bash -n scripts/setup.sh` exits 0.

### Step 5: Do not report a missing profile as a failed setup

In the closing stage of `scripts/setup.sh`, run `tk doctor` only when at least
one project profile exists.

The live file holds this at lines 343-363. Confirm it matches before you edit,
because the block below replaces all 21 lines:

```bash
stage "Lock the file and run the check"
chmod 600 "$ENV_FILE"
say "Wrote $ENV_FILE with mode 600."
say "tk doctor checks every provider, not only the one you set up now."
say "A gap in another provider is a separate fix, not a fault of this run."
TK="$(dirname "$0")/tk"
if [[ ! -x "$TK" ]]; then
  warn "No tk beside this script at $TK."
  say "Your tokens are saved. Run tk doctor once tk is in place."
  finish
  exit 1
fi

status=0
"$TK" doctor || status=$?
if (( status != 0 )); then
  say "tk doctor found gaps. The output above names each fix."
  finish
  exit "$status"
fi
finish
```

Replace those 21 lines with exactly this. It is complete: paste it, do not fill
anything in.

```bash
stage "Lock the file and run the check"
chmod 600 "$ENV_FILE"
say "Wrote $ENV_FILE with mode 600."
TK="$(dirname "$0")/tk"
if [[ ! -x "$TK" ]]; then
  warn "No tk beside this script at $TK."
  say "Your tokens are saved. Run tk doctor once tk is in place."
  finish
  exit 1
fi

# doctor reads every profile on disk. With none, its answer is "no project
# profiles found", which reads as a failed setup right after a token verified.
# A profile is not this wizard's job: tk init writes one when a ticket needs it.
shopt -s nullglob
profiles=("$HOME/.claude/ticket-workflow/projects"/*/config.json)
shopt -u nullglob
if (( ${#profiles[@]} == 0 )); then
  say "No project profile yet, so there is nothing more to check."
  say "The skill writes one with tk init the first time a ticket needs it."
  finish
  exit 0
fi

say "tk doctor checks every provider, not only the one you set up now."
say "A gap in another provider is a separate fix, not a fault of this run."
status=0
"$TK" doctor || status=$?
if (( status != 0 )); then
  say "tk doctor found gaps. The output above names each fix."
  finish
  exit "$status"
fi
finish
```

Two things moved on purpose. The two `say` lines about `doctor` now sit after
the profile check, because they describe a call that no longer always runs. And
the no-profile branch exits 0 after `finish`, because a saved token with no
profile yet is a successful run.

**Verify**: `shellcheck scripts/setup.sh` exits 0. Then run the wizard's
argument parsing without touching a terminal:

```bash
bash -n scripts/setup.sh && echo syntax-ok
```

### Step 6: Prove the fresh-machine path by hand

This is the behaviour the plan exists for, and no unit test covers the
subprocess boundary. Run it against a throwaway HOME, so your real
`secrets.env` and your real profiles stay untouched.

```bash
TMPHOME="$(mktemp -d)"
mkdir -p "$TMPHOME/.claude/ticket-workflow/projects/scratch"
cat > "$TMPHOME/.claude/ticket-workflow/projects/scratch/config.json" <<'EOF'
{"slug":"scratch","match":{"ticket_patterns":["^[0-9]{4,}$"]},
 "tracker":{"kind":"github","owner":"a","repo":"b"}}
EOF
HOME="$TMPHOME" python3 scripts/tk show 5438;   echo "show exit=$?"
HOME="$TMPHOME" python3 scripts/tk doctor;      echo "doctor exit=$?"
rm -rf "$TMPHOME"
```

**Verify**, against the measured before-state in "Why this matters":

- `show` answers
  `{"error": "secrets", "message": "GH_TOKEN is not set in secrets.env. Run scripts/setup.sh github to add it."}`
  and exits 1. Before this plan it named no variable and no stage.
- `doctor` answers a full report, not one error. It exits 1, `providers.github`
  is `false`, and `fix` holds `scripts/setup.sh github`. Before this plan it
  answered `{"error": "secrets", ...}` and reported nothing.

If `show` still says "no secrets file", `load` was not changed. If `doctor`
still answers a bare error, STOP: something else loads secrets eagerly.

### Step 7: Run the full gate

```bash
python3 -m compileall -q scripts
python3 -m unittest discover -s tests -t tests
shellcheck scripts/setup.sh
```

**Verify**: compile exits 0, the suite prints `OK` with 451 tests, shellcheck
exits 0.

## Test plan

New tests, all in `tests/test_secrets.py`, following the existing file's shape
(a module-level `write` helper for a temp file, one behaviour per test, a
sentence for a name):

1. `test_a_missing_file_answers_with_no_values` — replaces the old raise test.
2. `test_get_names_the_azure_stage_for_an_azure_variable` — the happy path of
   the new mapping.
3. `test_get_names_the_stage_for_every_provider_prefix` — the other three
   prefixes, one subTest each.
4. `test_get_names_the_bare_command_for_a_project_value` — a project scoped
   variable gets no invented stage.
5. `test_an_empty_value_reads_as_missing` — pins existing behaviour that the
   new message must not change.

Unchanged and load-bearing: `test_refuses_a_mode_other_than_600` proves the
mode guard survived step 1.

The wizard has no unit test in this repo. `shellcheck` plus the manual run in
step 6 are its gate.

## Done criteria

ALL must hold:

- [ ] `python3 -m unittest discover -s tests -t tests` prints `OK` with 451 tests
- [ ] The step 6 run: `tk show` names `GH_TOKEN` and `setup.sh github`, and
      `tk doctor` answers a report with a `fix` line instead of one error
- [ ] `python3 -c "import sys; sys.path.insert(0,'scripts'); from tk_lib import secrets; print(secrets.stage_for('AZDO_PAT'), secrets.stage_for('X'))"`
      prints `azure None`
- [ ] `grep -n 'WANT=' scripts/setup.sh` shows `WANT="${*:-superpowers}"`
- [ ] `shellcheck scripts/setup.sh` exits 0
- [ ] `python3 -m compileall -q scripts` exits 0
- [ ] `git status --short` lists only the three files in Scope
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- Any test outside `tests/test_secrets.py` fails after step 1. That would mean
  another module depends on `load` raising for an absent file, which this plan
  assumes nothing does.
- `scripts/tk_lib/verbs.py`, `doctor.py`, or any adapter needs an edit to make
  the suite pass. The change is meant to be contained to `secrets.py`.
- The manual check in step 6 answers with a traceback rather than JSON.
- The closing stage of `scripts/setup.sh` does not match the excerpt closely
  enough to wrap the `tk doctor` call without rewriting the stage.

## Maintenance notes

- `STAGES` is a prefix map. A new provider needs an entry there and a stage in
  `scripts/setup.sh` with the same name. A stage name that does not exist in the
  wizard would print a command that fails, and the wizard refuses an unknown
  argument, so keep the two lists in step.
- A reviewer should check one thing above all: the mode guard in `load` still
  raises. Losing it would let a world-readable `secrets.env` through in silence.
- After this plan, `tk doctor` is a diagnostic and no longer part of any first
  run. Plan 004 removes the last instruction that ran it as a gate.
- Deferred: nothing writes a project profile yet, so a fresh machine still
  cannot finish a ticket. That is plan 003.
