"""Azure Boards tracker and Azure Repos host."""
import urllib.parse

from . import htmltext, http, secrets, shape, util

KIND = "azure"
# Every route needs the preview version. A bare 7.1 answers some routes with
# VssInvalidPreviewVersionException, which reads like a permissions problem and
# costs time to find. A point release such as 7.1-preview.3 is fine.
VERSION_PREFIX = "7.1-preview"
# The open work items assigned to me. mine reads them, and repo_check reads one
# of them to prove the token can read work items at all.
MINE_QUERY = ("SELECT [System.Id] FROM WorkItems WHERE [System.AssignedTo]=@Me "
              "AND [System.State] NOT IN ('Done','Removed','Closed') "
              "ORDER BY [System.ChangedDate] DESC")
# The work items batch route takes at most 200 ids. A longer list is a refused
# request, not a truncated answer, so mine sends the ids in chunks of this size.
BATCH_IDS = 200


class Azure:
    KIND = KIND
    # The git routes need the point release. A plain 7.1-preview, which the
    # work item routes take, fails on a pull request route.
    GIT_VERSION = "7.1-preview.1"

    def __init__(self, profile, values, client=None):
        self.profile = profile
        self.tracker = profile.get("tracker") or {}
        self.host = profile.get("host") or {}
        self.slug = profile.get("slug")
        self.http = client or http.Http()
        # The tracker block, as a pull request host as well. This host reads
        # tracker.org and tracker.project too, so it always sits beside its own
        # Azure tracker, and one provider names one token variable in both
        # blocks. gitcmd reads host.auth_env, because that is the credential
        # git sends, and the schema page says to write the same variable there.
        auth = self.tracker.get("auth_env") or {}
        self.token = secrets.get(auth.get("token", "AZDO_PAT"), values)
        self.version = self.tracker.get("api_version") or VERSION_PREFIX
        if not str(self.version).startswith(VERSION_PREFIX):
            # A config.json that says 7.1 puts back the trap this file guards.
            raise ValueError(
                f"profile {self.slug} sets tracker.api_version to {self.version}. "
                f"Azure Boards needs {VERSION_PREFIX}, or a {VERSION_PREFIX}.N "
                "point release.")
        self.org = self._need("org").rstrip("/")
        self.project = urllib.parse.quote(self._need("project"))

    def _need(self, key):
        """The tracker value, or a sentence a user can act on.

        A plain subscript here raises KeyError, and Task 14 would print a
        traceback where a profile fix is the answer.
        """
        value = self.tracker.get(key)
        if not value or not isinstance(value, str):
            raise ValueError(
                f"profile {self.slug} has no tracker.{key}. Add it to config.json.")
        return value

    def _host_need(self, key):
        """The host value, or a sentence a user can act on.

        The same rule as _need, on the other block. A pull request route reads
        three host values, and a plain subscript answers with the key name
        alone.
        """
        value = self.host.get(key)
        if not value or not isinstance(value, str):
            raise ValueError(
                f"profile {self.slug} has no host.{key}. Add it to config.json.")
        return value

    def _headers(self, extra=None):
        head = {"Authorization": http.basic("", self.token)}
        head.update(extra or {})
        return head

    def _api(self, path, **query):
        query["api-version"] = self.version
        return f"{self.org}/{path}?{urllib.parse.urlencode(query, safe='$,/')}"

    def _versioned(self, url, version=None):
        """Adds api-version to a url that came from a payload.

        A relation url arrives with no version. The trap for this adapter is
        that every call needs one, so add it here. An existing query stays
        whole, and a url that already names a version stays as it is.

        version names the value to add. A git url needs GIT_VERSION, and the
        work item value it defaults to is the one value a git route refuses.
        """
        if not url or "api-version=" in url:
            return url
        join = "&" if "?" in url else "?"
        return f"{url}{join}api-version={version or self.version}"

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

    def _get(self, url):
        return self.http.json("GET", url, headers=self._headers())

    def _web_url(self, wid, item=None):
        """The browser url for a work item.

        A batch read with a fields filter carries no _links, so build the url
        from the org, the project, and the id. It costs no extra call. A _links
        href wins when the payload has one.
        """
        href = (((item or {}).get("_links") or {}).get("html") or {}).get("href")
        return href or f"{self.org}/{self.project}/_workitems/edit/{wid}"

    def _wiql(self, query, limit=None):
        """Runs one WIQL query. Returns the work item ids as strings.

        WIQL has its own route and a hand built url, because the query travels
        in the body. Every caller that needs ids comes through here, so a
        route change is one edit.
        """
        url = f"{self.org}/{self.project}/_apis/wit/wiql?api-version={self.version}"
        found = self.http.json("POST", url, {"query": query}, self._headers())
        ids = [str(item["id"]) for item in found.get("workItems", [])]
        return ids[:limit] if limit else ids

    def whoami(self):
        data = self._get(self._api("_apis/connectionData"))
        user = data.get("authenticatedUser") or {}
        return {"provider": KIND, "id": user.get("id"),
                "name": user.get("providerDisplayName")}

    def repo_check(self):
        """A PAT can reach the organization and still reach no work item.

        A PAT carries a project scope, and a scope for each API area. One
        scoped to another project still answers connectionData, so whoami
        proves nothing. A Core project route answers for a PAT scoped to Code
        alone, so it reports the project green and the run then fails at tk
        show with a 401 that reads as a permissions problem.

        So read a work item. That read needs the project and the Work Items
        scope together, which is what every verb on this tracker uses. An empty
        board is still a pass: no work item assigned to me is not a refusal.
        """
        try:
            self._wiql(MINE_QUERY, limit=1)
            return {"ok": True}
        except http.HttpError as error:
            # The body is scrubbed already, so no token value reaches the
            # caller through this string.
            return {"ok": False, "error": error.body}

    def mine(self):
        """Every assigned work item, hydrated in chunks the route accepts.

        The batch route takes at most BATCH_IDS ids. A longer list is not a
        short answer, it is a refused request, so a large board failed the call
        outright rather than reading partially.
        """
        ids = self._wiql(MINE_QUERY)
        if not ids:
            return []
        fields = "System.Id,System.WorkItemType,System.State,System.Title"
        items = []
        for start in range(0, len(ids), BATCH_IDS):
            batch = self._get(self._api("_apis/wit/workitems",
                                        ids=",".join(ids[start:start + BATCH_IDS]),
                                        fields=fields))
            items.extend(batch.get("value") or [])
        return [shape.summary(self._skeleton(item)) for item in items]

    def show(self, ticket, attachments_dir=None):
        # $expand=all brings the relations. Without it the parent, the children,
        # and the attachments are all absent, and the ticket still looks whole.
        item = self._get(self._api(f"_apis/wit/workitems/{ticket}", **{"$expand": "all"}))
        out = self._skeleton(item)
        out["comments"] = [
            {"author": (c.get("createdBy") or {}).get("displayName"),
             "created": c.get("createdDate"),
             "text": htmltext.html_to_text(c.get("text"))}
            for c in self._comments(ticket)]
        out["attachments"] = self._attachments(item, attachments_dir)
        # A designer usually drops the frame link in a comment, so read the
        # comments too. The description alone misses most links.
        out["figma_urls"] = shape.figma_urls(out["description_text"],
                                             *[c["text"] for c in out["comments"]])
        return out

    def _comments_path(self, ticket):
        """The comments route. The write and the read both come through here."""
        return f"{self.project}/_apis/wit/workItems/{ticket}/comments"

    def _comments(self, ticket):
        """Every comment, not the first page.

        The comments live on their own route. They are not in the work item.
        That route also pages, and it names the next page in continuationToken.
        A one page read returns a short list and no error, so the ticket looks
        whole while a late comment, and the frame link in it, is missing.
        """
        path = self._comments_path(ticket)
        out, token = [], None
        while True:
            page = self._get(self._api(path, **({"continuationToken": token}
                                                if token else {})))
            out.extend(page.get("comments") or [])
            following = page.get("continuationToken")
            # A server that repeats a token would loop for ever. Stop instead.
            if not following or following == token:
                return out
            token = following

    def _skeleton(self, item):
        fields = item.get("fields") or {}
        # A bug holds its spec in ReproSteps. Every other type holds it in
        # Description. Read both, because a bug can fill either field.
        body = "\n\n".join(
            htmltext.html_to_text(fields.get(name))
            for name in ("System.Description", "Microsoft.VSTS.TCM.ReproSteps")
            if fields.get(name))
        links, children, parent = [], [], None
        for relation in item.get("relations") or []:
            rel = relation.get("rel")
            url = relation.get("url", "")
            wid = url.rsplit("/", 1)[-1]
            if rel == "System.LinkTypes.Hierarchy-Reverse":
                parent = wid
                links.append({"rel": "parent", "id": wid, "url": url})
            elif rel == "System.LinkTypes.Hierarchy-Forward":
                children.append(wid)
                links.append({"rel": "child", "id": wid, "url": url})
            elif rel == "ArtifactLink":
                links.append({"rel": "artifact", "id": wid, "url": url})
        assigned = fields.get("System.AssignedTo") or {}
        wid = str(item.get("id"))
        return shape.ticket(
            slug=self.slug, tracker=KIND, id=wid, key=wid, url=self._web_url(wid, item),
            type=fields.get("System.WorkItemType"), state=fields.get("System.State"),
            assignee=assigned.get("displayName"), title=fields.get("System.Title"),
            description_text=body, links=links, parent=parent, children=children)

    def _attachments(self, item, target):
        out = []
        for relation in item.get("relations") or []:
            if relation.get("rel") != "AttachedFile":
                continue
            name = util.safe_name((relation.get("attributes") or {}).get("name"))
            path = None
            if target:
                # Fetch, check, then write. Any 2xx body used to land on disk
                # under the attachment name, so a sign-in page was saved as a
                # screenshot and reported as a good download.
                status, payload, _ = self.http.raw(
                    "GET", self._versioned(self._own_url(relation["url"])),
                    headers=self._headers())
                if status != 200 or not payload:
                    raise http.HttpError(status, f"no attachment body for {name}")
                path = util.write_new(target, name, payload)
            out.append({"filename": name, "path": path, "mime": None})
        return out

    def comment(self, ticket, text):
        """Posts one comment, then reads it back.

        A 200 is not proof. The editor can rewrite the text, and a shell can
        mangle it before it arrives. So read the comment back and compare.
        """
        url = self._api(self._comments_path(ticket))
        created = self.http.json("POST", url, {"text": text}, self._headers())
        # Read every page. A new comment lands last, so a one page read on a
        # long ticket misses it and reports a good write as a failure.
        stored = next((htmltext.html_to_text(c.get("text"))
                       for c in self._comments(ticket)
                       if c.get("id") == created.get("id")), None)
        # A missing value is never proof. Without that test an empty text
        # compares equal to nothing at all and the write reports success.
        return {"ok": stored is not None and util.readback_ok(text, stored),
                "id": created.get("id"), "stored": stored}

    def state(self, ticket, value, item_type=None):
        """Moves the work item to one state.

        The state name depends on the work item type. A Task goes to In
        Progress and a Bug goes to Committed, so value can be a map from type
        to state. A map with no type is an error, because a guess here writes
        the wrong state.
        """
        if isinstance(value, dict):
            if not item_type:
                raise ValueError("a state map needs the work item type")
            if item_type not in value:
                raise ValueError(
                    f"no state for type {item_type}. "
                    f"The map has: {', '.join(sorted(value))}")
            value = value[item_type]
        stored = self._patch(ticket, "/fields/System.State", value, "System.State")
        return {"ok": stored is not None and util.readback_ok(value, stored),
                "stored": stored}

    def assign(self, ticket, identity):
        """Sets the assignee. identity is a GUID or a mail address.

        The server answers with every name it holds for the person. The GUID
        and the mail address each name one person, so a match on either one is
        proof. A display name is not an identity. Two people can share one, so
        a name match can confirm a write that went to the wrong person.
        """
        who = self._patch(ticket, "/fields/System.AssignedTo", identity,
                          "System.AssignedTo") or {}
        # A mail address is not case sensitive, so fold the case on both sides.
        # A case difference is not a failed write, and a false failure sends
        # the caller back to write again.
        sent = str(identity).casefold()
        ok = any(util.readback_ok(sent, str(who[key]).casefold())
                 for key in ("id", "uniqueName") if who.get(key))
        return {"ok": ok, "stored": who.get("displayName")}

    def _patch(self, ticket, path, value, field):
        """One field update. Returns the value the server stored.

        A work item update is a PATCH with an array body and the media type
        application/json-patch+json. A plain application/json returns an error
        that reads like a permissions problem, which costs time to find.
        """
        body = [{"op": "add", "path": path, "value": value}]
        headers = self._headers({"Content-Type": "application/json-patch+json"})
        updated = self.http.json("PATCH", self._api(f"_apis/wit/workItems/{ticket}"),
                                 body, headers)
        return (updated.get("fields") or {}).get(field)

    def identity(self, name):
        """One person from a name, or a value that says why there is none.

        This PAT has no Graph scope, so the identities API is closed to it. A
        WIQL query over work items is the only route this token can take.

        One person gives {"id", "name", "unique"}. Nobody gives None. Two
        people give {"ambiguous": [...]}, because picking one of two assigns
        the wrong person and nobody sees it. The two failures need different
        sentences: nobody at all is a spelling to fix, and two people is a
        question for a human. One None for both left the caller unable to tell
        them apart.
        """
        # A quote inside a WIQL literal doubles. A name such as O'Brien breaks
        # the query without this.
        literal = str(name).replace("'", "''")
        query = ("SELECT [System.Id] FROM WorkItems "
                 f"WHERE [System.AssignedTo] CONTAINS '{literal}' "
                 "ORDER BY [System.ChangedDate] DESC")
        # Twenty recent work items keep the hydrate url short and still hold
        # enough people to see a second person behind one name. A short window
        # hides that person, and this method then answers with confidence about
        # the wrong one.
        ids = self._wiql(query, limit=20)
        if not ids:
            return None
        batch = self._get(self._api("_apis/wit/workitems", ids=",".join(ids),
                                    fields="System.AssignedTo"))
        people = {}
        for item in batch.get("value", []):
            who = (item.get("fields") or {}).get("System.AssignedTo") or {}
            if who.get("id"):
                people[who["id"]] = who
        if len(people) > 1:
            return {"ambiguous": [{"id": who["id"], "name": who.get("displayName"),
                                   "unique": who.get("uniqueName")}
                                  for who in people.values()]}
        if not people:
            return None
        who = next(iter(people.values()))
        return {"id": who["id"], "name": who.get("displayName"),
                "unique": who.get("uniqueName")}

    def _git(self, path, **query):
        """One pull request route. Every git call comes through here.

        The git routes carry GIT_VERSION, not the work item version, so a
        version change is one edit.
        """
        base = f"{self.org}/{self.project}/_apis/git/repositories/{self.host['repo_id']}"
        query["api-version"] = self.GIT_VERSION
        return f"{base}/{path}?{urllib.parse.urlencode(query, safe='$,/')}"

    def pr_create(self, head, title, body, base=None, links=(), reviewer=None):
        """Opens one pull request and links the work items it may link.

        links holds {"id", "type"} pairs, because the refusal rule reads the
        type. A merge completes every linked work item, so a type on
        never_link_types stays out of the link list and goes to refused. A bug
        that closes on merge skips its test pass.

        linked names what the server lists after the write. unlinked names what
        this call asked for and did not get, so a dropped link is a value the
        caller reads, not a shorter list it has to notice.

        reviewer_ok says whether the reviewer landed. It is None when the call
        asked for no reviewer. A reviewer the server refused does not fail the
        call, because the branch and the pull request are the costly part and
        they landed.

        Every host value this method needs is read first. The url in the answer
        reads repo, and pr_link builds the artifact uri from project_id and
        repo_id. A read after the POST raises where the pull request exists
        already: the caller never sees its id, and the run that fixes the
        profile and retries opens a second pull request.
        """
        for key in ("repo", "repo_id", "project_id"):
            self._host_need(key)
        never = set((self.profile.get("link_rules") or {}).get("never_link_types") or [])
        target = base or self.host.get("base_branch", "master")
        created = self.http.json("POST", self._git("pullrequests"), {
            "sourceRefName": f"refs/heads/{head}",
            "targetRefName": f"refs/heads/{target}",
            "title": title, "description": body}, self._headers())
        pr = created.get("pullRequestId")
        linked, refused, unlinked = [], [], []
        for item in links or []:
            if item.get("type") in never:
                refused.append(item["id"])
                continue
            self.pr_link(pr, item["id"])
            linked.append(item["id"])
        if linked:
            confirmed = self.http.json("GET", self._git(f"pullRequests/{pr}/workitems"),
                                       headers=self._headers())
            landed = [str(item["id"]) for item in confirmed.get("value", [])]
            # A link the server dropped shows only as a shorter list. Name the
            # gap here, so the caller reads it instead of diffing its own input.
            unlinked = [wid for wid in linked if wid not in landed]
            linked = landed
        reviewer_ok = None
        if reviewer:
            # An unresolved name reaches this route whole, so encode it. A space
            # builds a broken url.
            route = urllib.parse.quote(str(reviewer), safe="")
            try:
                added = self.http.json(
                    "PUT", self._git(f"pullRequests/{pr}/reviewers/{route}"),
                    {"vote": 0}, self._headers())
            except http.HttpError:
                # The pull request exists by now. Raising here loses its id, and
                # the caller then retries and opens a second pull request.
                added = {}
            # The answer names the identity the server stored. A different id,
            # or no id at all, means the reviewer never landed. Without this
            # compare that failure is silent, and nobody reviews the work.
            stored = str((added or {}).get("id") or "")
            reviewer_ok = bool(stored) and util.readback_ok(
                str(reviewer).casefold(), stored.casefold())
        web = f"{self.org}/{self.project}/_git/{self.host['repo']}/pullrequest/{pr}"
        return {"id": pr, "url": web, "linked": linked, "refused": refused,
                "unlinked": unlinked, "reviewer_ok": reviewer_ok}

    def pr_link(self, pr, ticket):
        """Links one work item to the pull request.

        The workItemRefs field at create time is unreliable. An explicit
        ArtifactLink relation on the work item holds. The artifact uri encodes
        its two separators as %2F. A plain slash there is not the format.
        """
        artifact = (f"vstfs:///Git/PullRequestId/{self.host['project_id']}"
                    f"%2F{self.host['repo_id']}%2F{pr}")
        body = [{"op": "add", "path": "/relations/-",
                 "value": {"rel": "ArtifactLink", "url": artifact,
                           "attributes": {"name": "Pull Request"}}}]
        headers = self._headers({"Content-Type": "application/json-patch+json"})
        return self.http.json("PATCH", self._api(f"_apis/wit/workItems/{ticket}"),
                              body, headers)

    def pr_threads(self, pr, me=None):
        """The open threads other people wrote into.

        A closed thread is answered already. A system thread is a vote or a
        build message, not a request. me is my identity or my display name.

        A thread with nothing but my own text is my own, so a resume run would
        answer itself. A thread anybody else wrote into stays, opener or not. A
        reviewer who replies inside the thread the bot opened is the most
        common shape a request takes, and a test on the opening comment alone
        drops it. The run then reports a clean pull request over a live
        request.
        """
        found = self.http.json("GET", self._git(f"pullRequests/{pr}/threads"),
                               headers=self._headers())
        out = []
        for thread in found.get("value", []):
            if thread.get("status") not in ("active", "pending"):
                continue
            comments = thread.get("comments") or []
            if not comments or comments[0].get("commentType") == "system":
                continue
            author = (comments[0].get("author") or {}).get("displayName")
            if me and all(self._is_me(comment, me) for comment in comments):
                continue
            out.append({"id": thread.get("id"), "status": thread.get("status"),
                        "author": author,
                        "comments": [{"id": c.get("id"),
                                      "author": (c.get("author") or {}).get("displayName"),
                                      "text": c.get("content")} for c in comments]})
        return out

    @staticmethod
    def _is_me(comment, me):
        """True when I wrote this comment.

        A display name is not an identity. Two people can share one, so a
        colleague with the agent's name would lose their thread and the resume
        run would never answer it. The id names one person. Accept either
        value, because a profile can hold either one, and me can hold more than
        one name for the same reason.

        me carries the host identity name beside the account id, and on this
        host that name is the git author name. So it can match a display name
        as well, and that is the same known risk, taken on purpose: cli.host_names
        sends both names because neither one alone serves both hosts.
        """
        who = comment.get("author") or {}
        names = util.name_set([who.get("id"), who.get("displayName")])
        return bool(names & util.name_set(me))

    def pr_comment(self, pr, text, reply_to=None):
        """Writes one thread, or one reply in a thread, then reads it back.

        No body here carries a status. An active status blocks the merge under
        the blocking comment policy. A fixed status collapses the text, so the
        reviewer never reads it, and the number 1 means fixed. A reply keeps
        the status the reviewer set, and goes under comment 1 of that thread.
        """
        if reply_to:
            posted = self.http.json(
                "POST",
                self._git(f"pullRequests/{pr}/threads/{reply_to}/comments"),
                {"content": text, "parentCommentId": 1, "commentType": 1},
                self._headers())
            back = self.http.json("GET",
                                  self._git(f"pullRequests/{pr}/threads/{reply_to}"),
                                  headers=self._headers())
            # Match on the id the server gave, not on the position. Another
            # person can post into the thread between the write and the read,
            # and the last comment is then theirs. A landed write would report
            # False, and the caller would post the reply a second time.
            stored = next((c.get("content") for c in (back.get("comments") or [])
                           if c.get("id") == posted.get("id")), None)
        else:
            created = self.http.json(
                "POST", self._git(f"pullRequests/{pr}/threads"),
                {"comments": [{"parentCommentId": 0, "content": text, "commentType": 1}]},
                self._headers())
            back = self.http.json(
                "GET", self._git(f"pullRequests/{pr}/threads/{created.get('id')}"),
                headers=self._headers())
            stored = (back.get("comments") or [{}])[0].get("content")
        # A missing value is never proof. Without that test an empty text
        # compares equal to nothing at all and the write reports success.
        return {"ok": stored is not None and util.readback_ok(text, stored),
                "stored": stored}

    def pr_attach(self, pr, path):
        """Uploads one file to the pull request. The body is raw bytes, not JSON.

        The name goes through two guards, because they answer two problems.
        util.safe_name drops any directory part, so no path fragment reaches
        the route. quote then encodes the rest: a screenshot name holds spaces,
        and a hash would end the path at the fragment and send the upload to
        the wrong route.

        The read-back compares the served bytes with the file bytes, because a
        short upload still answers with a url and the markdown then points at a
        broken image. A length compare would pass for equal length with other
        content.
        """
        name = util.safe_name(path)
        with open(path, "rb") as fh:
            payload = fh.read()
        route = urllib.parse.quote(name, safe="")
        created = self.http.json(
            "POST", self._git(f"pullRequests/{pr}/attachments/{route}"), payload,
            self._headers({"Content-Type": "application/octet-stream"}))
        url = created.get("url")
        # The url comes from the payload with no version, and every call needs
        # one. This url is a git route, so it needs the git value. The work
        # item value is the one value this route refuses.
        _, served, _ = self.http.raw("GET", self._versioned(url, self.GIT_VERSION),
                                     headers=self._headers())
        # Compare the bytes, not the length. Equal length with other content is
        # a failed upload that a length compare calls a success.
        # chr(33) builds the markdown image prefix without a source line that
        # starts with the escape character. An IPython cell rewrites such a
        # line, even inside a string.
        return {"url": url, "ok": served == payload,
                "markdown": chr(33) + f"[{name}]({url})"}

    def pr_describe(self, pr, body):
        """Replaces the pull request description, then compares what came back.

        An answer with no description is not proof of a write. Two missing
        values compare equal, so read the value before the compare.

        unlinked is always empty here, and that is a fact rather than a claim.
        An Azure link is an ArtifactLink relation on the work item, so no
        description rewrite can drop one. The key exists so one caller reads
        the same shape from this host and from the GitHub host, where a
        rewrite can drop a link.
        """
        updated = self.http.json("PATCH", self._git(f"pullRequests/{pr}"),
                                 {"description": body}, self._headers())
        stored = updated.get("description")
        return {"ok": stored is not None and util.readback_ok(body, stored),
                "stored": stored, "unlinked": []}
