# Plan 005: Make the first wizard run work, and print the summary it already builds

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 00d0bb2..HEAD -- scripts/setup.sh .github/workflows/test.yml`
> If either file changed since this plan was written, compare the "Current state"
> excerpts against the live code before you proceed. On a mismatch, treat it as a
> STOP condition.
>
> **Safety rule for this plan**: `scripts/setup.sh` writes the operator's real
> token file at `$HOME/.claude/ticket-workflow/secrets.env`, and it installs a
> Claude Code plugin. Never run the wizard, or any stage of it, while you work
> on this plan. Every verification below uses `bash -n`, `shellcheck`, or the
> library half of the file sourced in a subshell with a temporary `ENV_FILE`.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: `plans/001-ci-test-gate.md`. Step 5 adds a step to the workflow
  file that plan 001 creates.
- **Category**: dx
- **Planned at**: commit `00d0bb2`, 2026-08-23

## Why this matters

The wizard is the first thing a new user runs, and its Azure and Jira stages are
aimed at the example organisations from this repository's own fixtures. So the
wizard opens the token page of an organisation the user does not belong to, then
verifies the pasted token against that same organisation, then prints "The token
did not verify. Check the scopes, then run this stage again." A correct token is
reported as broken, and nothing on screen names the variable to set. This is the
highest cost defect in the repository for a person setting it up.

Two smaller faults sit in the same file. The wizard builds a closing summary and
never prints it, because nothing calls `finish`. The one gap the comment calls
unreportable, a failed Superpowers plugin install, is recorded into `SKIPPED` and
then discarded, and the warning that did print is wiped by the next stage's
screen clear. And `write_env` leaves a full copy of the token file behind if the
run is interrupted, because there is no trap.

## Current state

The stage section starts after the marker at `scripts/setup.sh:182-185`. The
library above it is generated code, marked "do not hand-edit". This plan edits
both halves, which is allowed, but keep the edits minimal and keep the marker.

The two defaults, and the three places they reach:

```bash
# scripts/setup.sh:235-236
AZDO_ORG="${AZDO_ORG:-northwind}"
JIRA_SITE="${JIRA_SITE:-globex.atlassian.net}"
```

```bash
# scripts/setup.sh:283
  open_url "https://dev.azure.com/$AZDO_ORG/_usersSettings/tokens"
```

```bash
# scripts/setup.sh:288-295
  if curl_cfg user ":$AZDO_PAT" \
      | curl -sf --config - \
        "https://dev.azure.com/$AZDO_ORG/_apis/connectionData?api-version=7.1-preview" \
      | grep -q authenticatedUser; then
    say "Verified. The token reads connectionData."
  else
    say "The token did not verify. Check the scopes, then run this stage again."
  fi
```

```bash
# scripts/setup.sh:308-310
  if curl_cfg user "$JIRA_EMAIL:$JIRA_TOKEN" \
      | curl -sf --config - "https://$JIRA_SITE/rest/api/3/myself" \
      | grep -q accountId; then
```

`northwind` is the example Azure project at
`examples/projects/northwind/config.json:2`, and `globex.atlassian.net` is the
example Jira site at `examples/projects/globex/config.json:10`.

The prompt helper already handles a default and a re-run:

```bash
# scripts/setup.sh:98-111
# ask KEY "Prompt" reads a value into $KEY. Offers the existing .env value as
# a default on re-runs (Enter keeps it). Visible input (non-secret).
ask() {
  local key="$1" prompt="$2" current input
  current=$(_existing "$key" || true)
  if [[ -n "$current" ]]; then
    printf '  %s%s%s %s[Enter keeps current]%s ' "$BOLD" "$prompt" "$RESET" "$DIM" "$RESET"
  else
    printf '  %s%s%s ' "$BOLD" "$prompt" "$RESET"
  fi
  read -r input || true
  [[ -z "$input" && -n "$current" ]] && input="$current"
  printf -v "$key" '%s' "$input"
}
```

The temp file window and the recorded summary:

```bash
# scripts/setup.sh:130-139
write_env() {
  local key="$1" value="$2" tmp
  touch "$ENV_FILE"
  tmp=$(mktemp)
  grep -vE "^${key}=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$ENV_FILE"
  WRITTEN_ENV+=("$key")
  printf '  %s✓ wrote%s %s → %s\n' "$GREEN" "$RESET" "$key" "$ENV_FILE"
}
```

```bash
# scripts/setup.sh:169-180
# finish clears, then shows a closing summary of everything configured.
finish() {
  _clear
  printf '\n%s%s  ✓ Setup complete%s\n' "$BOLD" "$GREEN" "$RESET"
  (( ${#WRITTEN_ENV[@]} ))    && note "wrote ${#WRITTEN_ENV[@]} value(s) to $ENV_FILE: ${WRITTEN_ENV[*]}"
  (( ${#WRITTEN_SECRET[@]} )) && note "set ${#WRITTEN_SECRET[@]} GitHub secret(s): ${WRITTEN_SECRET[*]}"
  if (( ${#SKIPPED[@]} )); then
    printf '\n'; warn "still to do by hand:"
    for s in "${SKIPPED[@]}"; do note "  - $s"; done
  fi
  printf '\n'
}
```

Facts about the current file, each checked by reading it:

- Nothing calls `banner` (defined at `:39`) or `finish` (defined at `:170`). The
  file ends at `:374` with the `tk doctor` call and an `exit`.
- `set_secret` (`:143`), `set_var` (`:157`) and `confirm` (`:84`) have no caller.
  The first two set GitHub Actions secrets through `gh`, which this repository
  never needs. `WRITTEN_SECRET` exists only for them.
- `SKIPPED` is appended at `:262` and `:272`, and read only inside `finish`.
- The safe parts, which this plan must not disturb: `umask 077` and the 0700
  temp directory at `:222-228`, hidden secret input at `:122`, and every
  credential reaching `curl` through `--config -` on a pipe at `:289`, `:309`,
  `:329` and `:349`, which keeps it out of `ps`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Syntax | `bash -n scripts/setup.sh` | exit 0, no output |
| Lint | `shellcheck scripts/setup.sh` | exit 0, no output |
| Library check | see step 4 | prints the summary lines |
| Python tests | `python3 -m unittest discover -s tests -t tests` | ends with `OK` |

If `shellcheck` is not installed, say so in your report and skip that gate. Do
not install it. Step 5 still adds it to CI, where it is available.

## Scope

**In scope**:
- `scripts/setup.sh`
- `.github/workflows/test.yml` (step 5 only, one added step)

**Out of scope** (do NOT touch):
- `scripts/tk_lib/**` and `tests/**`. This plan changes no Python.
- `README.md`. Plan 010 documents the two variables and the new prompts.
- The `curl --config -` pattern, the `umask`, and the temp directory setup.
  They are correct.
- The line `ENV_FILE="$HOME/.claude/ticket-workflow/secrets.env"` at `:209`. Do
  not make it overridable to help you test. Step 4 tests the library half
  without it.

## Git workflow

- Branch: `advisor/005-fix-the-setup-wizard`
- Commit per step. Suggested first message:
  `Ask for the organization the wizard verifies against`
- Do NOT push and do NOT open a pull request unless the operator asks.

## Steps

### Step 1: Ask for the organisation and the site

Delete the two lines at `:235-236`. In the Azure stage, before `open_url`, ask
for the organisation. In the Jira stage, before `open_url`, ask for the site.
Keep the environment variable as the non-interactive path.

Target shape for the Azure stage:

```bash
  # The org names the account this token belongs to, and it reaches the token
  # page and the verify call below. A default cannot be right for anybody, so
  # ask. The value stays out of secrets.env on purpose: tk adds every value in
  # that file to its scrub list, and the org name appears in ordinary output.
  AZDO_ORG="${AZDO_ORG:-}"
  [[ -n "$AZDO_ORG" ]] || ask AZDO_ORG "Your Azure DevOps organization, the name after dev.azure.com/:"
```

Do the same in the Jira stage with `JIRA_SITE` and the prompt
`Your Atlassian site, for example acme.atlassian.net:`.

Then refuse an empty answer rather than building a URL with a hole in it. Put
this immediately after each `ask`:

```bash
  if [[ -z "$AZDO_ORG" ]]; then
    warn "No organization, so this stage cannot open the token page."
    SKIPPED+=("set up the Azure token: re-run scripts/setup.sh azure")
  else
    ... the existing stage body ...
  fi
```

Keep the existing body unchanged inside the `else`. Do the same shape for Jira.

**Verify**: `bash -n scripts/setup.sh` → exit 0
**Verify**: `grep -c "northwind\|globex.atlassian.net" scripts/setup.sh` → `0`

### Step 2: Print the opening frame and the closing summary

Two changes.

First, take the screen clear out of `finish`. Delete the `_clear` line at `:171`
and change the comment above the function to say the summary follows the run
rather than replacing it. The summary must not erase the `tk doctor` output that
prints just before it.

Second, call both functions:

- Add `banner "Ticket workflow setup"` immediately after the `TOTAL_STAGES` loop
  ends at `:233`, so the count is already known.
- Call `finish` on every exit path at the end of the file: before the `exit 1` at
  `:366`, after the `tk doctor` call, and before the `exit "$status"` at `:373`.

**Verify**: `bash -n scripts/setup.sh` → exit 0
**Verify**: `grep -c "^finish$\|  finish$" scripts/setup.sh` → at least `2`

### Step 3: Delete the dead library functions and trap the temp file

Delete `confirm` (`:83-90`), `set_secret` (`:141-154`) and `set_var`
(`:156-167`). Delete the `WRITTEN_SECRET` array at `:28` and its line inside
`finish`, because nothing writes to it once `set_secret` is gone.

In `write_env`, remove the temp file on any exit from the function:

```bash
write_env() {
  local key="$1" value="$2" tmp
  touch "$ENV_FILE"
  tmp=$(mktemp)
  # The copy holds every token saved so far, so an interrupt between the
  # redirect and the mv must not leave it on disk.
  trap 'rm -f "$tmp"' RETURN
  ...
}
```

Confirm `trap ... RETURN` fires in this shell. If it does not, use an explicit
`rm -f "$tmp"` after the `mv` plus a script level
`trap 'rm -f "$TMPDIR"/tmp.*' EXIT INT TERM`, and say in your report which form
you used and why.

**Verify**: `bash -n scripts/setup.sh` → exit 0
**Verify**: `grep -c "set_secret\|set_var\|confirm()\|WRITTEN_SECRET" scripts/setup.sh` → `0`

### Step 4: Exercise the library half safely

The wizard is interactive and writes the operator's real token file, so do not
run it. Source only the library half against a temporary `ENV_FILE`:

```bash
work="$(mktemp -d)"
sed -n '1,181p' scripts/setup.sh > "$work/lib.sh"
ENV_FILE="$work/secrets.env" bash -c '
  source "'"$work"'/lib.sh"
  write_env AZDO_USER dev@example.com
  write_env AZDO_PAT placeholder-not-a-real-token
  SKIPPED+=("install the superpowers plugin")
  finish
'
cat "$work/secrets.env"
rm -rf "$work"
```

Adjust the line range if your edits moved the marker. Find it with
`grep -n "STAGES: author this section" scripts/setup.sh` and use the line above
it.

**Verify**: the run prints "Setup complete", one line naming 2 values written,
and a "still to do by hand" line naming the plugin. `cat` shows both keys in the
temp file, and no temp copy is left in `$work`.

### Step 5: Add the shell lint step to CI

In `.github/workflows/test.yml`, add one step to the existing job, after the
compile step and before the suite:

```yaml
      - name: Lint the wizard
        run: shellcheck scripts/setup.sh
```

`shellcheck` is preinstalled on `ubuntu-latest`. Plan 001 deliberately left this
step out, because the dead functions this plan deletes were the findings that
would have made the first CI run red.

**Verify**: `shellcheck scripts/setup.sh` → exit 0, if `shellcheck` is available
locally. If a warning remains that this plan did not cause, report it and do not
silence it with a directive comment.

## Test plan

This file has no test harness, and adding a bash test framework to a repository
with no dependencies is not worth the weight. The gates are `bash -n`,
`shellcheck` in CI, and the library exercise in step 4. State in your report
which of the three you ran and what each printed.

The Python suite must stay green, because this plan touches no Python:
`python3 -m unittest discover -s tests -t tests` → ends `OK`, 388 tests, or the
higher count a plan before this one left.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `bash -n scripts/setup.sh` exits 0
- [ ] `grep -c "northwind\|globex.atlassian.net" scripts/setup.sh` returns `0`
- [ ] `grep -c "set_secret\|set_var\|WRITTEN_SECRET" scripts/setup.sh` returns `0`
- [ ] `grep -n "banner " scripts/setup.sh` shows one call, not only the definition
- [ ] `grep -n "trap" scripts/setup.sh` returns at least one line
- [ ] `grep -n "shellcheck" .github/workflows/test.yml` returns one line
- [ ] the step 4 library run prints "Setup complete" and the skipped item
- [ ] `python3 -m unittest discover -s tests -t tests` exits 0
- [ ] `git status --porcelain` lists only the two in-scope files
- [ ] the status row for plan 005 in `plans/README.md` is updated

## STOP conditions

Stop and report back, do not improvise, if:

- You are about to run `scripts/setup.sh`, any stage of it, or any command that
  writes `$HOME/.claude/ticket-workflow/secrets.env`. That is the operator's live
  credential file.
- `shellcheck` reports a finding you cannot fix by deleting dead code, for
  example a quoting warning inside the generated library half. Report it. Do not
  add a `# shellcheck disable` comment.
- `trap ... RETURN` does not fire, and the script level trap you write would
  delete a file the wizard still needs.
- Removing `_clear` from `finish` breaks the layout in a way you cannot judge
  without running the wizard. Report it and leave the clear in place.

## Maintenance notes

- The wizard now has one prompt per provider host. If a fifth provider arrives,
  it needs the same shape: environment variable first, prompt second, refuse an
  empty answer and record it in `SKIPPED`.
- Never write a non-secret into `secrets.env`. `scripts/tk_lib/secrets.py:35-37`
  adds every value in that file to the scrub list, so an organisation name there
  would print as `***` inside ordinary messages.
- Plan 010 documents `AZDO_ORG` and `JIRA_SITE` in the README as the
  non-interactive path. Keep the variable names identical.
- A reviewer should read the two stage bodies and confirm the `else` branch still
  holds the original verification call unchanged.
