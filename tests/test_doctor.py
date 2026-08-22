import json
import unittest

import helpers  # noqa: F401

from tk_lib import doctor, secrets


class FakeAdapter:
    """Every adapter answers whoami and repo_check, so this fake does too.

    doctor calls repo_check with no test for the name. A fake without the
    method would model an adapter the table cannot hold.
    """

    def __init__(self, who=None, repo=None, error=None):
        self._who, self._repo, self._error = who, repo, error

    def whoami(self):
        if self._error:
            raise RuntimeError(self._error)
        return self._who

    def repo_check(self):
        return self._repo or {"ok": True}


class TestDoctor(unittest.TestCase):
    def test_reports_ok_when_every_provider_answers(self):
        got = doctor.check({"northwind": {"slug": "northwind", "tracker": {"kind": "azure"}}},
                           {"northwind": FakeAdapter(who={"provider": "azure",
                                                      "name": "Example"})})
        self.assertTrue(got["ok"])
        self.assertEqual(got["projects"][0]["name"], "Example")
        self.assertEqual(got["fix"], [])

    def test_a_failing_provider_names_the_setup_command(self):
        got = doctor.check({"globex": {"slug": "globex", "tracker": {"kind": "jira"}}},
                           {"globex": FakeAdapter(error="401 unauthorized")})
        self.assertFalse(got["ok"])
        self.assertIn("setup.sh jira", " ".join(got["fix"]))

    def test_a_repo_check_failure_is_reported_separately(self):
        got = doctor.check(
            {"globex": {"slug": "globex", "tracker": {"kind": "github"}}},
            {"globex": FakeAdapter(who={"provider": "github", "name": "k"},
                                 repo={"ok": False, "error": "SAML SSO"})})
        self.assertFalse(got["ok"])
        self.assertIn("SAML", got["projects"][0]["repo_error"])
        self.assertIn("authorize", " ".join(got["fix"]).lower())
        # One next step per row. A GitHub token has no Work Items scope to set,
        # and a reader who follows that sentence mints the wrong credential.
        self.assertNotIn("Work Items", " ".join(got["fix"]))

    def test_the_project_fix_line_names_the_scope_a_work_item_read_needs(self):
        # The Azure project check reads a work item, so a PAT scoped to Code
        # alone fails here. A fix line that names only the project sends the
        # user back to mint the same token again.
        got = doctor.check(
            {"northwind": {"slug": "northwind", "tracker": {"kind": "azure"}}},
            {"northwind": FakeAdapter(who={"provider": "azure", "name": "k"},
                                  repo={"ok": False, "error": "TF401027"})})
        self.assertIn("Work Items", " ".join(got["fix"]))

    def test_no_profiles_is_not_ok_and_says_so(self):
        got = doctor.check({}, {})
        self.assertFalse(got["ok"])
        self.assertIn("no project profiles", " ".join(got["fix"]))

    def test_every_project_gets_its_own_scoped_call(self):
        # One project can pass while another fails, so the check runs per
        # project. A per provider check would report the first answer twice.
        adapters = {"a": FakeAdapter(who={"name": "k"}),
                    "b": FakeAdapter(who={"name": "k"},
                                     repo={"ok": False, "error": "no access"})}
        got = doctor.check({"a": {"tracker": {"kind": "azure"}},
                            "b": {"tracker": {"kind": "azure"}}}, adapters)
        self.assertFalse(got["ok"])
        self.assertEqual([row["ok"] for row in got["projects"]], [True, False])

    def test_one_failing_project_makes_its_provider_false(self):
        # Two projects can share a provider. A summary that reads true above a
        # failing project is worse than no doctor, because the verb exists to
        # answer whether a run will work before it touches a real ticket.
        adapters = {"a": FakeAdapter(who={"name": "k"}),
                    "b": FakeAdapter(who={"name": "k"},
                                     repo={"ok": False, "error": "no access"})}
        got = doctor.check({"a": {"tracker": {"kind": "azure"}},
                            "b": {"tracker": {"kind": "azure"}}}, adapters)
        self.assertFalse(got["providers"]["azure"])

    def test_a_provider_stays_true_when_every_project_on_it_passes(self):
        adapters = {"a": FakeAdapter(who={"name": "k"}),
                    "b": FakeAdapter(who={"name": "k"})}
        got = doctor.check({"a": {"tracker": {"kind": "azure"}},
                            "b": {"tracker": {"kind": "azure"}}}, adapters)
        self.assertTrue(got["providers"]["azure"])
        self.assertTrue(got["ok"])

    def test_a_profile_with_no_tracker_kind_still_prints(self):
        # This is the broken setup the verb exists to find. A None key beside a
        # string key has no sort order, so cli.emit would write a part of the
        # document and then raise where nothing catches it.
        got = doctor.check({"broken": {"slug": "broken"}},
                           {"broken": FakeAdapter(error="unknown tracker kind None")})
        self.assertFalse(got["ok"])
        self.assertIn("unknown", got["providers"])
        json.dumps(got, sort_keys=True)
        self.assertIn("broken", " ".join(got["fix"]))
        self.assertNotIn("setup.sh None", " ".join(got["fix"]))

    def test_a_project_read_that_raises_keeps_the_rows_before_it(self):
        # repo_check catches HttpError only, so a reset connection escapes it.
        # Losing the whole report loses the rows that already passed.
        class Exploding(FakeAdapter):
            def repo_check(self):
                raise OSError("connection reset by peer")

        got = doctor.check({"a": {"tracker": {"kind": "azure"}},
                            "b": {"tracker": {"kind": "azure"}}},
                           {"a": FakeAdapter(who={"name": "k"}),
                            "b": Exploding(who={"name": "k"})})
        self.assertEqual(len(got["projects"]), 2)
        self.assertTrue(got["projects"][0]["ok"])
        self.assertFalse(got["projects"][1]["ok"])
        self.assertIn("reset", got["projects"][1]["repo_error"])

    def test_a_host_adapter_gets_a_row_of_its_own(self):
        # A profile whose host is a second provider carries a second token, and
        # the tracker row proves nothing about it.
        profiles = {"globex": {"slug": "globex", "tracker": {"kind": "jira"},
                             "host": {"kind": "github"}}}
        got = doctor.check(profiles, {"globex": FakeAdapter(who={"name": "k"})},
                           {"globex": FakeAdapter(who={"name": "k"})})
        self.assertTrue(got["ok"])
        self.assertEqual([(row["role"], row["provider"]) for row in got["projects"]],
                         [("tracker", "jira"), ("host", "github")])

    def test_a_dead_host_token_fails_the_report_and_names_its_setup(self):
        # A GitHub token that lost its single sign-on authorization used to
        # pass here and fail later, at tk pr create.
        profiles = {"globex": {"slug": "globex", "tracker": {"kind": "jira"},
                             "host": {"kind": "github"}}}
        got = doctor.check(profiles, {"globex": FakeAdapter(who={"name": "k"})},
                           {"globex": FakeAdapter(error="401 unauthorized")})
        self.assertFalse(got["ok"])
        self.assertTrue(got["providers"]["jira"])
        self.assertFalse(got["providers"]["github"])
        self.assertIn("setup.sh github", " ".join(got["fix"]))

    def test_a_host_kind_folds_to_its_provider_in_every_answer(self):
        # azure-repos is the host spelling of azure. setup.sh takes azure and
        # refuses azure-repos, so the raw kind here would hand the user the one
        # command this verb exists to name, and it would not run.
        profiles = {"x": {"slug": "x", "tracker": {"kind": "jira"},
                          "host": {"kind": "azure-repos"}}}
        got = doctor.check(profiles, {"x": FakeAdapter(who={"name": "k"})},
                           {"x": FakeAdapter(error="401 unauthorized")})
        self.assertEqual([row["provider"] for row in got["projects"]],
                         ["jira", "azure"])
        self.assertIn("azure", got["providers"])
        self.assertNotIn("azure-repos", got["providers"])
        self.assertIn(f"{doctor.SETUP} azure", got["fix"])

    def test_two_rows_of_one_provider_fold_into_one_answer(self):
        # The summary answers per provider. Two keys for one provider let a
        # true reading sit above a failing row of the same provider.
        profiles = {"x": {"slug": "x", "tracker": {"kind": "azure"},
                          "host": {"kind": "azure-repos"}}}
        got = doctor.check(profiles, {"x": FakeAdapter(who={"name": "k"})},
                           {"x": FakeAdapter(who={"name": "k"},
                                             repo={"ok": False,
                                                   "error": "no access"})})
        self.assertEqual(list(got["providers"]), ["azure"])
        self.assertFalse(got["providers"]["azure"])

    def test_both_error_strings_go_through_the_scrubber(self):
        # Every other path scrubs. No exception reachable here carries a token
        # today, so this is the second line of defence: an adapter, a socket
        # error, or a library can quote a header, and this report goes to
        # stdout.
        token = "patpatpatpat1234"
        secrets.SCRUB.append(token)
        self.addCleanup(secrets.SCRUB.remove, token)

        class Leaking(FakeAdapter):
            def repo_check(self):
                raise OSError(f"connection reset, sent Basic {token}")

        got = doctor.check(
            {"a": {"slug": "a", "tracker": {"kind": "azure"}},
             "b": {"slug": "b", "tracker": {"kind": "azure"}}},
            {"a": FakeAdapter(error=f"401 unauthorized for {token}"),
             "b": Leaking(who={"name": "k"})})
        printed = json.dumps(got, sort_keys=True)
        self.assertNotIn(token, printed)
        self.assertEqual(printed.count("***"), 2)


if __name__ == "__main__":
    unittest.main()
