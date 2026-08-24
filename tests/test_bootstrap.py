import argparse
import json
import pathlib
import re
import tempfile
import unittest

import helpers  # noqa: F401
from helpers import FakeHttp, FakeResponse

from tk_lib import bootstrap, cli, config, doctor

# A real Azure identity, mixed digits on purpose. doctor._placeholder refuses a
# guid whose characters are all one value after the hyphens go, and
# tests/test_doctor.py uses such a guid as a fixture. Copying that shape here
# would fail these cases for a reason that has nothing to do with init.
GUID = "9f2c41ab-7d05-4e63-8a19-2b6c0d5471ef"
PROJECT_GUID = "1a7b33c9-4e28-4f51-9d6a-8c0e2f45b731"

FULL_GIT = {"rev-parse --show-toplevel": "/repos/site",
            "remote get-url origin": "https://github.com/acme/site.git",
            "symbolic-ref --short refs/remotes/origin/HEAD": "origin/main",
            "config user.name": "Ada",
            "config user.email": "ada@example.com"}


def runner_for(answers):
    """A git runner that answers by subcommand. None means git failed."""
    def run(args):
        return answers.get(" ".join(args))

    return run


def detected_for(answers=None):
    return bootstrap.detect(runner=runner_for(FULL_GIT if answers is None
                                              else answers))


def init_args(**kwargs):
    """The namespace tk init hands to bootstrap.init."""
    fields = {"slug": "site", "tracker": "github", "ticket": None, "org": None,
              "project": None, "site": None, "owner": None, "repo": None,
              "path": None}
    fields.update(kwargs)
    return argparse.Namespace(**fields)


# init builds a real adapter through cli.adapter_for, so the token has to be
# present and the http client is the seam. A stub adapter would skip the
# constructor guards that judge the profile build wrote.
TOKENS = {"AZDO_PAT": "azure-token-1234", "GH_TOKEN": "ghp_tokentokentoken",
          "JIRA_EMAIL": "ada@example.com", "JIRA_TOKEN": "jira-token-1234"}


def azure_repo_response(repo_id=None, project_id=None):
    """The repository route answer, the one call repo_ids makes."""
    return FakeResponse(200, {"id": repo_id or GUID,
                              "project": {"id": project_id or PROJECT_GUID}})


class TestParseRemote(unittest.TestCase):
    def test_reads_a_github_https_remote_with_or_without_the_git_suffix(self):
        for url in ("https://github.com/acme/site.git",
                    "https://github.com/acme/site"):
            with self.subTest(url=url):
                got = bootstrap.parse_remote(url)
                self.assertEqual((got["provider"], got["owner"], got["repo"]),
                                 ("github", "acme", "site"))

    def test_reads_a_github_ssh_remote(self):
        got = bootstrap.parse_remote("git@github.com:acme/site.git")
        self.assertEqual((got["provider"], got["owner"], got["repo"]),
                         ("github", "acme", "site"))

    def test_reads_an_azure_https_remote(self):
        got = bootstrap.parse_remote(
            "https://dev.azure.com/northwind/Proj/_git/Repo")
        self.assertEqual(got, {"provider": "azure", "owner": None,
                               "repo": "Repo",
                               "org": "https://dev.azure.com/northwind",
                               "project": "Proj"})

    def test_unquotes_a_percent_escaped_azure_project(self):
        # Azure.__init__ quotes the project again. A value that arrives
        # escaped and gets quoted twice reads as a project that does not exist.
        got = bootstrap.parse_remote(
            "https://dev.azure.com/northwind/Contoso%20migration"
            "/_git/Contoso.migration")
        self.assertEqual(got["project"], "Contoso migration")
        self.assertEqual(got["repo"], "Contoso.migration")

    def test_drops_a_userinfo_part_before_reading_the_host(self):
        got = bootstrap.parse_remote(
            "https://northwind@dev.azure.com/northwind/Proj/_git/Repo")
        self.assertEqual(got["org"], "https://dev.azure.com/northwind")
        self.assertEqual(got["project"], "Proj")

    def test_reads_an_azure_ssh_v3_remote(self):
        got = bootstrap.parse_remote("git@ssh.dev.azure.com:v3/northwind/Proj/Repo")
        self.assertEqual(got, {"provider": "azure", "owner": None,
                               "repo": "Repo",
                               "org": "https://dev.azure.com/northwind",
                               "project": "Proj"})

    def test_reads_a_legacy_visualstudio_remote(self):
        got = bootstrap.parse_remote(
            "https://northwind.visualstudio.com/Proj/_git/Repo")
        self.assertEqual(got["org"], "https://northwind.visualstudio.com")
        self.assertEqual((got["project"], got["repo"]), ("Proj", "Repo"))

    def test_an_unknown_host_answers_a_null_provider_and_nothing_else(self):
        # A GitLab remote is not a failure. It means the host block cannot be
        # filled, and the caller says so.
        self.assertEqual(bootstrap.parse_remote("git@gitlab.com:acme/site.git"),
                         {"provider": None, "owner": None, "repo": None,
                          "org": None, "project": None})


class TestDetect(unittest.TestCase):
    def test_a_full_answer_set_fills_every_field(self):
        got = detected_for()
        self.assertEqual(got["root"], "/repos/site")
        self.assertEqual(got["provider"], "github")
        self.assertEqual(got["owner"], "acme")
        self.assertEqual(got["repo"], "site")
        self.assertEqual(got["base_branch"], "main")
        self.assertEqual(got["identity"],
                         {"name": "Ada", "email": "ada@example.com"})

    def test_no_origin_leaves_the_provider_null_and_keeps_the_identity(self):
        answers = dict(FULL_GIT)
        del answers["remote get-url origin"]
        got = detected_for(answers)
        self.assertIsNone(got["remote"])
        self.assertIsNone(got["provider"])
        self.assertEqual(got["identity"]["name"], "Ada")

    def test_a_missing_symbolic_ref_leaves_the_base_branch_null(self):
        answers = dict(FULL_GIT)
        del answers["symbolic-ref --short refs/remotes/origin/HEAD"]
        self.assertIsNone(detected_for(answers)["base_branch"])

    def test_strips_the_remote_name_from_the_head_ref(self):
        self.assertEqual(detected_for()["base_branch"], "main")

    def test_a_directory_outside_a_repository_answers_nulls_and_does_not_raise(self):
        got = detected_for({})
        self.assertIsNone(got["provider"])
        self.assertIsNone(got["remote"])
        self.assertIsNone(got["base_branch"])
        self.assertEqual(got["identity"], {"name": None, "email": None})
        # root falls back to the working directory, because a profile needs one
        # path to match on even before the directory is a clone.
        self.assertTrue(got["root"])


class TestBuild(unittest.TestCase):
    def test_a_numeric_ticket_keeps_its_digit_count(self):
        got = bootstrap.build("site", "github", detected_for(), ticket="5438",
                              owner="acme", repo="site")
        pattern = got["match"]["ticket_patterns"][0]
        self.assertEqual(pattern, "^[0-9]{4,}$")
        self.assertTrue(re.match(pattern, "5438"))
        # A bare ^[0-9]+$ would claim a three digit id from another tracker.
        self.assertIsNone(re.match(pattern, "543"))

    def test_a_key_ticket_becomes_a_key_pattern(self):
        got = bootstrap.build("site", "jira", detected_for(), ticket="DIST-4471",
                              site="acme.atlassian.net", project="DIST")
        self.assertEqual(got["match"]["ticket_patterns"], ["^DIST-[0-9]+$"])

    def test_no_ticket_gives_an_empty_pattern_list(self):
        got = bootstrap.build("site", "github", detected_for(), owner="acme",
                              repo="site")
        self.assertEqual(got["match"]["ticket_patterns"], [])

    def test_all_four_buckets_exist_with_a_null_state(self):
        got = bootstrap.build("site", "github", detected_for(), owner="acme",
                              repo="site")
        self.assertEqual(sorted(got["buckets"]),
                         ["fixable-here", "needs-clarification",
                          "owned-elsewhere", "split"])
        for name, bucket in got["buckets"].items():
            with self.subTest(bucket=name):
                self.assertIsNone(bucket["state"])

    def test_an_azure_tracker_carries_a_preview_api_version(self):
        got = bootstrap.build("nw", "azure", detected_for({}),
                              org="https://dev.azure.com/northwind",
                              project="Proj")
        self.assertTrue(got["tracker"]["api_version"].startswith("7.1-preview"))
        got["people"]["self"] = {"id": GUID}
        # The constructor guard is the judge of the tracker block, not a
        # hand-written expectation.
        cli.adapter_for(got, {"AZDO_PAT": "x" * 12})

    def test_only_an_azure_tracker_gets_both_link_lists(self):
        azure = bootstrap.build("nw", "azure", detected_for({}),
                                org="https://dev.azure.com/northwind",
                                project="Proj")
        self.assertEqual(sorted(azure["link_rules"]),
                         ["link_types", "never_link_types"])
        github = bootstrap.build("site", "github", detected_for(),
                                 owner="acme", repo="site")
        self.assertNotIn("link_rules", github)

    def test_a_jira_tracker_beside_an_azure_remote_gets_no_host_block(self):
        # gitcmd._base_url reads tracker.org for an azure-repos host, and a
        # Jira tracker holds none, so such a profile could never push.
        answers = dict(FULL_GIT)
        answers["remote get-url origin"] = \
            "https://dev.azure.com/northwind/Proj/_git/Repo"
        got = bootstrap.build("mix", "jira", detected_for(answers),
                              site="acme.atlassian.net", project="DIST")
        self.assertNotIn("host", got)

    def test_a_github_remote_beside_a_jira_tracker_gets_a_github_host(self):
        got = bootstrap.build("globex", "jira", detected_for(),
                              site="acme.atlassian.net", project="DIST")
        self.assertEqual(got["host"]["kind"], "github")
        self.assertEqual(got["host"]["owner"], "acme")
        self.assertEqual(got["host"]["base_branch"], "main")

    def test_a_missing_required_field_names_the_flag(self):
        with self.assertRaises(ValueError) as cm:
            bootstrap.build("nw", "azure", detected_for({}))
        self.assertIn("--org", str(cm.exception))
        self.assertIn("--project", str(cm.exception))


class TestWrite(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.detected = detected_for()
        self.profile = bootstrap.build("site", "github", self.detected,
                                       ticket="5438", owner="acme", repo="site")
        self.profile["people"]["self"] = {"login": "ada"}

    def _write(self):
        return bootstrap.write(self.profile,
                               bootstrap.notes_stub(self.profile, self.detected),
                               self.root)

    def test_the_written_profile_loads_back_under_its_slug(self):
        self._write()
        profiles = config.load_all(self.root)
        self.assertIn("site", profiles)
        self.assertEqual(profiles["site"]["tracker"]["kind"], "github")

    def test_resolve_matches_the_written_ticket_pattern(self):
        self._write()
        got = config.resolve("5438", config.load_all(self.root))
        self.assertEqual(got["slug"], "site")

    def test_resolve_matches_the_written_repo_path(self):
        self._write()
        got = config.resolve(None, config.load_all(self.root), cwd="/repos/site")
        self.assertEqual(got["slug"], "site")

    def test_a_second_write_refuses_and_changes_no_byte(self):
        written = self._write()
        before = pathlib.Path(written["config_path"]).read_bytes()
        with self.assertRaises(ValueError) as cm:
            self._write()
        self.assertIn("already exists", str(cm.exception))
        self.assertEqual(pathlib.Path(written["config_path"]).read_bytes(),
                         before)


class TestInit(unittest.TestCase):
    AZURE_GIT = dict(FULL_GIT,
                     **{"remote get-url origin":
                        "https://dev.azure.com/northwind/Proj/_git/Repo"})

    def setUp(self):
        self.root = tempfile.mkdtemp()

    def _init(self, responses, root=None, git=None, **kwargs):
        fake = FakeHttp(responses)
        got = bootstrap.init(init_args(**kwargs), TOKENS, client=fake,
                             root=root or self.root,
                             runner=runner_for(git or FULL_GIT))
        fake.assert_drained()
        return got, fake

    def test_a_failed_whoami_writes_nothing(self):
        # The ordering guarantee the retry story rests on. A profile written
        # before the call would leave a broken profile that doctor reports for
        # ever, and the retry would need a different command.
        def raiser():
            raise RuntimeError("401 from the provider")

        with self.assertRaises(RuntimeError):
            self._init([raiser], owner="acme", repo="site")
        self.assertFalse(pathlib.Path(self.root, "projects", "site").exists())

    def test_an_azure_host_gets_both_guids_from_one_call(self):
        got, fake = self._init(
            [FakeResponse(200, {"authenticatedUser": {"id": GUID,
                                                      "providerDisplayName": "Ada"}}),
             azure_repo_response()],
            git=self.AZURE_GIT, slug="nw", tracker="azure",
            org="https://dev.azure.com/northwind", project="Proj")
        self.assertEqual(got["host"], "azure-repos")
        written = json.loads(pathlib.Path(got["config_path"]).read_text())
        self.assertEqual(written["host"]["repo_id"], GUID)
        self.assertEqual(written["host"]["project_id"], PROJECT_GUID)
        # One call for the identity, one for the repository, and no more.
        self.assertEqual(len(fake.calls), 2)

    def test_people_self_uses_the_key_each_provider_answers_with(self):
        cases = (
            ("github", "login", [FakeResponse(200, {"login": "ada"})],
             {"owner": "acme", "repo": "site"}),
            ("jira", "accountId", [FakeResponse(200, {"accountId": "5f2c19"})],
             {"site": "acme.atlassian.net", "project": "DIST"}),
            ("azure", "id",
             [FakeResponse(200, {"authenticatedUser": {"id": GUID}})],
             {"org": "https://dev.azure.com/northwind", "project": "Proj"}))
        for tracker, key, responses, extra in cases:
            with self.subTest(tracker=tracker):
                got, _ = self._init(responses, root=tempfile.mkdtemp(),
                                    slug="p", tracker=tracker, **extra)
                written = json.loads(pathlib.Path(got["config_path"]).read_text())
                self.assertEqual(sorted(written["people"]["self"]), [key])

    def test_the_written_azure_profile_has_no_profile_gaps(self):
        # _profile_gaps checks three things only: every people role resolves to
        # a usable non-placeholder id, every bucket assignee names a role the
        # people block holds, and an azure-repos host holds both guids. It
        # reads no slug, no match, no tracker, and no bucket state, and
        # _profile_gaps({}) returns [] as well. So this proves the three
        # cross-block links, and nothing about the rest of the file.
        got, _ = self._init(
            [FakeResponse(200, {"authenticatedUser": {"id": GUID}}),
             azure_repo_response()],
            git=self.AZURE_GIT, slug="nw", tracker="azure",
            org="https://dev.azure.com/northwind", project="Proj")
        written = json.loads(pathlib.Path(got["config_path"]).read_text())
        self.assertEqual(doctor._profile_gaps(written), [])

    def test_an_adapter_builds_from_the_written_profile(self):
        # The assertion the gap check cannot make. This runs the api_version
        # guard and the org and project checks in Azure.__init__, so a tracker
        # block that build filled wrongly fails here.
        got, _ = self._init(
            [FakeResponse(200, {"authenticatedUser": {"id": GUID}})],
            slug="nw", tracker="azure",
            org="https://dev.azure.com/northwind", project="Proj")
        written = json.loads(pathlib.Path(got["config_path"]).read_text())
        adapter = cli.adapter_for(written, TOKENS)
        self.assertEqual(type(adapter).__name__, "Azure")

    def test_a_placeholder_account_id_is_refused_and_writes_nothing(self):
        # _placeholder refuses an id whose characters are all one value after
        # the hyphens go. An example profile ships such a guid, so a token that
        # answers one must not reach a written profile.
        with self.assertRaises(ValueError) as cm:
            self._init([FakeResponse(200, {"login": "3" * 12})],
                       owner="acme", repo="site")
        self.assertIn("no usable account id", str(cm.exception))
        self.assertFalse(pathlib.Path(self.root, "projects", "site").exists())


if __name__ == "__main__":
    unittest.main()
