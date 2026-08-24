# Plan 002: Keep a link target when rendered HTML becomes text, so a Figma link is never lost

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 00d0bb2..HEAD -- scripts/tk_lib/htmltext.py scripts/tk_lib/azure.py scripts/tk_lib/jira.py tests`
> If any in-scope file changed since this plan was written, compare the "Current
> state" excerpts against the live code before you proceed. On a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `00d0bb2`, 2026-08-23

## Why this matters

`tk show` reports `figma_urls: []` for a ticket that does carry a design link,
whenever the link is a hyperlink whose visible text is not the URL. The HTML to
text step deletes the `<a href="...">` tag and keeps only the anchor text, and
the Figma scan then runs on that text. Jira renders a pasted link as a smart
card, so the anchor text is a page title. That is the normal case on a Jira
project, not an edge case.

The cost is high because the routine treats a Figma link as an instruction.
`SKILL.md` step 2 says "Every url in `figma_urls` is an instruction". When the
list is empty the agent skips the design read and builds from guesswork, which
is the exact failure the skill exists to prevent. Nothing warns, because an
empty list is also the correct answer for a ticket with no design.

This was reproduced before the plan was written. With
`<p>Design: <a href="https://www.figma.com/design/ABC123/Checkout?node-id=1204-8891">Checkout mobile</a></p>`
the production call order returns `[]`, while the same HTML passed straight to
`shape.figma_urls` returns the URL.

## Current state

Three files matter. Read all three before you edit.

- `scripts/tk_lib/htmltext.py` converts rendered HTML to text. Line 32 removes
  every remaining tag, and the `href` value goes with it:

```python
# scripts/tk_lib/htmltext.py:13
_TAG = re.compile(r"<[^>]+>")

# scripts/tk_lib/htmltext.py:19-33
    text = _DROP.sub("", html)
    text = _SPAN.sub(lambda m: _INNER.sub(" ", m.group(0)), text)
    text = _CELL.sub(" | ", text)
    text = _ROW.sub("\n", text)
    text = _BREAK.sub("\n", text)
    text = _ITEM.sub("\n- ", text)
    text = _BLOCK.sub("\n", text)
    text = _TAG.sub("", text)
    text = html_module.unescape(text).replace("\xa0", " ")
```

- `scripts/tk_lib/azure.py` converts first, then scans. The description is
  converted at `_skeleton`:

```python
# scripts/tk_lib/azure.py:201-204
        body = "\n\n".join(
            htmltext.html_to_text(fields.get(name))
            for name in ("System.Description", "Microsoft.VSTS.TCM.ReproSteps")
            if fields.get(name))
```

```python
# scripts/tk_lib/azure.py:161-170
        out["comments"] = [
            {"author": (c.get("createdBy") or {}).get("displayName"),
             "created": c.get("createdDate"),
             "text": htmltext.html_to_text(c.get("text"))}
            for c in self._comments(ticket)]
        out["attachments"] = self._attachments(item, attachments_dir)
        out["figma_urls"] = shape.figma_urls(out["description_text"],
                                             *[c["text"] for c in out["comments"]])
```

- `scripts/tk_lib/jira.py` has the same order:

```python
# scripts/tk_lib/jira.py:148
        body = htmltext.html_to_text((issue.get("renderedFields") or {}).get("description"))

# scripts/tk_lib/jira.py:158-165
        out["comments"] = [{"author": (c.get("author") or {}).get("displayName"),
                            "created": c.get("created"),
                            "text": htmltext.html_to_text(c.get("renderedBody"))}
                           for c in comments]
        out["attachments"] = self._attachments(raw.get("attachment") or [], attachments_dir)
        out["figma_urls"] = shape.figma_urls(body, *[c["text"] for c in out["comments"]])
```

- GitHub is NOT affected and needs no change. That adapter never converts HTML.
  It reads markdown straight from the API, and the Figma pattern already matches
  a markdown link:

```python
# scripts/tk_lib/github.py:138-144
        out["comments"] = [{"author": (c.get("user") or {}).get("login"),
                            "created": c.get("created_at"), "text": c.get("body") or ""}
                           for c in comments]
        out["figma_urls"] = shape.figma_urls(out["description_text"],
                                             *[c["text"] for c in out["comments"]])
```

- The scanner needs the URL to be present in the text it reads:

```python
# scripts/tk_lib/shape.py:10
_FIGMA = re.compile(r"https://(?:www\.)?figma\.com/(?:design|proto|file)/[^\s\"'<>)\]]+")
```

- The existing unit test gives false confidence. It feeds raw HTML straight to
  the scanner, which production never does:

```python
# tests/test_shape.py:60-63
    def test_stops_at_a_closing_bracket_or_quote(self):
        url = "https://www.figma.com/design/A/x?node-id=1-2"
        self.assertEqual(shape.figma_urls(f'<a href="{url}">link</a>'), [url])
        self.assertEqual(shape.figma_urls(f"[design]({url})"), [url])
```

Repository conventions to follow:
- A module level compiled regex with a comment above it that says why. See
  `scripts/tk_lib/htmltext.py:5-13` and `scripts/tk_lib/shape.py:11-16`.
- Test style: one behaviour per test, a name that reads as a sentence, and a
  comment naming the defect it defends. See `tests/test_htmltext.py:39-47`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Tests | `python3 -m unittest discover -s tests -t tests` | ends with `OK` |
| One file | `python3 -m unittest discover -s tests -t tests -k HtmlToText` | `OK` |
| Syntax | `python3 -m compileall -q scripts` | exit 0, no output |

## Scope

**In scope**:
- `scripts/tk_lib/htmltext.py`
- `tests/test_htmltext.py`
- `tests/test_azure_read.py` (add one test)
- `tests/test_jira.py` (add one test)

**Out of scope** (do NOT touch):
- `scripts/tk_lib/shape.py`. The scanner is correct. It only needs the URL to
  be in the text it receives.
- `scripts/tk_lib/azure.py`, `scripts/tk_lib/jira.py`,
  `scripts/tk_lib/github.py`. Fixing this in `html_to_text` fixes both affected
  adapters at once and changes no call site. Do not add a second scan over raw
  HTML in the adapters. Two scans would report the same URL from two places and
  the dedupe would hide which path found it.
- The normalised shape in `shape.py:4-8`. No new key. `tests/test_azure_read.py`
  asserts the key set exactly, so a new key breaks it.

## Git workflow

- Branch: `advisor/002-keep-link-targets`
- One commit: `Keep a link target when rendered html becomes text`
- Do NOT push and do NOT open a pull request unless the operator asks.

## Steps

### Step 1: Keep the href when flattening an anchor

In `scripts/tk_lib/htmltext.py`, add a module level pattern and a replacement
function, and call it before the `_TAG.sub` line.

Target shape:

```python
# A link carries its target in the attribute, and the tag strip below deletes
# it. A ticket that links a design in a smart card or a toolbar link then holds
# no url at all, and shape.figma_urls, which reads this text, finds nothing. So
# write the target beside the words before the tags go.
_ANCHOR = re.compile(r"(?is)<a\b[^>]*\bhref=([\"'])(.*?)\1[^>]*>(.*?)</a>")


def _anchor(match):
    """The words, then the target in brackets.

    A target already inside the words stays once. Azure auto-links a pasted
    url, so there the words are the url, and a second copy would read as two
    links to a person and as one repeat to the scanner.
    """
    href, inner = match.group(2).strip(), match.group(3)
    if not href or href in inner:
        return inner
    return f"{inner} ({href})"
```

Then insert the substitution in `html_to_text`, immediately after the
`_DROP.sub` line and before the `_SPAN.sub` line:

```python
    text = _DROP.sub("", html)
    text = _ANCHOR.sub(_anchor, text)
```

Place it there, not later, so an anchor inside a table cell is flattened before
the cell and row rules run.

**Verify**: `python3 -m compileall -q scripts` → exit 0

### Step 2: Cover the conversion itself

Add these tests to `tests/test_htmltext.py`, in the existing
`TestHtmlToText` class, matching its style:

- an anchor with words that are not the url keeps both, in the order words then
  url in brackets
- an anchor whose words already are the url keeps one copy
- an anchor inside a table cell keeps the row shape, so the pipe separator and
  the newline still land
- an anchor with single quotes around the href works, because Azure and Jira
  do not agree on the quote character
- an anchor with no href keeps its words and adds no brackets

**Verify**: `python3 -m unittest discover -s tests -t tests -k HtmlToText` → `OK`

### Step 3: Cover the real call order, through `show`

The missing test is the one that goes through an adapter, because the defect
was in the order of two correct functions.

In `tests/test_azure_read.py`, add one test that drives `Azure.show` with a
queued fixture whose `System.Description` holds
`<p>Design: <a href="https://www.figma.com/design/ABC123/Checkout?node-id=1204-8891">Checkout mobile</a></p>`
and asserts `figma_urls` holds that one url. Use the `FakeHttp` harness from
`tests/helpers.py` the way the existing tests in that file do, and call
`assert_drained()` at the end, as they do.

In `tests/test_jira.py`, add the same test for `Jira.show`, with the anchor in
a comment `renderedBody` rather than in the description. That is the shape Jira
sends for a smart card, so it is the case that matters most there.

Add a comment on both tests naming the defect: the scan runs on converted text,
so a test that passes raw HTML to `shape.figma_urls` proves nothing about this
path.

**Verify**: `python3 -m unittest discover -s tests -t tests` → ends with `OK`,
and the count is 388 plus the number of tests you added

## Test plan

- New tests in `tests/test_htmltext.py`: five cases listed in step 2. Model
  them on `tests/test_htmltext.py:39-47`, which already tests the cell and
  break rules.
- New test in `tests/test_azure_read.py`: `Azure.show` finds a Figma url that
  only the `href` holds.
- New test in `tests/test_jira.py`: `Jira.show` finds the same in a comment.
- Leave `tests/test_shape.py:60-63` in place. It is still a true statement
  about the scanner. It is no longer the only cover for the anchor case.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python3 -m compileall -q scripts` exits 0
- [ ] `python3 -m unittest discover -s tests -t tests` exits 0
- [ ] the suite reports at least 395 tests and ends `OK`
- [ ] this command prints the url, proving the production order:
      `python3 -c "import sys; sys.path.insert(0,'scripts'); from tk_lib import htmltext, shape; print(shape.figma_urls(htmltext.html_to_text('<p>D: <a href=\"https://www.figma.com/design/A/x?node-id=1-2\">Frame</a></p>')))"`
      → `['https://www.figma.com/design/A/x?node-id=1-2']`
- [ ] `git status --porcelain` lists only the four in-scope files
- [ ] the status row for plan 002 in `plans/README.md` is updated

## STOP conditions

Stop and report back, do not improvise, if:

- An existing test in `tests/test_azure_read.py`, `tests/test_jira.py` or
  `tests/test_htmltext.py` fails after step 1. That means a fixture carries an
  anchor and asserts the old text. Report the test name and the assertion. The
  fix may be to update that expectation, but a reviewer decides, not you.
- The anchor pattern needs to handle nested anchors. It does not. HTML forbids
  a nested `<a>`, and neither provider sends one.
- You find yourself editing an adapter to make a test pass. The whole point is
  that one change in `html_to_text` serves both.

## Maintenance notes

- Every caller of `html_to_text` now gets link targets in the text, not only
  the Figma scan. That is intended: a ticket that links a pull request or a
  document is worth reading too. It does change `description_text` and comment
  text for any ticket with a link, so a reviewer should read one real `tk show`
  output before merge.
- `readback_ok` is not affected. It compares text this tool sent with text the
  server stored. It never reads converted description text.
- If a future change makes GitHub deliver HTML rather than markdown, that
  adapter gains this behaviour for free, because the fix is in the shared
  converter.
