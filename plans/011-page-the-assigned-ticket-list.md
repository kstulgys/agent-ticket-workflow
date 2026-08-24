# Plan 011: Read every assigned ticket, or say the read is not complete

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 00d0bb2..HEAD -- scripts/tk_lib/azure.py scripts/tk_lib/github.py scripts/tk_lib/jira.py tests`
> If any in-scope file changed since this plan was written, compare the "Current
> state" excerpts against the live code before you proceed. On a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: LOW
- **Depends on**: `plans/004-protect-the-attachment-path.md`. That plan edits the
  same two adapters, and landing this first would make its diff harder to read.
- **Category**: bug
- **Planned at**: commit `00d0bb2`, 2026-08-23

## Why this matters

`tk mine` is the entry point for the batch mode of the routine, the one that
answers "work on the tickets assigned to me". On all three trackers it reads one
page and reports the result as the whole answer. Past 100 assigned items the
agent plans against a partial backlog and reports a clean sweep, and nothing in
the answer says a ticket was left out. On Jira the missing ones are the least
recently updated, which is where stale work lives. On Azure the failure is
different and louder: every id goes into one batch request, and that route
accepts at most 200 ids, so a large board fails the call outright.

Two of the three adapters already state the rule this verb breaks. The GitHub
page walk says a one page read "answers short with no error", and the Azure
comment walk says the same. `mine` is the one read where all three
implementations disagree with their own file.

The trigger needs a large board, so this is lower leverage than the plans before
it. It is worth doing because the failure is silent, and because each adapter
already holds the pattern to copy.

## Current state

GitHub reads one page, while the correct walk sits 30 lines above it:

```python
# scripts/tk_lib/github.py:73-98
    def _pages(self, path):
        """Every item on one list route, not the first page.

        GitHub pages every list route, and it serves 30 items by default. A one
        page read answers short with no error, so a ticket looks whole while a
        late comment, and the frame link in it, is missing. The read stops on
        the first page that comes back short.

        A walk that runs out of pages raises. Answering with the pages it did
        read would put back the same silent short answer one level out: the
        caller cannot tell a complete read from a truncated one.
        """
        out = []
        for page in range(1, MAX_PAGES + 1):
            join = "&" if "?" in path else "?"
            found = self.http.json(
                "GET",
                self._repo_url(f"{path}{join}per_page={PAGE_SIZE}&page={page}"),
                headers=self._headers())
            items = list(found or [])
            out.extend(items)
            if len(items) < PAGE_SIZE:
                return out
        raise RuntimeError(
            f"{path} answered {MAX_PAGES} full pages of {PAGE_SIZE} items. "
            "This read is not complete, so no answer from it is whole.")

# scripts/tk_lib/github.py:119-124
    def mine(self):
        query = urllib.parse.quote(
            f"repo:{self.owner}/{self.repo} is:issue is:open assignee:@me", safe="")
        found = self.http.json("GET", f"{API}/search/issues?q={query}&per_page=100",
                               headers=self._headers())
        return [shape.summary(self._skeleton(item)) for item in found.get("items", [])]
```

`_pages` cannot be reused as it stands, because it builds a repository URL and
this route is an absolute search URL, and because the search route answers an
object with an `items` key rather than a bare list.

Jira sends a page size and never asks for the next page:

```python
# scripts/tk_lib/jira.py:104-120
    def mine(self):
        jql = (f"project = {self.project} AND assignee = currentUser() "
               "AND statusCategory != Done ORDER BY updated DESC")
        found = self.http.json("POST", self._url("search/jql"),
                               {"jql": jql, "maxResults": 100,
                                "fields": ["summary", "status", "issuetype"]},
                               self._headers())
        out = []
        for issue in found.get("issues", []):
            ...
        return out
```

The correct pattern for this adapter is in the same file, and its comment states
the stop rules:

```python
# scripts/tk_lib/jira.py:122-143
    def _comments(self, ticket):
        """Every comment, not the first page.
        ...
        The endpoint names startAt, maxResults, and total. Read again while the
        list is shorter than total. A page with nothing in it stops the loop, so
        a wrong total cannot spin for ever. A payload with no total gives the
        one page it gave.
        """
        out = []
        while True:
            page = self._get(f"issue/{ticket}/comment?expand=renderedBody"
                             f"&startAt={len(out)}&maxResults={COMMENT_PAGE}")
            found = page.get("comments") or []
            out.extend(found)
            total = page.get("total")
            if not found or total is None or len(out) >= total:
                return out
```

Azure hydrates every id in one request:

```python
# scripts/tk_lib/azure.py:148-154
    def mine(self):
        ids = self._wiql(MINE_QUERY)
        if not ids:
            return []
        fields = "System.Id,System.WorkItemType,System.State,System.Title"
        batch = self._get(self._api("_apis/wit/workitems", ids=",".join(ids), fields=fields))
        return [shape.summary(self._skeleton(item)) for item in batch.get("value", [])]
```

Provider contracts, checked against vendor documentation while writing this plan:

- Azure: the work items batch route accepts a maximum of 200 ids per request.
  Microsoft documents the limit on the "Get Work Items Batch" page.
- Jira: `/rest/api/3/search/jql` paginates with `nextPageToken` and reports
  `isLast`. It carries no `total`. `startAt` is gone. The default page is 50 and
  the effective maximum is 100. Atlassian's own community reports cases where
  `isLast` never turns true and the token chain does not advance, so a bound and
  a repeated-token stop are both needed.
- GitHub: the search API serves at most 100 per page and at most 1000 results in
  total, which is 10 pages.

The repository already handles a server that will not stop. The Azure comment
walk stops on a repeated continuation token, at `scripts/tk_lib/azure.py:192-194`.
Copy that habit for Jira.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Tests | `python3 -m unittest discover -s tests -t tests` | ends with `OK` |
| One adapter | `python3 -m unittest discover -s tests -t tests -k Jira` | `OK` |
| Syntax | `python3 -m compileall -q scripts` | exit 0 |

## Scope

**In scope**:
- `scripts/tk_lib/github.py` (`mine`, plus a constant)
- `scripts/tk_lib/jira.py` (`mine`, plus a constant)
- `scripts/tk_lib/azure.py` (`mine`, plus a constant)
- `tests/test_github.py`, `tests/test_jira.py`, `tests/test_azure_read.py`

**Out of scope** (do NOT touch):
- `_pages` in `github.py`, `_comments` in `jira.py` and `azure.py`. They are
  correct and they are the patterns to copy, not to change.
- `_wiql` in `azure.py`. The query route returns the ids and is not the limit.
  The hydrate call is.
- The `mine` answer shape. `verbs.py` emits `{"tickets": [...], "failed": [...]}`
  and the routine reads both keys.
- `shape.summary`. No change needed.

## Git workflow

- Branch: `advisor/011-page-the-assigned-ticket-list`
- Commit per adapter. Suggested first message:
  `Read every page of the assigned ticket list`
- Do NOT push and do NOT open a pull request unless the operator asks.

## Steps

### Step 1: Walk the GitHub search route

In `scripts/tk_lib/github.py`, add a constant beside `MAX_PAGES` and `PAGE_SIZE`,
with a comment naming the provider limit:

```python
# The search route serves at most 100 items per page and at most 1000 results
# in total, which is ten pages. A read that hits the last page is at the
# provider's ceiling, not at the end of the list.
SEARCH_MAX_PAGES = 10
```

Rewrite `mine` to walk pages. Keep the same query and the same answer shape.
Stop on the first short page. On a full tenth page, raise `RuntimeError` with the
same reasoning the `_pages` message uses: an answer that cannot be told from a
truncated one is worse than an error. `RuntimeError` already maps to the
`incomplete` code in `cli.error_codes`, and `verbs._mine` catches it per project
and reports it under `failed`, so one provider at its ceiling does not hide the
others.

**Verify**: `python3 -m unittest discover -s tests -t tests -k GitHub` → `OK`

### Step 2: Follow the Jira page token

In `scripts/tk_lib/jira.py`, add a constant for the bound and rewrite `mine`:

- send `maxResults` as it does today
- read `issues`, then read `nextPageToken`
- stop when the page carried no issues, when `isLast` is true, when there is no
  token, or when the token equals the one just used
- bound the loop, and raise `RuntimeError` when the bound is reached

Write the comment above the loop the way the `_comments` comment is written: name
each stop rule and say what it prevents. Include the reason for the repeated
token check, which is that Atlassian has shipped a token chain that never sets
`isLast`.

**Verify**: `python3 -m unittest discover -s tests -t tests -k Jira` → `OK`

### Step 3: Chunk the Azure hydrate call

In `scripts/tk_lib/azure.py`, add a constant with the documented limit:

```python
# The batch route takes at most 200 ids. A longer list is not a truncated
# answer, it is a refused request, so the ids arrive in chunks.
BATCH_IDS = 200
```

Rewrite `mine` to slice `ids` into chunks of `BATCH_IDS`, call the existing
hydrate route once per chunk, and concatenate. Keep the field list and the
`shape.summary` mapping unchanged. Keep the early return for an empty id list.

**Verify**: `python3 -m unittest discover -s tests -t tests -k Azure` → `OK`

### Step 4: Test each walk

Add tests with the `FakeHttp` harness, one per adapter, each calling
`assert_drained()` as the existing adapter tests do.

GitHub:
- two pages, the second short, returns every item from both
- one full page followed by nine more full pages raises `RuntimeError`
- a single short page makes exactly one request

Jira:
- a first page with a token and a second page with `isLast` true returns both
- a page that repeats the same token stops rather than looping
- a page with no issues stops

Azure:
- 250 ids produce two hydrate requests, and the second carries the remaining 50.
  Assert on the `ids` value in the recorded request URLs.
- 200 ids produce one hydrate request. That pins the boundary.

Each test gets a comment naming the defect: before this, `mine` reported a short
list as the whole answer, and on Azure a long list failed the request.

**Verify**: `python3 -m unittest discover -s tests -t tests` → ends `OK`

## Test plan

Listed in step 4, eight tests. Model them on the existing page walk tests in
`tests/test_github.py` and `tests/test_jira.py`, which already cover the comment
routes. Assert on the requests recorded by `FakeHttp.calls` for the chunking
test, because the request shape is the contract there.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "SEARCH_MAX_PAGES" scripts/tk_lib/github.py` returns at least two lines
- [ ] `grep -n "nextPageToken" scripts/tk_lib/jira.py` returns at least one line
- [ ] `grep -n "BATCH_IDS" scripts/tk_lib/azure.py` returns at least two lines
- [ ] `python3 -m compileall -q scripts` exits 0
- [ ] `python3 -m unittest discover -s tests -t tests` exits 0 and ends `OK`
- [ ] the suite reports at least 8 tests more than before this plan
- [ ] `git status --porcelain` lists only in-scope files
- [ ] the status row for plan 011 in `plans/README.md` is updated

## STOP conditions

Stop and report back, do not improvise, if:

- An existing `mine` test queues exactly one response and now fails because the
  code asks for a second page. That is expected for the GitHub and Jira walks:
  update the fixture to answer a short page. If the fixture models a full page,
  stop and report, because then the old test was asserting the truncation.
- The Jira response in the fixtures carries `startAt` and `total` rather than
  `nextPageToken`. That means the fixtures model the old endpoint while the code
  calls the new one. Report both, and do not change the endpoint.
- You are tempted to make `mine` return a partial list with a warning. The
  repository already decided this: the `_pages` docstring says answering with
  the pages it did read puts the silent short answer one level out.
- The Azure chunk test needs more than two chunks to be meaningful. Two is
  enough. Do not build a 600 id fixture.

## Maintenance notes

- Three providers, three paging mechanisms, and now three constants naming three
  documented ceilings. When a provider raises a limit, the constant is the only
  thing to change.
- `verbs._mine` reports a per project failure under `failed` and exits 1, so a
  `RuntimeError` from a ceiling is visible without hiding the projects that
  answered. Keep that behaviour when you raise.
- A reviewer should check that no walk silently returns a partial list, and that
  each stop rule has a test.
