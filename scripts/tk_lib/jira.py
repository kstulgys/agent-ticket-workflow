"""Jira Cloud tracker. Basic auth with the account email and an API token."""
from . import htmltext, http, secrets, shape, util

KIND = "jira"
# renderedFields holds a field only when the fields list names it. A list
# without description comes back with no body at all, and the ticket then looks
# whole with an empty spec. comment stays out of this list on purpose: the
# comments come from their own endpoint, which is the only route that renders
# them.
SHOW_FIELDS = ("summary,status,issuetype,priority,assignee,parent,labels,"
               "attachment,description")
# One comment page. A named size keeps the page loop honest: the server default
# is large enough to hide a second page until a ticket grows past it.
COMMENT_PAGE = 100


def _paragraph(block):
    """One paragraph node.

    A text node holds no newline in ADF, so a newline inside the block becomes
    a hardBreak node. Without the break node the renderer joins the two lines,
    and a list written with single newlines runs together on one line.
    """
    content = []
    for line in block.strip("\n").split("\n"):
        if content:
            content.append({"type": "hardBreak"})
        if line:
            content.append({"type": "text", "text": line})
    return {"type": "paragraph", "content": content}


def to_adf(text):
    """Jira rejects markdown. Every comment body is an ADF document.

    The line ending folds to LF first. A CRLF body holds no blank line that
    this split can see, so it would post as one paragraph with a stray CR in
    every text node. Text lifted from an Azure comment carries CRLF.

    A blank block never reaches the tree, because a text node holds no empty
    string in ADF. A body file that ends with a blank line makes such a block.
    """
    blocks = util.one_line_ending(text).split("\n\n")
    return {"type": "doc", "version": 1,
            "content": [_paragraph(block) for block in blocks if block.strip()]}


class Jira:
    KIND = KIND

    def __init__(self, profile, values, client=None):
        self.profile = profile
        self.tracker = profile.get("tracker") or {}
        self.slug = profile.get("slug")
        self.http = client or http.Http()
        auth = self.tracker.get("auth_env") or {}
        self.site = self._need("site").rstrip("/")
        self.project = self._need("project")
        self.auth = http.basic(secrets.get(auth.get("email", "JIRA_EMAIL"), values),
                               secrets.get(auth.get("token", "JIRA_TOKEN"), values))

    def _need(self, key):
        """The tracker value, or a sentence a user can act on.

        A plain subscript raises KeyError, and Task 14 would print a traceback
        where a profile fix is the answer. A missing project is worse still: the
        jql then reads project = None, and the search answers with nothing at
        all instead of failing.
        """
        value = self.tracker.get(key)
        if not value or not isinstance(value, str):
            raise ValueError(
                f"profile {self.slug} has no tracker.{key}. Add it to config.json.")
        return value

    def _headers(self):
        return {"Authorization": self.auth, "Accept": "application/json"}

    def _url(self, path):
        return f"{self.site}/rest/api/3/{path.lstrip('/')}"

    def _get(self, path):
        return self.http.json("GET", self._url(path), headers=self._headers())

    def whoami(self):
        me = self._get("myself")
        return {"provider": KIND, "id": me.get("accountId"), "name": me.get("displayName")}

    def repo_check(self):
        """A token can reach the account and still reach no project.

        A token with no browse permission on the project still answers myself,
        so whoami proves nothing. This read names the project, so it is the
        call that proves access.
        """
        try:
            self._get(f"project/{self.project}")
            return {"ok": True}
        except http.HttpError as error:
            # The body is scrubbed already, so no token value reaches the
            # caller through this string.
            return {"ok": False, "error": error.body}

    def mine(self):
        jql = (f"project = {self.project} AND assignee = currentUser() "
               "AND statusCategory != Done ORDER BY updated DESC")
        found = self.http.json("POST", self._url("search/jql"),
                               {"jql": jql, "maxResults": 100,
                                "fields": ["summary", "status", "issuetype"]},
                               self._headers())
        out = []
        for issue in found.get("issues", []):
            fields = issue.get("fields") or {}
            out.append(shape.summary(shape.ticket(
                slug=self.slug, tracker=KIND, id=issue["key"], key=issue["key"],
                url=f"{self.site}/browse/{issue['key']}",
                type=(fields.get("issuetype") or {}).get("name"),
                state=(fields.get("status") or {}).get("name"),
                title=fields.get("summary"))))
        return out

    def _comments(self, ticket):
        """Every comment, not the first page.

        The comment endpoint is the only route that renders a comment body, and
        it pages. A one page read returns a short list and no error, so the
        ticket looks whole while a late comment, and the frame link in it, is
        missing.

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

    def show(self, ticket, attachments_dir=None):
        issue = self._get(f"issue/{ticket}?fields={SHOW_FIELDS}&expand=renderedFields")
        raw = issue.get("fields") or {}
        body = htmltext.html_to_text((issue.get("renderedFields") or {}).get("description"))
        comments = self._comments(ticket)
        out = shape.ticket(
            slug=self.slug, tracker=KIND, id=issue.get("key"), key=issue.get("key"),
            url=f"{self.site}/browse/{issue.get('key')}",
            type=(raw.get("issuetype") or {}).get("name"),
            state=(raw.get("status") or {}).get("name"),
            assignee=(raw.get("assignee") or {}).get("displayName"),
            title=raw.get("summary"), description_text=body,
            parent=(raw.get("parent") or {}).get("key"))
        out["comments"] = [{"author": (c.get("author") or {}).get("displayName"),
                            "created": c.get("created"),
                            "text": htmltext.html_to_text(c.get("renderedBody"))}
                           for c in comments]
        out["attachments"] = self._attachments(raw.get("attachment") or [], attachments_dir)
        # A designer usually drops the frame link in a comment, so read the
        # comments too. The description alone misses most links.
        out["figma_urls"] = shape.figma_urls(body, *[c["text"] for c in out["comments"]])
        return out

    def _attachments(self, items, target):
        out = []
        for item in items:
            # The provider owns the name, so treat it as untrusted input.
            # safe_name keeps the write inside the target, and write_new keeps
            # two screenshots that share a name as two files.
            name = util.safe_name(item.get("filename"))
            path = None
            if target:
                # Fetch, check, then write. Any 2xx body used to land on disk
                # under the attachment name, so a sign-in page was saved as a
                # screenshot and reported as a good download.
                status, payload, _ = self.http.raw(
                    "GET", self._url(f"attachment/content/{item['id']}"),
                    headers=self._headers())
                if status != 200 or not payload:
                    raise http.HttpError(status, f"no attachment body for {name}")
                path = util.write_new(target, name, payload)
            out.append({"filename": name, "path": path, "mime": item.get("mimeType")})
        return out

    def comment(self, ticket, text):
        """Posts one comment as an ADF body, then reads it back.

        A 201 is not proof. The editor can rewrite the text, and a shell can
        mangle it before it arrives. So read the comment back and compare.
        """
        created = self.http.json("POST", self._url(f"issue/{ticket}/comment"),
                                 {"body": to_adf(text)}, self._headers())
        cid = created.get("id")
        # Without an id there is no comment to read. A read of comment/None
        # asks for a comment that cannot exist.
        if not cid:
            return {"ok": False, "id": None, "stored": None}
        back = self._get(f"issue/{ticket}/comment/{cid}?expand=renderedBody")
        rendered = back.get("renderedBody")
        stored = htmltext.html_to_text(rendered)
        # A missing value is never proof. Without that test an empty text
        # compares equal to nothing at all and the write reports success.
        return {"ok": bool(rendered) and util.readback_ok(text, stored),
                "id": cid, "stored": stored}

    def state(self, ticket, value, item_type=None):
        """Moves the issue to one status.

        A Jira workflow holds one status per issue, so value is a plain name.
        It can still be a map from issue type to name, because an Azure profile
        writes a map and cli calls every adapter the same way.

        A transition id differs per workflow and it changes with a workflow
        edit, so resolve the id by name at call time. A stored id posts to the
        wrong status.

        The name can be the transition or the status it lands on. A company
        managed workflow names a transition with a verb, so Start Progress
        lands on In Progress. The read-back compares the status against the
        target the transition names, never against the verb.

        A value that names no status is an error. A guess here writes a status
        nobody asked for.
        """
        name = value.get(item_type) if isinstance(value, dict) else value
        if not name:
            # A map that misses the issue type gives None here, which is an
            # ordinary authoring mistake. A None name matches a transition that
            # carries no target, because two Nones compare equal, so the issue
            # would move to a status nobody asked for. Refuse before any lookup.
            raise ValueError(
                f"profile {self.slug} gave no state name. "
                "Name the status in config.json.")
        available = self._get(f"issue/{ticket}/transitions").get("transitions", [])
        match = self._transition(available, name)
        if not match:
            # A workflow lists only the transitions out of the current status,
            # so a ticket already in the wanted status offers none into it. A
            # re-run is ordinary in an agent loop, and a human who moved the
            # ticket first gives the same list.
            stored = self._status(ticket)
            if stored is not None and util.readback_ok(name, stored):
                return {"ok": True, "stored": stored}
            names = ", ".join(sorted(t.get("name", "") for t in available))
            raise ValueError(f"no transition named {name}. Available: {names}")
        # The transition answers 204 with no body, so it proves nothing. Read
        # the status back with a second request.
        self.http.json("POST", self._url(f"issue/{ticket}/transitions"),
                       {"transition": {"id": match["id"]}}, self._headers())
        wanted = (match.get("to") or {}).get("name") or name
        stored = self._status(ticket)
        return {"ok": stored is not None and util.readback_ok(wanted, stored),
                "stored": stored}

    @staticmethod
    def _transition(available, name):
        """The transition the name asks for, or None.

        The transition name comes first. The target status is the friendlier
        thing for a profile author to write, so it matches too.
        """
        found = next((t for t in available if t.get("name") == name), None)
        if found:
            return found
        return next((t for t in available
                     if (t.get("to") or {}).get("name") == name), None)

    def _status(self, ticket):
        """The status the server holds now."""
        back = self._get(f"issue/{ticket}?fields=status")
        return ((back.get("fields") or {}).get("status") or {}).get("name")

    def assign(self, ticket, identity):
        """Sets the assignee. identity is a Jira account id.

        The account id names one person. A display name is not an identity,
        because two people can share one, so a name match can confirm a write
        that went to the wrong person.
        """
        self.http.json("PUT", self._url(f"issue/{ticket}/assignee"),
                       {"accountId": identity}, self._headers())
        back = self._get(f"issue/{ticket}?fields=assignee")
        stored = ((back.get("fields") or {}).get("assignee") or {}).get("accountId")
        return {"ok": stored is not None and util.readback_ok(identity, stored),
                "stored": stored}
