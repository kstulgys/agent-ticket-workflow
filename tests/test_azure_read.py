import os
import tempfile
import unittest

import helpers  # noqa: F401
from fixtures import AZ_COMMENTS, AZ_PROFILE, AZ_VALUES, AZ_WORKITEM
from helpers import FakeHttp, FakeResponse

from tk_lib import azure, http as http_mod, secrets, shape

ORG = "https://dev.azure.com/northwind"
PROJECT = "Contoso%20migration"
VERSION = "api-version=7.1-preview"
# Pin the whole url, not a part of it. assertIn("expand=all", url) also passes
# for %24expand=all, and assertIn(VERSION, url) also passes for 7.1-preview.3.
# Both of those fail against the real service.
ITEM_URL = f"{ORG}/_apis/wit/workitems/59644?$expand=all&{VERSION}"
COMMENTS_URL = f"{ORG}/{PROJECT}/_apis/wit/workItems/59644/comments?{VERSION}"
WIQL_URL = f"{ORG}/{PROJECT}/_apis/wit/wiql?{VERSION}"
BATCH_URL = (f"{ORG}/_apis/wit/workitems?ids=1,2"
             f"&fields=System.Id,System.WorkItemType,System.State,System.Title&{VERSION}")
WHOAMI_URL = f"{ORG}/_apis/connectionData?{VERSION}"


def client(*responses):
    fake = FakeHttp(responses)
    return azure.Azure(AZ_PROFILE, AZ_VALUES, fake), fake


def raiser(status, body):
    def item():
        raise http_mod.HttpError(status, body)

    return item


def reader():
    return client(FakeResponse(200, AZ_WORKITEM), FakeResponse(200, AZ_COMMENTS))


def attached(name, key):
    return {"rel": "AttachedFile", "attributes": {"name": name},
            "url": f"{ORG}/_apis/wit/attachments/{key}"}


def workitem_with(*relations):
    """AZ_WORKITEM with other relations. The fixture stays untouched."""
    item = dict(AZ_WORKITEM)
    item["relations"] = list(relations)
    return item


def profile_with(**tracker):
    out = dict(AZ_PROFILE)
    out["tracker"] = {**AZ_PROFILE["tracker"], **tracker}
    return out


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


class TestAzureShow(unittest.TestCase):
    def test_show_returns_the_normalised_shape(self):
        api, fake = reader()
        got = api.show("59644")
        self.assertEqual(got["slug"], "northwind")
        self.assertEqual(got["tracker"], "azure")
        self.assertEqual(got["id"], "59644")
        self.assertEqual(got["key"], "59644")
        self.assertEqual(got["type"], "Task")
        self.assertEqual(got["state"], "To Do")
        self.assertEqual(got["assignee"], "Example Dev")
        self.assertEqual(got["url"], "https://dev.azure.com/northwind/_workitems/edit/59644")
        fake.assert_drained()

    def test_show_fills_every_key_in_the_shape(self):
        api, fake = reader()
        got = api.show("59644")
        self.assertEqual(sorted(got), sorted(shape.KEYS))
        for key in shape.LIST_KEYS:
            self.assertIsInstance(got[key], list, key)
        fake.assert_drained()

    def test_description_keeps_the_table_row(self):
        api, fake = reader()
        self.assertIn("Brookfield | GTM-42", api.show("59644")["description_text"])
        fake.assert_drained()

    def test_comments_arrive_as_text(self):
        api, fake = reader()
        comments = api.show("59644")["comments"]
        self.assertEqual(comments[0]["author"], "Sam")
        self.assertEqual(comments[0]["text"], "for Brookfield the id is GTM-42")
        fake.assert_drained()

    def test_show_follows_every_page_of_comments(self):
        # The endpoint pages. One page read looks like a whole ticket, and the
        # frame link in a late comment goes missing with no error.
        late = "<p>https://www.figma.com/design/Z/y?node-id=9-9</p>"
        page1 = {"comments": [{"createdBy": {"displayName": "Sam"},
                               "text": "<p>one</p>"}],
                 "continuationToken": "tok1"}
        page2 = {"comments": [{"createdBy": {"displayName": "Ann"}, "text": late}]}
        api, fake = client(FakeResponse(200, AZ_WORKITEM), FakeResponse(200, page1),
                           FakeResponse(200, page2))
        got = api.show("59644")
        self.assertEqual([c["text"] for c in got["comments"]],
                         ["one", "https://www.figma.com/design/Z/y?node-id=9-9"])
        self.assertEqual(
            fake.calls[2]["url"],
            f"{ORG}/{PROJECT}/_apis/wit/workItems/59644/comments"
            f"?continuationToken=tok1&{VERSION}")
        self.assertIn("https://www.figma.com/design/Z/y?node-id=9-9", got["figma_urls"])
        fake.assert_drained()

    def test_a_repeated_continuation_token_stops_the_page_loop(self):
        # A server that returns the same token twice must not hang the CLI.
        page = {"comments": [{"text": "<p>one</p>"}], "continuationToken": "tok1"}
        api, fake = client(FakeResponse(200, AZ_WORKITEM), FakeResponse(200, page),
                           FakeResponse(200, page))
        got = api.show("59644")
        self.assertEqual([c["text"] for c in got["comments"]], ["one", "one"])
        fake.assert_drained()

    def test_figma_urls_come_from_the_description_and_the_comments(self):
        api, fake = reader()
        self.assertEqual(api.show("59644")["figma_urls"],
                         ["https://www.figma.com/design/ABC/x?node-id=1-2"])
        fake.assert_drained()
        # A designer usually drops the frame link in a comment. A url that only
        # a comment holds must reach the list too.
        text = "<p>https://www.figma.com/design/Z/y?node-id=9-9</p>"
        late = {"comments": [{"createdBy": {"displayName": "Ann"}, "text": text}]}
        api, fake = client(FakeResponse(200, AZ_WORKITEM), FakeResponse(200, late))
        self.assertEqual(api.show("59644")["figma_urls"],
                         ["https://www.figma.com/design/ABC/x?node-id=1-2",
                          "https://www.figma.com/design/Z/y?node-id=9-9"])
        fake.assert_drained()

    def test_parent_and_children_come_from_relations(self):
        api, fake = reader()
        got = api.show("59644")
        self.assertEqual(got["parent"], "59614")
        self.assertEqual(got["children"], ["59645"])
        fake.assert_drained()

    def test_the_work_item_and_the_comment_reads_use_the_exact_urls(self):
        api, fake = reader()
        api.show("59644")
        self.assertEqual(fake.calls[0]["url"], ITEM_URL)
        self.assertEqual(fake.calls[1]["url"], COMMENTS_URL)
        fake.assert_drained()

    def test_attachments_download_when_a_directory_is_given(self):
        target = self.enterContext(tempfile.TemporaryDirectory())
        api, fake = client(FakeResponse(200, AZ_WORKITEM), FakeResponse(200, AZ_COMMENTS),
                           FakeResponse(200, b"\x89PNG bytes"))
        got = api.show("59644", attachments_dir=target)
        self.assertEqual(got["attachments"][0]["filename"], "shot.png")
        self.assertEqual(read_bytes(got["attachments"][0]["path"]), b"\x89PNG bytes")
        # The relation url arrives with no version. The download is a call, so
        # it needs one too.
        self.assertEqual(fake.calls[2]["url"],
                         f"{ORG}/_apis/wit/attachments/aaa?{VERSION}")
        fake.assert_drained()

    def test_two_attachments_with_one_name_keep_both_files(self):
        # Two pasted screenshots on one work item is the ordinary case. Without
        # a unique path the second download overwrites the first, and both
        # records then point at the same bytes.
        target = self.enterContext(tempfile.TemporaryDirectory())
        item = workitem_with(attached("shot.png", "aaa"), attached("shot.png", "bbb"))
        api, fake = client(FakeResponse(200, item), FakeResponse(200, AZ_COMMENTS),
                           FakeResponse(200, b"first"), FakeResponse(200, b"second"))
        paths = [a["path"] for a in api.show("59644", attachments_dir=target)["attachments"]]
        self.assertNotEqual(paths[0], paths[1])
        self.assertEqual([read_bytes(p) for p in paths], [b"first", b"second"])
        self.assertEqual(sorted(os.listdir(target)), ["shot-1.png", "shot.png"])
        fake.assert_drained()

    def test_an_attachment_name_cannot_leave_the_target_directory(self):
        # The provider owns the name, so treat it as untrusted input.
        root = self.enterContext(tempfile.TemporaryDirectory())
        target = os.path.join(root, "att")
        os.mkdir(target)
        item = workitem_with(
            attached("../escaped.png", "aaa"),
            attached(os.path.join(root, "absolute.png"), "bbb"),
            attached("", "ccc"),
            attached("..", "ddd"))
        api, fake = client(FakeResponse(200, item), FakeResponse(200, AZ_COMMENTS),
                           FakeResponse(200, b"a"), FakeResponse(200, b"b"),
                           FakeResponse(200, b"c"), FakeResponse(200, b"d"))
        got = api.show("59644", attachments_dir=target)
        for entry in got["attachments"]:
            self.assertEqual(os.path.dirname(entry["path"]), target, entry["filename"])
        self.assertEqual(sorted(os.listdir(target)),
                         ["absolute.png", "attachment", "attachment-1", "escaped.png"])
        self.assertEqual(os.listdir(root), ["att"])
        fake.assert_drained()

    def test_attachments_are_listed_without_a_directory_and_not_fetched(self):
        api, fake = reader()
        got = api.show("59644")
        self.assertIsNone(got["attachments"][0]["path"])
        self.assertEqual(len(fake.calls), 2)
        fake.assert_drained()


class TestAzureMine(unittest.TestCase):
    def test_mine_runs_wiql_then_hydrates(self):
        wiql = {"workItems": [{"id": 1}, {"id": 2}]}
        # A batch read with a fields filter carries no _links, so item 1 has
        # none. Item 2 has one, and it must win over the built url.
        hydrated = {"value": [
            {"id": 1, "fields": {"System.WorkItemType": "Bug", "System.State": "New",
                                 "System.Title": "one"}},
            {"id": 2, "fields": {"System.WorkItemType": "Task", "System.State": "To Do",
                                 "System.Title": "two"},
             "_links": {"html": {"href": "https://example.test/two"}}}]}
        api, fake = client(FakeResponse(200, wiql), FakeResponse(200, hydrated))
        got = api.mine()
        self.assertEqual([item["title"] for item in got], ["one", "two"])
        self.assertEqual(got[0]["url"], f"{ORG}/{PROJECT}/_workitems/edit/1")
        self.assertEqual(got[1]["url"], "https://example.test/two")
        self.assertEqual(fake.calls[0]["method"], "POST")
        self.assertIn("@Me", fake.calls[0]["body"]["query"])
        self.assertEqual(fake.calls[0]["url"], WIQL_URL)
        self.assertEqual(fake.calls[1]["url"], BATCH_URL)
        fake.assert_drained()

    def test_mine_with_no_hits_skips_the_hydrate_call(self):
        api, fake = client(FakeResponse(200, {"workItems": []}))
        self.assertEqual(api.mine(), [])
        self.assertEqual(len(fake.calls), 1)
        fake.assert_drained()


class TestAzureWhoami(unittest.TestCase):
    def test_whoami_reads_connection_data(self):
        payload = {"authenticatedUser": {"id": "guid", "providerDisplayName": "Example"}}
        api, fake = client(FakeResponse(200, payload))
        got = api.whoami()
        self.assertEqual(got["name"], "Example")
        self.assertEqual(got["id"], "guid")
        self.assertEqual(fake.calls[0]["url"], WHOAMI_URL)
        fake.assert_drained()

    def test_repo_check_reads_a_work_item_not_a_core_route(self):
        # A PAT carries a project scope and a scope per API area. One scoped to
        # Code alone answers a Core project route, so that read reports the
        # project green and the run then fails at tk show with a 401 that reads
        # as a permissions problem. A work item read needs the project and the
        # Work Items scope together.
        api, fake = client(FakeResponse(200, {"workItems": [{"id": 59644}]}))
        self.assertTrue(api.repo_check()["ok"])
        self.assertEqual(fake.calls[0]["method"], "POST")
        self.assertEqual(fake.calls[0]["url"], WIQL_URL)
        self.assertIn("System.AssignedTo", fake.calls[0]["body"]["query"])
        fake.assert_drained()

    def test_repo_check_is_ok_when_no_work_item_is_assigned(self):
        # An empty board is not a permissions failure.
        api, fake = client(FakeResponse(200, {"workItems": []}))
        self.assertTrue(api.repo_check()["ok"])
        fake.assert_drained()

    def test_repo_check_reports_the_refusal_instead_of_raising(self):
        api, fake = client(raiser(403, "TF400813 access denied"))
        got = api.repo_check()
        self.assertFalse(got["ok"])
        self.assertIn("TF400813", got["error"])
        fake.assert_drained()


class TestAzureProfile(unittest.TestCase):
    def test_a_missing_org_or_project_names_the_slug_and_the_key(self):
        for key in ("org", "project"):
            with self.subTest(key=key):
                with self.assertRaises(ValueError) as caught:
                    azure.Azure(profile_with(**{key: None}), AZ_VALUES, FakeHttp())
                self.assertIn("northwind", str(caught.exception))
                self.assertIn(f"tracker.{key}", str(caught.exception))

    def test_a_version_without_the_preview_suffix_is_rejected(self):
        # A config.json that says 7.1 reinstates the trap this adapter guards.
        for bad in ("7.1", "6.0", "7.2-preview"):
            with self.subTest(version=bad):
                with self.assertRaises(ValueError) as caught:
                    azure.Azure(profile_with(api_version=bad), AZ_VALUES, FakeHttp())
                self.assertIn("7.1-preview", str(caught.exception))
                self.assertIn(bad, str(caught.exception))

    def test_a_preview_point_release_is_accepted(self):
        api = azure.Azure(profile_with(api_version="7.1-preview.3"), AZ_VALUES, FakeHttp())
        self.assertEqual(api.version, "7.1-preview.3")


class TestAzureAuth(unittest.TestCase):
    def test_a_missing_token_names_the_variable_and_not_the_value(self):
        # The dict holds the real token under another name. With no token in the
        # dict at all, the second assertion has nothing to catch.
        values = {"AZDO_USER": "me@example.com", "OTHER_PAT": AZ_VALUES["AZDO_PAT"]}
        with self.assertRaises(secrets.SecretsError) as caught:
            azure.Azure(AZ_PROFILE, values, FakeHttp())
        self.assertIn("AZDO_PAT", str(caught.exception))
        self.assertNotIn(AZ_VALUES["AZDO_PAT"], str(caught.exception))


if __name__ == "__main__":
    unittest.main()
