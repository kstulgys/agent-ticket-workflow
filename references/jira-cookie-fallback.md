# Jira without an API token

Use this only when your organization blocks personal API tokens, so
`scripts/setup.sh jira` cannot verify one. Every `tk` Jira verb needs
`JIRA_EMAIL` and `JIRA_TOKEN`. On this path you make the REST calls yourself,
from a browser that already holds the session.

```bash
cd ~/.claude/skills/agent-ticket-workflow
python3 scripts/jira-cookies.py --site your-site.atlassian.net
```

It writes `~/.claude/ticket-workflow/jira-state.json`, mode 0600, in the same
directory as `secrets.env`. Pass `--out` for another path.

The script decrypts the Chrome cookie database, so it needs `secretstorage`,
`cryptography`, and an unlocked login keyring. It finds the profile by the
session cookie. `--site` is required and has no default, because a default
reads the wrong tenant in silence.

The file holds the same `{cookies, origins}` shape that `agent-browser state
save` writes, so the browser loads it as it is. Confirm the identity before you
trust any other call:

```bash
agent-browser state load ~/.claude/ticket-workflow/jira-state.json
agent-browser open "https://<site>/rest/api/3/myself"
agent-browser get text body        # your accountId, not a login page
```

The script is the path that needs no Chrome restart. `agent-browser
--auto-connect state save ~/.claude/ticket-workflow/jira-state.json` reads a
live Chrome instead. That Chrome must have started with
`--remote-debugging-port=9222`, so the user closes and reopens their browser
first.

From a page on that origin, every call is a same-origin `fetch` with
`credentials: 'include'`:

```bash
cat <<'EOF' | agent-browser eval --stdin
(async () => {
  const r = await fetch('/rest/api/3/issue/DIST-1234', { credentials: 'include' });
  return (await r.json()).fields.summary;
})()
EOF
```

`eval` takes one expression. A top level `await` or `return` is refused, so
wrap the calls in an async arrow and call it, the way the block above does.

The endpoints and the body formats match what the Jira adapter uses, so read
`scripts/tk_lib/jira.py` for the exact shapes. A comment still needs an ADF
body.

Two rules. Re-authenticate at the start of every session, because the file
holds live session tokens. At the end of the run, `rm -f
~/.claude/ticket-workflow/jira-state.json` and `agent-browser close --all`.

Deleting the file is not enough on its own. A session token stays valid until
you sign out of Jira or it expires, so sign out too when a session has been
written.
