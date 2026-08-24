# Plan 004: Stop a credential crossing hosts on a redirect, and never write an unchecked download

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 00d0bb2..HEAD -- scripts/tk_lib/http.py scripts/tk_lib/azure.py scripts/tk_lib/jira.py scripts/tk_lib/util.py scripts/tk_lib/figma.py tests`
> If any in-scope file changed since this plan was written, compare the "Current
> state" excerpts against the live code before you proceed. On a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: `plans/003-bound-and-classify-requests.md`. Both edit the
  `Http` constructor, and 003 adds the `timeout` keyword this plan must keep.
- **Category**: security
- **Planned at**: commit `00d0bb2`, 2026-08-23

## Why this matters

Three faults share one code path, the attachment download that `SKILL.md` step 2
runs on every ticket read.

First, the credential follows a redirect to another host. The standard library
redirect handler copies every header except the two content headers into the new
request, so `Authorization` survives a hop to a different host. This was
confirmed by reading
`urllib.request.HTTPRedirectHandler.redirect_request` on the interpreter that
runs this tool, Python 3.14.2. The Jira attachment content route answers 303
with a `Location` on `api.media.atlassian.com`, which Atlassian documents, so
today the Jira account credential is sent to a host the profile never named. It
is the same vendor, so this is not an open door. The sharp case is Azure, where
the request URL is lifted from the work item payload with no scheme or host
check at all.

Second, the bytes are written with no check. Any 2xx body is saved under the
attachment name and reported as a successful download, so a sign-in page can land
on disk as a screenshot. `figma.render` has the same shape and returns
`error: None` for it, while `references/figma.md` tells the agent to trust that
key before opening the file.

Third, the write follows a symlink. `free_path` picks a name with
`os.path.exists`, which follows links and answers False for a dangling one, and
the adapters then call `open(path, "wb")`, which follows it too. It needs a local
attacker who can already write to the target directory, so this is hardening
rather than an open door, and the fix is one helper.

The repository already holds the right pattern in two places. `figma.py:90`
downloads the rendered image with no headers, so the Figma token never reaches
the CDN. So each fix here copies a choice the authors already made.

## Current state

```python
# scripts/tk_lib/http.py:27-31
class Http:
    def __init__(self, opener=None, sleep=None, retries=2):
        self._opener = opener or urllib.request.urlopen
        self._sleep = sleep or time.sleep
        self._retries = retries
```

After plan 003 lands, that signature also carries `timeout=TIMEOUT` and line 49
reads `with self._opener(request, timeout=self._timeout) as response:`. Keep
both.

```python
# scripts/tk_lib/azure.py:226-240
    def _attachments(self, item, target):
        out = []
        for relation in item.get("relations") or []:
            if relation.get("rel") != "AttachedFile":
                continue
            name = util.safe_name((relation.get("attributes") or {}).get("name"))
            path = None
            if target:
                path = util.free_path(target, name)
                _, payload, _ = self.http.raw(
                    "GET", self._versioned(relation["url"]), headers=self._headers())
                with open(path, "wb") as fh:
                    fh.write(payload)
            out.append({"filename": name, "path": path, "mime": None})
        return out
```

```python
# scripts/tk_lib/jira.py:168-184
    def _attachments(self, items, target):
        out = []
        for item in items:
            # The provider owns the name, so treat it as untrusted input.
            # safe_name keeps the write inside the target, and free_path keeps
            # two screenshots that share a name as two files.
            name = util.safe_name(item.get("filename"))
            path = None
            if target:
                path = util.free_path(target, name)
                _, payload, _ = self.http.raw(
                    "GET", self._url(f"attachment/content/{item['id']}"),
                    headers=self._headers())
                with open(path, "wb") as fh:
                    fh.write(payload)
            out.append({"filename": name, "path": path, "mime": item.get("mimeType")})
        return out
```

```python
# scripts/tk_lib/util.py:80-93
def free_path(target, name):
    """A path under target that no file holds yet.

    Two attachments on one ticket often share a name. Without the number the
    second download overwrites the first, and both records then point at the
    same bytes with nothing to say one went missing.
    """
    stem, ext = os.path.splitext(name)
    path = os.path.join(target, name)
    count = 1
    while os.path.exists(path):
        path = os.path.join(target, f"{stem}-{count}{ext}")
        count += 1
    return path
```

```python
# scripts/tk_lib/figma.py:79-93
    def render(self, url, out_path, scale=2):
        key, node = _target(url)
        query = urllib.parse.urlencode({"ids": node, "format": "png", "scale": scale})
        found = self.http.json("GET", f"{API}/v1/images/{key}?{query}",
                               headers=self._headers())
        image = (found.get("images") or {}).get(node)
        if not image:
            return {"path": None, "node": node, "bytes": None,
                    "error": f"no render for node {node}"}
        _, payload, _ = self.http.raw("GET", image)
        with open(out_path, "wb") as fh:
            fh.write(payload)
        return {"path": out_path, "node": node, "bytes": len(payload), "error": None}
```

The Azure organisation URL comes from the profile and is already stripped of a
trailing slash:

```python
# scripts/tk_lib/azure.py:44
        self.org = self._need("org").rstrip("/")
```

`util.safe_name` at `scripts/tk_lib/util.py:68-77` already blocks path escape.
Do not change it. Its tests are at `tests/test_shape.py:156-167`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Tests | `python3 -m unittest discover -s tests -t tests` | ends with `OK` |
| Syntax | `python3 -m compileall -q scripts` | exit 0 |
| Redirect fact | `python3 -c "import inspect,urllib.request as u; print('Authorization' in inspect.getsource(u.HTTPRedirectHandler.redirect_request))"` | `False` |

The last command is a reminder, not a gate: the standard library never names the
header, which is exactly why it forwards it.

## Scope

**In scope**:
- `scripts/tk_lib/http.py` (add the opener, keep everything plan 003 added)
- `scripts/tk_lib/util.py` (one new helper)
- `scripts/tk_lib/azure.py` (`_attachments` only)
- `scripts/tk_lib/jira.py` (`_attachments` only)
- `scripts/tk_lib/figma.py` (`render` only)
- `tests/test_http.py`, `tests/test_shape.py`, `tests/test_azure_read.py`,
  `tests/test_jira.py`, `tests/test_figma.py`

**Out of scope** (do NOT touch):
- `util.safe_name`. Path escape is already handled and tested.
- `util.free_path`. Keep it. The new helper calls it for the name choice.
- The `?redirect=false` parameter on the Jira attachment route. It may remove
  the hop entirely, but its exact response contract was not verified for this
  plan, and guessing it would trade a known behaviour for an unknown one. The
  host check in step 1 covers the risk either way. Record it as a follow up.
- `scripts/tk_lib/github.py`. That adapter writes no attachment file. Its
  docstring at `github.py:126-133` says why.
- Any change to the `attachments` answer shape. `tests/test_azure_read.py`
  asserts the ticket key set exactly.

## Git workflow

- Branch: `advisor/004-protect-the-attachment-path`
- Commit per step. Suggested first message:
  `Strip the credential on a cross host redirect`
- Do NOT push and do NOT open a pull request unless the operator asks.

## Steps

### Step 1: Strip auth headers when a redirect crosses hosts

In `scripts/tk_lib/http.py`, add a redirect handler and make it the default
opener.

Target shape:

```python
# A redirect to another host must not carry the credential. The standard
# library copies every header except the two content headers into the new
# request, so Authorization survives a hop off the vendor. The Jira attachment
# route answers 303 to a media host, and an Azure attachment url comes out of
# the work item payload, so neither target is a value this profile named.
_AUTH_HEADERS = ("authorization", "x-figma-token", "cookie")


class _StripAuthAcrossHosts(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        following = super().redirect_request(req, fp, code, msg, headers, newurl)
        if following is None:
            return None
        if _same_host(req.full_url, following.full_url):
            return following
        for name in _AUTH_HEADERS:
            # Request keeps header names capitalised, and holds them in two
            # dicts. remove_header covers both.
            following.remove_header(name.capitalize())
            following.remove_header(name.title())
        return following


def _same_host(before, after):
    """True when scheme and host match, so a credential may travel."""
    one, two = urllib.parse.urlsplit(before), urllib.parse.urlsplit(after)
    return (one.scheme, one.netloc) == (two.scheme, two.netloc)
```

Add `import urllib.parse` to the imports at the top of the file.

Then build one module level opener and use it as the default:

```python
# One opener for the process. build_opener keeps the default handler set and
# replaces the redirect handler with the one above.
_OPENER = urllib.request.build_opener(_StripAuthAcrossHosts())
```

In `__init__`, change the default from `urllib.request.urlopen` to
`_OPENER.open`. Both take a request and a `timeout` keyword, so the call at
line 49 does not change.

Before you write `remove_header`, confirm the exact capitalisation urllib uses
for a header added with `add_header`, and make the stripping test in step 4
prove the header is gone rather than trusting the spelling.

**Verify**: `python3 -m unittest discover -s tests -t tests -k Http` → `OK`

### Step 2: Refuse a payload URL that is not on the organisation host

In `scripts/tk_lib/azure.py`, guard the URL before the credential is attached.
Add a small method beside `_versioned`:

```python
    def _own_url(self, url):
        """A payload url this token may carry a credential to.

        An attachment url arrives inside the work item, so it is provider data,
        not a value this profile named. A request to any other host would hand
        the PAT to whoever the payload names.
        """
        if not str(url).startswith(self.org + "/"):
            raise ValueError(
                f"profile {self.slug} received an attachment url outside "
                f"{self.org}. tk does not send the credential there.")
        return url
```

Call it in `_attachments`, wrapping the payload URL:
`self._versioned(self._own_url(relation["url"]))`.

`self.org` already comes from the profile with any trailing slash removed, and
the example profiles use `https://dev.azure.com/<org>`. The comparison keeps the
scheme, so an `http://` payload URL against an `https://` org is refused too.

**Verify**: `python3 -m unittest discover -s tests -t tests -k Azure` → `OK`

### Step 3: Write a download once, atomically, and only after a check

In `scripts/tk_lib/util.py`, add one helper that both adapters call:

```python
def write_new(target, name, payload):
    """Writes payload under target as name, without following a link.

    free_path picks a free name, and os.path.exists follows a symlink and
    answers False for a dangling one. So the open below refuses a link and
    refuses an existing file, and a collision asks free_path for the next name.
    That folds the choice and the write into one step, with no window between
    them.
    """
    for _ in range(FREE_TRIES):
        path = free_path(target, name)
        try:
            handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(handle, "wb") as fh:
            fh.write(payload)
        return path
    raise OSError(f"no free name for {name} under {target} after "
                  f"{FREE_TRIES} tries")
```

Add `FREE_TRIES = 50` beside `FALLBACK_NAME` with a comment saying the bound
exists so a directory an attacker keeps filling cannot spin the loop.

In `scripts/tk_lib/azure.py` and `scripts/tk_lib/jira.py`, replace the
`free_path` call and the `open(path, "wb")` block with one call to
`util.write_new(target, name, payload)`, and check the response first. The order
must be: fetch, check, then write. A body that is empty, or a status that is not
200, is not an attachment:

```python
                status, payload, _ = self.http.raw(...)
                if status != 200 or not payload:
                    raise http.HttpError(status, f"no attachment body for {name}")
                path = util.write_new(target, name, payload)
```

`jira.py` already imports `http`. Check `azure.py` does too before you use it.

In `scripts/tk_lib/figma.py`, apply the same rule to `render`. A PNG starts with
a fixed eight byte signature, so a sign-in page is easy to refuse. Return the
existing error shape rather than raising, because `references/figma.md` tells the
agent to read `error` on the answer:

```python
        status, payload, _ = self.http.raw("GET", image)
        # A render is a png. Any other body is an error page, and writing it
        # would report a good render for a file no viewer can open.
        if status != 200 or not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            return {"path": None, "node": node, "bytes": None,
                    "error": f"the render for node {node} came back as "
                             f"{len(payload)} bytes that are not a png"}
```

**Verify**: `python3 -m unittest discover -s tests -t tests` → ends with `OK`.
Existing fixture tests may need a status or a body correction. See the STOP
conditions before you change an assertion.

### Step 4: Test each guarantee

New tests, each with a comment naming what it defends:

In `tests/test_http.py`:
- a 302 to another host produces a request with no `Authorization` header. Drive
  it through `_StripAuthAcrossHosts.redirect_request` directly with a
  `urllib.request.Request` that carries the header, and assert
  `following.get_header("Authorization")` is None.
- a 302 to the same host keeps the header.

In `tests/test_shape.py`, beside `TestSafeName`:
- `util.write_new` writes the bytes and returns the path
- a second call with the same name writes a second file, not over the first
- a symlink at the chosen name is refused, and the target of the link is not
  written. Create the link with `os.symlink` inside a
  `tempfile.TemporaryDirectory`.

In `tests/test_azure_read.py`:
- an attachment url on another host raises, and no file is written
- a 200 with an empty body raises rather than writing a zero byte file

In `tests/test_figma.py`:
- a render body that is not a PNG returns `path: None` and a non empty `error`
- a real PNG signature writes the file and reports its byte count

**Verify**: `python3 -m unittest discover -s tests -t tests` → ends with `OK`

## Test plan

Listed in step 4. Model the http tests on `tests/test_http.py:35-56`, the util
tests on `TestSafeName` at `tests/test_shape.py:156`, and the adapter tests on
the existing `FakeHttp` use in `tests/test_azure_read.py`. Every adapter test
must call `assert_drained()` at the end, as the existing ones do, so a call the
code never makes fails the test.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "O_NOFOLLOW" scripts/tk_lib/util.py` returns one line
- [ ] `grep -c "open(path, \"wb\")" scripts/tk_lib/azure.py scripts/tk_lib/jira.py` returns 0 for both files
- [ ] `grep -n "_StripAuthAcrossHosts" scripts/tk_lib/http.py` returns two lines
- [ ] `grep -n "_own_url" scripts/tk_lib/azure.py` returns two lines
- [ ] `grep -n "x89PNG" scripts/tk_lib/figma.py` returns one line
- [ ] `python3 -m compileall -q scripts` exits 0
- [ ] `python3 -m unittest discover -s tests -t tests` exits 0 and ends `OK`
- [ ] `git status --porcelain` lists only in-scope files
- [ ] the status row for plan 004 in `plans/README.md` is updated

## STOP conditions

Stop and report back, do not improvise, if:

- An existing fixture queues an attachment response with a status other than
  200, or with an empty body. Report the test name. The fixture may be modelling
  a real provider answer this plan would now refuse, and that is a design
  question, not an edit for you to make.
- `remove_header` does not remove the header in your test. Report what
  `following.headers` and `following.unredirected_hdrs` hold. Do not reach into
  those dicts directly until a reviewer agrees.
- The Azure host check refuses a URL in an existing fixture. That means the
  fixture organisation and the fixture attachment host disagree, and the fixture
  may be wrong. Report both values.
- You are tempted to add `?redirect=false` to the Jira route. It is out of scope
  for the reason stated above.

## Maintenance notes

- Rotation: a provider token already used against the Jira attachment route has
  been sent to Atlassian's media host. Same vendor, so the operator decides
  whether to rotate. Say so in the pull request rather than deciding for them.
- A new provider that needs a credential header must add its header name to
  `_AUTH_HEADERS`. That list, not the adapter, is now the place that knows which
  headers are secret.
- `util.write_new` sets mode 0600 on every attachment. That is stricter than
  before. If a later change needs a shared download directory, revisit the mode,
  not the `O_NOFOLLOW`.
- A reviewer should confirm the opener is built once at module scope. Building
  it per request would drop connection reuse and add no safety.
