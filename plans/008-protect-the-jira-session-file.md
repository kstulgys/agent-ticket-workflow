# Plan 008: Write the Jira session file where only its owner can read it

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 00d0bb2..HEAD -- scripts/jira-cookies.py references/jira-cookie-fallback.md`
> If either file changed since this plan was written, compare the "Current state"
> excerpts against the live code before you proceed. On a mismatch, treat it as a
> STOP condition.
>
> **Safety rule for this plan**: this script decrypts live browser cookies. Do
> not run it. Every verification below works on the code, not on a real session.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `00d0bb2`, 2026-08-23

## Why this matters

`scripts/jira-cookies.py` is the documented fallback for an Atlassian
organisation that blocks API tokens, named in
`references/jira-cookie-fallback.md` and in the wizard's Jira stage. It writes a
live Atlassian session to a fixed path in a shared directory, under the process
umask, so on a stock Ubuntu the file lands at mode 0644. A session cookie is a
full account credential and is not limited by the API token scopes. Every local
user and every process on the machine can read it for as long as it exists, and
the only control today is a sentence in the docstring asking the operator to
delete it by hand.

Two smaller faults sit beside it. The write follows a symlink and never closes
its handle. And the cookie query collects every Atlassian host in the browser
profile rather than the one tenant the run needs, so unrelated sessions are
decrypted into the same file.

The tool already holds the standard this file misses: `secrets.py:17-20` refuses
to read `secrets.env` unless it is exactly mode 0600.

## Current state

```python
# scripts/jira-cookies.py:16-17
Security: /tmp/jira-state.json holds LIVE session tokens. Delete it when you finish
(`rm -f /tmp/jira-state.json`) and close the browser — the workflow does this each turn.
```

```python
# scripts/jira-cookies.py:30-32
CHROME = os.path.expanduser("~/.config/google-chrome")
TARGET = "globex.atlassian.net"
OUT = "/tmp/jira-state.json"
```

`globex.atlassian.net` is the example Jira site from
`examples/projects/globex/config.json:10`, so the shipped default matches nobody.

```python
# scripts/jira-cookies.py:78-96
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    state = {"cookies": [], "origins": []}
    for h, n, pa, sec, ho, exp, sm, ev in con.execute(
        "SELECT host_key,name,path,is_secure,is_httponly,expires_utc,samesite,encrypted_value "
        "FROM cookies WHERE host_key LIKE '%atlassian%'"
    ):
        state["cookies"].append(
            {
                "name": n,
                "value": dec(ev),
                ...
            }
        )
    json.dump(state, open(OUT, "w"))
```

Three defects in those lines: the `LIKE '%atlassian%'` filter, the `open(OUT,
"w")` with no mode and no link refusal, and the handle that is never closed.

The comparison this file should match:

```python
# scripts/tk_lib/secrets.py:17-20
        raise SecretsError(f"no secrets file at {path}. Run {SETUP} to create it.")
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode != 0o600:
        raise SecretsError(f"{path} has mode {oct(mode)}. Run: chmod 600 {path}")
```

The configuration directory already exists at mode 0700, created by
`scripts/setup.sh:222-228` with `umask 077`.

This script is standalone. Nothing in `scripts/tk_lib/` imports it, so a change
here cannot break the CLI.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Syntax | `python3 -m py_compile scripts/jira-cookies.py` | exit 0 |
| Usage text | `python3 scripts/jira-cookies.py --help` | prints usage, exits 0 |
| Python tests | `python3 -m unittest discover -s tests -t tests` | ends with `OK` |

The `--help` gate matters: the script imports two third party packages at module
scope today, so it cannot even print its own usage on a machine without them.
Step 1 fixes that as a side effect of adding an argument parser only if the
imports move. Read the STOP conditions first.

## Scope

**In scope**:
- `scripts/jira-cookies.py`
- `references/jira-cookie-fallback.md`

**Out of scope** (do NOT touch):
- `scripts/tk_lib/**` and `tests/**`. This script is not part of `tk`.
- `README.md`. Plan 010 owns the dependency claim in "Requirements".
- The decryption itself at `scripts/jira-cookies.py:70-76`. It is correct and it
  is not this plan's subject.
- Adding a test file for this script. It drives Chrome's cookie database, DBus
  and the login keyring. A unit test would assert against mocks of all three and
  defend nothing real. Its correctness is proved by running it, which
  `references/jira-cookie-fallback.md` already instructs.

## Git workflow

- Branch: `advisor/008-protect-the-jira-session-file`
- Commit per step. Suggested first message:
  `Write the jira session file with mode 0600`
- Do NOT push and do NOT open a pull request unless the operator asks.

## Steps

### Step 1: Take the site from the command line, and put the file in the private directory

Replace the two module constants with values the caller supplies.

- Add `import argparse` and parse two arguments: `--site`, required, and
  `--out`, optional.
- Default `--out` to
  `os.path.expanduser("~/.claude/ticket-workflow/jira-state.json")`. That
  directory is already 0700.
- Delete the `TARGET` and `OUT` constants. Pass the site and the path through to
  the functions that need them, rather than reading a global.
- Keep `CHROME` as a constant, and add one line to the error message at
  `scripts/jira-cookies.py:63` naming the path that was searched, so a user on
  macOS learns why no profile matched instead of reading "log in to Jira first".

Update the docstring at the top of the file: the new usage line, the new default
path, and the security note pointing at the private directory.

**Verify**: `python3 -m py_compile scripts/jira-cookies.py` → exit 0

### Step 2: Narrow the cookie query to the site the caller named

Change the `SELECT` at `scripts/jira-cookies.py:80-83` to filter on the target
host rather than on `%atlassian%`, using a bound parameter as the other query in
this file already does at `scripts/jira-cookies.py:54-57`.

Use `host_key LIKE ?` with `f"%{site}"`, matching the existing style, and add a
comment: a session for another tenant is a credential this run has no reason to
decrypt.

Close the connection when the read is done. The `find_profile` function already
does this at `scripts/jira-cookies.py:58`.

**Verify**: `grep -c "%atlassian%" scripts/jira-cookies.py` → `0`

### Step 3: Write the file so only the owner can read it, and never through a link

Replace `json.dump(state, open(OUT, "w"))` with an explicit descriptor:

```python
    # A session cookie is a full account credential, so the file it lands in
    # gets the same floor secrets.env gets. O_EXCL refuses an existing file and
    # O_NOFOLLOW refuses a symlink, so a planted path cannot redirect the write
    # or leave an old session behind under a mode this run did not set.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        handle = os.open(out_path, flags, 0o600)
    except FileExistsError:
        os.unlink(out_path)
        handle = os.open(out_path, flags, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
```

The unlink then re-open keeps the script re-runnable, which the workflow needs,
while still refusing to write through a link. Add that reason to the comment.

**Verify**: `grep -c "O_NOFOLLOW" scripts/jira-cookies.py` → `1`
**Verify**: `grep -c "open(OUT" scripts/jira-cookies.py` → `0`

### Step 4: Update the reference page

In `references/jira-cookie-fallback.md`:

- replace every `/tmp/jira-state.json` with the new default path
- replace the "edit that constant" instruction with the `--site` argument, since
  a tracked file loses a hand edit on the next `git pull`
- keep the sentence that names `secretstorage` and `cryptography`. It is correct
  and plan 010 makes the README agree with it.
- add one line telling the operator to sign out of Jira, not only delete the
  file, when a session has been written. Deleting the file does not invalidate
  the session.

**Verify**: `grep -c "/tmp/jira-state.json" references/jira-cookie-fallback.md scripts/jira-cookies.py` → `0` for both files

## Test plan

No automated test, for the reason stated in "Out of scope". The gates are the
three commands in the table, plus one manual read: confirm the new
`os.open` call cannot be reached with `out_path` still holding the old `/tmp`
default.

State in your report that the script was not run.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python3 -m py_compile scripts/jira-cookies.py` exits 0
- [ ] `grep -c "globex" scripts/jira-cookies.py` returns `0`
- [ ] `grep -c "/tmp/" scripts/jira-cookies.py` returns `0`
- [ ] `grep -c "O_NOFOLLOW" scripts/jira-cookies.py` returns `1`
- [ ] `grep -c "%atlassian%" scripts/jira-cookies.py` returns `0`
- [ ] `grep -c "/tmp/jira-state.json" references/jira-cookie-fallback.md` returns `0`
- [ ] `python3 -m unittest discover -s tests -t tests` exits 0
- [ ] `git status --porcelain` lists only the two in-scope files
- [ ] the status row for plan 008 in `plans/README.md` is updated

## STOP conditions

Stop and report back, do not improvise, if:

- You are about to run `scripts/jira-cookies.py`. It reads a live keyring and
  decrypts live session cookies.
- Moving the third party imports below the argument parser would change the
  failure message a user without those packages sees. Report what you propose.
  Making `--help` work without them is worth having, but not at the cost of a
  worse error for the normal case.
- `references/jira-cookie-fallback.md` documents a consumer that reads the old
  `/tmp` path in a way an argument cannot change, for example a hard coded path
  inside another tool.

## Maintenance notes

- Any session already written to `/tmp/jira-state.json` on a real machine is
  burned. Deleting the file is not enough: the session stays valid until it is
  signed out or it expires. Say this in the pull request body so the operator can
  decide, and do not do it for them.
- The new path sits in the same directory as `secrets.env`. If a future change
  adds a mode audit like the one in `secrets.py`, this file should be in it.
- A reviewer should confirm no default site value came back. A default here is
  what made the shipped script work for nobody.
