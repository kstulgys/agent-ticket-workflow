# Plan 006: Refuse a malformed profile with the documented error, not a traceback

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 00d0bb2..HEAD -- scripts/tk_lib/config.py scripts/tk_lib/doctor.py tests/test_config.py`
> If any in-scope file changed since this plan was written, compare the "Current
> state" excerpts against the live code before you proceed. On a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none. Run after `plans/003-bound-and-classify-requests.md` if
  that plan is still open, because both plans read the same error table.
- **Category**: bug
- **Planned at**: commit `00d0bb2`, 2026-08-23

## Why this matters

Both `README.md` and `SKILL.md` promise that every failure prints a fixed code
under `error` and a sentence under `message`, and the routine tells the agent to
switch on that code. A hand edited `config.json` that is valid JSON but not an
object breaks that promise. `json.load` succeeds, the `BadProfile` guard passes,
and the next line raises `TypeError`, which the error table does not hold. The
result is a traceback on stderr and nothing on stdout.

Every verb starts by loading every profile, so one malformed file disables the
whole CLI, `doctor` included. `doctor` is the verb whose job is to find a broken
setup, and this is the one setup error it cannot report.

A second shape has the same effect for a different reason. A profile whose
`tracker` is a string rather than an object reaches `doctor` line 36, which calls
`.get("kind")` on it. That call sits outside the `_row` guard that keeps one bad
project from taking down the sweep, so the whole report dies with
`AttributeError`.

## Current state

```python
# scripts/tk_lib/config.py:45-61
        path = os.path.join(directory, "config.json")
        if not os.path.exists(path):
            # The skip stays, but it is no longer silent. A profile that fails
            # to load stops competing for its ticket pattern. That can turn a
            # refusal into a confident wrong answer.
            sys.stderr.write(f"skipped {directory}, it holds no config.json\n")
            continue
        with open(path, encoding="utf-8") as fh:
            try:
                profile = json.load(fh)
            except ValueError as error:
                # The default message gives no file name, and a person with
                # several profiles cannot tell which file to repair.
                raise BadProfile(f"{path} is not valid JSON: {error}") from error
        profile["_dir"] = directory
        profiles[slug] = profile
    return profiles
```

Line 59, `profile["_dir"] = directory`, is the crash site. A list, a string or a
number all reach it.

```python
# scripts/tk_lib/config.py:29-30
class BadProfile(ValueError):
    """A profile on disk that this tool cannot read."""
```

`BadProfile` already has an entry in the error table, mapped to `profile`:

```python
# scripts/tk_lib/cli.py:58-68
    return ((config.Ambiguous, "ambiguous"),
            (config.Unresolved, "unresolved"),
            (secrets.SecretsError, "secrets"),
            (http.HttpError, "http"),
            (config.BadProfile, "profile"),
            (KeyError, "profile"),
            ...
```

The unguarded reads in `doctor`:

```python
# scripts/tk_lib/doctor.py:36-42
        units = [("tracker", cli.provider_of((profile.get("tracker") or {})
                                             .get("kind")),
                  adapters.get(slug))]
        if (hosts or {}).get(slug) is not None:
            units.append(("host", cli.provider_of((profile.get("host") or {})
                                                  .get("kind")),
                          hosts[slug]))
```

The same `.get` on a block that could be a non-object also appears at
`scripts/tk_lib/cli.py:129`, `cli.py:160-161`, `cli.py:202-208` and
`scripts/tk_lib/config.py:95`. One guard at load time covers all of them, which
is why this plan puts it there and not at each read.

Convention to follow: a refusal names the file to repair and the key to fix. See
the `BadProfile` message above, and `scripts/tk_lib/jira.py:62-74`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Tests | `python3 -m unittest discover -s tests -t tests` | ends with `OK` |
| Config only | `python3 -m unittest discover -s tests -t tests -k Config` | `OK` |
| Syntax | `python3 -m compileall -q scripts` | exit 0 |

## Scope

**In scope**:
- `scripts/tk_lib/config.py` (`load_all` only)
- `tests/test_config.py`

**Out of scope** (do NOT touch):
- `scripts/tk_lib/cli.py`. Do not add `TypeError` or `AttributeError` to the
  error table. Those two classes are how a real internal bug announces itself,
  and mapping them to `profile` would label a code defect as a user's
  configuration mistake. The guard at load time is precise and this is not.
- `scripts/tk_lib/doctor.py`. Once `load_all` refuses a non-object block, the
  reads at lines 36 to 42 cannot meet one.
- The missing `config.json` branch at `config.py:46-51`. The warning there is
  deliberate and its comment says why.
- Any schema validation beyond the block types listed in step 1. A profile with
  a wrong value inside a correct block is plan 012's subject.

## Git workflow

- Branch: `advisor/006-refuse-a-malformed-profile`
- One commit: `Refuse a profile that is not an object`
- Do NOT push and do NOT open a pull request unless the operator asks.

## Steps

### Step 1: Guard the shape at load time

In `scripts/tk_lib/config.py`, after the `json.load` block and before
`profile["_dir"] = directory`, refuse anything that is not an object, then
refuse a block that is present and not an object.

Target shape:

```python
        if not isinstance(profile, dict):
            # Valid JSON is not a valid profile. A list or a string clears the
            # guard above and then crashes on the assignment below, and a
            # traceback is the one answer this CLI promises never to give.
            raise BadProfile(
                f"{path} holds {type(profile).__name__}, not an object. "
                "A profile is a JSON object. See references/profiles.md.")
        for block in ("match", "tracker", "host", "buckets", "people",
                      "link_rules", "deploy_gate", "preview"):
            if block in profile and not isinstance(profile[block], dict):
                # doctor reads tracker.kind outside its own guard, so a string
                # here takes down the whole report rather than one row.
                raise BadProfile(
                    f"{path} has {block} as {type(profile[block]).__name__}, "
                    "not an object. See references/profiles.md.")
```

Keep the block list in the order `references/profiles.md` documents them, so a
reader can compare the two.

**Verify**: `python3 -m compileall -q scripts` → exit 0

### Step 2: Prove the refusal reaches the caller as JSON

Add tests to `tests/test_config.py`. The existing helper `tmp_profile` in
`tests/helpers.py:72-78` takes a dict and cannot write a malformed file, so
write these files directly with `pathlib`, creating
`<root>/projects/<slug>/config.json` by hand.

Cases:

- a `config.json` holding `[]` raises `config.BadProfile`, and the message names
  the path
- a `config.json` holding `"azure"` raises `config.BadProfile`
- a profile whose `tracker` is the string `"azure"` raises `config.BadProfile`,
  and the message names `tracker`
- a well formed profile still loads, and `_dir` is set. If an existing test
  already covers this, do not add a second one.

Then add one test that proves the contract the routine depends on: a malformed
profile makes a guarded verb print `{"error": "profile", ...}` and exit 1, not a
traceback. Drive `cli.VERBS["resolve"]` with `config.ROOT` patched to the
temporary root, capture stdout the way `tests/test_verbs.py` does with
`contextlib.redirect_stdout`, and assert both the code and the exit status.

Give each test a comment naming the defect: before this, one hand edited file
took down every verb with a traceback.

**Verify**: `python3 -m unittest discover -s tests -t tests` → ends `OK`, count
is the previous count plus the tests you added

## Test plan

Covered in step 2. Model the file layout on `tests/helpers.py:72-78` and the
stdout capture on the guarded tests at `tests/test_verbs.py:271`. The last test
is the important one, because it asserts the observable contract, the printed
code and the exit status, rather than the exception class.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "isinstance(profile, dict)" scripts/tk_lib/config.py` returns one line
- [ ] `python3 -m compileall -q scripts` exits 0
- [ ] `python3 -m unittest discover -s tests -t tests` exits 0 and ends `OK`
- [ ] this command prints a JSON object with `"error": "profile"` and exits 1:
      `mkdir -p /tmp/tkp/projects/x && echo '[]' > /tmp/tkp/projects/x/config.json && python3 -c "import sys; sys.path.insert(0,'scripts'); from tk_lib import cli, config; config.ROOT='/tmp/tkp'; sys.exit(cli.main(['resolve','59644']))"; echo "exit=$?"`
- [ ] no `TypeError` or `AttributeError` entry was added to
      `scripts/tk_lib/cli.py`
- [ ] `git status --porcelain` lists only the two in-scope files
- [ ] the status row for plan 006 in `plans/README.md` is updated

## STOP conditions

Stop and report back, do not improvise, if:

- An existing test writes a profile with a block that is not an object, for
  example `"preview": null`. A `null` is not a dict, so the new guard would
  refuse it. `null` may be a legitimate way to say "no preview", and if a
  fixture or `references/profiles.md` uses it, the guard must allow `None`.
  Report the file and line before you change either side.
- The block list needs a name that `references/profiles.md` does not document.
- The final done criteria command prints a traceback rather than JSON.

## Maintenance notes

- A new top level profile block must be added to the list in step 1, or a wrong
  type in it will crash somewhere far from the file that holds it.
- The guard runs on every verb, because every verb loads every profile. It is
  two `isinstance` checks per profile, so the cost is not measurable.
- A reviewer should confirm the message names the file path. The whole value of
  `BadProfile` over a bare `TypeError` is that the reader learns which file to
  repair.
