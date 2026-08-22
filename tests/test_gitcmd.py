import base64
import binascii
import contextlib
import io
import os
import re
import tempfile
import unittest

import helpers  # noqa: F401  its import puts scripts/ on sys.path
from fixtures import AZ_PROFILE, AZ_VALUES

from tk_lib import gitcmd, secrets

# A Jira tracker beside a GitHub host is a real profile. The tracker names the
# Jira token, so a read in block order sends that token to GitHub.
MIXED = {"slug": "globex",
         "tracker": {"kind": "jira", "site": "https://globex.atlassian.net",
                     "project": "DIST",
                     "auth_env": {"email": "JIRA_EMAIL", "token": "JIRA_TOKEN"}},
         "host": {"kind": "github", "owner": "globex-dist", "repo": "Web",
                  "base_branch": "main", "local_path": "/repos/Web",
                  "auth_env": {"token": "GH_TOKEN"}}}
MIXED_VALUES = {"JIRA_EMAIL": "me@example.com", "JIRA_TOKEN": "jiratokentoken1",
                "GH_TOKEN": "ghp_tokentokentoken"}
# The same hosts with no auth_env, to read the default for the kind.
AZ_BARE = {"slug": "northwind", "tracker": AZ_PROFILE["tracker"],
           "host": {"kind": "azure-repos", "local_path": "/repos/x"}}
GH_BARE = {"slug": "globex", "tracker": MIXED["tracker"],
           "host": {"kind": "github", "local_path": "/repos/Web"}}


def pair(env):
    """The user and the token git would send, from the header value."""
    return base64.b64decode(env["GIT_CONFIG_VALUE_0"].split("Basic ", 1)[1]).decode()


def decoded_runs(line):
    """Every base64 run in a command line, decoded to text.

    A leak can encode the credential any way it likes, and each encoding is a
    different string. This reads the plaintext behind all of them, so the guard
    below tests the one thing that cannot change: the token itself.
    """
    out = []
    for run in re.findall(r"[A-Za-z0-9+/]{16,}={0,2}", line):
        padded = run + "=" * (-len(run) % 4)
        try:
            out.append(base64.b64decode(padded).decode("utf-8", "replace"))
        except (ValueError, binascii.Error):
            continue
    return out


class TestGitCmd(unittest.TestCase):
    def test_env_holds_the_header(self):
        env = gitcmd.env_for(AZ_PROFILE, AZ_VALUES)
        self.assertEqual(env["GIT_CONFIG_COUNT"], "1")
        self.assertTrue(env["GIT_CONFIG_VALUE_0"].startswith("AUTHORIZATION: Basic "))

    def test_the_header_decodes_to_the_user_and_the_token_in_that_order(self):
        # A prefix check passes for any pair, so it holds for a swapped pair and
        # for a token read from the wrong profile block. git would then send a
        # credential no server accepts. Decode the value and pin the pair.
        self.assertEqual(pair(gitcmd.env_for(AZ_PROFILE, AZ_VALUES)),
                         f"{AZ_VALUES['AZDO_USER']}:{AZ_VALUES['AZDO_PAT']}")

    def test_the_header_reads_the_host_block_not_the_tracker(self):
        raw = pair(gitcmd.env_for(MIXED, MIXED_VALUES))
        self.assertIn(MIXED_VALUES["GH_TOKEN"], raw)
        self.assertNotIn(MIXED_VALUES["JIRA_TOKEN"], raw)

    def test_the_key_scopes_the_header_to_the_azure_org(self):
        # A bare http.extraheader key sends the credential with every http
        # request in the command, so a submodule fetch during a clone hands our
        # token to the host that submodule lives on.
        self.assertEqual(gitcmd.env_for(AZ_PROFILE, AZ_VALUES)["GIT_CONFIG_KEY_0"],
                         "http.https://dev.azure.com/northwind.extraheader")

    def test_the_key_scopes_the_header_to_github_for_a_github_host(self):
        self.assertEqual(gitcmd.env_for(MIXED, MIXED_VALUES)["GIT_CONFIG_KEY_0"],
                         "http.https://github.com/.extraheader")

    def test_an_azure_host_with_no_org_raises_and_names_the_profile(self):
        profile = {"slug": "northwind", "tracker": {"kind": "jira"},
                   "host": {"kind": "azure-repos", "auth_env": {"token": "AZDO_PAT"}}}
        with self.assertRaises(ValueError) as caught:
            gitcmd.env_for(profile, AZ_VALUES)
        self.assertIn("northwind", str(caught.exception))

    def test_a_host_with_no_auth_env_takes_the_default_for_its_kind(self):
        self.assertEqual(pair(gitcmd.env_for(AZ_BARE, AZ_VALUES)),
                         f":{AZ_VALUES['AZDO_PAT']}")
        self.assertEqual(pair(gitcmd.env_for(GH_BARE, MIXED_VALUES)),
                         f"{gitcmd.GITHUB_USER}:{MIXED_VALUES['GH_TOKEN']}")

    def test_a_github_host_never_sends_an_empty_user(self):
        # Azure Repos takes an empty user beside a PAT. github over https
        # refuses one, so every push would fail with a credential that looks
        # right in the config. The host block here names no user.
        self.assertTrue(pair(gitcmd.env_for(MIXED, MIXED_VALUES)).startswith(
            f"{gitcmd.GITHUB_USER}:"))

    def test_an_azure_host_never_falls_back_to_the_github_token(self):
        # One fallback name cannot serve both host kinds. A GitHub token in the
        # Authorization header to an Azure Repos server is the mix-up to stop.
        with self.assertRaises(secrets.SecretsError) as caught:
            gitcmd.env_for(AZ_BARE, {"GH_TOKEN": "ghp_tokentokentoken"})
        self.assertIn("AZDO_PAT", str(caught.exception))

    def test_a_host_kind_we_do_not_serve_raises_and_names_the_profile(self):
        profile = {"slug": "globex", "host": {"kind": "gitlab"}}
        with self.assertRaises(ValueError) as caught:
            gitcmd.env_for(profile, AZ_VALUES)
        self.assertIn("globex", str(caught.exception))
        self.assertIn("gitlab", str(caught.exception))

    def test_terminal_prompts_are_disabled_so_a_hang_becomes_an_error(self):
        self.assertEqual(gitcmd.env_for(AZ_PROFILE, AZ_VALUES)["GIT_TERMINAL_PROMPT"], "0")

    def test_run_passes_the_identity_and_the_arguments(self):
        seen = {}

        def runner(argv, cwd, env):
            seen.update(argv=argv, cwd=cwd, env=env)
            return 0

        rc = gitcmd.run(AZ_PROFILE, AZ_VALUES, ["fetch", "origin", "master"], runner=runner)
        self.assertEqual(rc, 0)
        self.assertEqual(seen["argv"][:3], ["git", "-c", "user.name=Example.Dev"])
        self.assertEqual(seen["argv"][-3:], ["fetch", "origin", "master"])
        self.assertEqual(seen["cwd"], "/repos/Contoso-migration")

    def test_the_credential_never_reaches_argv(self):
        seen = {}

        def runner(argv, cwd, env):
            seen.update(argv=argv, env=env)
            return 0

        gitcmd.run(AZ_PROFILE, AZ_VALUES, ["push"], runner=runner)
        line = " ".join(seen["argv"])
        # A token in plain text, in a -c value or in a remote url.
        self.assertNotIn(AZ_VALUES["AZDO_PAT"], line)
        # And a token behind any base64 in that line. A compare against the
        # one blob env_for built holds for that encoding alone: `Basic
        # base64(":token")`, the empty user half this repository documents for
        # Azure, is a different blob and a working credential. Decode every run
        # and read the plaintext, which closes every encoding of the pair.
        for text in decoded_runs(line):
            self.assertNotIn(AZ_VALUES["AZDO_PAT"], text)
        # The credential still has to reach the child, through the environment.
        # A run that dropped it would pass every assertion above.
        self.assertTrue(
            seen["env"]["GIT_CONFIG_VALUE_0"].startswith("AUTHORIZATION: Basic "))


class TestFailedSpawn(unittest.TestCase):
    def test_a_directory_that_is_not_there_returns_a_code(self):
        # run promises an int. A missing local_path, or a git binary that is not
        # on PATH, raises out of subprocess, and the user reads a traceback.
        missing = os.path.join(self.enterContext(tempfile.TemporaryDirectory()), "gone")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = gitcmd.run(AZ_PROFILE, AZ_VALUES, ["status"], cwd=missing)
        self.assertEqual(code, gitcmd.FATAL)
        self.assertEqual(len(err.getvalue().strip().splitlines()), 1)
        self.assertIn(missing, err.getvalue())
        self.assertNotIn(AZ_VALUES["AZDO_PAT"], err.getvalue())


if __name__ == "__main__":
    unittest.main()
