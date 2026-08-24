# Plan 013: Delete the one dead function, and mark the three that wait for a verb

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 00d0bb2..HEAD -- scripts/tk_lib/http.py scripts/tk_lib/util.py scripts/tk_lib/azure.py scripts/tk_lib/cli.py tests`
> If any in-scope file changed since this plan was written, compare the "Current
> state" excerpts against the live code before you proceed. On a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none. Run it last, so it does not conflict with a plan that
  might give one of these functions a caller.
- **Category**: tech-debt
- **Planned at**: commit `00d0bb2`, 2026-08-23

## Why this matters

Four functions have no caller in `scripts/`. Three of them carry about 17 tests.
A repository that advertises its test count as a quality signal pays twice for
that: the tests are maintained, and they make unreachable code look load bearing
to the next reader.

The four are not the same case, so this plan does not treat them the same.

`Http.text` is pure dead weight. Nothing calls it and nothing tests it. Delete
it.

`util.slugify`, `util.expand` and `Azure.identity` are finished, careful, tested
work that sits one verb away from real friction the routine hands to a model
today. `SKILL.md` tells the agent to expand the branch and commit patterns
itself, which is what `expand` and `slugify` do. Profile authoring needs a raw
Azure identity, which is what `Azure.identity` finds. The maintainer read both
proposals in the audit that produced this plan and chose to build neither for
now. Deleting the code would throw away tested behaviour that the next decision
may want, and keeping it silent leaves the reader misled. So this plan does the
smaller, reversible thing: it says in one line, at each definition, that the
function has no caller and why it is kept.

The wire or delete decision stays open, and `plans/README.md` records it.

## Current state

Confirmed by grep across `scripts/` and `tests/` while writing this plan.

`Http.text`, no caller anywhere, no test:

```python
# scripts/tk_lib/http.py:62-64
    def text(self, method, url, body=None, headers=None):
        _, payload, _ = self.raw(method, url, body, headers)
        return payload.decode("utf-8", "replace")
```

`util.slugify` and `util.expand`, called only from `tests/test_shape.py:114-153`,
ten tests:

```python
# scripts/tk_lib/util.py:42-52
def slugify(text, words=5):
    """Lowercase words joined by a dash. Returns an empty string when none survive.

    An accented letter loses the accent and keeps its word whole. A Dutch title
    is the normal case here, so a word like Financiele must not split in two and
    spend two of the word slots.
    """
```

```python
# scripts/tk_lib/util.py:55-65
def expand(pattern, **values):
    """Fills every {name} hole in one pass. An unknown hole stays as it is.

    One pass means a value that holds a brace hole is never rewritten by a later
    key, so the result does not depend on the argument order.
    """
```

`Azure.identity`, called only from `tests/test_azure_write.py:194-247`, seven
tests:

```python
# scripts/tk_lib/azure.py:311-323
    def identity(self, name):
        """One person from a name, or a value that says why there is none.

        This PAT has no Graph scope, so the identities API is closed to it. A
        WIQL query over work items is the only route this token can take.

        One person gives {"id", "name", "unique"}. Nobody gives None. Two
        people give {"ambiguous": [...]}, because picking one of two assigns
        the wrong person and nobody sees it. The two failures need different
        sentences: nobody at all is a spelling to fix, and two people is a
        question for a human. One None for both left the caller unable to tell
        them apart.
        """
```

Why each one is one verb away from being reachable:

- `SKILL.md:107-108` tells the agent to expand `host.branch_pattern` and
  `host.commit_subject` itself. Those two patterns are in
  `examples/projects/northwind/config.json:22-23`.
- `references/profiles.md` requires a raw `id`, `accountId` or `login` in the
  `people` block, and states that a display name is not an identity. The wizard
  writes no identity at all.
- `scripts/tk_lib/cli.py:213-234` raises when it cannot resolve the operator's
  own identity on the host, and names the three places it could go, without
  helping the reader find the value.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Tests | `python3 -m unittest discover -s tests -t tests` | ends with `OK` |
| Caller check | `grep -rn "\.text(" scripts/` | no output |
| Syntax | `python3 -m compileall -q scripts` | exit 0 |

## Scope

**In scope**:
- `scripts/tk_lib/http.py` (delete `text`)
- `scripts/tk_lib/util.py` (two comment lines)
- `scripts/tk_lib/azure.py` (one comment line)

**Out of scope** (do NOT touch):
- `tests/test_shape.py` and `tests/test_azure_write.py`. The tests stay, because
  the functions stay.
- `util.slugify`, `util.expand`, `Azure.identity` themselves. Do not delete them,
  do not rename them, do not change a line of their behaviour.
- Any new verb. Building `tk names` or `tk whois` is a separate decision the
  maintainer has deferred.
- `scripts/tk_lib/cli.py`. Reading it is part of step 2, editing it is not.

## Git workflow

- Branch: `advisor/013-retire-the-unreached-code`
- One commit: `Delete the unused text reader and mark what waits for a verb`
- Do NOT push and do NOT open a pull request unless the operator asks.

## Steps

### Step 1: Delete `Http.text`

Remove the method at `scripts/tk_lib/http.py:62-64`. Check first that nothing
calls it:

- `grep -rn "\.text(" scripts/` → no output
- `grep -rn "\.text(" tests/` → no output

If either prints a line, stop. That is a caller this plan did not find.

**Verify**: `grep -c "def text" scripts/tk_lib/http.py` → `0`
**Verify**: `python3 -m unittest discover -s tests -t tests` → ends `OK` with the
same test count as before

### Step 2: Say that the other three have no caller

Add one line to each docstring, at the end, in the repository's plain style. Keep
it factual: what is true, and what would use it.

For `util.slugify` and `util.expand`, one line each, for example:

```
    No caller in tk today. SKILL.md step 6 has the agent expand
    host.branch_pattern by hand, and this is the function that would do it.
```

For `Azure.identity`:

```
    No caller in tk today. It is the lookup a profile author needs for the
    people block, which no verb offers yet.
```

Write the sentence for the reader who is deciding whether the function is safe to
change. Do not write a promise about a future verb, and do not name a plan
number that does not exist.

**Verify**: `python3 -m compileall -q scripts` → exit 0
**Verify**: `grep -c "No caller in tk today" scripts/tk_lib/util.py scripts/tk_lib/azure.py`
→ `2` for `util.py` and `1` for `azure.py`

## Test plan

No new tests, and no test deleted. The suite must report the same number of tests
as before this plan and still end `OK`, because `Http.text` had none and nothing
else changed.

If the count drops, you deleted a test. Restore it.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -c "def text" scripts/tk_lib/http.py` returns `0`
- [ ] `grep -rn "\.text(" scripts/` prints nothing
- [ ] `grep -c "def slugify\|def expand" scripts/tk_lib/util.py` returns `2`
- [ ] `grep -c "def identity" scripts/tk_lib/azure.py` returns `1`
- [ ] `python3 -m compileall -q scripts` exits 0
- [ ] `python3 -m unittest discover -s tests -t tests` exits 0, ends `OK`, and
      reports the same count as before this plan
- [ ] `git status --porcelain` lists only the three in-scope files
- [ ] the status row for plan 013 in `plans/README.md` is updated

## STOP conditions

Stop and report back, do not improvise, if:

- `grep` finds a caller for any of the four functions. One of the earlier plans
  may have wired it, which changes this plan entirely.
- You believe the three kept functions should be deleted after all. Say so in
  your report with your reasoning. Do not delete them. The maintainer owns that
  call, and the audit that produced this plan asked and got "not now".
- The test count changes in either direction.

## Maintenance notes

- The open decision: build `tk names` and `tk whois`, or delete these three
  functions with their tests. `plans/README.md` records it under the rejected and
  deferred findings, so it is not re-audited from scratch.
- Deleting is cheap to do later and the history holds the code either way. The
  reverse, rebuilding a tested WIQL identity lookup with its quote escaping, is
  not cheap.
- A reviewer should check that the added lines state a fact and do not read as a
  promise. A comment that promises a verb ages badly.
