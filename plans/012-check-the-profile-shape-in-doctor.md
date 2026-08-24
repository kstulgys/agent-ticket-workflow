# Plan 012: Make `tk doctor` fail a profile whose hand edited fields are still placeholders

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 00d0bb2..HEAD -- scripts/tk_lib/doctor.py scripts/tk_lib/verbs.py tests/test_doctor.py`
> If any in-scope file changed since this plan was written, compare the "Current
> state" excerpts against the live code before you proceed. On a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: LOW
- **Depends on**: `plans/006-refuse-a-malformed-profile.md`. That plan
  guarantees every profile block is an object, so this check can read a block
  without guarding its type.
- **Category**: tests
- **Planned at**: commit `00d0bb2`, 2026-08-23

## Why this matters

`README.md` tells a new user to copy an example profile, edit it, then run
`scripts/tk doctor`, and says exit 0 means every provider answered. The verb
makes exactly two calls per project, an account read and a project data read.
It reads no other field. So a profile whose `repo_id`, `project_id` and
`people` ids are still the example placeholders passes green.

The failure then arrives much later, at `tk pr create`, as a 404 on a
placeholder GUID that reads like a permissions problem. That late failure is the
one this verb exists to prevent: the host row was added for exactly this reason,
and its comment says so.

An Azure Repos host is the worst case, because it gets no row at all. When the
host and the tracker share a provider, the host check is skipped to avoid testing
one token twice, so nothing ever looks at the two GUIDs the pull request route
needs.

The new check needs no network, so it costs nothing and it is easy to test.

## Current state

`doctor` reads two fields from the profile, `tracker.kind` and `host.kind`, and
nothing else:

```python
# scripts/tk_lib/doctor.py:61-82
def _row(slug, role, kind, adapter, fix):
    """One provider row. It appends the fix line for the gap it finds."""
    row = {"slug": slug, "role": role, "provider": kind}
    try:
        who = adapter.whoami()
        row.update(ok=True, name=who.get("name"), id=who.get("id"))
    except Exception as error:
        row.update(ok=False, error=secrets.scrub(error))
        fix.append(f"{SETUP} {kind}" if kind else
                   f"{slug}: the profile names no {role}.kind. "
                   "Add it to config.json.")
    if row.get("ok"):
        try:
            repo = adapter.repo_check()
```

The answer shape, which this plan extends with rows and fix lines only:

```python
# scripts/tk_lib/doctor.py:57-58
    return {"ok": all(row.get("ok") for row in projects),
            "providers": providers, "projects": projects, "fix": sorted(set(fix))}
```

The host row is skipped when host and tracker are one provider:

```python
# scripts/tk_lib/verbs.py:78-88
def _host_is_second_provider(profile):
    """True when the pull request host needs a check of its own.

    The globex profile is a Jira tracker beside a GitHub host, so its GitHub
    token reaches no check through the tracker. The northwind host is azure-repos
    beside an azure tracker: one organization and one token, so the tracker
    check answers for both.
    """
    host = cli.provider_of((profile.get("host") or {}).get("kind"))
    return bool(host) and host != cli.provider_of(
        (profile.get("tracker") or {}).get("kind"))
```

The example profile ships placeholder GUIDs, which is correct for an example and
is exactly what a copied profile keeps:

```json
// examples/projects/northwind/config.json:18-19
  "repo_id": "11111111-1111-1111-1111-111111111111",
  "project_id": "22222222-2222-2222-2222-222222222222",
```

```json
// examples/projects/northwind/config.json:39-42
  "people": {
    "self": { "id": "33333333-3333-3333-3333-333333333333" },
    "reviewer": { "id": "44444444-4444-4444-4444-444444444444" }
  },
```

The identity keys the code reads, one per provider:

```python
# scripts/tk_lib/cli.py:175-178
def _first_id(who):
    """One identity out of one people entry. Azure, Jira, and GitHub in order."""
    who = who or {}
    return who.get("id") or who.get("accountId") or who.get("login")
```

The bucket rule that fails at write time when a role has no identity:

```python
# scripts/tk_lib/cli.py:260-269
    role = bucket.get("assignee")
    who = person(profile, role) if role else None
    if role and not who:
        people = (profile.get("people") or {})
        raise ValueError(
            f"bucket {name} assigns the role {role}, and the people block holds "
            f"no identity for it. Known: {', '.join(sorted(people)) or 'none'}")
```

The test double to reuse:

```python
# tests/test_doctor.py:9-25
class FakeAdapter:
    """Every adapter answers whoami and repo_check, so this fake does too."""

    def __init__(self, who=None, repo=None, error=None):
        self._who, self._repo, self._error = who, repo, error

    def whoami(self):
        if self._error:
            raise RuntimeError(self._error)
        return self._who

    def repo_check(self):
        return self._repo or {"ok": True}
```

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Tests | `python3 -m unittest discover -s tests -t tests` | ends with `OK` |
| Doctor only | `python3 -m unittest discover -s tests -t tests -k Doctor` | `OK` |
| Syntax | `python3 -m compileall -q scripts` | exit 0 |

## Scope

**In scope**:
- `scripts/tk_lib/doctor.py`
- `tests/test_doctor.py`

**Out of scope** (do NOT touch):
- `scripts/tk_lib/verbs.py`. The `_doctor` verb passes the profiles already, and
  `_host_is_second_provider` stays as it is. Its skip is correct for tokens, and
  the new check is not a token check.
- The two existing calls in `_row`. Do not add a network call. Every check this
  plan adds is local.
- `examples/projects/*/config.json`. The placeholders belong in an example.
  Detecting them is the point.
- `cli.apply_bucket`. Its write time refusal stays. This is the same rule checked
  earlier, not a replacement.

## Git workflow

- Branch: `advisor/012-check-the-profile-shape-in-doctor`
- Commit per step. Suggested first message:
  `Check the profile fields no api call touches`
- Do NOT push and do NOT open a pull request unless the operator asks.

## Steps

### Step 1: Add a profile row that needs no network

In `scripts/tk_lib/doctor.py`, add one function that reads a profile and returns
a row in the same shape the provider rows use, plus its fix lines. Give it the
role name `profile`, so a reader can tell it from `tracker` and `host`.

The checks, each one a field no API call touches:

1. Every `buckets.<name>.assignee` role that is set names an entry in `people`.
   `cli.apply_bucket` raises for this at write time, which is one ticket too
   late.
2. Every entry in `people` carries an identity that `cli._first_id` can read,
   which is `id`, `accountId` or `login`.
3. When `host.kind` is `azure-repos`, `host.repo_id` and `host.project_id` are
   both present. The pull request route cannot work without them, and no token
   check reads them.
4. No identity value is a placeholder. A GUID whose hex digits are all the same
   character is the shape the examples ship, so treat that as unset. Write the
   rule as a small helper with a comment naming why it is safe: a real Azure
   identity is never one repeated digit.
5. When `host.local_path` is set, it names a directory that exists. `tk git`
   runs there, and a wrong path fails at push time with a git error rather than
   a profile error.

Each failure appends one fix line that names the file and the key, in the style
the existing fix lines use: a sentence a person can act on.

Then call the function once per profile in `check`, and add its row to
`projects`. Keep the `ok` fold as it is, so one failing row makes the whole
report false. Do not add the profile row to `providers`: that map is keyed by
provider and this row belongs to no provider.

**Verify**: `python3 -m compileall -q scripts` → exit 0

### Step 2: Keep the answer readable

The report grows by one row per project. Confirm two things by reading the code
you wrote:

- `cli.emit` sorts keys and writes JSON, so a row with no `provider` key must
  still be sortable. Give the profile row `"provider": None` if that is what the
  other rows do for an unknown kind, and check `doctor.py:49`, which already
  handles `None` by keying the summary under `unknown`.
- The `fix` list is de-duplicated and sorted at `doctor.py:58`. Write each fix
  line so two projects with the same gap produce two distinct lines, by naming
  the slug in every line.

**Verify**: `python3 -m unittest discover -s tests -t tests -k Doctor` → `OK`

### Step 3: Test each check

Add tests to `tests/test_doctor.py`, reusing `FakeAdapter` so no network is
involved. One test per rule, each asserting the report is not `ok` and the fix
line names the key:

- a bucket assigns a role the `people` block does not hold
- a `people` entry holds a name but no identity key
- an `azure-repos` host has no `repo_id`
- a `people` identity is a repeated digit GUID
- a `host.local_path` that does not exist. Use `tempfile.TemporaryDirectory` for
  the passing case and a path inside it that you did not create for the failing
  one.

Then one test for the whole point of the plan: a profile copied from the example,
with placeholder GUIDs, and both adapter calls answering fine, reports
`ok: False`. Before this plan that profile was green.

Also add one test that a complete, correct profile still reports `ok: True`, so
the new check cannot silently fail every profile.

**Verify**: `python3 -m unittest discover -s tests -t tests` → ends `OK`

## Test plan

Seven tests, listed in step 3. Model them on the existing tests at
`tests/test_doctor.py:29-63`, which already assert on `got["ok"]`,
`got["projects"][0]` and the joined `got["fix"]`. Each new test names the defect
it defends in a comment: a placeholder profile used to pass, and the failure
arrived at `tk pr create` instead.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -c "profile" scripts/tk_lib/doctor.py` returns more than before,
      and the new row uses the role name `profile`
- [ ] `python3 -m compileall -q scripts` exits 0
- [ ] `python3 -m unittest discover -s tests -t tests` exits 0 and ends `OK`
- [ ] the suite reports at least 7 tests more than before this plan
- [ ] no new network call: `grep -c "whoami\|repo_check" scripts/tk_lib/doctor.py`
      is unchanged from before this plan
- [ ] `git status --porcelain` lists only the two in-scope files
- [ ] the status row for plan 012 in `plans/README.md` is updated

## STOP conditions

Stop and report back, do not improvise, if:

- A rule in step 1 would fail a profile that is legitimately incomplete. For
  example a profile with no `host` block at all is valid for a tracker only
  project. The check must distinguish absent from wrong: an absent optional
  block passes, a present block with a missing required key fails. If you cannot
  tell which a key is, read `references/profiles.md` and report what it says.
- The repeated digit GUID rule would reject a real identity. Report the value
  shape, with the digits replaced, and let a reviewer decide.
- `doctor` output becomes hard to read with the extra row. Report it rather than
  hiding the row behind a flag.
- Any check you add needs a network call.

## Maintenance notes

- This row is the place for any future check that needs no token. A check that
  needs one belongs in an adapter's `repo_check`.
- The placeholder rule is tied to the example files. If the examples change their
  placeholder shape, this rule must change with them, and the test in step 3
  will catch that.
- `cli.apply_bucket` keeps its write time refusal. Two checks of one rule is not
  duplication here: one is preflight and one is the last line before a write.
- A reviewer should confirm the report still exits 0 for a correct profile, and
  that every new fix line names both the slug and the key.
