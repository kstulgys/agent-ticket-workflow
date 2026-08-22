import contextlib
import io
import unittest

# This import must stay first. It puts scripts/ on sys.path, so every tk_lib
# import below depends on it. Move it after them and the whole suite fails to
# import.
import helpers

from tk_lib import cli


class TestCli(unittest.TestCase):
    def test_help_lists_every_verb_and_exits_zero(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["--help"])
        self.assertEqual(rc, 0)
        for verb in ("doctor", "resolve", "mine", "show", "comment", "state",
                     "assign", "pr", "figma", "git"):
            self.assertIn(verb, out.getvalue())

    def test_unknown_verb_exits_one_and_names_it(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = cli.main(["frobnicate"])
        self.assertEqual(rc, 1)
        self.assertIn("frobnicate", err.getvalue())

    def test_no_verb_exits_one(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main([]), 1)

    def test_a_verb_that_returns_no_code_exits_one(self):
        @cli.verb("silent")
        def _silent(rest):
            return None

        self.addCleanup(cli.VERBS.pop, "silent", None)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = cli.main(["silent"])
        self.assertEqual(rc, 1)
        self.assertIn("silent", err.getvalue())


class TestHarness(unittest.TestCase):
    def test_assert_drained_names_the_unused_response(self):
        http = helpers.FakeHttp([helpers.FakeResponse(body={"a": 1}),
                                 helpers.FakeResponse(body={"b": 2})])
        http.json("GET", "https://x/first")
        with self.assertRaises(AssertionError) as caught:
            http.assert_drained()
        message = str(caught.exception)
        self.assertIn("1", message)
        self.assertIn("GET https://x/first", message)
        http.json("GET", "https://x/second")
        self.assertIsNone(http.assert_drained())

    def test_a_str_body_stays_utf_8_text(self):
        response = helpers.FakeResponse(status=500, body="Internal Server Error")
        self.assertEqual(response.read(), b"Internal Server Error")
