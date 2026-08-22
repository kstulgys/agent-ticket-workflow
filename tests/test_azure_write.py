import unittest

import helpers  # noqa: F401
from fixtures import AZ_PROFILE, AZ_VALUES
from helpers import FakeHttp, FakeResponse

from tk_lib import azure

ORG = "https://dev.azure.com/northwind"
PROJECT = "Contoso%20migration"
VERSION = "api-version=7.1-preview"
# Pin the whole url. assertIn(VERSION, url) also passes for 7.1-preview.3, and
# a partial media type check also passes for application/json.
COMMENTS_URL = f"{ORG}/{PROJECT}/_apis/wit/workItems/59644/comments?{VERSION}"
PATCH_URL = f"{ORG}/_apis/wit/workItems/59644?{VERSION}"
WIQL_URL = f"{ORG}/{PROJECT}/_apis/wit/wiql?{VERSION}"
BATCH_URL = f"{ORG}/_apis/wit/workitems?ids=3&fields=System.AssignedTo&{VERSION}"


def client(*responses):
    fake = FakeHttp(responses)
    return azure.Azure(AZ_PROFILE, AZ_VALUES, fake), fake


class TestAzureComment(unittest.TestCase):
    def test_comment_posts_then_reads_back(self):
        posted = {"id": 5, "text": "<p>Fixed in PR 6453</p>"}
        stored = {"comments": [{"id": 5, "text": "<p>Fixed in PR 6453</p>"}]}
        api, fake = client(FakeResponse(200, posted), FakeResponse(200, stored))
        got = api.comment("59644", "Fixed in PR 6453")
        self.assertTrue(got["ok"])
        self.assertEqual(got["id"], 5)
        self.assertEqual(fake.calls[0]["method"], "POST")
        self.assertEqual(fake.calls[0]["body"]["text"], "Fixed in PR 6453")
        self.assertEqual(fake.calls[0]["url"], COMMENTS_URL)
        self.assertEqual(fake.calls[1]["method"], "GET")
        self.assertEqual(fake.calls[1]["url"], COMMENTS_URL)
        fake.assert_drained()

    def test_a_mangled_read_back_is_not_ok(self):
        posted = {"id": 5, "text": "sent"}
        stored = {"comments": [{"id": 5, "text": "something else"}]}
        api, fake = client(FakeResponse(200, posted), FakeResponse(200, stored))
        got = api.comment("59644", "sent")
        self.assertFalse(got["ok"])
        self.assertEqual(got["stored"], "something else")
        fake.assert_drained()

    def test_a_comment_that_never_comes_back_is_not_ok(self):
        # A 200 with an empty list is a lost write, not a success.
        posted = {"id": 5, "text": "sent"}
        api, fake = client(FakeResponse(200, posted), FakeResponse(200, {"comments": []}))
        got = api.comment("59644", "sent")
        self.assertFalse(got["ok"])
        self.assertIsNone(got["stored"])
        fake.assert_drained()

    def test_the_read_back_matches_on_the_id_and_not_the_order(self):
        posted = {"id": 7, "text": "mine"}
        stored = {"comments": [{"id": 5, "text": "someone else"},
                               {"id": 7, "text": "mine"}]}
        api, fake = client(FakeResponse(200, posted), FakeResponse(200, stored))
        got = api.comment("59644", "mine")
        self.assertTrue(got["ok"])
        self.assertEqual(got["stored"], "mine")
        fake.assert_drained()


class TestAzureState(unittest.TestCase):
    def test_state_patches_the_field_with_a_json_patch_body(self):
        api, fake = client(FakeResponse(200, {"fields": {"System.State": "In Progress"}}))
        got = api.state("59644", "In Progress")
        self.assertTrue(got["ok"])
        self.assertEqual(got["stored"], "In Progress")
        self.assertEqual(fake.calls[0]["method"], "PATCH")
        self.assertEqual(fake.calls[0]["url"], PATCH_URL)
        self.assertEqual(fake.calls[0]["headers"]["Content-Type"],
                         "application/json-patch+json")
        self.assertEqual(fake.calls[0]["body"],
                         [{"op": "add", "path": "/fields/System.State",
                           "value": "In Progress"}])
        fake.assert_drained()

    def test_a_state_the_server_never_took_is_not_ok(self):
        # The read-back compares. A server that kept the old state is a failure.
        api, fake = client(FakeResponse(200, {"fields": {"System.State": "To Do"}}))
        got = api.state("59644", "In Progress")
        self.assertFalse(got["ok"])
        self.assertEqual(got["stored"], "To Do")
        fake.assert_drained()

    def test_a_missing_state_field_is_not_ok(self):
        # A read-back that gives nothing back is not proof of a write.
        api, fake = client(FakeResponse(200, {"fields": {}}))
        got = api.state("59644", "")
        self.assertFalse(got["ok"])
        self.assertIsNone(got["stored"])
        fake.assert_drained()

    def test_a_state_map_picks_by_work_item_type(self):
        api, fake = client(FakeResponse(200, {"fields": {"System.State": "Committed"}}))
        got = api.state("59614", {"Task": "In Progress", "Bug": "Committed"},
                        item_type="Bug")
        self.assertTrue(got["ok"])
        self.assertEqual(got["stored"], "Committed")
        self.assertEqual(fake.calls[0]["body"][0]["value"], "Committed")
        fake.assert_drained()

    def test_a_state_map_without_a_type_is_an_error(self):
        api, fake = client()
        with self.assertRaises(ValueError):
            api.state("59614", {"Bug": "Committed"})
        self.assertEqual(fake.calls, [])

    def test_a_type_missing_from_the_map_names_the_known_types(self):
        api, fake = client()
        with self.assertRaises(ValueError) as cm:
            api.state("59614", {"Bug": "Committed"}, item_type="Task")
        self.assertIn("Bug", str(cm.exception))
        self.assertEqual(fake.calls, [])


class TestAzureAssign(unittest.TestCase):
    def test_assign_patches_assigned_to(self):
        api, fake = client(FakeResponse(200, {"fields": {
            "System.AssignedTo": {"displayName": "Lee", "id": "guid-lee"}}}))
        got = api.assign("59644", "guid-lee")
        self.assertTrue(got["ok"])
        self.assertEqual(fake.calls[0]["url"], PATCH_URL)
        self.assertEqual(fake.calls[0]["headers"]["Content-Type"],
                         "application/json-patch+json")
        self.assertEqual(fake.calls[0]["body"][0]["path"], "/fields/System.AssignedTo")
        self.assertEqual(fake.calls[0]["body"][0]["value"], "guid-lee")
        # The name is the value a report can print. The id is what the compare uses.
        self.assertEqual(got["stored"], "Lee")
        fake.assert_drained()

    def test_an_assignee_the_server_never_took_is_not_ok(self):
        api, fake = client(FakeResponse(200, {"fields": {
            "System.AssignedTo": {"displayName": "Ana", "id": "guid-ana"}}}))
        got = api.assign("59644", "guid-lee")
        self.assertFalse(got["ok"])
        self.assertEqual(got["stored"], "Ana")
        fake.assert_drained()

    def test_an_email_identity_matches_the_unique_name(self):
        # A person can arrive as a GUID or as a mail address. Both name one
        # person, so both count as proof.
        api, fake = client(FakeResponse(200, {"fields": {
            "System.AssignedTo": {"displayName": "Lee",
                                  "uniqueName": "lee@example.com"}}}))
        got = api.assign("59644", "lee@example.com")
        self.assertTrue(got["ok"])
        self.assertEqual(got["stored"], "Lee")
        fake.assert_drained()

    def test_a_display_name_alone_is_not_proof(self):
        # Two people can share a display name. The server resolved a different
        # Lee here, and a name match would call that write a success.
        api, fake = client(FakeResponse(200, {"fields": {
            "System.AssignedTo": {"displayName": "Lee", "id": "guid-other-lee",
                                  "uniqueName": "lee.other@example.com"}}}))
        got = api.assign("59644", "Lee")
        self.assertFalse(got["ok"])
        self.assertEqual(got["stored"], "Lee")
        fake.assert_drained()

    def test_the_identity_compare_ignores_the_case(self):
        # A mail address is not case sensitive. A case difference here is not a
        # failed write, and reporting one sends the agent back to write again.
        api, fake = client(FakeResponse(200, {"fields": {
            "System.AssignedTo": {"displayName": "Lee",
                                  "uniqueName": "lee@example.com"}}}))
        got = api.assign("59644", "Lee@Example.com")
        self.assertTrue(got["ok"])
        fake.assert_drained()

    def test_an_empty_assigned_to_field_is_not_ok(self):
        api, fake = client(FakeResponse(200, {"fields": {}}))
        got = api.assign("59644", "guid-lee")
        self.assertFalse(got["ok"])
        self.assertIsNone(got["stored"])
        fake.assert_drained()

    def test_an_empty_identity_is_not_ok(self):
        # An empty name and an empty field must not compare equal.
        api, fake = client(FakeResponse(200, {"fields": {}}))
        got = api.assign("59644", "")
        self.assertFalse(got["ok"])
        fake.assert_drained()


class TestAzureIdentity(unittest.TestCase):
    def test_identity_resolves_through_work_items(self):
        wiql = {"workItems": [{"id": 3}]}
        hydrated = {"value": [{"id": 3, "fields": {"System.AssignedTo": {
            "id": "guid-ana", "displayName": "Ana Fletcher",
            "uniqueName": "ana@example.com"}}}]}
        api, fake = client(FakeResponse(200, wiql), FakeResponse(200, hydrated))
        got = api.identity("Ana Fletcher")
        self.assertEqual(got, {"id": "guid-ana", "name": "Ana Fletcher",
                               "unique": "ana@example.com"})
        self.assertIn("CONTAINS 'Ana Fletcher'", fake.calls[0]["body"]["query"])
        self.assertEqual(fake.calls[0]["method"], "POST")
        self.assertEqual(fake.calls[0]["url"], WIQL_URL)
        self.assertEqual(fake.calls[1]["url"], BATCH_URL)
        fake.assert_drained()

    def test_identity_not_found_returns_none(self):
        api, fake = client(FakeResponse(200, {"workItems": []}))
        self.assertIsNone(api.identity("Nobody"))
        self.assertEqual(len(fake.calls), 1)
        fake.assert_drained()

    def test_two_people_behind_one_name_read_apart_from_nobody(self):
        # A name that reaches two people cannot be assigned. Picking the first
        # one assigns the wrong person, and nobody sees it. The caller prints a
        # different sentence for this than for a name that reaches nobody, so
        # the two answers must not look the same.
        wiql = {"workItems": [{"id": 3}, {"id": 4}]}
        hydrated = {"value": [
            {"id": 3, "fields": {"System.AssignedTo": {
                "id": "guid-ana", "displayName": "Ana Fletcher"}}},
            {"id": 4, "fields": {"System.AssignedTo": {
                "id": "guid-ana-two", "displayName": "Ana Fletchers"}}}]}
        api, fake = client(FakeResponse(200, wiql), FakeResponse(200, hydrated))
        got = api.identity("Ana Fletcher")
        self.assertIsNotNone(got)
        self.assertIsNone(got.get("id"))
        self.assertEqual([person["id"] for person in got["ambiguous"]],
                         ["guid-ana", "guid-ana-two"])
        fake.assert_drained()

    def test_one_person_on_many_work_items_still_resolves(self):
        wiql = {"workItems": [{"id": 3}, {"id": 4}]}
        who = {"id": "guid-ana", "displayName": "Ana Fletcher",
               "uniqueName": "ana@example.com"}
        hydrated = {"value": [{"id": 3, "fields": {"System.AssignedTo": who}},
                              {"id": 4, "fields": {"System.AssignedTo": who}}]}
        api, fake = client(FakeResponse(200, wiql), FakeResponse(200, hydrated))
        self.assertEqual(api.identity("Ana Fletcher")["id"], "guid-ana")
        fake.assert_drained()

    def test_a_name_holding_a_quote_cannot_break_the_query(self):
        api, fake = client(FakeResponse(200, {"workItems": []}))
        self.assertIsNone(api.identity("O'Brien"))
        self.assertIn("CONTAINS 'O''Brien'", fake.calls[0]["body"]["query"])
        fake.assert_drained()

    def test_the_hydrate_call_reads_at_most_twenty_work_items(self):
        # The window must be wide enough to see a second person behind one
        # name. A short window hides the second one, and identity then answers
        # with confidence about the wrong person.
        wiql = {"workItems": [{"id": n} for n in range(1, 26)]}
        api, fake = client(FakeResponse(200, wiql), FakeResponse(200, {"value": []}))
        self.assertIsNone(api.identity("Nobody"))
        wanted = ",".join(str(n) for n in range(1, 21))
        self.assertIn(f"ids={wanted}&", fake.calls[1]["url"])
        fake.assert_drained()


class TestAzureSeams(unittest.TestCase):
    def test_mine_and_identity_run_through_one_wiql_seam(self):
        # One home for the WIQL route. A caller that builds its own url makes a
        # route change two edits, and FakeHttp fails here when one does.
        api, fake = client()
        seen = []

        def fake_wiql(query, limit=None):
            seen.append(query)
            return []

        api._wiql = fake_wiql
        self.assertEqual(api.mine(), [])
        self.assertIsNone(api.identity("Nobody"))
        self.assertEqual(len(seen), 2)
        self.assertEqual(fake.calls, [])

    def test_the_comment_write_and_the_comment_read_share_one_path(self):
        # comment posts to the route that _comments reads, so the route has one
        # home and a change to it is one edit.
        api, fake = client(FakeResponse(200, {"id": 5, "text": "x"}),
                           FakeResponse(200, {"comments": []}))
        api._comments_path = lambda ticket: f"seam/{ticket}/comments"
        api.comment("59644", "x")
        for call in fake.calls:
            self.assertIn("seam/59644/comments", call["url"])
        fake.assert_drained()


if __name__ == "__main__":
    unittest.main()
