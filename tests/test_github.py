"""GitHub Issues tracker and GitHub pull request host."""
import pathlib
import shutil
import tempfile
import unittest

import helpers  # noqa: F401
from helpers import FakeHttp, FakeResponse

from tk_lib import github
from tk_lib import http as http_mod

PROFILE = {"slug": "globex",
           "tracker": {"kind": "github", "owner": "globex-dist", "repo": "Web",
                       "auth_env": {"token": "GH_TOKEN"}},
           "host": {"kind": "github", "owner": "globex-dist", "repo": "Web",
                    "base_branch": "main", "screenshot_branch": "pr-screenshots",
                    "auth_env": {"token": "GH_TOKEN"}}}
VALUES = {"GH_TOKEN": "ghp_tokentokentoken"}
# A Jira tracker beside a GitHub host is a real profile shape. The tracker
# auth_env names the Jira token there, and only the host block names GitHub.
MIXED = {"slug": "globex",
         "tracker": {"kind": "jira", "site": "https://globex.atlassian.net",
                     "project": "DIST",
                     "auth_env": {"email": "JIRA_EMAIL", "token": "JIRA_TOKEN"}},
         "host": {"kind": "github", "owner": "globex-dist", "repo": "Web",
                  "base_branch": "main", "auth_env": {"token": "GH_TOKEN"}}}

API = "https://api.github.com"
REPO = f"{API}/repos/globex-dist/Web"

ISSUE = {"number": 12, "title": "Label is wrong", "state": "open",
         "html_url": "https://github.com/globex-dist/Web/issues/12",
         "body": "See https://www.figma.com/design/A/x?node-id=1-2",
         "assignee": {"login": "devuser"}, "labels": [{"name": "bug"}]}
COMMENTS = [{"id": 5, "user": {"login": "reviewer"}, "created_at": "2026-08-03T00:00:00Z",
             "body": "the target wording is in the story"}]


def raiser(status, body):
    def item():
        raise http_mod.HttpError(status, body)

    return item


def client(*responses):
    fake = FakeHttp(responses)
    return github.GitHub(PROFILE, VALUES, fake), fake


def tmp_bytes(test, name, payload):
    """Writes one file in a temp directory that goes away with the test."""
    root = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, root, True)
    path = pathlib.Path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


class TestGitHubReads(unittest.TestCase):
    def test_show_returns_the_normalised_shape(self):
        api, fake = client(FakeResponse(200, ISSUE), FakeResponse(200, COMMENTS))
        got = api.show("12")
        self.assertEqual(got["tracker"], "github")
        self.assertEqual(got["id"], "12")
        self.assertEqual(got["state"], "open")
        self.assertEqual(got["type"], "bug")
        self.assertEqual(got["assignee"], "devuser")
        self.assertEqual(got["comments"][0]["author"], "reviewer")
        self.assertEqual(got["figma_urls"],
                         ["https://www.figma.com/design/A/x?node-id=1-2"])
        fake.assert_drained()

    def test_show_reads_every_page_of_comments(self):
        # A designer drops the frame link in a late comment. A one page read
        # answers short with no error, so the ticket looks whole while the link
        # is gone and tk still exits 0.
        full = [{"id": n, "user": {"login": "sam"}, "created_at": "t",
                 "body": "no link here"} for n in range(100)]
        late = [{"id": 999, "user": {"login": "designer"}, "created_at": "t",
                 "body": "the frame is https://www.figma.com/design/B/y?node-id=3-4"}]
        api, fake = client(FakeResponse(200, ISSUE), FakeResponse(200, full),
                           FakeResponse(200, late))
        got = api.show("12")
        self.assertEqual(len(got["comments"]), 101)
        self.assertIn("https://www.figma.com/design/B/y?node-id=3-4",
                      got["figma_urls"])
        self.assertIn("per_page=100", fake.calls[1]["url"])
        self.assertIn("page=2", fake.calls[2]["url"])
        fake.assert_drained()

    def test_a_page_walk_that_runs_out_refuses_to_answer(self):
        # A route that keeps answering full pages used to return the cap. That
        # is the same silent short answer, one level out: the caller cannot
        # tell a complete read from a truncated one.
        full = [{"id": n, "user": {"login": "sam"}, "created_at": "t",
                 "body": "text"} for n in range(github.PAGE_SIZE)]
        api, fake = client(FakeResponse(200, ISSUE),
                           *[FakeResponse(200, full)
                             for _ in range(github.MAX_PAGES)])
        with self.assertRaises(RuntimeError) as cm:
            api.show("12")
        self.assertIn("not complete", str(cm.exception))
        self.assertEqual(len(fake.calls), github.MAX_PAGES + 1)
        fake.assert_drained()

    def test_mine_searches_open_issues_assigned_to_me(self):
        payload = {"items": [{"number": 12, "title": "one", "state": "open",
                              "html_url": "u", "labels": []}]}
        api, fake = client(FakeResponse(200, payload))
        got = api.mine()
        self.assertEqual(got[0]["id"], "12")
        self.assertIn("assignee%3A%40me", fake.calls[0]["url"])
        self.assertIn("repo%3Aglobex-dist%2FWeb", fake.calls[0]["url"])
        fake.assert_drained()

    def test_mine_reads_every_page_of_the_assigned_list(self):
        # A one page read reported a short list as the whole answer, and mine is
        # the entry point for the batch mode of the routine.
        def issue(n):
            return {"number": n, "title": f"t{n}", "state": "open",
                    "html_url": "u", "labels": []}

        first = {"items": [issue(n) for n in range(github.PAGE_SIZE)]}
        second = {"items": [issue(999)]}
        api, fake = client(FakeResponse(200, first), FakeResponse(200, second))
        got = api.mine()
        self.assertEqual(len(got), github.PAGE_SIZE + 1)
        self.assertEqual(got[-1]["id"], "999")
        self.assertIn("page=1", fake.calls[0]["url"])
        self.assertIn("page=2", fake.calls[1]["url"])
        fake.assert_drained()

    def test_mine_makes_one_request_for_a_short_page(self):
        payload = {"items": [{"number": 12, "title": "one", "state": "open",
                              "html_url": "u", "labels": []}]}
        api, fake = client(FakeResponse(200, payload))
        api.mine()
        self.assertEqual(len(fake.calls), 1)
        fake.assert_drained()

    def test_mine_at_the_search_ceiling_refuses_to_answer(self):
        # The search route serves 1000 results at most. A read that fills the
        # last page is at that ceiling, and a caller cannot tell such an answer
        # from a whole one.
        full = {"items": [{"number": n, "title": "t", "state": "open",
                           "html_url": "u", "labels": []}
                          for n in range(github.PAGE_SIZE)]}
        api, fake = client(*[FakeResponse(200, full)
                             for _ in range(github.SEARCH_MAX_PAGES)])
        with self.assertRaises(RuntimeError) as cm:
            api.mine()
        self.assertIn("not complete", str(cm.exception))
        self.assertEqual(len(fake.calls), github.SEARCH_MAX_PAGES)
        fake.assert_drained()

    def test_repo_check_reports_the_sso_failure_instead_of_raising(self):
        api, fake = client(raiser(403, "SAML SSO enforcement"))
        got = api.repo_check()
        self.assertFalse(got["ok"])
        self.assertIn("SAML", got["error"])
        fake.assert_drained()

    def test_repo_check_passes_when_the_repo_reads(self):
        api, fake = client(FakeResponse(200, {"full_name": "globex-dist/Web"}))
        self.assertTrue(api.repo_check()["ok"])
        fake.assert_drained()

    def test_repo_check_reads_the_repository_not_the_account(self):
        # A token that is not authorized for the organization under single sign
        # on passes /user and fails here. So the repository call is the one
        # that proves access.
        api, fake = client(FakeResponse(200, {"full_name": "globex-dist/Web"}))
        api.repo_check()
        self.assertEqual(fake.calls[0]["url"], REPO)
        fake.assert_drained()

    def test_whoami_names_the_login(self):
        api, fake = client(FakeResponse(200, {"login": "devuser", "name": "Example"}))
        got = api.whoami()
        self.assertEqual((got["provider"], got["id"], got["name"]),
                         ("github", "devuser", "Example"))
        self.assertEqual(fake.calls[0]["url"], f"{API}/user")
        fake.assert_drained()

    def test_the_token_comes_from_the_block_that_names_github(self):
        # The tracker block names the Jira token here. Reading the tracker
        # first would send that token to GitHub.
        fake = FakeHttp([FakeResponse(200, {"full_name": "globex-dist/Web"})])
        api = github.GitHub(MIXED, VALUES, fake)
        self.assertTrue(api.repo_check()["ok"])
        self.assertEqual(fake.calls[0]["url"], REPO)
        self.assertIn("ghp_tokentokentoken", fake.calls[0]["headers"]["Authorization"])
        fake.assert_drained()


class TestGitHubWrites(unittest.TestCase):
    def test_comment_reads_back_the_exact_markdown(self):
        created = {"id": 99, "body": "Fixed in PR 3"}
        api, fake = client(FakeResponse(201, created), FakeResponse(200, created))
        self.assertTrue(api.comment("12", "Fixed in PR 3")["ok"])
        self.assertEqual(fake.calls[0]["url"], f"{REPO}/issues/12/comments")
        self.assertEqual(fake.calls[1]["url"], f"{REPO}/issues/comments/99")
        fake.assert_drained()

    def test_a_comment_the_server_rewrote_is_not_ok(self):
        api, fake = client(FakeResponse(201, {"id": 99, "body": "Fixed in PR 3"}),
                           FakeResponse(200, {"id": 99, "body": "Fixed in PR"}))
        self.assertFalse(api.comment("12", "Fixed in PR 3")["ok"])
        fake.assert_drained()

    def test_a_comment_with_no_stored_body_is_not_ok(self):
        # Two missing values compare equal, so an empty answer would report a
        # write that nobody can read.
        api, fake = client(FakeResponse(201, {"id": 99}), FakeResponse(200, {"id": 99}))
        got = api.comment("12", "")
        self.assertFalse(got["ok"])
        fake.assert_drained()

    def test_a_comment_with_no_id_never_reads_a_comment_back(self):
        api, fake = client(FakeResponse(201, {}))
        got = api.comment("12", "text")
        self.assertFalse(got["ok"])
        self.assertIsNone(got["id"])
        self.assertEqual(len(fake.calls), 1)
        fake.assert_drained()

    def test_state_adds_and_removes_labels(self):
        # Four writes here: the label add, the label remove, the open or closed
        # flag, and the read-back.
        api, fake = client(FakeResponse(200, [{"name": "in progress"}]),
                           FakeResponse(200, {}),
                           FakeResponse(200, {}),
                           FakeResponse(200, {"labels": [{"name": "in progress"}],
                                              "state": "open"}))
        got = api.state("12", {"add_labels": ["in progress"],
                               "remove_labels": ["triage"], "closed": False})
        self.assertTrue(got["ok"])
        self.assertEqual(fake.calls[0]["method"], "POST")
        self.assertIn("/labels/triage", fake.calls[1]["url"])
        self.assertEqual(fake.calls[2]["body"], {"state": "open"})
        fake.assert_drained()

    def test_removing_a_label_that_is_absent_is_not_an_error(self):
        api, fake = client(raiser(404, "Label does not exist"),
                           FakeResponse(200, {"labels": [], "state": "open"}))
        self.assertTrue(api.state("12", {"remove_labels": ["triage"]})["ok"])
        fake.assert_drained()

    def test_a_real_failure_on_a_label_still_fails(self):
        api, fake = client(raiser(500, "server error"))
        with self.assertRaises(http_mod.HttpError):
            api.state("12", {"remove_labels": ["triage"]})
        fake.assert_drained()

    def test_a_label_the_server_kept_is_not_ok(self):
        api, fake = client(FakeResponse(200, {}),
                           FakeResponse(200, {"labels": [{"name": "triage"}],
                                              "state": "open"}))
        got = api.state("12", {"remove_labels": ["triage"]})
        self.assertFalse(got["ok"])
        self.assertEqual(got["stored"]["labels"], ["triage"])
        fake.assert_drained()

    def test_a_label_that_came_back_in_another_case_is_ok(self):
        # GitHub holds one label per name, in the case the repository owns.
        api, fake = client(FakeResponse(200, {}),
                           FakeResponse(200, {"labels": [{"name": "in progress"}],
                                              "state": "open"}))
        self.assertTrue(api.state("12", {"add_labels": ["In Progress"]})["ok"])
        fake.assert_drained()

    def test_a_label_name_with_a_slash_stays_in_one_path_segment(self):
        api, fake = client(FakeResponse(200, {}),
                           FakeResponse(200, {"labels": [], "state": "open"}))
        api.state("12", {"remove_labels": ["area/ui"]})
        self.assertEqual(fake.calls[0]["url"],
                         f"{REPO}/issues/12/labels/area%2Fui")
        fake.assert_drained()

    def test_a_close_that_did_not_land_is_not_ok(self):
        api, fake = client(FakeResponse(200, {}),
                           FakeResponse(200, {"labels": [], "state": "open"}))
        got = api.state("12", {"closed": True})
        self.assertFalse(got["ok"])
        self.assertEqual(fake.calls[0]["body"], {"state": "closed"})
        fake.assert_drained()

    def test_a_state_map_reads_the_entry_for_the_item_type(self):
        api, fake = client(FakeResponse(200, {}),
                           FakeResponse(200, {"labels": [{"name": "wip"}],
                                              "state": "open"}))
        got = api.state("12", {"Bug": {"add_labels": ["wip"]}}, item_type="Bug")
        self.assertTrue(got["ok"])
        self.assertEqual(fake.calls[0]["body"], {"labels": ["wip"]})
        fake.assert_drained()

    def test_a_state_map_with_no_entry_for_the_type_is_refused(self):
        # The map used to fall through as the spec. No branch then ran, and the
        # call answered ok with nothing behind it.
        api, fake = client()
        with self.assertRaises(ValueError) as cm:
            api.state("12", {"Bug": {"add_labels": ["wip"]}}, item_type="Task")
        self.assertIn("Task", str(cm.exception))
        self.assertIn("Bug", str(cm.exception))
        self.assertEqual(fake.calls, [])

    def test_a_state_map_with_no_item_type_is_refused(self):
        # An issue with no labels gives no type, and _skeleton reads the type
        # from the first label. So this is an ordinary path, not a rare one.
        api, fake = client()
        with self.assertRaises(ValueError) as cm:
            api.state("12", {"Bug": {"add_labels": ["wip"]}})
        self.assertIn("Bug", str(cm.exception))
        self.assertEqual(fake.calls, [])

    def test_a_state_map_key_answers_for_a_label_in_another_case(self):
        # A label is not case sensitive, so bug must find the key Bug. A
        # refusal on the case alone would stop a good config.
        api, fake = client(FakeResponse(200, {}),
                           FakeResponse(200, {"labels": [{"name": "wip"}],
                                              "state": "open"}))
        got = api.state("12", {"Bug": {"add_labels": ["wip"]}}, item_type="bug")
        self.assertTrue(got["ok"])
        self.assertEqual(fake.calls[0]["body"], {"labels": ["wip"]})
        fake.assert_drained()

    def test_a_type_spelled_twice_in_the_map_is_refused(self):
        # Two spellings fold to one key. The last one would win in silence, and
        # the call would write an operation the author did not mean.
        api, fake = client()
        with self.assertRaises(ValueError) as cm:
            api.state("12", {"Bug": {"add_labels": ["wip"]},
                             "bug": {"add_labels": ["triage"]}}, item_type="bug")
        self.assertIn("Bug", str(cm.exception))
        self.assertIn("bug", str(cm.exception))
        self.assertEqual(fake.calls, [])

    def test_an_empty_state_writes_nothing_and_is_refused(self):
        api, fake = client()
        for value in ({}, None):
            with self.assertRaises(ValueError):
                api.state("12", value)
        self.assertEqual(fake.calls, [])

    def test_a_state_name_instead_of_a_label_operation_is_refused(self):
        # A name is the Jira shape. Refuse it before any write, and name the
        # shape config.json needs.
        api, fake = client()
        with self.assertRaises(ValueError) as cm:
            api.state("12", "In Progress")
        self.assertIn("add_labels", str(cm.exception))
        self.assertEqual(fake.calls, [])

    def test_assign_reads_the_assignee_back(self):
        api, fake = client(FakeResponse(201, {}),
                           FakeResponse(200, {"assignees": [{"login": "DevUser"}]}))
        got = api.assign("12", "devuser")
        self.assertTrue(got["ok"])
        self.assertEqual(fake.calls[0]["body"], {"assignees": ["devuser"]})
        fake.assert_drained()

    def test_an_assignee_the_server_never_took_is_not_ok(self):
        api, fake = client(FakeResponse(201, {}), FakeResponse(200, {"assignees": []}))
        self.assertFalse(api.assign("12", "devuser")["ok"])
        fake.assert_drained()

    def test_pr_create_posts_head_and_base(self):
        api, fake = client(FakeResponse(201, {"number": 3, "html_url": "u"}))
        got = api.pr_create(head="fix/dist-1", title="t", body="d")
        self.assertEqual(got["id"], 3)
        self.assertEqual(fake.calls[0]["body"]["base"], "main")
        self.assertEqual(fake.calls[0]["body"]["head"], "fix/dist-1")
        self.assertIsNone(got["reviewer_ok"])
        fake.assert_drained()

    def test_pr_create_answers_the_same_six_keys_as_the_azure_host(self):
        api, fake = client(FakeResponse(201, {"number": 3, "html_url": "u",
                                              "body": "d\n\nRefs #12\n"}))
        got = api.pr_create(head="b", title="t", body="d",
                            links=[{"id": "12", "type": "Bug"}])
        self.assertEqual(sorted(got),
                         ["id", "linked", "refused", "reviewer_ok", "unlinked", "url"])
        self.assertEqual(got["linked"], ["12"])
        # A GitHub issue carries no merge side effect, so nothing is refused.
        self.assertEqual(got["refused"], [])
        self.assertEqual(got["unlinked"], [])
        fake.assert_drained()

    def test_pr_create_writes_the_ref_line_that_makes_the_link(self):
        # GitHub links an issue through a phrase in the body. Without the
        # phrase the linked list is a claim about a link nobody made.
        api, fake = client(FakeResponse(201, {"number": 3, "html_url": "u",
                                              "body": "what changed\n\nRefs #12\n"}))
        got = api.pr_create(head="b", title="t", body="what changed",
                            links=[{"id": "12", "type": "bug"}])
        sent = fake.calls[0]["body"]["body"]
        self.assertIn("Refs #12", sent)
        self.assertIn("what changed", sent)
        self.assertEqual(got["linked"], ["12"])
        fake.assert_drained()

    def test_the_ref_line_never_holds_a_closing_keyword(self):
        # A closing keyword completes the issue on merge, and an issue that
        # closes on merge skips its test pass.
        api, fake = client(FakeResponse(201, {"number": 3, "html_url": "u",
                                              "body": "d\n\nRefs #12\n"}))
        api.pr_create(head="b", title="t", body="d", links=[{"id": "12"}])
        sent = fake.calls[0]["body"]["body"]
        for keyword in ("Fixes", "Closes", "Resolves", "fixes", "closes"):
            self.assertNotIn(keyword, sent)
        fake.assert_drained()

    def test_a_link_the_stored_body_does_not_hold_is_named_unlinked(self):
        api, fake = client(FakeResponse(201, {"number": 3, "html_url": "u",
                                              "body": "d\n\nRefs #12\n"}))
        got = api.pr_create(head="b", title="t", body="d",
                            links=[{"id": "12"}, {"id": "13"}])
        self.assertEqual(got["linked"], ["12"])
        self.assertEqual(got["unlinked"], ["13"])
        fake.assert_drained()

    def test_a_longer_number_does_not_answer_for_a_shorter_one(self):
        api, fake = client(FakeResponse(201, {"number": 3, "html_url": "u",
                                              "body": "d\n\nRefs #123\n"}))
        got = api.pr_create(head="b", title="t", body="d", links=[{"id": "12"}])
        self.assertEqual(got["linked"], [])
        self.assertEqual(got["unlinked"], ["12"])
        fake.assert_drained()

    def test_an_id_that_is_not_a_number_is_unlinked_and_asks_for_nothing(self):
        # The globex profile holds a Jira tracker beside this host, so --link
        # DIST-1235 is a real command. GitHub reads a link from a hash and a
        # number, so that key links nothing. A body phrase naming it, and a
        # linked list holding it, are both claims about a link nobody made.
        api, fake = client(FakeResponse(201, {"number": 3, "html_url": "u",
                                              "body": "d"}))
        got = api.pr_create(head="b", title="t", body="d",
                            links=[{"id": "DIST-1235"}])
        self.assertEqual(got["linked"], [])
        self.assertEqual(got["unlinked"], ["DIST-1235"])
        self.assertEqual(fake.calls[0]["body"]["body"], "d")
        fake.assert_drained()

    def test_a_number_the_body_already_names_gets_no_second_line(self):
        api, fake = client(FakeResponse(201, {"number": 3, "html_url": "u",
                                              "body": "see #12 for the wording"}))
        got = api.pr_create(head="b", title="t", body="see #12 for the wording",
                            links=[{"id": "12"}])
        self.assertEqual(fake.calls[0]["body"]["body"], "see #12 for the wording")
        self.assertEqual(got["linked"], ["12"])
        fake.assert_drained()

    def test_a_reviewer_reads_back_from_the_requested_list(self):
        api, fake = client(FakeResponse(201, {"number": 3, "html_url": "u"}),
                           FakeResponse(201, {"requested_reviewers":
                                              [{"login": "Reviewer"}]}))
        got = api.pr_create(head="b", title="t", body="d", reviewer="reviewer")
        self.assertTrue(got["reviewer_ok"])
        self.assertEqual(fake.calls[1]["url"], f"{REPO}/pulls/3/requested_reviewers")
        fake.assert_drained()

    def test_a_reviewer_the_server_refused_keeps_the_pull_request(self):
        api, fake = client(FakeResponse(201, {"number": 3, "html_url": "u"}),
                           raiser(422, "not a collaborator"))
        got = api.pr_create(head="b", title="t", body="d", reviewer="reviewer")
        self.assertEqual(got["id"], 3)
        self.assertFalse(got["reviewer_ok"])
        fake.assert_drained()

    def test_pr_threads_returns_other_people_comments(self):
        review = [{"id": 1, "user": {"login": "reviewer"}, "body": "rename",
                   "in_reply_to_id": None}]
        issue = [{"id": 2, "user": {"login": "devuser"}, "body": "mine"}]
        api, fake = client(FakeResponse(200, review), FakeResponse(200, issue))
        got = api.pr_threads(3, me="devuser")
        self.assertEqual([thread["author"] for thread in got], ["reviewer"])
        fake.assert_drained()

    def test_my_own_comment_goes_out_whatever_case_the_profile_spells(self):
        review = [{"id": 1, "user": {"login": "devuser"}, "body": "mine",
                   "in_reply_to_id": None}]
        api, fake = client(FakeResponse(200, review), FakeResponse(200, []))
        self.assertEqual(api.pr_threads(3, me="DevUser"), [])
        fake.assert_drained()

    def test_my_own_thread_goes_out_when_me_holds_a_tracker_id_beside_the_login(self):
        # The live globex profile is a Jira tracker beside this host, so the
        # caller hands over the Jira account id beside the GitHub login. A
        # single wrong name left every thread in the list, and a resume run
        # answered its own comments.
        review = [{"id": 1, "user": {"login": "devuser"}, "body": "mine",
                   "in_reply_to_id": None}]
        issue = [{"id": 2, "user": {"login": "reviewer"}, "body": "rename"}]
        api, fake = client(FakeResponse(200, review), FakeResponse(200, issue))
        got = api.pr_threads(3, me=["devuser", "712020:db94cfd4-ccce"])
        self.assertEqual([thread["author"] for thread in got], ["reviewer"])
        fake.assert_drained()

    def test_pr_threads_groups_a_reply_under_the_thread_it_answers(self):
        # One shape for both hosts. The thread id is the id a reply needs, and
        # a flat list holds no such id.
        review = [{"id": 1, "user": {"login": "reviewer"}, "body": "rename",
                   "created_at": "t1", "in_reply_to_id": None},
                  {"id": 2, "user": {"login": "devuser"}, "body": "done",
                   "created_at": "t2", "in_reply_to_id": 1}]
        issue = [{"id": 5, "user": {"login": "lead"}, "body": "the title too",
                  "created_at": "t3"}]
        api, fake = client(FakeResponse(200, review), FakeResponse(200, issue))
        got = api.pr_threads(3, me="devuser")
        self.assertEqual([thread["id"] for thread in got], [1, 5])
        self.assertEqual(got[0]["author"], "reviewer")
        self.assertEqual(got[0]["text"], "rename")
        self.assertEqual(got[0]["created"], "t1")
        self.assertEqual([row["author"] for row in got[0]["comments"]],
                         ["reviewer", "devuser"])
        self.assertEqual(got[1]["comments"][0]["text"], "the title too")
        fake.assert_drained()

    def test_a_second_reply_stays_in_one_thread(self):
        # The reply route takes the id of the comment that opened the thread,
        # so every reply names that same id. One thread never splits in two.
        review = [{"id": 1, "user": {"login": "reviewer"}, "body": "rename",
                   "created_at": "t1", "in_reply_to_id": None},
                  {"id": 2, "user": {"login": "lead"}, "body": "agree",
                   "created_at": "t2", "in_reply_to_id": 1},
                  {"id": 3, "user": {"login": "reviewer"}, "body": "still open",
                   "created_at": "t3", "in_reply_to_id": 1}]
        api, fake = client(FakeResponse(200, review), FakeResponse(200, []))
        got = api.pr_threads(3)
        self.assertEqual(len(got), 1)
        self.assertEqual([row["id"] for row in got[0]["comments"]], [1, 2, 3])
        fake.assert_drained()

    def test_a_thread_carries_the_keys_the_azure_host_carries(self):
        review = [{"id": 1, "user": {"login": "reviewer"}, "body": "rename",
                   "created_at": "t1", "in_reply_to_id": None}]
        api, fake = client(FakeResponse(200, review), FakeResponse(200, []))
        thread = api.pr_threads(3)[0]
        for key in ("id", "status", "author", "comments"):
            self.assertIn(key, thread)
        self.assertEqual(sorted(thread["comments"][0]), ["author", "id", "text"])
        fake.assert_drained()

    def test_a_reply_in_my_own_thread_keeps_the_thread(self):
        # Resume mode looks for the requests nobody answered. A reviewer who
        # replies inside the thread the bot opened is the most common shape a
        # request takes, and a test on the opener alone drops it. The run then
        # reports a clean pull request over a live request.
        review = [{"id": 1, "user": {"login": "devuser"}, "body": "fixed",
                   "created_at": "t1", "in_reply_to_id": None},
                  {"id": 2, "user": {"login": "reviewer"}, "body": "still wrong",
                   "created_at": "t2", "in_reply_to_id": 1}]
        api, fake = client(FakeResponse(200, review), FakeResponse(200, []))
        got = api.pr_threads(3, me="devuser")
        self.assertEqual([thread["id"] for thread in got], [1])
        self.assertEqual(got[0]["comments"][1]["text"], "still wrong")
        fake.assert_drained()

    def test_a_thread_holding_nothing_but_my_text_goes_out(self):
        review = [{"id": 1, "user": {"login": "devuser"}, "body": "fixed",
                   "created_at": "t1", "in_reply_to_id": None},
                  {"id": 2, "user": {"login": "DevUser"}, "body": "and this",
                   "created_at": "t2", "in_reply_to_id": 1}]
        api, fake = client(FakeResponse(200, review), FakeResponse(200, []))
        self.assertEqual(api.pr_threads(3, me="devuser"), [])
        fake.assert_drained()

    def test_pr_comment_replies_inside_the_review_thread(self):
        api, fake = client(FakeResponse(200, {"id": 1}),
                           FakeResponse(201, {"id": 8, "body": "done"}))
        got = api.pr_comment(3, "done", reply_to=1)
        self.assertTrue(got["ok"])
        self.assertEqual(fake.calls[0]["url"], f"{REPO}/pulls/comments/1")
        self.assertEqual(fake.calls[1]["url"],
                         f"{REPO}/pulls/3/comments/1/replies")
        fake.assert_drained()

    def test_a_reply_to_an_issue_comment_goes_under_the_pull_request(self):
        # An issue comment has no reply route. A reply on the review route
        # answers 404 and the text is lost.
        api, fake = client(raiser(404, "Not Found"),
                           FakeResponse(201, {"id": 8, "body": "done"}))
        got = api.pr_comment(3, "done", reply_to=5)
        self.assertTrue(got["ok"])
        self.assertEqual(fake.calls[1]["url"], f"{REPO}/issues/3/comments")
        fake.assert_drained()

    def test_a_real_failure_on_the_reply_probe_still_fails(self):
        api, fake = client(raiser(500, "server error"))
        with self.assertRaises(http_mod.HttpError):
            api.pr_comment(3, "done", reply_to=5)
        fake.assert_drained()

    def test_a_pr_comment_with_no_stored_body_is_not_ok(self):
        api, fake = client(FakeResponse(201, {"id": 8}))
        self.assertFalse(api.pr_comment(3, "")["ok"])
        fake.assert_drained()

    def test_pr_describe_reads_the_body_back(self):
        api, fake = client(FakeResponse(200, {"body": "old text"}),
                           FakeResponse(200, {"body": "what changed"}))
        got = api.pr_describe(3, "what changed")
        self.assertTrue(got["ok"])
        self.assertEqual(fake.calls[1]["method"], "PATCH")
        self.assertEqual(got["unlinked"], [])
        fake.assert_drained()

    def test_a_description_the_server_never_stored_is_not_ok(self):
        api, fake = client(FakeResponse(200, {"body": ""}), FakeResponse(200, {}))
        self.assertFalse(api.pr_describe(3, "")["ok"])
        fake.assert_drained()

    def test_a_rewrite_that_drops_a_ref_names_the_issue_it_unlinked(self):
        # The link lives in the body now, so a rewrite can destroy it and
        # GitHub says nothing. Name the number instead of going silent.
        api, fake = client(FakeResponse(200, {"body": "old\n\nRefs #12\nRefs #13\n"}),
                           FakeResponse(200, {"body": "new\n\nRefs #13\n"}))
        got = api.pr_describe(3, "new\n\nRefs #13\n")
        self.assertTrue(got["ok"])
        self.assertEqual(got["unlinked"], ["12"])
        self.assertEqual(fake.calls[0]["method"], "GET")
        fake.assert_drained()

    def test_a_rewrite_that_keeps_every_ref_unlinks_nothing(self):
        api, fake = client(FakeResponse(200, {"body": "old\n\nRefs #12\n"}),
                           FakeResponse(200, {"body": "new\n\nRefs #12\n"}))
        self.assertEqual(api.pr_describe(3, "new\n\nRefs #12\n")["unlinked"], [])
        fake.assert_drained()


class TestGitHubAttach(unittest.TestCase):
    def test_pr_attach_creates_the_branch_then_commits_the_file(self):
        png = tmp_bytes(self, "shot.png", b"\x89PNG")
        api, fake = client(raiser(404, "no ref"),
                           FakeResponse(200, {"object": {"sha": "basesha"}}),
                           FakeResponse(201, {"ref": "refs/heads/pr-screenshots"}),
                           FakeResponse(201, {"commit": {"sha": "newsha"}}))
        got = api.pr_attach(3, str(png))
        self.assertIn("raw=true", got["url"])
        self.assertIn("newsha", got["url"])
        self.assertEqual(got["markdown"][0], chr(33))
        self.assertTrue(got["ok"])
        self.assertEqual(fake.calls[1]["url"], f"{REPO}/git/ref/heads/main")
        self.assertEqual(fake.calls[2]["body"]["ref"], "refs/heads/pr-screenshots")
        self.assertEqual(fake.calls[3]["body"]["branch"], "pr-screenshots")
        fake.assert_drained()

    def test_an_existing_branch_is_not_created_again(self):
        png = tmp_bytes(self, "shot.png", b"\x89PNG")
        api, fake = client(FakeResponse(200, {"object": {"sha": "oldsha"}}),
                           FakeResponse(201, {"commit": {"sha": "newsha"}}))
        api.pr_attach(3, str(png))
        self.assertEqual([call["method"] for call in fake.calls], ["GET", "PUT"])
        fake.assert_drained()

    def test_two_screenshots_that_share_a_name_both_survive(self):
        # The screenshot branch keeps every earlier file, so GitHub refuses a
        # create over a path it already holds.
        png = tmp_bytes(self, "shot.png", b"\x89PNG")
        api, fake = client(FakeResponse(200, {"object": {"sha": "oldsha"}}),
                           raiser(422, "sha was not supplied"),
                           FakeResponse(201, {"commit": {"sha": "newsha"}}))
        got = api.pr_attach(3, str(png))
        self.assertEqual(fake.calls[1]["url"],
                         f"{REPO}/contents/screenshots/shot.png")
        self.assertEqual(fake.calls[2]["url"],
                         f"{REPO}/contents/screenshots/shot-1.png")
        self.assertIn("shot-1.png", got["url"])
        fake.assert_drained()

    def test_a_real_failure_on_the_commit_still_fails(self):
        png = tmp_bytes(self, "shot.png", b"\x89PNG")
        api, fake = client(FakeResponse(200, {"object": {"sha": "oldsha"}}),
                           raiser(403, "no write access"))
        with self.assertRaises(http_mod.HttpError):
            api.pr_attach(3, str(png))
        fake.assert_drained()

    def test_no_directory_part_of_the_path_reaches_the_route(self):
        # The route must name one file inside the screenshots directory. A path
        # fragment there writes somewhere nobody asked for.
        png = tmp_bytes(self, "deep/shot.png", b"\x89PNG")
        api, fake = client(FakeResponse(200, {"object": {"sha": "oldsha"}}),
                           FakeResponse(201, {"commit": {"sha": "newsha"}}))
        api.pr_attach(3, str(png))
        self.assertEqual(fake.calls[1]["url"],
                         f"{REPO}/contents/screenshots/shot.png")
        fake.assert_drained()

    def test_a_name_with_a_space_is_encoded_in_the_route(self):
        png = tmp_bytes(self, "panel one.png", b"\x89PNG")
        api, fake = client(FakeResponse(200, {"object": {"sha": "oldsha"}}),
                           FakeResponse(201, {"commit": {"sha": "newsha"}}))
        got = api.pr_attach(3, str(png))
        self.assertEqual(fake.calls[1]["url"],
                         f"{REPO}/contents/screenshots/panel%20one.png")
        self.assertIn("panel%20one.png", got["url"])
        fake.assert_drained()

    def test_a_commit_with_no_sha_is_not_ok(self):
        png = tmp_bytes(self, "shot.png", b"\x89PNG")
        api, fake = client(FakeResponse(200, {"object": {"sha": "oldsha"}}),
                           FakeResponse(201, {}))
        self.assertFalse(api.pr_attach(3, str(png))["ok"])
        fake.assert_drained()

    def test_a_name_walk_that_runs_out_raises_the_last_answer(self):
        # The walk is bounded. Without the bound a route that answers 422 for
        # another reason would loop, and the caller would read no error at all.
        png = tmp_bytes(self, "shot.png", b"\x89PNG")
        api, fake = client(FakeResponse(200, {"object": {"sha": "oldsha"}}),
                           *[raiser(422, "sha was not supplied")
                             for _ in range(github.TAKEN_TRIES)])
        with self.assertRaises(http_mod.HttpError):
            api.pr_attach(3, str(png))
        fake.assert_drained()


if __name__ == "__main__":
    unittest.main()
