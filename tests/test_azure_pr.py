"""Azure Repos pull requests: create, link, threads, attachments."""
import pathlib
import shutil
import tempfile
import unittest

import helpers  # noqa: F401
from fixtures import AZ_PROFILE, AZ_VALUES
from helpers import FakeHttp, FakeResponse

from tk_lib import azure, http

ORG = "https://dev.azure.com/northwind"
PROJECT = "Contoso%20migration"
GIT = f"{ORG}/{PROJECT}/_apis/git/repositories/repo-guid"
# Pin the whole url. A git route needs 7.1-preview.1, and a test that only
# looks for 7.1-preview also passes for the work item version, which the git
# routes refuse.
GIT_VERSION = "api-version=7.1-preview.1"
WIT_VERSION = "api-version=7.1-preview"
CREATE_URL = f"{GIT}/pullrequests?{GIT_VERSION}"
LINKED_URL = f"{GIT}/pullRequests/6453/workitems?{GIT_VERSION}"
THREADS_URL = f"{GIT}/pullRequests/6453/threads?{GIT_VERSION}"
REPLY_URL = f"{GIT}/pullRequests/6453/threads/7/comments?{GIT_VERSION}"
ATTACH_URL = f"{GIT}/pullRequests/6453/attachments/panel.png?{GIT_VERSION}"
PR_URL = f"{GIT}/pullRequests/6453?{GIT_VERSION}"
WIT_PATCH_URL = f"{ORG}/_apis/wit/workItems/59644?{WIT_VERSION}"
# The url Azure answers with after an upload is a git route, so its read-back
# needs the git version, not the work item version.
SERVED_URL = f"{GIT}/pullRequests/6453/attachments/panel.png"


def thread_url(thread_id):
    return f"{GIT}/pullRequests/6453/threads/{thread_id}?{GIT_VERSION}"


def client(*responses):
    fake = FakeHttp(responses)
    return azure.Azure(AZ_PROFILE, AZ_VALUES, fake), fake


def tmp_bytes(test, name, payload):
    """Writes one file in a temp directory that goes away with the test.

    The parents come first, as in test_github.py. A name holding a separator is
    one file name on POSIX and a path on Windows, and the separator case below
    needs the same bytes on disk to ask the same question on both.
    """
    root = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, root, True)
    path = pathlib.Path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


class TestPrCreate(unittest.TestCase):
    def test_creates_against_the_base_branch(self):
        api, fake = client(FakeResponse(200, {"pullRequestId": 6453}))
        got = api.pr_create(head="feature/59644-gtm",
                            title="[59644] Hillcrest | fields", body="what changed")
        self.assertEqual(got["id"], 6453)
        # No reviewer asked for, so there is nothing to report about one.
        self.assertIsNone(got["reviewer_ok"])
        self.assertEqual(fake.calls[0]["method"], "POST")
        self.assertEqual(fake.calls[0]["body"]["sourceRefName"],
                         "refs/heads/feature/59644-gtm")
        self.assertEqual(fake.calls[0]["body"]["targetRefName"], "refs/heads/master")
        self.assertEqual(fake.calls[0]["body"]["title"], "[59644] Hillcrest | fields")
        self.assertEqual(fake.calls[0]["body"]["description"], "what changed")
        self.assertIn("7.1-preview.1", fake.calls[0]["url"])
        self.assertEqual(fake.calls[0]["url"], CREATE_URL)
        fake.assert_drained()

    def test_links_a_task_with_an_explicit_artifact_relation(self):
        api, fake = client(FakeResponse(200, {"pullRequestId": 6453}),
                           FakeResponse(200, {"id": 59644}),
                           FakeResponse(200, {"value": [{"id": 59644}]}))
        got = api.pr_create(head="b", title="t", body="d",
                            links=[{"id": "59644", "type": "Task"}])
        relation = fake.calls[1]["body"][0]["value"]
        self.assertEqual(relation["rel"], "ArtifactLink")
        self.assertEqual(relation["url"],
                         "vstfs:///Git/PullRequestId/proj-guid%2Frepo-guid%2F6453")
        self.assertEqual(got["linked"], ["59644"])
        self.assertEqual(got["unlinked"], [])
        self.assertEqual(fake.calls[1]["method"], "PATCH")
        self.assertEqual(fake.calls[1]["url"], WIT_PATCH_URL)
        self.assertEqual(fake.calls[1]["headers"]["Content-Type"],
                         "application/json-patch+json")
        self.assertEqual(fake.calls[2]["method"], "GET")
        self.assertEqual(fake.calls[2]["url"], LINKED_URL)
        fake.assert_drained()

    def test_refuses_to_link_a_type_on_the_never_list(self):
        api, fake = client(FakeResponse(200, {"pullRequestId": 6453}))
        got = api.pr_create(head="b", title="t", body="d",
                            links=[{"id": "59614", "type": "Bug"}])
        self.assertEqual(got["linked"], [])
        self.assertEqual(got["refused"], ["59614"])
        self.assertEqual(len(fake.calls), 1)
        fake.assert_drained()

    def test_a_refused_type_does_not_stop_the_allowed_one(self):
        # A merge completes every linked work item. The bug keeps its test pass,
        # and the task still gets its link.
        api, fake = client(FakeResponse(200, {"pullRequestId": 6453}),
                           FakeResponse(200, {"id": 59644}),
                           FakeResponse(200, {"value": [{"id": 59644}]}))
        got = api.pr_create(head="b", title="t", body="d",
                            links=[{"id": "59614", "type": "Bug"},
                                   {"id": "59644", "type": "Task"}])
        self.assertEqual(got["refused"], ["59614"])
        self.assertEqual(got["linked"], ["59644"])
        self.assertEqual(fake.calls[1]["url"], WIT_PATCH_URL)
        fake.assert_drained()

    def test_a_reviewer_goes_on_with_no_vote_and_reads_back(self):
        api, fake = client(FakeResponse(200, {"pullRequestId": 6453}),
                           FakeResponse(200, {"id": "rev-guid"}))
        got = api.pr_create(head="b", title="t", body="d", reviewer="rev-guid")
        self.assertTrue(got["reviewer_ok"])
        self.assertEqual(fake.calls[1]["method"], "PUT")
        self.assertEqual(fake.calls[1]["url"],
                         f"{GIT}/pullRequests/6453/reviewers/rev-guid?{GIT_VERSION}")
        self.assertEqual(fake.calls[1]["body"], {"vote": 0})
        fake.assert_drained()

    def test_a_reviewer_the_server_never_took_is_not_ok(self):
        # The branch and the pull request landed. Only the reviewer did not, so
        # say so and keep the pull request.
        api, fake = client(FakeResponse(200, {"pullRequestId": 6453}),
                           FakeResponse(200, {"id": "someone-else"}))
        got = api.pr_create(head="b", title="t", body="d", reviewer="rev-guid")
        self.assertFalse(got["reviewer_ok"])
        self.assertEqual(got["id"], 6453)
        fake.assert_drained()

    def test_an_empty_reviewer_answer_is_not_ok(self):
        api, fake = client(FakeResponse(200, {"pullRequestId": 6453}),
                           FakeResponse(200, {}))
        got = api.pr_create(head="b", title="t", body="d", reviewer="rev-guid")
        self.assertFalse(got["reviewer_ok"])
        fake.assert_drained()

    def test_a_link_the_server_dropped_is_named(self):
        # A dropped link shows only as a shorter list. Name the gap, so the
        # caller does not have to diff the ids it sent.
        api, fake = client(FakeResponse(200, {"pullRequestId": 6453}),
                           FakeResponse(200, {"id": 59644}),
                           FakeResponse(200, {"id": 59645}),
                           FakeResponse(200, {"value": [{"id": 59644}]}))
        got = api.pr_create(head="b", title="t", body="d",
                            links=[{"id": "59644", "type": "Task"},
                                   {"id": "59645", "type": "Task"}])
        self.assertEqual(got["linked"], ["59644"])
        self.assertEqual(got["unlinked"], ["59645"])
        fake.assert_drained()

    def test_a_reviewer_the_server_refused_keeps_the_pull_request(self):
        # A refusal arrives as a 400, not as a 200 naming another id. The pull
        # request exists by then. Losing its id here makes the caller retry and
        # open a second pull request.
        def refuse():
            raise http.HttpError(400, "reviewer not found")

        api, fake = client(FakeResponse(200, {"pullRequestId": 6453}), refuse)
        got = api.pr_create(head="b", title="t", body="d", reviewer="rev-guid")
        self.assertEqual(got["id"], 6453)
        self.assertFalse(got["reviewer_ok"])
        fake.assert_drained()

    def test_a_reviewer_name_with_a_space_is_encoded_in_the_url(self):
        # An unresolved name reaches this route whole, spaces and all.
        api, fake = client(FakeResponse(200, {"pullRequestId": 6453}),
                           FakeResponse(200, {"id": "Ana Fletcher"}))
        got = api.pr_create(head="b", title="t", body="d",
                            reviewer="Ana Fletcher")
        self.assertEqual(
            fake.calls[1]["url"],
            f"{GIT}/pullRequests/6453/reviewers/Ana%20Fletcher?{GIT_VERSION}")
        self.assertTrue(got["reviewer_ok"])
        fake.assert_drained()

    def test_an_incomplete_host_block_is_refused_before_the_create(self):
        # The url in the answer reads host.repo, and pr_link reads project_id
        # and repo_id. A read after the POST raises where the pull request
        # exists already: the caller loses its id, and the retry that follows
        # opens a second pull request on a real repository.
        for key in ("repo", "repo_id", "project_id"):
            with self.subTest(key=key):
                host = {name: value for name, value in AZ_PROFILE["host"].items()
                        if name != key}
                fake = FakeHttp([FakeResponse(200, {"pullRequestId": 6453})])
                api = azure.Azure({**AZ_PROFILE, "host": host}, AZ_VALUES, fake)
                with self.assertRaises(ValueError) as caught:
                    api.pr_create(head="b", title="t", body="d",
                                  links=[{"id": "59644", "type": "Task"}])
                self.assertIn(f"host.{key}", str(caught.exception))
                self.assertIn("northwind", str(caught.exception))
                # No write behind the refusal.
                self.assertEqual(fake.calls, [])


class TestPrThreads(unittest.TestCase):
    def test_returns_open_threads_from_other_people_only(self):
        threads = {"value": [
            {"id": 1, "status": "active", "comments": [
                {"id": 1, "author": {"displayName": "Ana"}, "content": "rename this",
                 "commentType": "text"}]},
            {"id": 2, "status": "active", "comments": [
                {"id": 1, "author": {"displayName": "Example"}, "content": "mine",
                 "commentType": "text"}]},
            {"id": 3, "status": "fixed", "comments": [
                {"id": 1, "author": {"displayName": "Ana"}, "content": "done",
                 "commentType": "text"}]},
            {"id": 4, "status": "active", "comments": [
                {"id": 1, "author": {"displayName": "System"}, "content": "voted",
                 "commentType": "system"}]}]}
        api, fake = client(FakeResponse(200, threads))
        got = api.pr_threads(6453, me="Example")
        self.assertEqual([thread["id"] for thread in got], [1])
        self.assertEqual(got[0]["author"], "Ana")
        self.assertEqual(fake.calls[0]["method"], "GET")
        self.assertEqual(fake.calls[0]["url"], THREADS_URL)
        fake.assert_drained()

    def test_my_own_thread_goes_by_identity_and_pending_stays(self):
        # A display name is not an identity. A colleague sharing the agent's
        # display name must keep their thread, or resume mode never answers it.
        # A pending thread is open, so the filter accepts it.
        threads = {"value": [
            {"id": 5, "status": "pending", "comments": [
                {"id": 1, "author": {"id": "ana-guid", "displayName": "Example Dev"},
                 "content": "rename this", "commentType": "text"}]},
            {"id": 6, "status": "active", "comments": [
                {"id": 1, "author": {"id": "me-guid", "displayName": "Example Dev"},
                 "content": "mine", "commentType": "text"}]}]}
        api, fake = client(FakeResponse(200, threads))
        got = api.pr_threads(6453, me="me-guid")
        self.assertEqual([thread["id"] for thread in got], [5])
        self.assertEqual(got[0]["status"], "pending")
        fake.assert_drained()

    def test_a_reply_in_my_own_thread_keeps_the_thread(self):
        # Resume mode looks for the requests nobody answered. A reviewer who
        # replies inside the thread the bot opened is the most common shape a
        # request takes, and a test on the opening comment alone drops it. The
        # run then reports a clean pull request over a live request.
        threads = {"value": [
            {"id": 7, "status": "active", "comments": [
                {"id": 1, "author": {"id": "me-guid", "displayName": "Example"},
                 "content": "fixed in this commit", "commentType": "text"},
                {"id": 2, "author": {"id": "ana-guid", "displayName": "Ana"},
                 "content": "still the old wording", "commentType": "text"}]},
            {"id": 8, "status": "active", "comments": [
                {"id": 1, "author": {"id": "me-guid", "displayName": "Example"},
                 "content": "mine", "commentType": "text"},
                {"id": 2, "author": {"id": "me-guid", "displayName": "Example"},
                 "content": "mine too", "commentType": "text"}]}]}
        api, fake = client(FakeResponse(200, threads))
        got = api.pr_threads(6453, me="me-guid")
        self.assertEqual([thread["id"] for thread in got], [7])
        self.assertEqual(got[0]["comments"][1]["text"], "still the old wording")
        fake.assert_drained()

    def test_me_takes_every_name_the_host_knows_me_by(self):
        # The caller hands over the host identity name beside the account id,
        # because one value cannot serve both hosts. The Azure host knows me by
        # the id, so the extra name must change nothing here.
        threads = {"value": [
            {"id": 9, "status": "active", "comments": [
                {"id": 1, "author": {"id": "ana-guid", "displayName": "Ana"},
                 "content": "rename this", "commentType": "text"}]},
            {"id": 10, "status": "active", "comments": [
                {"id": 1, "author": {"id": "me-guid", "displayName": "Example Dev"},
                 "content": "mine", "commentType": "text"}]}]}
        api, fake = client(FakeResponse(200, threads))
        got = api.pr_threads(6453, me=["Example.Dev", "me-guid"])
        self.assertEqual([thread["id"] for thread in got], [9])
        fake.assert_drained()


class TestPrComment(unittest.TestCase):
    def test_a_new_thread_omits_status_and_reads_back(self):
        created = {"id": 9, "comments": [{"id": 1, "content": "the payload carries the id"}]}
        api, fake = client(FakeResponse(200, created), FakeResponse(200, created))
        got = api.pr_comment(6453, "the payload carries the id")
        self.assertTrue(got["ok"])
        # No status key at all. An active status blocks the merge under the
        # blocking comment policy, and a fixed status hides the text.
        self.assertNotIn("status", fake.calls[0]["body"])
        self.assertNotIn("status", fake.calls[0]["body"]["comments"][0])
        self.assertEqual(fake.calls[0]["body"]["comments"][0]["commentType"], 1)
        self.assertEqual(fake.calls[0]["url"], THREADS_URL)
        self.assertEqual(fake.calls[1]["method"], "GET")
        self.assertEqual(fake.calls[1]["url"], thread_url(9))
        fake.assert_drained()

    def test_a_mangled_thread_read_back_is_not_ok(self):
        created = {"id": 9, "comments": [{"id": 1, "content": "something else"}]}
        api, fake = client(FakeResponse(200, created), FakeResponse(200, created))
        got = api.pr_comment(6453, "sent")
        self.assertFalse(got["ok"])
        self.assertEqual(got["stored"], "something else")
        fake.assert_drained()

    def test_a_reply_targets_the_thread_and_parent_comment_one(self):
        thread = {"id": 7, "comments": [{"id": 1, "content": "ask"},
                                        {"id": 2, "content": "changed it"}]}
        api, fake = client(FakeResponse(200, {"id": 2}), FakeResponse(200, thread))
        got = api.pr_comment(6453, "changed it", reply_to=7)
        self.assertTrue(got["ok"])
        self.assertIn("/threads/7/comments", fake.calls[0]["url"])
        self.assertEqual(fake.calls[0]["body"]["parentCommentId"], 1)
        self.assertNotIn("status", fake.calls[0]["body"])
        fake.assert_drained()

    def test_a_reply_reads_back_by_the_id_the_server_returned(self):
        thread = {"id": 7, "comments": [{"id": 1, "content": "ask"},
                                        {"id": 2, "content": "not what I sent"}]}
        api, fake = client(FakeResponse(200, {"id": 2}), FakeResponse(200, thread))
        got = api.pr_comment(6453, "changed it", reply_to=7)
        self.assertFalse(got["ok"])
        self.assertEqual(got["stored"], "not what I sent")
        self.assertEqual(fake.calls[0]["url"], REPLY_URL)
        self.assertEqual(fake.calls[1]["url"], thread_url(7))
        fake.assert_drained()

    def test_a_late_comment_from_someone_else_does_not_fail_my_reply(self):
        # The last comment in the thread is not always mine. Matching on the
        # position would report a landed write as failed, and the caller would
        # post the reply twice.
        thread = {"id": 7, "comments": [{"id": 1, "content": "ask"},
                                        {"id": 2, "content": "changed it"},
                                        {"id": 3, "content": "thanks, one more"}]}
        api, fake = client(FakeResponse(200, {"id": 2}), FakeResponse(200, thread))
        got = api.pr_comment(6453, "changed it", reply_to=7)
        self.assertTrue(got["ok"])
        self.assertEqual(got["stored"], "changed it")
        fake.assert_drained()

    def test_a_reply_that_never_comes_back_is_not_ok(self):
        thread = {"id": 7, "comments": [{"id": 1, "content": "ask"}]}
        api, fake = client(FakeResponse(200, {"id": 2}), FakeResponse(200, thread))
        got = api.pr_comment(6453, "changed it", reply_to=7)
        self.assertFalse(got["ok"])
        self.assertIsNone(got["stored"])
        fake.assert_drained()

    def test_a_thread_that_comes_back_with_no_comment_is_not_ok(self):
        # A missing value is never proof. An empty text against nothing at all
        # compares equal, so the guard reads the value first.
        api, fake = client(FakeResponse(200, {"id": 9}),
                           FakeResponse(200, {"id": 9, "comments": []}))
        got = api.pr_comment(6453, "")
        self.assertFalse(got["ok"])
        self.assertIsNone(got["stored"])
        fake.assert_drained()


class TestPrAttachAndDescribe(unittest.TestCase):
    def test_attach_sends_raw_bytes_and_returns_the_url(self):
        png = tmp_bytes(self, "panel.png", b"\x89PNG data")
        url = "https://dev.azure.com/northwind/attachments/panel.png"
        api, fake = client(FakeResponse(200, {"url": url}),
                           FakeResponse(200, b"\x89PNG data"))
        got = api.pr_attach(6453, str(png))
        self.assertEqual(got["url"], url)
        self.assertTrue(got["ok"])
        self.assertEqual(fake.calls[0]["body"], b"\x89PNG data")
        self.assertEqual(fake.calls[0]["headers"]["Content-Type"],
                         "application/octet-stream")
        self.assertEqual(fake.calls[0]["url"], ATTACH_URL)
        fake.assert_drained()

    def test_a_short_upload_is_not_ok(self):
        # A truncated upload serves fewer bytes than the file holds. The
        # markdown would then point at a broken image.
        png = tmp_bytes(self, "panel.png", b"\x89PNG data")
        api, fake = client(FakeResponse(200, {"url": "http://x/panel.png"}),
                           FakeResponse(200, b"\x89PNG"))
        got = api.pr_attach(6453, str(png))
        self.assertFalse(got["ok"])
        fake.assert_drained()

    def test_other_bytes_of_the_same_length_are_not_ok(self):
        # A length compare passes for content that does not match. The bytes
        # are already in hand, so compare them.
        png = tmp_bytes(self, "panel.png", b"\x89PNG data")
        api, fake = client(FakeResponse(200, {"url": SERVED_URL}),
                           FakeResponse(200, b"other one"))
        got = api.pr_attach(6453, str(png))
        self.assertFalse(got["ok"])
        fake.assert_drained()

    def test_a_name_with_a_space_and_a_hash_is_encoded_in_the_url(self):
        # A desktop screenshot name holds spaces. A hash would end the path at
        # the fragment, so the upload would go to the wrong route.
        png = tmp_bytes(self, "Screen Shot #2.png", b"\x89PNG")
        api, fake = client(FakeResponse(200, {"url": "http://x/panel.png"}),
                           FakeResponse(200, b"\x89PNG"))
        got = api.pr_attach(6453, str(png))
        self.assertEqual(
            fake.calls[0]["url"],
            f"{GIT}/pullRequests/6453/attachments/Screen%20Shot%20%232.png"
            f"?{GIT_VERSION}")
        # The markdown label keeps the name a person reads.
        self.assertIn("[Screen Shot #2.png]", got["markdown"])
        fake.assert_drained()

    def test_a_separator_in_the_name_cannot_reach_the_url(self):
        # A backslash is a separator on a Windows client and an ordinary
        # character in a POSIX file name. So this is one file called
        # shots\panel.png here and a file in a shots directory there, and
        # util.safe_name drops the directory part either way: no path fragment
        # reaches the route.
        png = tmp_bytes(self, "shots\\panel.png", b"\x89PNG")
        api, fake = client(FakeResponse(200, {"url": "http://x/panel.png"}),
                           FakeResponse(200, b"\x89PNG"))
        api.pr_attach(6453, str(png))
        self.assertEqual(fake.calls[0]["url"], ATTACH_URL)
        fake.assert_drained()

    def test_the_attachment_read_back_carries_the_git_api_version(self):
        # The url comes from the payload with no version, and it is a git
        # route. The work item version, which _versioned adds by default, is
        # the one version this route refuses.
        png = tmp_bytes(self, "panel.png", b"\x89PNG")
        api, fake = client(FakeResponse(200, {"url": SERVED_URL}),
                           FakeResponse(200, b"\x89PNG"))
        api.pr_attach(6453, str(png))
        self.assertEqual(fake.calls[1]["url"], f"{SERVED_URL}?{GIT_VERSION}")
        fake.assert_drained()

    def test_the_markdown_image_line_never_starts_with_the_escape_character(self):
        png = tmp_bytes(self, "panel.png", b"\x89PNG")
        api, fake = client(FakeResponse(200, {"url": "http://x/panel.png"}),
                           FakeResponse(200, b"\x89PNG"))
        got = api.pr_attach(6453, str(png))
        self.assertEqual(got["markdown"][0], chr(33))
        self.assertIn("(http://x/panel.png)", got["markdown"])
        fake.assert_drained()

    def test_describe_patches_the_description_and_reads_back(self):
        api, fake = client(FakeResponse(200, {"description": "new text"}))
        got = api.pr_describe(6453, "new text")
        self.assertTrue(got["ok"])
        self.assertEqual(fake.calls[0]["method"], "PATCH")
        self.assertEqual(fake.calls[0]["url"], PR_URL)
        fake.assert_drained()

    def test_describe_answers_the_keys_the_github_host_answers(self):
        # One caller reads one shape. A caller that reads unlinked after a
        # describe must not raise KeyError on this host.
        api, fake = client(FakeResponse(200, {"description": "new text"}))
        got = api.pr_describe(6453, "new text")
        self.assertEqual(sorted(got), ["ok", "stored", "unlinked"])
        # An Azure link is a relation on the work item, so a rewrite of the
        # description cannot drop one.
        self.assertEqual(got["unlinked"], [])
        fake.assert_drained()

    def test_a_mangled_description_read_back_is_not_ok(self):
        api, fake = client(FakeResponse(200, {"description": "the old text"}))
        got = api.pr_describe(6453, "new text")
        self.assertFalse(got["ok"])
        self.assertEqual(got["stored"], "the old text")
        fake.assert_drained()

    def test_a_description_the_server_never_stored_is_not_ok(self):
        # An answer with no description field is not proof of a write. Two
        # missing values compare equal, so read the value first.
        api, fake = client(FakeResponse(200, {}))
        got = api.pr_describe(6453, None)
        self.assertFalse(got["ok"])
        self.assertIsNone(got["stored"])
        fake.assert_drained()


class TestPrArgumentNames(unittest.TestCase):
    def test_every_pr_method_names_its_first_argument_pr(self):
        # The three adapters read identically, so one caller passes the same
        # keyword to each. A name that differs here is a TypeError at run time.
        api, fake = client(FakeResponse(200, {"description": "new text"}),
                           FakeResponse(200, {"value": []}))
        self.assertTrue(api.pr_describe(pr=6453, body="new text")["ok"])
        self.assertEqual(api.pr_threads(pr=6453), [])
        fake.assert_drained()


if __name__ == "__main__":
    unittest.main()
