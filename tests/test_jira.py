import json
import os
import tempfile
import unittest

import helpers  # noqa: F401
from helpers import FakeHttp, FakeResponse

from tk_lib import http as http_mod, jira, secrets, shape

PROFILE = {"slug": "globex",
           "tracker": {"kind": "jira", "site": "https://globex.atlassian.net",
                       "project": "DIST",
                       "auth_env": {"email": "JIRA_EMAIL", "token": "JIRA_TOKEN"}}}
VALUES = {"JIRA_EMAIL": "me@example.com", "JIRA_TOKEN": "tokentokentoken1"}

ISSUE = {"key": "DIST-1235",
         "fields": {"summary": "Required flags are wrong",
                    "issuetype": {"name": "Bug"}, "status": {"name": "To Do"},
                    "assignee": {"displayName": "Example Dev"},
                    "parent": {"key": "DIST-1000"},
                    "attachment": [{"id": "77", "filename": "shot.png",
                                    "mimeType": "image/png"}]},
         "renderedFields": {
             "description": "<table><tr><td>Field</td><td>Required</td></tr></table>"}}
COMMENTS = {"comments": [{"id": "10", "author": {"displayName": "Luke"},
                          "created": "2026-08-02T09:00:00Z",
                          "renderedBody": "<p>it is in the story, see the table</p>"}]}

API = "https://globex.atlassian.net/rest/api/3"
# Pin the whole url, not a part of it. assertIn("expand=renderedFields", url)
# also passes for a url that asks for no description, and that url comes back
# from the real service with an empty body.
FIELDS = ("summary,status,issuetype,priority,assignee,parent,labels,attachment,"
          "description")
ISSUE_URL = f"{API}/issue/DIST-1235?fields={FIELDS}&expand=renderedFields"
PAGE = 100


def comments_url(start=0):
    return (f"{API}/issue/DIST-1235/comment?expand=renderedBody"
            f"&startAt={start}&maxResults={PAGE}")


COMMENTS_URL = comments_url()
COMMENT_READ_URL = f"{API}/issue/DIST-1235/comment/10?expand=renderedBody"
TRANSITIONS_URL = f"{API}/issue/DIST-1235/transitions"
STATUS_URL = f"{API}/issue/DIST-1235?fields=status"
ASSIGNEE_URL = f"{API}/issue/DIST-1235/assignee"
ASSIGNEE_READ_URL = f"{API}/issue/DIST-1235?fields=assignee"
SEARCH_URL = f"{API}/search/jql"
MYSELF_URL = f"{API}/myself"
PROJECT_URL = f"{API}/project/DIST"


def client(*responses):
    fake = FakeHttp(responses)
    return jira.Jira(PROFILE, VALUES, fake), fake


def reader():
    return client(FakeResponse(200, ISSUE), FakeResponse(200, COMMENTS))


def issue_with(*attachments, description=None):
    """ISSUE with other attachments. The fixture stays untouched."""
    out = dict(ISSUE)
    out["fields"] = {**ISSUE["fields"], "attachment": list(attachments)}
    if description is not None:
        out["renderedFields"] = {"description": description}
    return out


def moves(*items):
    """A transitions payload. A real one always names the target status.

    Each item is an id and a name, and a third value when the transition name
    and the status it lands on differ.
    """
    return {"transitions": [{"id": item[0], "name": item[1],
                             "to": {"name": item[-1]}} for item in items]}


def status(name):
    return {"fields": {"status": {"name": name}}}


def attached(name, key):
    return {"id": key, "filename": name, "mimeType": "image/png"}


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


class TestJiraShow(unittest.TestCase):
    def test_show_returns_the_normalised_shape(self):
        api, fake = reader()
        got = api.show("DIST-1235")
        self.assertEqual(got["tracker"], "jira")
        self.assertEqual(got["key"], "DIST-1235")
        self.assertEqual(got["id"], "DIST-1235")
        self.assertEqual(got["type"], "Bug")
        self.assertEqual(got["state"], "To Do")
        self.assertEqual(got["parent"], "DIST-1000")
        self.assertEqual(got["url"], "https://globex.atlassian.net/browse/DIST-1235")
        self.assertIn("Field | Required", got["description_text"])
        self.assertEqual(sorted(got), sorted(shape.KEYS))
        fake.assert_drained()

    def test_comments_come_from_the_comment_endpoint(self):
        api, fake = reader()
        got = api.show("DIST-1235")
        self.assertEqual(got["comments"][0]["text"], "it is in the story, see the table")
        self.assertIn("expand=renderedBody", fake.calls[1]["url"])
        self.assertEqual(fake.calls[1]["url"], COMMENTS_URL)
        fake.assert_drained()

    def test_show_follows_every_page_of_comments(self):
        # The endpoint pages. A designer drops the frame link in a late
        # comment, so a one page read loses that link while the ticket still
        # looks whole.
        late = "<p>https://www.figma.com/design/Z/y?node-id=9-9</p>"
        page1 = {"comments": [{"id": "10", "renderedBody": "<p>one</p>"}],
                 "startAt": 0, "maxResults": 1, "total": 2}
        page2 = {"comments": [{"id": "11", "renderedBody": late}],
                 "startAt": 1, "maxResults": 1, "total": 2}
        api, fake = client(FakeResponse(200, ISSUE), FakeResponse(200, page1),
                           FakeResponse(200, page2))
        got = api.show("DIST-1235")
        self.assertEqual([c["text"] for c in got["comments"]],
                         ["one", "https://www.figma.com/design/Z/y?node-id=9-9"])
        self.assertEqual(fake.calls[1]["url"], comments_url(0))
        self.assertEqual(fake.calls[2]["url"], comments_url(1))
        self.assertIn("https://www.figma.com/design/Z/y?node-id=9-9", got["figma_urls"])
        fake.assert_drained()

    def test_an_empty_page_stops_the_comment_loop(self):
        # A total the server got wrong must not spin the loop for ever.
        page1 = {"comments": [{"id": "10", "renderedBody": "<p>one</p>"}], "total": 5}
        api, fake = client(FakeResponse(200, ISSUE), FakeResponse(200, page1),
                           FakeResponse(200, {"comments": [], "total": 5}))
        got = api.show("DIST-1235")
        self.assertEqual([c["text"] for c in got["comments"]], ["one"])
        self.assertEqual(len(fake.calls), 3)
        fake.assert_drained()

    def test_a_page_with_no_total_is_the_only_page(self):
        api, fake = reader()
        got = api.show("DIST-1235")
        self.assertEqual(len(got["comments"]), 1)
        self.assertEqual(len(fake.calls), 2)
        fake.assert_drained()

    def test_the_issue_read_asks_for_the_rendered_description(self):
        # renderedFields holds a field only when the fields list names it. A
        # list without description comes back with no body at all, and the
        # ticket then looks whole with an empty spec.
        api, fake = reader()
        api.show("DIST-1235")
        self.assertEqual(fake.calls[0]["url"], ISSUE_URL)
        fake.assert_drained()

    def test_attachments_download_by_content_id(self):
        target = self.enterContext(tempfile.TemporaryDirectory())
        api, fake = client(FakeResponse(200, ISSUE), FakeResponse(200, COMMENTS),
                           FakeResponse(200, b"\x89PNG"))
        got = api.show("DIST-1235", attachments_dir=target)
        self.assertIn("/attachment/content/77", fake.calls[2]["url"])
        self.assertEqual(got["attachments"][0]["mime"], "image/png")
        self.assertEqual(got["attachments"][0]["filename"], "shot.png")
        self.assertEqual(read_bytes(got["attachments"][0]["path"]), b"\x89PNG")
        fake.assert_drained()

    def test_attachments_are_listed_without_a_directory_and_not_fetched(self):
        api, fake = reader()
        got = api.show("DIST-1235")
        self.assertIsNone(got["attachments"][0]["path"])
        self.assertEqual(len(fake.calls), 2)
        fake.assert_drained()

    def test_two_attachments_with_one_name_keep_both_files(self):
        # Two pasted screenshots on one ticket is the ordinary case. Without a
        # unique path the second download overwrites the first, and both
        # records then point at the same bytes.
        target = self.enterContext(tempfile.TemporaryDirectory())
        issue = issue_with(attached("shot.png", "77"), attached("shot.png", "78"))
        api, fake = client(FakeResponse(200, issue), FakeResponse(200, COMMENTS),
                           FakeResponse(200, b"first"), FakeResponse(200, b"second"))
        paths = [a["path"]
                 for a in api.show("DIST-1235", attachments_dir=target)["attachments"]]
        self.assertNotEqual(paths[0], paths[1])
        self.assertEqual([read_bytes(p) for p in paths], [b"first", b"second"])
        self.assertEqual(sorted(os.listdir(target)), ["shot-1.png", "shot.png"])
        fake.assert_drained()

    def test_an_attachment_name_cannot_leave_the_target_directory(self):
        # The provider owns the name, so treat it as untrusted input.
        root = self.enterContext(tempfile.TemporaryDirectory())
        target = os.path.join(root, "att")
        os.mkdir(target)
        issue = issue_with(attached("../escaped.png", "1"),
                           attached(os.path.join(root, "absolute.png"), "2"),
                           attached("", "3"), attached("..", "4"))
        api, fake = client(FakeResponse(200, issue), FakeResponse(200, COMMENTS),
                           FakeResponse(200, b"a"), FakeResponse(200, b"b"),
                           FakeResponse(200, b"c"), FakeResponse(200, b"d"))
        got = api.show("DIST-1235", attachments_dir=target)
        for entry in got["attachments"]:
            self.assertEqual(os.path.dirname(entry["path"]), target, entry["filename"])
        self.assertEqual(sorted(os.listdir(target)),
                         ["absolute.png", "attachment", "attachment-1", "escaped.png"])
        self.assertEqual(os.listdir(root), ["att"])
        fake.assert_drained()

    def test_figma_urls_come_from_the_description_and_the_comments(self):
        # A designer usually drops the frame link in a comment, so a url that
        # only a comment holds must reach the list too.
        issue = issue_with(
            description="<p>https://www.figma.com/design/ABC/x?node-id=1-2</p>")
        late = {"comments": [{"author": {"displayName": "Ann"},
                              "renderedBody":
                                  "<p>https://www.figma.com/design/Z/y?node-id=9-9</p>"}]}
        api, fake = client(FakeResponse(200, issue), FakeResponse(200, late))
        self.assertEqual(api.show("DIST-1235")["figma_urls"],
                         ["https://www.figma.com/design/ABC/x?node-id=1-2",
                          "https://www.figma.com/design/Z/y?node-id=9-9"])
        fake.assert_drained()

    def test_a_design_link_behind_words_in_a_comment_reaches_figma_urls(self):
        # The scan runs on converted text, so a test that hands raw html to
        # shape.figma_urls proves nothing about this path. Jira renders a
        # pasted link as a smart card, so the words are a page title.
        url = "https://www.figma.com/design/ABC123/Checkout?node-id=1204-8891"
        late = {"comments": [{"author": {"displayName": "Ann"},
                              "renderedBody":
                                  f'<p>Design: <a href="{url}">Checkout mobile</a></p>'}]}
        api, fake = client(FakeResponse(200, ISSUE), FakeResponse(200, late))
        self.assertEqual(api.show("DIST-1235")["figma_urls"], [url])
        fake.assert_drained()


class TestJiraMine(unittest.TestCase):
    def test_mine_posts_jql_for_the_current_user(self):
        payload = {"issues": [{"key": "DIST-1", "fields": {
            "summary": "one", "status": {"name": "To Do"},
            "issuetype": {"name": "Bug"}}}]}
        api, fake = client(FakeResponse(200, payload))
        got = api.mine()
        self.assertEqual(got[0]["key"], "DIST-1")
        self.assertIn("assignee = currentUser()", fake.calls[0]["body"]["jql"])
        self.assertIn("project = DIST", fake.calls[0]["body"]["jql"])
        self.assertEqual(fake.calls[0]["method"], "POST")
        self.assertEqual(fake.calls[0]["url"], SEARCH_URL)
        self.assertEqual(sorted(got[0]), sorted(shape.SUMMARY_KEYS))
        fake.assert_drained()

    def test_mine_returns_an_empty_list_when_nothing_is_assigned(self):
        api, fake = client(FakeResponse(200, {"issues": []}))
        self.assertEqual(api.mine(), [])
        fake.assert_drained()


class TestJiraWhoami(unittest.TestCase):
    def test_whoami_reads_myself(self):
        api, fake = client(FakeResponse(200, {"accountId": "557058:abc",
                                              "displayName": "Example Dev"}))
        self.assertEqual(api.whoami(), {"provider": "jira", "id": "557058:abc",
                                        "name": "Example Dev"})
        self.assertEqual(fake.calls[0]["url"], MYSELF_URL)
        fake.assert_drained()

    def test_repo_check_reads_the_project_not_the_account(self):
        # A token with no browse permission on the project still answers
        # myself, so the project read is the call that proves access.
        api, fake = client(FakeResponse(200, {"key": "DIST"}))
        self.assertTrue(api.repo_check()["ok"])
        self.assertEqual(fake.calls[0]["url"], PROJECT_URL)
        fake.assert_drained()

    def test_repo_check_reports_the_refusal_instead_of_raising(self):
        def item():
            raise http_mod.HttpError(404, "No project could be found with key DIST")

        api, fake = client(item)
        got = api.repo_check()
        self.assertFalse(got["ok"])
        self.assertIn("No project", got["error"])
        fake.assert_drained()


class TestAdf(unittest.TestCase):
    def test_blank_lines_become_separate_paragraphs(self):
        doc = jira.to_adf("first line\n\nsecond block")
        self.assertEqual(doc["type"], "doc")
        self.assertEqual(len(doc["content"]), 2)
        self.assertEqual(doc["content"][1]["content"][0]["text"], "second block")

    def test_the_text_travels_as_a_text_node_and_not_as_markup(self):
        # Jira takes no markdown. A body that is a string posts the asterisks.
        doc = jira.to_adf("**bold** in a comment")
        self.assertEqual(doc["version"], 1)
        self.assertEqual(doc["content"][0]["type"], "paragraph")
        self.assertEqual(doc["content"][0]["content"][0],
                         {"type": "text", "text": "**bold** in a comment"})

    def test_a_body_that_ends_with_a_blank_line_holds_no_empty_text_node(self):
        # A body file ends with a newline, and two make a blank block. Jira
        # takes no text node with an empty string.
        doc = jira.to_adf("Fixed in PR 12\n\n")
        self.assertEqual(len(doc["content"]), 1)
        self.assertEqual(doc["content"][0]["content"][0]["text"], "Fixed in PR 12")

    def test_a_crlf_body_splits_into_paragraphs_and_holds_no_cr(self):
        # Text lifted from an Azure comment carries CRLF, and this skill moves
        # a spec between trackers. Without one line ending the body never
        # splits and every text node keeps a stray CR. The read-back cannot
        # catch it, because readback_ok folds the line ending on both sides.
        doc = jira.to_adf("a\r\n\r\nb")
        self.assertEqual(doc, jira.to_adf("a\n\nb"))
        self.assertEqual(len(doc["content"]), 2)
        self.assertNotIn("\r", json.dumps(doc))

    def test_a_crlf_line_break_travels_as_a_hard_break(self):
        doc = jira.to_adf("line one\r\nline two")
        self.assertEqual(doc["content"][0]["content"],
                         [{"type": "text", "text": "line one"},
                          {"type": "hardBreak"},
                          {"type": "text", "text": "line two"}])


class TestJiraWrites(unittest.TestCase):
    def test_comment_posts_adf_and_reads_back(self):
        created = {"id": "10", "renderedBody": "<p>Fixed in PR 12</p>"}
        api, fake = client(FakeResponse(201, created), FakeResponse(200, created))
        got = api.comment("DIST-1235", "Fixed in PR 12")
        self.assertTrue(got["ok"])
        self.assertEqual(got["id"], "10")
        self.assertEqual(got["stored"], "Fixed in PR 12")
        self.assertEqual(fake.calls[0]["body"]["body"]["type"], "doc")
        self.assertEqual(fake.calls[0]["url"], f"{API}/issue/DIST-1235/comment")
        self.assertEqual(fake.calls[1]["url"], COMMENT_READ_URL)
        fake.assert_drained()

    def test_a_two_paragraph_comment_reads_back_ok(self):
        # Jira renders two paragraphs as two <p> blocks, and the text of those
        # holds one newline. A false failure here makes the caller post the
        # comment again.
        created = {"id": "10",
                   "renderedBody": "<p>first block</p><p>second block</p>"}
        api, fake = client(FakeResponse(201, created), FakeResponse(200, created))
        got = api.comment("DIST-1235", "first block\n\nsecond block")
        self.assertTrue(got["ok"])
        fake.assert_drained()

    def test_a_line_break_travels_as_a_hard_break_and_reads_back_ok(self):
        # A text node holds no newline in ADF. A newline inside a paragraph is
        # a hardBreak node, and Jira renders that node as <br/>.
        created = {"id": "10", "renderedBody": "<p>line one<br/>line two</p>"}
        api, fake = client(FakeResponse(201, created), FakeResponse(200, created))
        got = api.comment("DIST-1235", "line one\nline two")
        self.assertTrue(got["ok"])
        self.assertEqual(fake.calls[0]["body"]["body"]["content"][0]["content"],
                         [{"type": "text", "text": "line one"},
                          {"type": "hardBreak"},
                          {"type": "text", "text": "line two"}])
        fake.assert_drained()

    def test_a_markdown_body_never_reaches_the_wire_as_a_string(self):
        text = "**Root cause**\n\n- the flag is off"
        created = {"id": "10", "renderedBody": "<p>ignored</p>"}
        api, fake = client(FakeResponse(201, created), FakeResponse(200, created))
        api.comment("DIST-1235", text)
        sent = fake.calls[0]["body"]["body"]
        self.assertIsInstance(sent, dict)
        self.assertEqual([node["content"][0]["text"] for node in sent["content"]],
                         ["**Root cause**", "- the flag is off"])
        fake.assert_drained()

    def test_a_mangled_read_back_is_not_ok(self):
        created = {"id": "10", "renderedBody": "<p>something else</p>"}
        api, fake = client(FakeResponse(201, created), FakeResponse(200, created))
        got = api.comment("DIST-1235", "sent")
        self.assertFalse(got["ok"])
        self.assertEqual(got["stored"], "something else")
        fake.assert_drained()

    def test_a_comment_that_never_comes_back_is_not_ok(self):
        # An empty read-back is a lost write, not a success.
        api, fake = client(FakeResponse(201, {"id": "10"}), FakeResponse(200, {}))
        got = api.comment("DIST-1235", "")
        self.assertFalse(got["ok"])
        fake.assert_drained()

    def test_a_post_with_no_comment_id_is_not_ok_and_reads_nothing(self):
        # Without an id there is no comment to read, so make no second request.
        api, fake = client(FakeResponse(201, {}))
        got = api.comment("DIST-1235", "sent")
        self.assertFalse(got["ok"])
        self.assertIsNone(got["id"])
        self.assertIsNone(got["stored"])
        self.assertEqual(len(fake.calls), 1)
        fake.assert_drained()

    def test_state_resolves_the_transition_id_by_name(self):
        api, fake = client(FakeResponse(200, moves(("21", "In Progress"),
                                                  ("34", "Ready for Test"))),
                           FakeResponse(204, b""),
                           FakeResponse(200, status("Ready for Test")))
        got = api.state("DIST-1235", "Ready for Test")
        self.assertTrue(got["ok"])
        self.assertEqual(fake.calls[1]["body"]["transition"]["id"], "34")
        self.assertEqual(fake.calls[0]["url"], TRANSITIONS_URL)
        self.assertEqual(fake.calls[1]["url"], TRANSITIONS_URL)
        fake.assert_drained()

    def test_state_reads_the_stored_status_with_a_second_request(self):
        # The transition answers 204 with no body, so the write response is no
        # proof at all. Read the issue again and compare.
        api, fake = client(FakeResponse(200, moves(("34", "Ready for Test"))),
                           FakeResponse(204, b""),
                           FakeResponse(200, status("Ready for Test")))
        got = api.state("DIST-1235", "Ready for Test")
        self.assertEqual(got["stored"], "Ready for Test")
        self.assertEqual(fake.calls[2]["method"], "GET")
        self.assertEqual(fake.calls[2]["url"], STATUS_URL)
        fake.assert_drained()

    def test_a_verb_named_transition_proves_the_status_it_lands_on(self):
        # A company-managed workflow names a transition with a verb. Start
        # Progress lands on In Progress, so the status read can never equal the
        # transition name. Comparing the two reports a failure on a write that
        # landed, and the retry raises because that transition is now gone.
        api, fake = client(FakeResponse(200, moves(("21", "Start Progress",
                                                   "In Progress"))),
                           FakeResponse(204, b""), FakeResponse(200, status("In Progress")))
        got = api.state("DIST-1235", "Start Progress")
        self.assertTrue(got["ok"])
        self.assertEqual(got["stored"], "In Progress")
        self.assertEqual(fake.calls[1]["body"]["transition"]["id"], "21")
        fake.assert_drained()

    def test_a_profile_can_name_the_status_instead_of_the_transition(self):
        # The target status is the friendlier thing for a profile author to
        # write, so a name that matches to.name picks that transition.
        api, fake = client(FakeResponse(200, moves(("21", "Start Progress",
                                                   "In Progress"))),
                           FakeResponse(204, b""), FakeResponse(200, status("In Progress")))
        got = api.state("DIST-1235", "In Progress")
        self.assertTrue(got["ok"])
        self.assertEqual(fake.calls[1]["body"]["transition"]["id"], "21")
        fake.assert_drained()

    def test_a_transition_with_no_target_falls_back_to_the_given_name(self):
        api, fake = client(FakeResponse(200, {"transitions": [
            {"id": "34", "name": "Ready for Test"}]}),
            FakeResponse(204, b""), FakeResponse(200, status("Ready for Test")))
        got = api.state("DIST-1235", "Ready for Test")
        self.assertTrue(got["ok"])
        fake.assert_drained()

    def test_a_ticket_already_in_the_wanted_status_is_done(self):
        # A workflow lists only the transitions out of the current status, so a
        # directional workflow offers no transition into the status the issue
        # already holds. A re-run is ordinary in an agent loop, and a human who
        # moved the ticket first gives the same thing.
        api, fake = client(FakeResponse(200, moves(("21", "Start Progress",
                                                   "In Progress"))),
                           FakeResponse(200, status("Ready for Test")))
        got = api.state("DIST-1235", "Ready for Test")
        self.assertTrue(got["ok"])
        self.assertEqual(got["stored"], "Ready for Test")
        # No transition posted, and the status read is the second call.
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[1]["url"], STATUS_URL)
        fake.assert_drained()

    def test_a_state_name_of_none_raises_before_any_lookup(self):
        # A state map that misses the issue type gives None here. A None name
        # matched a transition that carries no target, because two Nones
        # compare equal, and the issue then moved to a status nobody asked for.
        api, fake = client()
        with self.assertRaises(ValueError) as caught:
            api.state("DIST-1235", None)
        self.assertIn("globex", str(caught.exception))
        self.assertIn("state name", str(caught.exception))
        self.assertEqual(fake.calls, [])

    def test_an_empty_state_name_raises_before_any_lookup(self):
        api, fake = client()
        with self.assertRaises(ValueError) as caught:
            api.state("DIST-1235", "")
        self.assertIn("globex", str(caught.exception))
        self.assertIn("state name", str(caught.exception))
        self.assertEqual(fake.calls, [])

    def test_a_status_the_server_never_took_is_not_ok(self):
        api, fake = client(FakeResponse(200, moves(("34", "Ready for Test"))),
                           FakeResponse(204, b""), FakeResponse(200, status("To Do")))
        got = api.state("DIST-1235", "Ready for Test")
        self.assertFalse(got["ok"])
        self.assertEqual(got["stored"], "To Do")
        fake.assert_drained()

    def test_a_missing_status_is_not_ok(self):
        # A read-back that gives nothing back is not proof of a write.
        api, fake = client(FakeResponse(200, moves(("34", "Ready for Test"))),
                           FakeResponse(204, b""), FakeResponse(200, {"fields": {}}))
        got = api.state("DIST-1235", "Ready for Test")
        self.assertFalse(got["ok"])
        self.assertIsNone(got["stored"])
        fake.assert_drained()

    def test_an_unknown_state_name_lists_what_is_available(self):
        api, fake = client(FakeResponse(200, moves(("21", "In Progress"))),
                           FakeResponse(200, status("To Do")))
        with self.assertRaises(ValueError) as cm:
            api.state("DIST-1235", "Nope")
        self.assertIn("In Progress", str(cm.exception))
        # An unknown name must not pick a transition. The two calls are the
        # transition list and the status that tells the ticket is not there yet.
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual([c["method"] for c in fake.calls], ["GET", "GET"])
        fake.assert_drained()

    def test_a_state_map_picks_by_issue_type(self):
        api, fake = client(FakeResponse(200, moves(("21", "In Progress"),
                                                  ("34", "Ready for Test"))),
                           FakeResponse(204, b""), FakeResponse(200, status("In Progress")))
        got = api.state("DIST-1235", {"Bug": "In Progress", "Task": "Ready for Test"},
                        item_type="Bug")
        self.assertTrue(got["ok"])
        self.assertEqual(fake.calls[1]["body"]["transition"]["id"], "21")
        fake.assert_drained()

    def test_assign_puts_the_account_id(self):
        api, fake = client(FakeResponse(204, b""),
                           FakeResponse(200, {"fields": {"assignee": {
                               "accountId": "557058:abc"}}}))
        got = api.assign("DIST-1235", "557058:abc")
        self.assertTrue(got["ok"])
        self.assertEqual(fake.calls[0]["method"], "PUT")
        self.assertEqual(fake.calls[0]["url"], ASSIGNEE_URL)
        self.assertEqual(fake.calls[0]["body"], {"accountId": "557058:abc"})
        self.assertEqual(fake.calls[1]["url"], ASSIGNEE_READ_URL)
        fake.assert_drained()

    def test_an_assignee_the_server_never_took_is_not_ok(self):
        api, fake = client(FakeResponse(204, b""),
                           FakeResponse(200, {"fields": {"assignee": {
                               "accountId": "557058:other"}}}))
        got = api.assign("DIST-1235", "557058:abc")
        self.assertFalse(got["ok"])
        self.assertEqual(got["stored"], "557058:other")
        fake.assert_drained()

    def test_an_empty_assignee_read_back_is_not_ok(self):
        api, fake = client(FakeResponse(204, b""),
                           FakeResponse(200, {"fields": {"assignee": None}}))
        got = api.assign("DIST-1235", "557058:abc")
        self.assertFalse(got["ok"])
        self.assertIsNone(got["stored"])
        fake.assert_drained()


class TestJiraProfile(unittest.TestCase):
    def test_a_missing_site_or_project_names_the_slug_and_the_key(self):
        # A profile fix needs a sentence, not a traceback. A missing project is
        # worse than a missing site, because the jql then reads project = None
        # and the search answers with nothing at all.
        for key in ("site", "project"):
            tracker = {k: v for k, v in PROFILE["tracker"].items() if k != key}
            with self.assertRaises(ValueError) as caught:
                jira.Jira({"slug": "globex", "tracker": tracker}, VALUES, FakeHttp())
            self.assertIn("globex", str(caught.exception))
            self.assertIn(f"tracker.{key}", str(caught.exception))


class TestJiraAuth(unittest.TestCase):
    def test_a_missing_token_names_the_variable_and_not_the_value(self):
        with self.assertRaises(secrets.SecretsError) as caught:
            jira.Jira(PROFILE, {"JIRA_EMAIL": "me@example.com"}, FakeHttp())
        self.assertIn("JIRA_TOKEN", str(caught.exception))
        self.assertNotIn(VALUES["JIRA_TOKEN"], str(caught.exception))

    def test_the_token_travels_in_the_header_and_never_in_a_url(self):
        api, fake = reader()
        api.show("DIST-1235")
        for call in fake.calls:
            self.assertNotIn(VALUES["JIRA_TOKEN"], call["url"])
            self.assertTrue(call["headers"]["Authorization"].startswith("Basic "))
        fake.assert_drained()


if __name__ == "__main__":
    unittest.main()
