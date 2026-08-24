"""GitHub Issues tracker and GitHub host."""
import base64
import os
import re
import urllib.parse

from . import http, secrets, shape, util

KIND = "github"
API = "https://api.github.com"
# GitHub refuses a create over a path the branch already holds. It answers 422
# when no blob sha came with the write, and 409 when the sha is stale. Both mean
# the same thing here: the name is taken.
TAKEN_STATUS = (409, 422)
# Enough names for one ticket. A wider walk would hide a route that answers 422
# for another reason behind a long run of failed writes. The cost of this
# choice is that a 422 with another cause is paid for in ten failed writes
# before the loop re-raises it.
TAKEN_TRIES = 10
# The largest page GitHub serves. The default is 30, and a default sized read
# hides a late comment behind a page nobody asked for.
PAGE_SIZE = 100
# A stop for a server that keeps answering full pages. Five thousand comments
# on one pull request is not a case, and an unbounded loop hangs the CLI.
MAX_PAGES = 50
# The search route serves at most 100 items per page and at most 1000 results in
# total, which is ten pages. A read that fills the tenth page is at the
# provider's ceiling, not at the end of the list.
SEARCH_MAX_PAGES = 10
# GitHub links an issue through a phrase in the pull request body. Refs links
# and closes nothing. A closing keyword such as Fixes completes the issue on
# merge, and an issue that closes on merge skips its test pass.
REF_WORD = "Refs"
# The keys of one label operation. Any other key set is a map from item type to
# one operation.
OP_KEYS = ("add_labels", "remove_labels", "closed")
# Every issue number a body names. GitHub reads a link from any one of them.
MENTION = re.compile(r"#(\d+)(?!\d)")


class GitHub:
    KIND = KIND

    def __init__(self, profile, values, client=None):
        self.profile = profile
        self.tracker = profile.get("tracker") or {}
        self.host = profile.get("host") or self.tracker
        self.slug = profile.get("slug")
        self.http = client or http.Http()
        auth = self._setting("auth_env") or {}
        self.token = secrets.get(auth.get("token", "GH_TOKEN"), values)
        self.owner = self._setting("owner")
        self.repo = self._setting("repo")

    def _setting(self, key):
        """One profile value, from a block that names this provider first.

        A Jira tracker beside a GitHub host is a real profile. The tracker
        auth_env there names the Jira token, and a read in block order would
        send that token to GitHub.
        """
        named = [block for block in (self.tracker, self.host)
                 if block.get("kind") == KIND]
        for block in named or (self.tracker, self.host):
            if block.get(key):
                return block[key]
        return None

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "agent-ticket-workflow"}

    def _repo_url(self, path):
        return f"{API}/repos/{self.owner}/{self.repo}/{path.lstrip('/')}".rstrip("/")

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

    def whoami(self):
        me = self.http.json("GET", f"{API}/user", headers=self._headers())
        return {"provider": KIND, "id": me.get("login"), "name": me.get("name")}

    def repo_check(self):
        """A token can read the account and still fail on the repository.

        A token that nobody authorized for the organization under single sign
        on passes /user. So whoami proves nothing, and this call is the one
        that proves access.
        """
        try:
            self.http.json("GET", self._repo_url(""), headers=self._headers())
            return {"ok": True}
        except http.HttpError as error:
            # The body is scrubbed already, so no token value reaches the
            # caller through this string.
            return {"ok": False, "error": error.body}

    def mine(self):
        """Every assigned issue, not the first page.

        The search route pages like every other list route here, and a one page
        read answers short with no error. mine is the entry point for the batch
        mode of the routine, so a short answer plans against a partial backlog
        and reports a clean sweep.

        A walk that fills the last page raises, for the reason _pages gives:
        answering with the pages it did read puts the silent short answer one
        level out, and the caller cannot tell a complete read from a truncated
        one.
        """
        query = urllib.parse.quote(
            f"repo:{self.owner}/{self.repo} is:issue is:open assignee:@me", safe="")
        out = []
        for page in range(1, SEARCH_MAX_PAGES + 1):
            found = self.http.json(
                "GET",
                f"{API}/search/issues?q={query}&per_page={PAGE_SIZE}&page={page}",
                headers=self._headers())
            items = list(found.get("items") or [])
            out.extend(items)
            if len(items) < PAGE_SIZE:
                return [shape.summary(self._skeleton(item)) for item in out]
        raise RuntimeError(
            f"the assigned issue search answered {SEARCH_MAX_PAGES} full pages "
            f"of {PAGE_SIZE} items, which is the search ceiling. This read is "
            "not complete, so no answer from it is whole.")

    def show(self, ticket, attachments_dir=None):
        """The normalised shape for one issue.

        attachments_dir has no work here. GitHub holds an image as a markdown
        link in the body, not as an attachment record, so there is no file list
        to write to disk. The argument stays, because one adapter table calls
        every tracker the same way.
        """
        issue = self.http.json("GET", self._repo_url(f"issues/{ticket}"),
                               headers=self._headers())
        comments = self._pages(f"issues/{ticket}/comments")
        out = self._skeleton(issue)
        out["comments"] = [{"author": (c.get("user") or {}).get("login"),
                            "created": c.get("created_at"), "text": c.get("body") or ""}
                           for c in comments]
        # A designer usually drops the frame link in a comment, so read the
        # comments too. The description alone misses most links.
        out["figma_urls"] = shape.figma_urls(out["description_text"],
                                             *[c["text"] for c in out["comments"]])
        return out

    def _skeleton(self, issue):
        # A GitHub issue holds no type field. The first label is the closest
        # value, and a bucket rule reads it.
        labels = [label.get("name") for label in issue.get("labels") or []]
        return shape.ticket(
            slug=self.slug, tracker=KIND, id=str(issue.get("number")),
            key=str(issue.get("number")), url=issue.get("html_url"),
            type=labels[0] if labels else None, state=issue.get("state"),
            assignee=(issue.get("assignee") or {}).get("login"),
            title=issue.get("title"), description_text=issue.get("body") or "")

    def comment(self, ticket, text):
        """Posts one comment as markdown, then reads it back.

        A 201 is not proof. The editor can rewrite the text, and a shell can
        mangle it before it arrives. So read the comment back and compare.
        """
        created = self.http.json("POST", self._repo_url(f"issues/{ticket}/comments"),
                                 {"body": text}, self._headers())
        cid = created.get("id")
        # Without an id there is no comment to read. A read of comments/None
        # asks for a comment that cannot exist.
        if not cid:
            return {"ok": False, "id": None, "stored": None}
        back = self.http.json("GET", self._repo_url(f"issues/comments/{cid}"),
                              headers=self._headers())
        stored = back.get("body")
        # A missing value is never proof. Without that test an empty text
        # compares equal to nothing at all and the write reports success.
        return {"ok": stored is not None and util.readback_ok(text, stored),
                "id": cid, "stored": stored}

    def _spec(self, value, item_type):
        """The label operation this call must write.

        value is one label operation, or a map from item type to one. A map
        with no entry for the type used to fall through as the whole map, and
        then no branch ran and the call answered ok with nothing behind it.
        That is the worst answer a write can give, so refuse instead.

        The type reaches here from the first label on the issue, so an issue
        with no labels gives None. Both cases are ordinary, and neither one
        names a state.
        """
        if not value:
            raise ValueError(
                f"profile {self.slug} gave no state. Name a label operation in "
                'config.json, such as {"add_labels": ["in progress"]}.')
        if isinstance(value, dict) and not any(key in value for key in OP_KEYS):
            keys = ", ".join(sorted(str(key) for key in value))
            if not item_type:
                raise ValueError(
                    f"profile {self.slug} gave a state map with the keys {keys}. "
                    "This issue names no type, so no entry answers for it.")
            # A label is not case sensitive, so a key spelled Bug answers for a
            # label spelled bug. A refusal on the case alone would stop a good
            # config.
            folded = {}
            for key in value:
                folded.setdefault(str(key).casefold(), []).append(key)
            twice = sorted(str(name) for group in folded.values()
                           if len(group) > 1 for name in group)
            if twice:
                # One type spelled two ways folds to one key. The last spelling
                # would win in silence, and the call would write an operation
                # the author did not mean.
                raise ValueError(
                    f"profile {self.slug} spells one type more than once in the "
                    f"state map: {', '.join(twice)}. Keep one spelling.")
            found = folded.get(str(item_type).casefold())
            if found is None:
                raise ValueError(
                    f"no state for type {item_type}. The map has: {keys}")
            value = value[found[0]]
        if not isinstance(value, dict) or not value:
            # A name here is the Jira shape. A plain read of it raises an
            # AttributeError, where a config fix is the answer.
            raise ValueError(
                f"profile {self.slug} gave the state {value!r}. GitHub needs a "
                "label operation in config.json, such as "
                '{"add_labels": ["in progress"], "closed": false}.')
        return value

    def state(self, ticket, value, item_type=None):
        """Moves the issue with labels, and closes or opens it.

        An issue holds open or closed plus its labels. v1 leaves Projects v2
        alone, so a bucket state is a label operation. value can also be a map
        from item type to that operation, because an Azure profile writes a map
        and one adapter table calls every tracker the same way.
        """
        spec = self._spec(value, item_type)
        if spec.get("add_labels"):
            self.http.json("POST", self._repo_url(f"issues/{ticket}/labels"),
                           {"labels": spec["add_labels"]}, self._headers())
        for label in spec.get("remove_labels") or []:
            # safe="" keeps a name such as area/ui inside one path segment. A
            # plain quote leaves the slash, and the route then names a label
            # the repository does not hold.
            quoted = urllib.parse.quote(str(label), safe="")
            try:
                self.http.json("DELETE",
                               self._repo_url(f"issues/{ticket}/labels/{quoted}"),
                               headers=self._headers())
            except http.HttpError as error:
                # A label the issue never held answers 404. The issue already
                # reads the way this call asks for, so that is not a failure.
                # Every other status is.
                if error.status != 404:
                    raise
        if spec.get("closed") is not None:
            self.http.json("PATCH", self._repo_url(f"issues/{ticket}"),
                           {"state": "closed" if spec["closed"] else "open"},
                           self._headers())
        back = self.http.json("GET", self._repo_url(f"issues/{ticket}"),
                              headers=self._headers())
        names = [label.get("name") for label in back.get("labels") or []]
        stored = {"labels": names, "state": back.get("state")}
        return {"ok": self._state_ok(spec, names, back.get("state")), "stored": stored}

    @staticmethod
    def _state_ok(spec, names, stored_state):
        """True when the issue reads the way the spec asked for.

        Every part of the write gets a read-back. Without the removal test and
        the state test, a spec that only removes a label, or only closes the
        issue, would report success on any answer at all.

        GitHub holds one label per name, in the case the repository owns, so it
        can answer with a case this call did not send. A case difference is not
        a failed write, and a false failure sends the caller back to write
        again.
        """
        held = {str(name).casefold() for name in names if name}
        wanted = {str(name).casefold() for name in spec.get("add_labels") or []}
        gone = {str(name).casefold() for name in spec.get("remove_labels") or []}
        if not wanted.issubset(held) or gone & held:
            return False
        if spec.get("closed") is None:
            return True
        return stored_state == ("closed" if spec["closed"] else "open")

    def assign(self, ticket, identity):
        """Sets the assignee. identity is a GitHub login.

        A login names one person and it is not case sensitive, so fold the case
        on both sides. A false failure sends the caller back to write again.
        """
        self.http.json("POST", self._repo_url(f"issues/{ticket}/assignees"),
                       {"assignees": [identity]}, self._headers())
        back = self.http.json("GET", self._repo_url(f"issues/{ticket}"),
                              headers=self._headers())
        stored = [who.get("login") for who in back.get("assignees") or []]
        wanted = str(identity).casefold()
        return {"ok": any(str(login).casefold() == wanted for login in stored if login),
                "stored": stored}

    def pr_create(self, head, title, body, base=None, links=(), reviewer=None):
        """Opens one pull request, links the issues, and asks for the reviewer.

        GitHub makes the link from a phrase in the body, so this method writes
        one Refs line per issue. linked then names the numbers the stored body
        holds, and unlinked names what this call asked for and did not get. A
        list of the ids the caller handed over would be a claim, not a fact.

        reviewer_ok says whether the reviewer landed. It is None when the call
        asked for no reviewer. A reviewer the server refused does not fail the
        call, because the branch and the pull request are the costly part and
        they landed.

        A GitHub link is a hash and a number, so only an all digit id can make
        one. A tracker key such as DIST-1235 reaches the body as plain text and
        links nothing, and this profile shape is real: a Jira tracker sits
        beside this host. Such an id goes straight to unlinked, and no Refs
        line asks for it.
        """
        asked = [str(item["id"]) for item in links or []]
        numbers = [issue for issue in asked if issue.isdigit()]
        created = self.http.json(
            "POST", self._repo_url("pulls"),
            {"title": title, "head": head,
             "base": base or self.host.get("base_branch", "main"),
             "body": self._with_refs(body, numbers)},
            self._headers())
        number = created.get("number")
        reviewer_ok = None
        if reviewer:
            # GitHub answers with the pull request, and its requested_reviewers
            # list is the stored value. A refusal must not lose the pull request.
            try:
                back = self.http.json(
                    "POST", self._repo_url(f"pulls/{number}/requested_reviewers"),
                    {"reviewers": [reviewer]}, self._headers())
                reviewer_ok = str(reviewer).casefold() in [
                    str(person.get("login", "")).casefold()
                    for person in back.get("requested_reviewers") or []]
            except http.HttpError:
                reviewer_ok = False
        stored = created.get("body") or ""
        linked = [issue for issue in numbers if self._names(stored, issue)]
        # A dropped link shows only as a shorter list. Name the gap here, so
        # the caller reads it instead of diffing its own input.
        unlinked = [issue for issue in asked if issue not in linked]
        # A GitHub issue carries no merge side effect, so no type is refused.
        # The key exists so one caller reads the same shape from this host and
        # from the Azure host.
        return {"id": number, "url": created.get("html_url"),
                "linked": linked, "unlinked": unlinked, "refused": [],
                "reviewer_ok": reviewer_ok}

    @staticmethod
    def _names(body, number):
        """True when the body names the issue the way GitHub reads a link.

        GitHub makes the link from any hash and number in the body, so any
        mention counts. The lookahead stops #12 from answering for #123.

        number is a digit string. pr_create keeps anything else out, because
        this pattern takes the id as it comes and would answer True for a
        phrase GitHub reads no link from.
        """
        return re.search(rf"#{re.escape(str(number))}(?!\d)", body or "") is not None

    def _with_refs(self, body, numbers):
        """The body with one Refs line per issue the body does not name yet.

        A number the author already wrote needs no second line. GitHub reads
        the first mention, and a repeat only adds noise to the description.
        """
        lines = [f"{REF_WORD} #{number}" for number in numbers
                 if not self._names(body, number)]
        if not lines:
            return body
        text = util.one_line_ending(body or "").rstrip()
        block = "\n".join(lines)
        return f"{text}\n\n{block}\n" if text else f"{block}\n"

    def pr_threads(self, pr, me=None):
        """The threads other people wrote into, in the Azure host shape.

        A review comment sits on a line of the diff, and every reply to it
        carries the id of the comment that opened the thread. An issue comment
        sits under the pull request and opens a thread of its own. The thread
        id is the id pr_comment needs for a reply, and a flat comment list
        holds no such id.

        Every thread here reads active, because the REST API carries no
        resolved flag on a review thread. So a thread somebody resolved stays
        in the list, and the reader can meet an answered thread.

        A thread with nothing but my own text is my own, so a resume run would
        answer itself. A thread anybody else wrote into stays, opener or not. A
        reviewer who replies inside the thread the bot opened is the most
        common shape a request takes, and a test on the opener alone drops it.
        The run then reports a clean pull request over a live request.
        """
        threads, order = {}, []

        def thread(item, tid):
            if tid not in threads:
                threads[tid] = {"id": tid, "status": "active",
                                "author": (item.get("user") or {}).get("login"),
                                "created": item.get("created_at"),
                                "text": item.get("body"), "comments": []}
                order.append(tid)
            return threads[tid]

        for item in self._pages(f"pulls/{pr}/comments"):
            parent = item.get("in_reply_to_id") or item.get("id")
            thread(item, parent)["comments"].append(self._row(item))
        for item in self._pages(f"issues/{pr}/comments"):
            thread(item, item.get("id"))["comments"].append(self._row(item))
        # A host knows me by a login. The caller passes every name that means
        # me, because the profile holds a tracker account id beside it, and a
        # single wrong name leaves my own thread in the list. The resume run
        # then answers itself.
        mine = util.name_set(me)
        return [threads[tid] for tid in order
                if not mine or any(str(row["author"]).casefold() not in mine
                                   for row in threads[tid]["comments"])]

    @staticmethod
    def _row(item):
        """One comment inside a thread, in the shape the Azure host returns."""
        return {"id": item.get("id"),
                "author": (item.get("user") or {}).get("login"),
                "text": item.get("body")}

    def pr_comment(self, pr, text, reply_to=None):
        """Writes one comment, or one reply in the thread reply_to names.

        A review thread has a reply route, and the id it takes is the id of the
        comment that opened the thread. An issue comment has no reply route, so
        a reply there is one more comment under the pull request. pr_threads
        answers with both kinds of thread id, and the caller cannot tell them
        apart, so ask the server which kind this is. A reply on the wrong route
        answers 404 and the text is lost.

        The answer holds the comment the server stored, so it is the read-back.
        """
        if reply_to and self._is_review_comment(reply_to):
            created = self.http.json(
                "POST", self._repo_url(f"pulls/{pr}/comments/{reply_to}/replies"),
                {"body": text}, self._headers())
        else:
            created = self.http.json("POST", self._repo_url(f"issues/{pr}/comments"),
                                     {"body": text}, self._headers())
        stored = created.get("body")
        # A missing value is never proof. Without that test an empty text
        # compares equal to nothing at all and the write reports success.
        return {"ok": stored is not None and util.readback_ok(text, stored),
                "id": created.get("id"), "stored": stored}

    def _is_review_comment(self, cid):
        """True when the id names a review comment, so the reply route exists.

        A 404 means the id names an issue comment instead. Every other status
        is a real failure, and it must not send the reply to the other route.
        """
        try:
            self.http.json("GET", self._repo_url(f"pulls/comments/{cid}"),
                           headers=self._headers())
            return True
        except http.HttpError as error:
            if error.status != 404:
                raise
            return False

    def pr_attach(self, pr, path):
        """Puts one image where a comment can render it.

        GitHub has no API that attaches a file to a comment. So commit the file
        to a branch that never merges, and answer with the blob url that
        carries raw=true. That branch is not the branch under review, and no
        pull request opens from it, so the file never reaches the diff the
        reviewer reads.
        """
        branch = self.host.get("screenshot_branch", "pr-screenshots")
        # The name comes from a file on disk, so treat it as untrusted input.
        # safe_name drops any directory part, so no path fragment reaches the
        # route and a name holding .. cannot leave the screenshots directory.
        name = util.safe_name(path)
        with open(path, "rb") as fh:
            payload = fh.read()
        self._ensure_branch(branch)
        stored, created = self._commit_file(pr, branch, name, payload)
        sha = (created.get("commit") or {}).get("sha")
        # A screenshot name holds spaces, and a space builds a broken url.
        url = (f"https://github.com/{self.owner}/{self.repo}/blob/{sha}"
               f"/screenshots/{urllib.parse.quote(stored)}?raw=true")
        # chr(33) builds the markdown image prefix without a source line that
        # starts with the escape character. An IPython cell rewrites such a
        # line, even inside a string.
        return {"url": url, "ok": bool(sha),
                "markdown": chr(33) + f"[{stored}]({url})"}

    def _ensure_branch(self, branch):
        """Creates the screenshot branch from the base branch when it is missing."""
        try:
            self.http.json("GET", self._repo_url(f"git/ref/heads/{branch}"),
                           headers=self._headers())
            return
        except http.HttpError as error:
            if error.status != 404:
                raise
        base = self.host.get("base_branch", "main")
        head = self.http.json("GET", self._repo_url(f"git/ref/heads/{base}"),
                              headers=self._headers())
        self.http.json("POST", self._repo_url("git/refs"),
                       {"ref": f"refs/heads/{branch}",
                        "sha": (head.get("object") or {}).get("sha")},
                       self._headers())

    def _commit_file(self, pr, branch, name, payload):
        """Commits the file under a name the branch does not hold yet.

        The screenshot branch keeps every earlier file, and two pasted
        screenshots that share a name is the ordinary case. So walk the same
        numbers util.free_path walks on disk. Without the walk the second file
        fails, and its comment then shows the first image.
        """
        stem, ext = os.path.splitext(name)
        body = {"message": f"Add the screenshot for pull request {pr}",
                "content": base64.b64encode(payload).decode(), "branch": branch}
        taken = None
        for count in range(TAKEN_TRIES):
            candidate = name if count == 0 else f"{stem}-{count}{ext}"
            route = urllib.parse.quote(candidate, safe="")
            try:
                created = self.http.json(
                    "PUT", self._repo_url(f"contents/screenshots/{route}"),
                    body, self._headers())
            except http.HttpError as error:
                if error.status not in TAKEN_STATUS:
                    raise
                taken = error
                continue
            return candidate, created
        raise taken

    def pr_describe(self, pr, body):
        """Replaces the pull request body, then compares what came back.

        An answer with no body is not proof of a write. Two missing values
        compare equal, so read the value before the compare.

        The issue link lives in the body, so a rewrite can drop it and GitHub
        says nothing. Read the body first, and name every number the new body
        no longer holds under unlinked, the word pr_create answers with. This
        adds no text the caller did not ask for: a caller that means to drop a
        link reads its own number back and moves on.
        """
        before = self.http.json("GET", self._repo_url(f"pulls/{pr}"),
                                headers=self._headers()).get("body")
        updated = self.http.json("PATCH", self._repo_url(f"pulls/{pr}"),
                                 {"body": body}, self._headers())
        stored = updated.get("body")
        return {"ok": stored is not None and util.readback_ok(body, stored),
                "stored": stored, "unlinked": self._lost(before, stored)}

    @staticmethod
    def _lost(before, after):
        """Every issue number the old body named and the new body does not."""
        out = []
        for number in MENTION.findall(before or ""):
            if number not in out and not GitHub._names(after, number):
                out.append(number)
        return out
