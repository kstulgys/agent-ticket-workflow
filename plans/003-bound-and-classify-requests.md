# Plan 003: Give every request a deadline, and name every transport failure correctly

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 00d0bb2..HEAD -- scripts/tk_lib/http.py scripts/tk_lib/cli.py tests/test_http.py tests/test_verbs.py`
> If any in-scope file changed since this plan was written, compare the "Current
> state" excerpts against the live code before you proceed. On a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none. Plans 004, 006 and 009 edit the same two files, so run
  this one before them.
- **Category**: bug
- **Planned at**: commit `00d0bb2`, 2026-08-23

## Why this matters

`tk` runs as a subprocess under an agent, so a bounded wall clock is the
property its caller needs most. Today there is none. No request sets a timeout,
so a provider that completes the TCP handshake and then sends nothing blocks the
process for ever. The worst case is `doctor`, which collects every row in memory
and prints after the last one, so one stalled provider destroys the whole report
that the verb exists to produce.

Two smaller faults sit in the same file. A `Retry-After` header is slept
unclamped, twice, so a provider can park the CLI for minutes with nothing on
stdout. And a 2xx response that is not JSON raises `ValueError`, which the error
table maps to `usage`, so a dead Azure token reports that the command line is
wrong.

The error table also misses two transport classes. `http.client.IncompleteRead`
subclasses `HTTPException` alone, so a truncated body escapes every handler and
prints a traceback with no JSON. `http.client.RemoteDisconnected` is a
`ConnectionResetError`, so a reset prints `filesystem`. The `guarded` docstring
claims a reset is covered, which is not true today. Adding a timeout makes this
worse if left alone, because `TimeoutError` is also an `OSError`, so every
timeout would report `filesystem`.

All four faults live in one file plus one table, and one test seam covers them.

## Current state

```python
# scripts/tk_lib/http.py:27-56
class Http:
    def __init__(self, opener=None, sleep=None, retries=2):
        self._opener = opener or urllib.request.urlopen
        self._sleep = sleep or time.sleep
        self._retries = retries

    def raw(self, method, url, body=None, headers=None):
        headers = dict(headers or {})
        if body is None or isinstance(body, bytes):
            data = body
        else:
            data = json.dumps(body).encode()
            if _find_header(headers, "Content-Type") is None:
                headers["Content-Type"] = "application/json"
        for attempt in range(self._retries + 1):
            request = urllib.request.Request(url, data=data, method=method)
            for key, value in headers.items():
                request.add_header(key, value)
            try:
                with self._opener(request) as response:
                    return response.status, response.read(), dict(response.headers)
            except urllib.error.HTTPError as error:
                payload = error.read() or b""
                if _may_retry(method, error.code) and attempt < self._retries:
                    self._sleep(_retry_after(error.headers))
                    continue
                raise HttpError(error.code, payload.decode("utf-8", "replace")) from None
```

```python
# scripts/tk_lib/http.py:58-60
    def json(self, method, url, body=None, headers=None):
        _, payload, _ = self.raw(method, url, body, headers)
        return json.loads(payload) if payload.strip() else {}
```

```python
# scripts/tk_lib/http.py:88-93
def _retry_after(headers):
    value = _find_header(headers, "Retry-After")
    try:
        return float(1 if value is None else value)
    except (TypeError, ValueError):
        return 1.0
```

```python
# scripts/tk_lib/cli.py:56-68
    from . import config, http, secrets

    return ((config.Ambiguous, "ambiguous"),
            (config.Unresolved, "unresolved"),
            (secrets.SecretsError, "secrets"),
            (http.HttpError, "http"),
            (config.BadProfile, "profile"),
            (KeyError, "profile"),
            (UnicodeDecodeError, "encoding"),
            (urllib.error.URLError, "network"),
            (OSError, "filesystem"),
            (RuntimeError, "incomplete"),
            (ValueError, "usage"))
```

Facts checked on Python 3.14.2 with the interpreter, not from memory:

- `http.client.IncompleteRead.__mro__` is `IncompleteRead, HTTPException,
  Exception`. It is not an `OSError`, so no entry above catches it.
- `http.client.RemoteDisconnected.__mro__` includes `ConnectionResetError,
  ConnectionError, OSError` and `HTTPException`.
- `TimeoutError` is a subclass of `OSError`.
- `json.JSONDecodeError` is a subclass of `ValueError`.

Two conventions this plan must honour:

- `cli.py:114-115` picks the first entry whose class matches, so order in the
  table is precedence. A subclass must sit above its base.
- `cli.py:4` imports `urllib.error` at module scope, and `error_codes` does
  `from . import config, http, secrets` locally. That local name `http` shadows
  the standard library package of the same name inside that function. So import
  the exception class by name at module scope, never `import http.client`.

The test seams already exist:

```python
# tests/test_http.py:11-20
def opener_returning(*items):
    queue = list(items)

    def opener(request):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return opener
```

```python
# tests/test_verbs.py:271-274
class TestGuarded(unittest.TestCase):
    def run_raising(self, error):
        @cli.guarded
        def boom(argv):
```

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Tests | `python3 -m unittest discover -s tests -t tests` | ends with `OK` |
| Http only | `python3 -m unittest discover -s tests -t tests -k Http` | `OK` |
| Guard only | `python3 -m unittest discover -s tests -t tests -k Guarded` | `OK` |
| Syntax | `python3 -m compileall -q scripts` | exit 0 |

## Scope

**In scope**:
- `scripts/tk_lib/http.py`
- `scripts/tk_lib/cli.py` (the `error_codes` table and the `guarded` docstring
  only)
- `tests/test_http.py`
- `tests/test_verbs.py` (the `TestGuarded` class only)
- any other test file that injects an opener, which step 2 finds by grep

**Out of scope** (do NOT touch):
- The retry status lists at `scripts/tk_lib/http.py:10-17`. The comment there
  states why a POST retries on 429 only. That is a settled decision.
- The adapters. None of them constructs `Http` with arguments, so none needs an
  edit.
- Redirect handling. Plan 004 owns it and edits the same constructor. Do not
  add an opener with handlers here.
- The `KeyError, "profile"` entry. It is load bearing for a profile that misses
  a key.

## Git workflow

- Branch: `advisor/003-bound-and-classify-requests`
- Commit per step is fine. Suggested first message:
  `Give every request a deadline`
- Do NOT push and do NOT open a pull request unless the operator asks.

## Steps

### Step 1: Add a request deadline and clamp the retry sleep

In `scripts/tk_lib/http.py`, add two module constants beside `RETRY_STATUS`,
each with a comment that says why, matching the style of the comment already
there:

```python
# Every request carries a deadline. urlopen with no timeout waits for ever, and
# tk runs as a subprocess under an agent, so a provider that accepts the
# connection and then sends nothing would hang the whole run with no output.
# Thirty seconds is longer than any call this tool makes, an attachment upload
# included.
TIMEOUT = 30
# A provider can ask for a wait of minutes. retries defaults to 2, so an
# unclamped value sleeps it twice with nothing on stdout. A capped wait can hit
# 429 again and fail, and a clear failure beats a silent stall.
MAX_RETRY_AFTER = 30
```

Take the timeout as a constructor argument so a test can shorten it, and pass
it to the opener:

- add `timeout=TIMEOUT` to the `__init__` signature, and store `self._timeout`
- change the call at line 49 to `with self._opener(request, timeout=self._timeout) as response:`

Clamp in `_retry_after`, keeping the existing fallback behaviour:

- wrap the returned value in `min(..., MAX_RETRY_AFTER)`

**Verify**: `python3 -m compileall -q scripts` → exit 0

### Step 2: Update every injected opener to accept the timeout

The real `urlopen` takes `timeout` as a keyword. The fakes in the tests take one
argument, so they now break.

Find them: `grep -rn "def opener" tests/` and `grep -rn "opener=" tests/`.

Change every fake signature to `def opener(request, timeout=None)`. Do not
assert on the timeout value inside the existing tests. One new test in step 4
covers that.

**Verify**: `python3 -m unittest discover -s tests -t tests -k Http` → `OK`

### Step 3: Make a non-JSON 2xx body an http error, and widen the error table

In `scripts/tk_lib/http.py`, rewrite `json` so a body that is not JSON becomes
`HttpError`, which carries the status and is already scrubbed and truncated by
its own constructor:

```python
    def json(self, method, url, body=None, headers=None):
        """The decoded body, or an HttpError naming the status.

        A 2xx is not proof of a JSON body. An Azure PAT that lost its scope
        answers 203 with a sign-in page, and json.loads then raises ValueError,
        which the error table reads as a usage mistake. So a body that does not
        decode is reported as what it is: an answer from the server.
        """
        status, payload, _ = self.raw(method, url, body, headers)
        if not payload.strip():
            return {}
        try:
            return json.loads(payload)
        except ValueError:
            raise HttpError(status, payload.decode("utf-8", "replace")) from None
```

In `scripts/tk_lib/cli.py`:

- at module scope, beside `import urllib.error`, add
  `from http.client import HTTPException`
- in `error_codes`, add three entries mapped to `network`, all above the
  `(OSError, "filesystem")` line:
  `(HTTPException, "network")`, `(TimeoutError, "network")`,
  `(ConnectionError, "network")`
- correct the `guarded` docstring. It currently claims a reset connection is one
  of the failures the table came from. Say what is true after this change: a
  reset, a truncated body and a timeout all report `network`.

Keep `(OSError, "filesystem")` where it is. A real disk failure still belongs
there.

**Verify**: `python3 -m unittest discover -s tests -t tests` → ends with `OK`

### Step 4: Test each new behaviour

In `tests/test_http.py`, add tests that:

- the opener receives the timeout: capture the keyword in a fake opener and
  assert it equals `http.TIMEOUT`
- a `Retry-After` of `600` sleeps `http.MAX_RETRY_AFTER`, not `600`. The sleep
  function is injectable at `Http(sleep=...)`, so record the value.
- a 200 with an HTML body raises `http.HttpError`, and the error carries the
  status. Model it on the existing error tests in that file, and note in a
  comment that a dead Azure PAT is the real case.
- a 204 with an empty body still returns `{}`. This behaviour exists today at
  `tests/test_http.py:43-45`, so keep it green rather than adding a duplicate.

In the `TestGuarded` class in `tests/test_verbs.py`, add one test per class,
using the existing `run_raising` helper:

- `http.client.IncompleteRead(b"")` reports `error: "network"` and exit 1
- `http.client.RemoteDisconnected()` reports `error: "network"`
- `TimeoutError()` reports `error: "network"`

Each test gets a comment naming what it defends: before this, the first printed
nothing at all and the other two printed `filesystem`.

**Verify**: `python3 -m unittest discover -s tests -t tests` → ends with `OK`,
count is 388 plus the tests you added

## Test plan

Covered in step 4. Model the http tests on `tests/test_http.py:35-56` and the
guard tests on the existing cases inside `TestGuarded` at
`tests/test_verbs.py:271`. Every one of them asserts an observable contract: the
keyword the opener receives, the number slept, the exception class raised, and
the code printed.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "timeout=self._timeout" scripts/tk_lib/http.py` returns one line
- [ ] `grep -c "MAX_RETRY_AFTER" scripts/tk_lib/http.py` returns at least 2
- [ ] `grep -n "HTTPException" scripts/tk_lib/cli.py` returns two lines, the
      import and the table entry
- [ ] `python3 -m compileall -q scripts` exits 0
- [ ] `python3 -m unittest discover -s tests -t tests` exits 0 and ends `OK`
- [ ] the suite reports at least 395 tests
- [ ] `git status --porcelain` lists only in-scope files
- [ ] the status row for plan 003 in `plans/README.md` is updated

## STOP conditions

Stop and report back, do not improvise, if:

- A fake opener exists that cannot take a keyword argument, for example a
  `functools.partial` or a `Mock` with a strict signature. Report the file and
  line.
- Adding `(ConnectionError, "network")` changes an existing assertion from
  `filesystem` to `network`. That is the intended change, but if a test asserts
  `filesystem` for a connection error, report it rather than editing the
  assertion silently.
- You are tempted to retry on a timeout. Retrying is a separate decision, and a
  POST must not be replayed. The comment at `http.py:10-17` states why.
- The suite was not green before you started.

## Maintenance notes

- Plan 004 replaces the default opener with one that strips credentials across a
  cross host redirect. It must keep the `timeout` keyword this plan added,
  because `OpenerDirector.open` accepts it in the same position as `urlopen`.
- If a future call needs longer than 30 seconds, pass `Http(timeout=...)` at
  that call site rather than raising the constant for every provider.
- A reviewer should check the table order in `error_codes`. A subclass below its
  base is silently dead, and the tuple is the only thing that documents
  precedence.
