# Plan 001: Run the test suite automatically on every push and pull request

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 00d0bb2..HEAD -- .github tests scripts`
> If any of those paths changed since this plan was written, compare the
> "Current state" facts against the live repository before you proceed. On a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `00d0bb2`, 2026-08-23

## Why this matters

This repository is a CLI whose whole value is being correct across three
trackers and two pull request hosts. Every change today rests on a person
remembering to run one command. The test suite is the cheapest CI that can
exist: it needs no dependency install, no service container, no secret, and no
network, and it finishes in about 0.04 seconds. There is no workflow file at
all. This plan adds the gate. Later plans in this directory change the request
layer, the adapters and the wizard, and each one is safer with an automatic
check behind it.

## Current state

- `.github/` does not exist. A glob over `.github/**` returns nothing.
- `README.md` has a "Tests" section that names one command:
  `python3 -m unittest discover -s tests -t tests`.
- `tests/helpers.py:1-5` puts `scripts/` on `sys.path` itself:

```python
# tests/helpers.py:1-5
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
```

- `tests/helpers.py:31-38` states that the harness imports nothing from
  `tk_lib` and replays queued responses, so no test opens a socket.
- `scripts/tk:1-13` needs no install step. It inserts its own directory on
  `sys.path` and calls `cli.main()`.
- The floor is Python 3.11. Tests call `self.enterContext`, added in 3.11. One
  example is `tests/test_verbs.py:484`:

```python
# tests/test_verbs.py:484
self.enterContext(mock.patch.object(verbs.secrets, "load", lambda: GH_ONLY))
```

- The workstation that generated this plan runs Python 3.14.2, so the floor and
  the current release are the two versions worth testing.
- There is no `pyproject.toml`, `setup.cfg`, lint config, or `Makefile`. Do not
  add one. This repository is deliberately standard library only, stated in
  `README.md` under "Requirements".

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Tests | `python3 -m unittest discover -s tests -t tests` | ends with `OK`, 388 tests |
| Syntax | `python3 -m compileall -q scripts` | exit 0, no output |
| Workflow text | `grep -c "unittest discover" .github/workflows/test.yml` | `1` |

Run every command from the repository root.

## Scope

**In scope** (the only files you should create or modify):
- `.github/workflows/test.yml` (create)

**Out of scope** (do NOT touch, even though they look related):
- `scripts/setup.sh`. It has dead functions that `shellcheck` reports. Plan 005
  fixes those and adds the `shellcheck` step to this workflow. Adding that step
  now would make the first CI run red for a reason this plan does not fix.
- Any test file. This plan changes no behaviour and needs no new test.
- `README.md`. Plan 010 owns every documentation edit.
- Any linter, formatter, or type checker. The code is standard library only and
  consistently formatted. A checker would find close to nothing here, so the
  cost is not paid back.

## Git workflow

- Branch: `advisor/001-ci-test-gate`
- One commit. Message style matches `git log`: sentence case, imperative, no
  prefix. Example from history: `Add use cases and limits to the readme`.
  Use: `Run the test suite on every push and pull request`.
- Do NOT push and do NOT open a pull request unless the operator asks.

## Steps

### Step 1: Write the workflow file

Create `.github/workflows/test.yml` with this content:

```yaml
name: tests

on:
  push:
  pull_request:

jobs:
  unittest:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        # 3.11 is the floor README.md states, and the floor the tests need:
        # they call unittest's enterContext, added in 3.11. 3.14 is the release
        # the maintainer runs. Two ends of the range catch a change that only
        # one of them would.
        python-version: ["3.11", "3.14"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      # No install step. This project has no dependencies, so there is nothing
      # to cache and nothing to resolve.
      - name: Compile every module
        run: python3 -m compileall -q scripts
      - name: Run the suite
        run: python3 -m unittest discover -s tests -t tests
```

Keep the comments. This repository explains why in a comment beside the code,
and a bare matrix invites someone to add a version the tests cannot run on.

**Verify**: `grep -c "unittest discover" .github/workflows/test.yml` → `1`

### Step 2: Run locally what the workflow runs

Run both commands from the repository root, in this order.

**Verify**: `python3 -m compileall -q scripts` → exit 0, no output
**Verify**: `python3 -m unittest discover -s tests -t tests` → ends with `OK`
and reports 388 tests

## Test plan

No new tests. This plan adds no runtime code path, so there is no behaviour to
defend. The workflow itself is verified by running the same two commands
locally, and by the first push to GitHub, which is outside this plan.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `.github/workflows/test.yml` exists
- [ ] `grep -c "unittest discover" .github/workflows/test.yml` returns `1`
- [ ] `python3 -m compileall -q scripts` exits 0
- [ ] `python3 -m unittest discover -s tests -t tests` exits 0 and reports 388 tests
- [ ] `git status --porcelain` lists only `.github/workflows/test.yml`
- [ ] the status row for plan 001 in `plans/README.md` is updated

## STOP conditions

Stop and report back, do not improvise, if:

- `.github/` already holds a workflow. Another person added CI and this plan
  needs rewriting against it.
- The suite does not pass at HEAD before you change anything. This plan assumes
  a green baseline, and a red one is a different problem.
- The suite reports a number other than 388. Some other plan landed first. Note
  the number and continue only if the run ends `OK`.
- You are tempted to add a lint, format, or type check step. That is out of
  scope for a reason stated above.

## Maintenance notes

- Plan 005 adds a `shellcheck scripts/setup.sh` step to this same file, after
  it removes the dead functions in the wizard. Keep the step list in the order
  cheap-to-slow so a failure surfaces fast.
- When a plan in this directory adds a test, the 388 in the done criteria of
  later plans moves. The workflow itself needs no edit for that.
- A reviewer should check the matrix still names the floor in
  `README.md` under "Requirements". If the README floor rises, this file
  changes with it.
