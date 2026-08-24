# Plan 007: Pin the exit code of every verb that changes a ticket

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 00d0bb2..HEAD -- scripts/tk_lib/verbs.py tests/test_verbs.py`
> If either file changed since this plan was written, compare the "Current state"
> excerpts against the live code before you proceed. On a mismatch, treat it as a
> STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none. Run after `plans/003-bound-and-classify-requests.md`
  because that plan also adds tests to `tests/test_verbs.py`.
- **Category**: tests
- **Planned at**: commit `00d0bb2`, 2026-08-23

## Why this matters

The whole routine rests on one contract, stated in `README.md`: exit 0 means
done, exit 1 means error. Four lines in `verbs.py` turn an adapter's `ok` flag
into that exit code, and not one of them is exercised by a test. They are exactly
the verbs that change a ticket: `comment`, `state`, `assign` and `pr comment`.

The adapters are well covered. Each one computes `ok` by reading back what the
server stored, and those read-backs are pinned in three large test files. The
layer that turns `ok` into an exit code is not covered at all. If `_comment`
returned 0 for `ok: False`, the agent would record a comment that was never
stored, mark the ticket done, and move on. No later phase would catch it.

This plan adds no production code. It closes the gap between a tested adapter and
an untested exit code.

## Current state

The four unexercised lines:

```python
# scripts/tk_lib/verbs.py:154-157
    _, adapter, ticket, _ = _context(args.ticket, args.slug)
    result = adapter.comment(ticket, cli.read_body(args.body_file))
    cli.emit(result)
    return 0 if result.get("ok") else 1
```

```python
# scripts/tk_lib/verbs.py:178-185
    profile, adapter, ticket, _ = _context(args.ticket, args.slug)
    item_type = args.item_type or adapter.show(ticket)["type"]
    if args.gate:
        result = cli.apply_gate(profile, adapter, ticket, item_type)
    else:
        result = cli.apply_bucket(profile, adapter, ticket, args.bucket, item_type)
    cli.emit(result)
    return 0 if result.get("ok") else 1
```

```python
# scripts/tk_lib/verbs.py:196-200
    profile, adapter, ticket, _ = _context(args.ticket, args.slug)
    who = cli.person(profile, args.owner) or args.owner
    result = adapter.assign(ticket, who)
    cli.emit(result)
    return 0 if result.get("ok") else 1
```

```python
# scripts/tk_lib/verbs.py:248-251
    cli.emit(result)
    if isinstance(result, dict) and result.get("ok") is False:
        return 1
    return 0
```

What the tests cover today:

- `tests/test_verbs.py` never calls `cli.VERBS["comment"]` or
  `cli.VERBS["assign"]`.
- The state verb is called only for its two pre-flight refusals, which return
  before any profile load. Those are at `scripts/tk_lib/verbs.py:173-177`.
- The pull request double defines three methods only, so `pr comment` and
  `pr attach` never run:

```python
# tests/test_verbs.py:461-478
class FakeHost:
    """The pull request half of an adapter. It records what the verb sent."""

    def __init__(self):
        self.calls = []

    def pr_create(self, head, title, body, base=None, links=(), reviewer=None):
        self.calls.append(("create", head, title, body, base, list(links), reviewer))
        return {"id": 7, "url": "u", "linked": [], "unlinked": [], "refused": [],
                "reviewer_ok": None}

    def pr_threads(self, pr, me=None):
        self.calls.append(("threads", pr, me))
        return []

    def pr_describe(self, pr, body):
        self.calls.append(("describe", pr, body))
        return {"ok": True, "stored": body, "unlinked": []}
```

The two harnesses to reuse. A tracker double that records calls:

```python
# tests/test_verbs.py:61-71
class Recorder:
    def __init__(self):
        self.calls = []

    def state(self, ticket, value, item_type=None):
        self.calls.append(("state", ticket, value, item_type))
        return {"ok": True, "stored": value}

    def assign(self, ticket, who):
        self.calls.append(("assign", ticket, who))
        return {"ok": True, "stored": who}
```

And the patching pattern a verb test uses:

```python
# tests/test_verbs.py:482-506
    def setUp(self):
        self.host = FakeHost()
        self.enterContext(mock.patch.object(verbs.secrets, "load", lambda: GH_ONLY))
        self.enterContext(mock.patch.object(verbs.config, "load_all",
                                            lambda: {"globex": MIXED}))
        self.enterContext(mock.patch.object(
            verbs.cli, "host_adapter_for", lambda p, v, c=None: self.host))

    def no_tracker(self):
        """Fails the test when the verb builds the tracker adapter."""
        def build(*args, **kwargs):
            raise AssertionError("the pr verb built the tracker adapter")

        self.enterContext(mock.patch.object(verbs.cli, "adapter_for", build))

    def body_file(self, text):
        path = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()), "b.md")
        path.write_text(text, encoding="utf-8")
        return str(path)
```

Test conventions in this repository: one behaviour per test, a name that reads as
a sentence, and a comment naming the defect the test defends. Adapter tests call
`assert_drained()`; verb tests use doubles instead, because the verb layer is
what is under test.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Tests | `python3 -m unittest discover -s tests -t tests` | ends with `OK` |
| Verbs only | `python3 -m unittest discover -s tests -t tests -k Verb` | `OK` |

## Scope

**In scope**:
- `tests/test_verbs.py`

**Out of scope** (do NOT touch):
- `scripts/tk_lib/**`. This plan changes no production code. If a test you write
  fails because the production code is wrong, that is a finding to report, not
  an edit to make.
- The `pr create` answer. It carries no `ok` key on purpose. `SKILL.md` names all
  six keys it does carry and states that a refused reviewer does not fail the
  pull request. Do not add an `ok` assertion for `pr create`.
- The existing `TestStateVerb` refusal tests. Keep them and add beside them.

## Git workflow

- Branch: `advisor/007-test-the-write-verbs`
- One commit: `Pin the exit code of every verb that changes a ticket`
- Do NOT push and do NOT open a pull request unless the operator asks.

## Steps

### Step 1: Give the pull request double its two missing methods

Add to `FakeHost`, matching the existing style and the real adapter signatures
in `scripts/tk_lib/azure.py:501` and `scripts/tk_lib/azure.py:538`:

```python
    def pr_comment(self, pr, text, reply_to=None):
        self.calls.append(("comment", pr, text, reply_to))
        return dict(self.reply)

    def pr_attach(self, pr, path):
        self.calls.append(("attach", pr, path))
        return dict(self.attachment)
```

Give the class two attributes a test can set before the call, defaulting to
success, so one double serves both the pass and the fail case. Keep the default
answers in the shape the real adapters return: `pr_comment` answers `ok` and
`stored`, `pr_attach` answers `url`, `ok` and `markdown`.

**Verify**: `python3 -m unittest discover -s tests -t tests -k Verb` → `OK`

### Step 2: Test the tracker write verbs

Add one test class per verb, or one class with clear test names. For each of
`comment`, `state --bucket`, `state --gate` and `assign`, write two tests:

- the adapter answers `ok: True`, the verb exits 0, and stdout holds the
  adapter's answer
- the adapter answers `ok: False`, the verb exits 1, and stdout still holds the
  answer, because the routine reads `stored` to see what landed

Use the `Recorder` class for `state` and `assign`. Extend it with a `comment`
method rather than writing a second double, and let each test set the answer it
wants. Patch `verbs.secrets.load`, `verbs.config.load_all` and
`verbs.cli.adapter_for` the way `TestPrVerb.setUp` does. Build the body file with
the `body_file` helper.

For `state`, also pin the extra read: with no `--type`, the verb calls
`adapter.show(ticket)["type"]` once, and with `--type Task` it calls `show` not
at all. That read costs a full ticket fetch on Azure, every comment page
included, so a change that made it unconditional would be expensive and silent.

**Verify**: `python3 -m unittest discover -s tests -t tests` → ends `OK`

### Step 3: Test the pull request write actions

For `pr comment` and `pr attach`, write the same pair of tests each: `ok: True`
exits 0, `ok: False` exits 1.

Add one more for the shape carve-out: an answer with no `ok` key at all exits 0.
That is what `pr create` returns, and `verbs.py:249` tests `is False` on purpose
rather than truthiness. A test that pins it stops a future simplification from
turning a successful pull request into exit 1.

**Verify**: `python3 -m unittest discover -s tests -t tests` → ends `OK`

## Test plan

The tests are the deliverable. Counting the cases above: two each for comment,
state by bucket, state by gate, assign, pr comment and pr attach, plus the two
`show` call-count tests and the missing-`ok` test. That is 15 new tests.

Every one asserts an observable contract: the process exit code and the JSON on
stdout. None asserts on an internal call unless the call itself is the contract,
which is the case only for the two `show` tests.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -c "pr_comment\|pr_attach" tests/test_verbs.py` returns at least 4
- [ ] `grep -c "VERBS\[\"comment\"\]" tests/test_verbs.py` returns at least 2
- [ ] `grep -c "VERBS\[\"assign\"\]" tests/test_verbs.py` returns at least 2
- [ ] `python3 -m unittest discover -s tests -t tests` exits 0 and ends `OK`
- [ ] the suite reports at least 15 tests more than before this plan
- [ ] `git status --porcelain` lists only `tests/test_verbs.py`
- [ ] the status row for plan 007 in `plans/README.md` is updated

## STOP conditions

Stop and report back, do not improvise, if:

- A test you wrote from this plan fails against the current production code.
  That means a real defect. Report the verb, the expected exit code and the
  actual one. Do not change `scripts/tk_lib/verbs.py` to make it pass.
- `cli.apply_bucket` refuses your fixture profile. It raises for an unknown
  bucket name and for a bucket whose assignee role has no identity in the
  `people` block. Use a profile that satisfies both, such as the `PROFILE`
  constant the existing bucket tests use at `tests/test_verbs.py:74-95`.
- The state verb needs a real network call to resolve `item_type`. It should
  not: the double answers `show`.

## Maintenance notes

- A sixth write verb must arrive with the same pair of tests. The exit code is
  the contract the agent reads, so an untested one is an untested promise.
- If `pr create` ever gains an `ok` key, the missing-`ok` test in step 3 becomes
  wrong and `SKILL.md` needs the same edit. They are one decision.
- A reviewer should check that no test asserts on a mock's internals where the
  exit code would do. The exit code is what the routine reads.
