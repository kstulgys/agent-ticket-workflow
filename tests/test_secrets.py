import os
import pathlib
import shutil
import tempfile
import unittest

import helpers  # noqa: F401

from tk_lib import secrets


def write(test, text, mode=0o600):
    """One secrets file in a directory that goes away with the test."""
    root = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, root, True)
    path = pathlib.Path(root, "secrets.env")
    path.write_text(text, encoding="utf-8")
    os.chmod(path, mode)
    return str(path)


class TestSecrets(unittest.TestCase):
    def setUp(self):
        secrets.SCRUB.clear()

    def test_parses_keys_and_ignores_comments_and_blanks(self):
        path = write(self, '# a comment\n\nAZDO_PAT=abcdefgh12345678\nJIRA_EMAIL="me@x.com"\n')
        values = secrets.load(path)
        self.assertEqual(values["AZDO_PAT"], "abcdefgh12345678")
        self.assertEqual(values["JIRA_EMAIL"], "me@x.com")

    def test_keeps_an_equals_sign_inside_the_value(self):
        self.assertEqual(secrets.load(write(self, "GH_TOKEN=aa=bb=cc\n"))["GH_TOKEN"],
                         "aa=bb=cc")

    def test_strips_one_quote_pair_and_no_more(self):
        values = secrets.load(write(self, 'A=""abc""\nB=\'abcdefgh12345678\'\n'))
        self.assertEqual(values["A"], '"abc"')
        self.assertEqual(values["B"], "abcdefgh12345678")

    def test_refuses_a_mode_other_than_600(self):
        with self.assertRaises(secrets.SecretsError) as cm:
            secrets.load(write(self, "GH_TOKEN=abcdefgh12345678\n", mode=0o644))
        self.assertIn("chmod 600", str(cm.exception))

    def test_missing_file_names_the_setup_script(self):
        with self.assertRaises(secrets.SecretsError) as cm:
            secrets.load("/nonexistent/secrets.env")
        self.assertIn("setup.sh", str(cm.exception))

    def test_get_returns_the_value_for_a_present_name(self):
        self.assertEqual(secrets.get("GH_TOKEN", {"GH_TOKEN": "abcdefgh12345678"}),
                         "abcdefgh12345678")

    def test_get_names_the_missing_variable_and_the_setup_script(self):
        with self.assertRaises(secrets.SecretsError) as cm:
            secrets.get("GH_TOKEN", {})
        self.assertIn("GH_TOKEN", str(cm.exception))
        self.assertIn("setup.sh", str(cm.exception))

    def test_scrub_replaces_every_loaded_value(self):
        secrets.load(write(self, "GH_TOKEN=abcdefgh12345678\n"))
        self.assertEqual(secrets.scrub("token abcdefgh12345678 leaked"), "token *** leaked")

    def test_scrub_ignores_a_short_value_that_would_match_everything(self):
        secrets.load(write(self, "SHORT=ab\n"))
        self.assertEqual(secrets.scrub("abcabc"), "abcabc")

    def test_scrub_masks_a_longer_value_that_contains_a_shorter_one(self):
        secrets.load(write(self, "A=abcdefgh\nB=xxabcdefghyy\n"))
        self.assertEqual(secrets.scrub("body xxabcdefghyy body"), "body *** body")
