import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

# This import must stay first. It puts scripts/ on sys.path, so the tk_lib
# import below depends on it. Move it after that line and the suite fails to
# import.
from helpers import tmp_profile

from tk_lib import cli, config

NORTHWIND = {"slug": "northwind", "tracker": {"kind": "azure"},
         "match": {"ticket_patterns": ["^[0-9]{5}$"],
                   "tracker_urls": ["dev.azure.com/northwind"],
                   "repo_paths": ["/repos/Contoso-migration"]}}
MMAI = {"slug": "mmai", "tracker": {"kind": "azure"},
        "match": {"ticket_patterns": ["^[0-9]{5}$"],
                  "tracker_urls": ["dev.azure.com/infrastructurebidfood"],
                  "repo_paths": ["/repos/MatchMakerAI"]}}
GLOBEX = {"slug": "globex", "tracker": {"kind": "jira"},
        "match": {"ticket_patterns": ["^DIST-[0-9]+$"],
                  "tracker_urls": ["globex.atlassian.net"],
                  "repo_paths": ["/repos/Globex.Dist.WebPlatform"]}}


_ROOTS = []


def root_with(*configs):
    """One temp root holding every config as a project. Removed at module exit."""
    root = tempfile.mkdtemp()
    _ROOTS.append(root)
    for config_dict in configs:
        tmp_profile(config_dict, root=root)
    return root


def tearDownModule():
    for root in _ROOTS:
        shutil.rmtree(root, ignore_errors=True)


class TestLoadAll(unittest.TestCase):
    def test_loads_every_project_directory(self):
        self.assertEqual(sorted(config.load_all(root_with(NORTHWIND, GLOBEX))),
                         ["globex", "northwind"])

    def test_a_missing_projects_directory_is_empty_not_an_error(self):
        self.assertEqual(config.load_all("/nonexistent"), {})


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.profiles = config.load_all(root_with(NORTHWIND, MMAI, GLOBEX))

    def test_a_jira_key_resolves_by_pattern(self):
        got = config.resolve("DIST-1235", self.profiles, cwd="/tmp")
        self.assertEqual((got["slug"], got["ticket"]), ("globex", "DIST-1235"))

    def test_an_azure_url_yields_the_work_item_id(self):
        url = "https://dev.azure.com/northwind/Contoso%20migration/_workitems/edit/59644"
        got = config.resolve(url, self.profiles, cwd="/tmp")
        self.assertEqual((got["slug"], got["ticket"]), ("northwind", "59644"))

    def test_a_jira_browse_url_yields_the_key(self):
        got = config.resolve("https://globex.atlassian.net/browse/DIST-42",
                             self.profiles, cwd="/tmp")
        self.assertEqual((got["slug"], got["ticket"]), ("globex", "DIST-42"))

    def test_a_github_issue_url_yields_the_number(self):
        profiles = config.load_all(root_with(
            {"slug": "gh", "tracker": {"kind": "github"},
             "match": {"ticket_patterns": ["^[0-9]{1,4}$"],
                       "tracker_urls": ["github.com/me/repo"], "repo_paths": []}}))
        got = config.resolve("https://github.com/me/repo/issues/12", profiles, cwd="/tmp")
        self.assertEqual((got["slug"], got["ticket"]), ("gh", "12"))

    def test_two_azure_projects_on_a_bare_number_is_ambiguous(self):
        with self.assertRaises(config.Ambiguous) as cm:
            config.resolve("59644", self.profiles, cwd="/tmp")
        self.assertEqual(cm.exception.slugs, ["mmai", "northwind"])

    def test_cwd_breaks_the_tie(self):
        got = config.resolve("59644", self.profiles, cwd="/repos/Contoso-migration/src")
        self.assertEqual(got["slug"], "northwind")

    def test_no_argument_uses_cwd(self):
        got = config.resolve(None, self.profiles, cwd="/repos/Globex.Dist.WebPlatform")
        self.assertEqual(got["slug"], "globex")
        self.assertIsNone(got["ticket"])

    def test_nothing_matches_raises_unresolved(self):
        with self.assertRaises(config.Unresolved):
            config.resolve("WAT-1", self.profiles, cwd="/tmp")

    def test_notes_path_points_at_the_profile_directory(self):
        got = config.resolve("DIST-1", self.profiles, cwd="/tmp")
        self.assertTrue(got["notes_path"].endswith(os.path.join("globex", "notes.md")))
        self.assertTrue(os.path.exists(got["notes_path"]))

    def test_a_repo_path_matches_only_on_a_full_directory_name(self):
        with self.assertRaises(config.Ambiguous):
            config.resolve("59644", self.profiles, cwd="/repos/Contoso-migration-old")

    def test_two_profiles_on_one_url_refuses_to_guess(self):
        wide = {"slug": "wide", "tracker": {"kind": "azure"},
                "match": {"ticket_patterns": [], "tracker_urls": ["dev.azure.com"],
                          "repo_paths": []}}
        profiles = config.load_all(root_with(NORTHWIND, wide))
        with self.assertRaises(config.Ambiguous) as cm:
            config.resolve("https://dev.azure.com/northwind/p/_workitems/edit/1",
                           profiles, cwd="/tmp")
        self.assertEqual(cm.exception.slugs, ["northwind", "wide"])

    def test_two_repo_paths_in_one_profile_are_not_a_tie(self):
        dup = {"slug": "dup", "tracker": {"kind": "azure"},
               "match": {"ticket_patterns": ["^[0-9]{5}$"], "tracker_urls": [],
                         "repo_paths": ["/repos/dup", "/repos/dup/site"]}}
        profiles = config.load_all(root_with(dup, NORTHWIND))
        self.assertEqual(
            config.resolve(None, profiles, cwd="/repos/dup/site")["slug"], "dup")
        self.assertEqual(
            config.resolve("59644", profiles, cwd="/repos/dup/site")["slug"], "dup")


class TestBrokenProfile(unittest.TestCase):
    def test_broken_json_names_the_file(self):
        root = root_with(NORTHWIND)
        path = os.path.join(root, "projects", "northwind", "config.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{oops")
        with self.assertRaises(ValueError) as cm:
            config.load_all(root)
        self.assertIn(path, str(cm.exception))
        self.assertIsInstance(cm.exception, config.BadProfile)

    def test_a_directory_without_a_config_is_skipped_and_named_on_stderr(self):
        root = root_with(GLOBEX)
        scratch = os.path.join(root, "projects", "scratch")
        os.mkdir(scratch)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            profiles = config.load_all(root)
        self.assertEqual(sorted(profiles), ["globex"])
        self.assertIn(scratch, err.getvalue())

    def test_a_stray_file_beside_the_profiles_is_silent(self):
        # A directory with no config.json is a broken profile, and the warning
        # is for the reader. A file there is not a profile at all, and every
        # verb loads these profiles, so one stray file would warn for ever.
        root = root_with(GLOBEX)
        with open(os.path.join(root, "projects", ".DS_Store"), "w",
                  encoding="utf-8") as fh:
            fh.write("x")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            profiles = config.load_all(root)
        self.assertEqual(sorted(profiles), ["globex"])
        self.assertEqual(err.getvalue(), "")

    def _overwrite(self, root, slug, text):
        """Writes raw text as one profile's config.json. A dict cannot do this."""
        path = os.path.join(root, "projects", slug, "config.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_valid_json_that_is_not_an_object_names_the_file(self):
        # json.load succeeds, the guard above passes, and the next line used to
        # raise TypeError, which the error table does not hold. One hand edited
        # file then took down every verb with a traceback and no JSON.
        for text in ("[]", '"azure"', "42"):
            with self.subTest(text=text):
                root = root_with(NORTHWIND)
                path = self._overwrite(root, "northwind", text)
                with self.assertRaises(config.BadProfile) as cm:
                    config.load_all(root)
                self.assertIn(path, str(cm.exception))

    def test_a_block_that_is_not_an_object_names_the_block(self):
        # doctor reads tracker.kind outside its own row guard, so a string here
        # took down the whole report with AttributeError instead of one row.
        root = root_with(NORTHWIND)
        self._overwrite(root, "northwind",
                        json.dumps({"slug": "northwind", "tracker": "azure"}))
        with self.assertRaises(config.BadProfile) as cm:
            config.load_all(root)
        self.assertIn("tracker", str(cm.exception))

    def test_a_well_formed_profile_still_loads_and_carries_its_directory(self):
        root = root_with(NORTHWIND)
        loaded = config.load_all(root)["northwind"]
        self.assertEqual(loaded["_dir"],
                         os.path.join(root, "projects", "northwind"))


class TestResolveVerb(unittest.TestCase):
    """The verb owns the exit codes, so the codes need their own tests."""

    def _run(self, argv, root):
        original = config.ROOT
        config.ROOT = root
        self.addCleanup(setattr, config, "ROOT", original)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(argv)
        return code, json.loads(out.getvalue())

    def test_an_ambiguous_id_exits_two_and_lists_the_slugs(self):
        code, payload = self._run(["resolve", "59644"], root_with(NORTHWIND, MMAI))
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"], "ambiguous")
        self.assertEqual(payload["slugs"], ["mmai", "northwind"])
        self.assertIn("northwind", payload["message"])

    def test_an_unmatched_id_exits_one_with_a_fixed_code_and_a_message(self):
        code, payload = self._run(["resolve", "WAT-1"], root_with(NORTHWIND))
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "unresolved")
        self.assertIn("WAT-1", payload["message"])

    def test_a_resolved_id_exits_zero_with_the_slug(self):
        code, payload = self._run(["resolve", "DIST-7"], root_with(GLOBEX))
        self.assertEqual(code, 0)
        self.assertEqual((payload["slug"], payload["ticket"]), ("globex", "DIST-7"))

    def test_a_malformed_profile_prints_the_profile_code_not_a_traceback(self):
        # The routine switches on the code, and README and SKILL.md both promise
        # one. A profile that is valid JSON but not an object used to print a
        # traceback on stderr and nothing at all on stdout.
        root = root_with(NORTHWIND)
        with open(os.path.join(root, "projects", "northwind", "config.json"),
                  "w", encoding="utf-8") as fh:
            fh.write("[]")
        code, payload = self._run(["resolve", "59644"], root)
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "profile")
        self.assertIn("config.json", payload["message"])
