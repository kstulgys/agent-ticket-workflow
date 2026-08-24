# Plan 009: Mask the credential in the form it travels in, and say what the tool guarantees

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 00d0bb2..HEAD -- scripts/tk_lib/secrets.py scripts/tk_lib/http.py scripts/tk_lib/gitcmd.py README.md tests`
> If any in-scope file changed since this plan was written, compare the "Current
> state" excerpts against the live code before you proceed. On a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: `plans/003-bound-and-classify-requests.md` and
  `plans/004-protect-the-attachment-path.md`. Both edit `http.py`, and this plan
  should describe the behaviour those two leave behind.
- **Category**: security
- **Planned at**: commit `00d0bb2`, 2026-08-23

## Why this matters

`README.md` states: "a token never reaches the terminal, a log, or an agent
transcript. No verb prints a secret." The scrubber holds the raw values read
from `secrets.env`, but a credential travels as `Basic <base64>`, which is a
different string that the list never holds. So on every path that does scrub,
the encoded form cannot be masked. The comment in `doctor.py` calls the scrubber
the second line of defence, and for the form the credential actually takes,
there is no second line.

One path does not scrub at all. `tk git` runs git with the credential in an
environment supplied config value and inherits stdout and stderr, so anything
git prints goes straight to the terminal and into the agent transcript. Git
reports environment supplied config beside file config, so a config listing run
through this verb prints the header verbatim.

Neither gap is a live leak in the normal flow: `SKILL.md` step 6 runs fetch,
checkout, commit and push. The defect is that the README makes an absolute
promise the code does not keep. This plan closes the part that is cheap to close
and corrects the sentence to match the rest.

## Current state

```python
# scripts/tk_lib/secrets.py:1-8
"""Read secrets.env. A value never leaves this process in plain text."""
import os
import stat

DEFAULT_PATH = os.path.expanduser("~/.claude/ticket-workflow/secrets.env")
SETUP = "scripts/setup.sh"
SCRUB = []
```

```python
# scripts/tk_lib/secrets.py:35-38
    for value in values.values():
        if len(value) >= 8 and value not in SCRUB:
            SCRUB.append(value)
    return values
```

```python
# scripts/tk_lib/secrets.py:47-55
def scrub(text):
    text = str(text)
    # Mask the longest value first. When one secret contains another, replacing
    # the shorter one first leaves the edges of the longer one in the output. A
    # part mask is worse than no mask, because it looks safe. The sort lives
    # here, not in load, so the order holds even if a caller appends to SCRUB.
    for value in sorted(SCRUB, key=len, reverse=True):
        text = text.replace(value, "***")
    return text
```

```python
# scripts/tk_lib/http.py:96-97
def basic(user, token):
    return "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()
```

```python
# scripts/tk_lib/gitcmd.py:47-51
    env.update({"GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": key,
                "GIT_CONFIG_VALUE_0": "AUTHORIZATION: " + http.basic(user, token),
                "GIT_TERMINAL_PROMPT": "0"})
    return env
```

```python
# scripts/tk_lib/gitcmd.py:74-82
def _default_runner(argv, cwd, env):
    try:
        return subprocess.call(argv, cwd=cwd, env=env)
    except OSError as error:
        sys.stderr.write(secrets.scrub(f"cannot run git: {error}") + "\n")
        return FATAL
```

`subprocess.call` inherits both streams, so git's own output never passes
through `scrub`.

The README sentence to correct:

```markdown
<!-- README.md:150-152 -->
Tokens live in `~/.claude/ticket-workflow/secrets.env`, mode 0600. `tk` reads
that file itself, so a token never reaches the terminal, a log, or an agent
transcript. No verb prints a secret.
```

Test hygiene fact, which this plan must respect: `SCRUB` is process global.
`tests/test_secrets.py:24` and `tests/test_http.py:37` clear it in `setUp` with
no cleanup, while `tests/test_doctor.py:183-184` and `tests/test_verbs.py:363-364`
append with `addCleanup`. Registering a value inside `http.basic` means the
existing test at `tests/test_http.py:149`, which asserts
`http.basic("", "pat") == "Basic OnBhdA=="`, would leave that string in `SCRUB`
for every later test in the process.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Tests | `python3 -m unittest discover -s tests -t tests` | ends with `OK` |
| Secrets only | `python3 -m unittest discover -s tests -t tests -k Secrets` | `OK` |
| Order check | `python3 -m unittest discover -s tests -t tests -k Http && python3 -m unittest discover -s tests -t tests` | both `OK` |
| Syntax | `python3 -m compileall -q scripts` | exit 0 |

## Scope

**In scope**:
- `scripts/tk_lib/secrets.py`
- `scripts/tk_lib/http.py` (`basic` only)
- `scripts/tk_lib/gitcmd.py` (`env_for` only)
- `README.md` (the paragraph at lines 150 to 152 only)
- `tests/test_secrets.py`, `tests/test_http.py`

**Out of scope** (do NOT touch):
- The `len(value) >= 8` floor at `secrets.py:36`. Keep it. A short value would
  mask ordinary words. Step 3 makes the skip visible instead of silent.
- Capturing git's stdout and stderr. Re-emitting them through the scrubber
  would break the progress output of `git push`, which writes partial lines. The
  honest fix is the narrowed sentence in step 4 plus the `tk git` note. If the
  operator later wants filtering, that is its own plan.
- Moving `SCRUB` out of module scope. It is deliberately a process wide masking
  list, and threading it through every call site would cost more than it saves.
- The other README sections. Plan 010 owns them.

## Git workflow

- Branch: `advisor/009-close-the-scrub-gaps`
- Commit per step. Suggested first message:
  `Mask the credential in the form it travels in`
- Do NOT push and do NOT open a pull request unless the operator asks.

## Steps

### Step 1: Give the scrubber a way to learn one more value

In `scripts/tk_lib/secrets.py`, add a function beside `scrub`:

```python
def mask(value):
    """Adds one more value the scrubber must hide. Returns it unchanged.

    load registers what secrets.env holds. A credential travels in another
    form: Basic and a base64 of the pair. That string is not in the file, so
    the list cannot hold it unless the code that builds it says so.
    """
    value = str(value)
    if len(value) >= 8 and value not in SCRUB:
        SCRUB.append(value)
    return value
```

Then use it in `load` in place of the inline append, so one rule lives in one
place.

**Verify**: `python3 -m unittest discover -s tests -t tests -k Secrets` → `OK`

### Step 2: Register the encoded forms where they are built

In `scripts/tk_lib/http.py`, wrap the return of `basic`:

```python
def basic(user, token):
    # The header is the form the credential travels in, and it is not the value
    # secrets.env holds, so register it here or the scrubber cannot see it.
    return secrets.mask("Basic " + base64.b64encode(f"{user}:{token}".encode()).decode())
```

`http.py` already imports `secrets` at line 8.

In `scripts/tk_lib/gitcmd.py`, register the config value too. It is a third
string, `AUTHORIZATION: ` followed by the header:

```python
    header = secrets.mask("AUTHORIZATION: " + http.basic(user, token))
```

Then use `header` in the `env.update` call.

**Verify**: `python3 -m compileall -q scripts` → exit 0

### Step 3: Say when a value is too short to mask

In `mask`, when the value is shorter than the floor, write one line to stderr
naming the variable class rather than the value:

```python
    if len(value) < 8:
        sys.stderr.write(
            "a secret shorter than 8 characters cannot be masked in output\n")
        return value
```

Add `import sys` to the module. Never print the value itself, and never name the
key, because a key name plus a length is already a hint. The message says only
that masking is not available.

**Verify**: `python3 -m unittest discover -s tests -t tests` → ends `OK`

### Step 4: Correct the README paragraph

Replace the sentence "No verb prints a secret." with text that matches the code.
Keep the first two sentences. Add, in the repository's plain style:

- `tk` scrubs every message it prints itself, both the value in `secrets.env`
  and the encoded header built from it.
- `tk git` passes git's own output through untouched, so do not run a git
  command that prints configuration through it. Name `git config --list` as the
  example, since that is the command that would show the header.

Keep it to three sentences or fewer. Do not add a heading.

**Verify**: `grep -c "No verb prints a secret" README.md` → `0`

### Step 5: Keep the test suite order independent

Registering a value inside `basic` means any test that calls it leaves a string
in the global list.

- In `tests/test_http.py`, add `self.addCleanup(secrets.SCRUB.clear)` beside the
  existing `secrets.SCRUB.clear()` in `setUp` at line 37, so the list cannot
  outlive a test either way.
- Do the same in `tests/test_secrets.py` at line 24.
- Add one test proving the new behaviour: after `http.basic("u", "a-long-token")`,
  `secrets.scrub` masks the returned header string.
- Add one test proving the floor: `secrets.mask("short")` leaves `SCRUB`
  unchanged and writes a line to stderr. Capture stderr with
  `contextlib.redirect_stderr`.

**Verify**: `python3 -m unittest discover -s tests -t tests` → ends `OK`, twice
in a row, and also when run with `-k Http` first. A test that passes alone and
fails in the suite is the failure mode this step exists to prevent.

## Test plan

Two new tests in step 5, plus the two cleanup additions. Model them on the
existing scrub tests in `tests/test_secrets.py`. Each asserts an observable
contract: what `scrub` masks, and what `mask` refuses to register.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "def mask" scripts/tk_lib/secrets.py` returns one line
- [ ] `grep -n "secrets.mask" scripts/tk_lib/http.py scripts/tk_lib/gitcmd.py` returns two lines
- [ ] `grep -c "No verb prints a secret" README.md` returns `0`
- [ ] `grep -c "git config" README.md` returns at least `1`
- [ ] `python3 -m compileall -q scripts` exits 0
- [ ] `python3 -m unittest discover -s tests -t tests` exits 0 and ends `OK`
- [ ] the suite passes when run twice in the same session
- [ ] `git status --porcelain` lists only in-scope files
- [ ] the status row for plan 009 in `plans/README.md` is updated

## STOP conditions

Stop and report back, do not improvise, if:

- An existing test asserts on a string that now comes back as `***`. That is the
  masking working, but the assertion has to move, and a reviewer should see
  which one. Report the test name.
- `tests/test_gitcmd.py` asserts the exact `GIT_CONFIG_VALUE_0` value. It should
  still pass, because `mask` returns the value unchanged, but if it fails, stop:
  something else changed.
- You are tempted to capture git's output to make the README sentence true as
  written. That is out of scope, stated above.
- The stderr warning in step 3 fires during a normal test run. That means a
  fixture holds a token shorter than eight characters, and the noise would train
  a reader to ignore the line.

## Maintenance notes

- Any future code that builds a new credential form must call `secrets.mask` on
  it. That function, not the adapter, is now the place that knows what has to
  stay hidden.
- The README paragraph and the code are one decision. If a later plan adds
  output filtering to `tk git`, that sentence changes back.
- A reviewer should confirm no test prints a real token, and that the new stderr
  line never carries a value.
