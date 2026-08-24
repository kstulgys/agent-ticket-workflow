import contextlib
import io
import json
import pathlib
import tempfile
import unittest
import urllib.error
from unittest import mock
from http.client import IncompleteRead, RemoteDisconnected

import helpers  # noqa: F401

from tk_lib import azure, cli, config, github, gitcmd, http, jira, secrets, verbs

PROFILE = {
    "slug": "northwind", "tracker": {"kind": "azure"},
    "buckets": {
        "fixable-here": {"assignee": "self",
                         "state": {"Task": "In Progress", "Bug": "Committed"}},
        "owned-elsewhere": {"assignee": "backend", "state": None},
        "needs-clarification": {"assignee": None, "state": None}},
    "people": {"self": {"id": "guid-me"}, "backend": {"id": "guid-lee"}},
    "deploy_gate": {"state": {"Bug": "Ready for Test"}},
}

AZ = {"slug": "northwind",
      "tracker": {"kind": "azure", "org": "https://dev.azure.com/northwind",
                  "project": "Contoso migration"}}
JIRA = {"slug": "globex",
        "tracker": {"kind": "jira", "site": "https://globex.atlassian.net",
                    "project": "DIST"}}
GH = {"slug": "web",
      "tracker": {"kind": "github", "owner": "globex-dist", "repo": "Web"}}
VALUES = {"AZDO_PAT": "patpatpatpat1234", "JIRA_EMAIL": "me@example.com",
          "JIRA_TOKEN": "tokentokentoken1", "GH_TOKEN": "ghp_tokentokentoken"}
# The live globex shape: a Jira tracker beside a GitHub host. A git command on
# this profile touches Jira not at all, so it must need no Jira secret. The
# tracker people block holds Jira account ids, and the host block holds the
# GitHub login and the host's own people map, so the two identity systems sit
# side by side the way they do on disk.
MIXED = {"slug": "globex",
         "tracker": {"kind": "jira", "site": "https://globex.atlassian.net",
                     "project": "DIST"},
         "host": {"kind": "github", "owner": "globex-dist", "repo": "Web",
                  "base_branch": "main", "local_path": "/repos/Web",
                  "identity": {"name": "devuser",
                               "email": "me@example.com"},
                  "people": {"reviewer": {"login": "lee-gh"}}},
         "people": {"self": {"accountId": "712020:db94cfd4-ccce"},
                    "reviewer": {"accountId": "557058:eb56070b-6c45"}}}
GH_ONLY = {"GH_TOKEN": "ghp_tokentokentoken"}
# The same shape with the link rules the northwind profile carries. A Bug completes
# on merge, so it never links.
LINKED = dict(MIXED, link_rules={"link_types": ["Task"], "never_link_types": ["Bug"]})
# The live northwind shape: an azure tracker beside an azure-repos host. Two kinds,
# one provider, one organization, one token.
AZ_HOSTED = dict(AZ, host={"kind": "azure-repos", "repo": "Contoso.migration",
                           "repo_id": "repo-guid", "project_id": "proj-guid",
                           "local_path": "/repos/Contoso-migration"})


class Recorder:
    """The tracker half of an adapter. It records what the verb sent.

    Each answer defaults to success. A test that drives the failure path sets
    the matching attribute before the call, so one double serves both paths.
    """

    def __init__(self):
        self.calls = []
        self.commented = {"ok": True, "stored": "text", "id": 1}
        self.written = True

    def show(self, ticket, attachments_dir=None):
        self.calls.append(("show", ticket, attachments_dir))
        return {"type": "Task"}

    def comment(self, ticket, text):
        self.calls.append(("comment", ticket, text))
        return dict(self.commented)

    def state(self, ticket, value, item_type=None):
        self.calls.append(("state", ticket, value, item_type))
        return {"ok": self.written, "stored": value}

    def assign(self, ticket, who):
        self.calls.append(("assign", ticket, who))
        return {"ok": self.written, "stored": who}


class TestBucketApply(unittest.TestCase):
    def test_a_bucket_sends_state_then_assignee(self):
        rec = Recorder()
        got = cli.apply_bucket(PROFILE, rec, "59644", "fixable-here", item_type="Task")
        self.assertEqual(rec.calls[0][:3],
                         ("state", "59644", {"Task": "In Progress", "Bug": "Committed"}))
        self.assertEqual(rec.calls[1], ("assign", "59644", "guid-me"))
        self.assertTrue(got["ok"])
        # No label key. A bucket label wrote nothing and nothing read it, and a
        # key that does nothing reads as a key that works.
        self.assertNotIn("label", got)

    def test_a_bucket_with_no_state_only_assigns(self):
        rec = Recorder()
        cli.apply_bucket(PROFILE, rec, "59644", "owned-elsewhere", item_type="Bug")
        self.assertEqual([call[0] for call in rec.calls], ["assign"])

    def test_a_bucket_with_neither_touches_nothing(self):
        rec = Recorder()
        got = cli.apply_bucket(PROFILE, rec, "59644", "needs-clarification")
        self.assertEqual(rec.calls, [])
        self.assertTrue(got["ok"])

    def test_the_gate_uses_the_deploy_gate_state(self):
        rec = Recorder()
        cli.apply_gate(PROFILE, rec, "59614", item_type="Bug")
        self.assertEqual(rec.calls[0][2], {"Bug": "Ready for Test"})

    def test_an_unknown_bucket_name_lists_the_known_ones(self):
        with self.assertRaises(ValueError) as cm:
            cli.apply_bucket(PROFILE, Recorder(), "1", "nope")
        self.assertIn("fixable-here", str(cm.exception))

    def test_a_profile_with_no_gate_raises(self):
        with self.assertRaises(ValueError):
            cli.apply_gate({"slug": "x"}, Recorder(), "1")

    def test_a_bucket_naming_a_role_the_people_block_lacks_is_refused(self):
        # person() answers None for a role nobody defines, and a None assignee
        # clears the field on a real ticket. Refuse before the write, the way
        # an unknown bucket name is refused four lines above.
        profile = dict(PROFILE, buckets={
            "ghost": {"assignee": "nobody", "state": None}})
        rec = Recorder()
        with self.assertRaises(ValueError) as cm:
            cli.apply_bucket(profile, rec, "59644", "ghost")
        self.assertIn("nobody", str(cm.exception))
        self.assertIn("ghost", str(cm.exception))
        self.assertEqual(rec.calls, [])


class TestAdapterFor(unittest.TestCase):
    def test_an_unknown_tracker_kind_raises(self):
        with self.assertRaises(ValueError):
            cli.adapter_for({"tracker": {"kind": "trello"}}, {})

    def test_every_tracker_kind_comes_from_the_one_table(self):
        # One table is the only route to an adapter. A verb that builds its own
        # would need a second edit for every new provider.
        for profile, kind in ((AZ, azure.Azure), (JIRA, jira.Jira), (GH, github.GitHub)):
            with self.subTest(kind=kind.KIND):
                self.assertIsInstance(cli.adapter_for(profile, VALUES), kind)


class TestHostAdapterFor(unittest.TestCase):
    def test_the_host_block_wins_over_the_tracker(self):
        # The live globex profile is a Jira tracker beside a GitHub host. Jira
        # holds no pull request, so a pull request must go to the host.
        self.assertIsInstance(cli.host_adapter_for(MIXED, GH_ONLY), github.GitHub)

    def test_a_github_tracker_with_no_host_block_falls_back_to_the_tracker(self):
        # A GitHub tracker holds the owner and the repository already, so it
        # answers for its own pull requests. An Azure tracker does not: the
        # git routes need host.repo_id, so it is refused below instead.
        self.assertIsInstance(cli.host_adapter_for(GH, VALUES), github.GitHub)

    def test_one_host_kind_spelling_serves_the_pull_request_and_git_routes(self):
        # This table used to take azure beside azure-repos, and gitcmd takes
        # azure-repos alone. A profile spelled azure then opened a pull request
        # and failed every git command, and neither message named the other
        # spelling. One spelling has to satisfy both call sites.
        profile = dict(AZ, host={"kind": "azure-repos", "repo": "Contoso.migration",
                                 "repo_id": "repo-guid", "project_id": "proj-guid",
                                 "local_path": "/repos/Contoso-migration"})
        self.assertIsInstance(cli.host_adapter_for(profile, VALUES), azure.Azure)
        self.assertIn("GIT_CONFIG_VALUE_0", gitcmd.env_for(profile, VALUES))
        stale = dict(profile, host=dict(profile["host"], kind="azure"))
        for call in (cli.host_adapter_for, gitcmd.env_for):
            with self.subTest(call=call.__name__):
                with self.assertRaises(ValueError) as cm:
                    call(stale, VALUES)
                self.assertIn("azure-repos", str(cm.exception))

    def test_a_kind_that_hosts_no_pull_request_raises(self):
        # An azure tracker with no host block lands here too. The git routes
        # need host.repo_id, so it could never open a pull request, and this
        # sentence names the setting to add.
        for profile, named in ((JIRA, "jira"), (AZ, "azure")):
            with self.subTest(kind=named):
                with self.assertRaises(ValueError) as cm:
                    cli.host_adapter_for(profile, VALUES)
                self.assertIn(named, str(cm.exception))
                self.assertIn("host.kind", str(cm.exception))


class TestHostIdentity(unittest.TestCase):
    """One rule for every host verb: a role resolves against the host."""

    def test_a_tracker_identity_never_reaches_a_host_on_another_provider(self):
        # This is the defect the live run found. A Jira account id is no GitHub
        # login, so it filters no thread and it names no reviewer.
        self.assertEqual(cli.host_names(MIXED, "self"), ["devuser"])
        self.assertEqual(cli.host_person(MIXED, "reviewer"), "lee-gh")
        for role in ("self", "reviewer"):
            with self.subTest(role=role):
                self.assertNotIn(cli.person(MIXED, role),
                                 cli.host_names(MIXED, role))

    def test_a_host_on_the_tracker_provider_reads_the_people_block(self):
        # azure-repos beside azure is one identity system, and the Azure host
        # knows me by the account id the people block holds. The host identity
        # name is the git author name, and it names no Azure account, so an
        # account identity always comes first.
        profile = dict(AZ_HOSTED, people={"self": {"id": "me-guid"},
                                          "reviewer": {"id": "ana-guid"}},
                       host=dict(AZ_HOSTED["host"],
                                 identity={"name": "Example.Dev"}))
        self.assertEqual(cli.host_names(profile, "self"),
                         ["me-guid", "Example.Dev"])
        self.assertEqual(cli.host_person(profile, "self"), "me-guid")
        self.assertEqual(cli.host_person(profile, "reviewer"), "ana-guid")

    def test_a_tracker_that_hosts_itself_reads_the_people_block(self):
        # A GitHub tracker with no host block answers for its own pull
        # requests, so its people block is the host's people block.
        profile = dict(GH, people={"reviewer": {"login": "octocat"}})
        self.assertEqual(cli.host_person(profile, "reviewer"), "octocat")

    def test_a_role_nobody_names_answers_none(self):
        # The caller then sends the name it was given, and the host reads it.
        self.assertIsNone(cli.host_person(MIXED, "backend"))
        self.assertEqual(cli.host_names(MIXED, "backend"), [])

    def test_the_host_people_map_wins_over_the_tracker_people_block(self):
        # Both blocks can hold one role on one provider, and then the host's
        # own map is the answer: it is the map the host owns. Nothing else
        # pinned this step, so the order was documented and free to move.
        profile = dict(AZ_HOSTED, people={"self": {"id": "tracker-guid"},
                                          "reviewer": {"id": "tracker-ana"}},
                       host=dict(AZ_HOSTED["host"],
                                 people={"self": {"id": "host-guid"},
                                         "reviewer": {"id": "host-ana"}}))
        self.assertEqual(cli.host_person(profile, "reviewer"), "host-ana")
        self.assertEqual(cli.host_names(profile, "self"),
                         ["host-guid", "tracker-guid"])

    def test_a_profile_that_resolves_no_self_on_its_host_is_refused(self):
        # Both adapters read no name as "filter nothing", so an empty answer
        # would hand a resume run its own threads to answer. host.identity.name
        # is optional, and gitcmd falls back to the git config on disk, so a
        # profile can reach this with no name at all.
        profile = dict(MIXED, host={key: value
                                    for key, value in MIXED["host"].items()
                                    if key not in ("identity", "people")})
        self.assertEqual(cli.host_names(profile, "self"), [])
        with self.assertRaises(ValueError) as cm:
            cli.host_self(profile)
        for named in ("globex", "host.identity.name", "host.people.self",
                      "people.self"):
            with self.subTest(named=named):
                self.assertIn(named, str(cm.exception))

    def test_a_profile_that_resolves_a_self_answers_every_name(self):
        self.assertEqual(cli.host_self(MIXED), ["devuser"])


class TestBodyFile(unittest.TestCase):
    def test_read_body_reads_a_file(self):
        path = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()), "body.md")
        path.write_text("line one\n\nline two", encoding="utf-8")
        self.assertEqual(cli.read_body(str(path)), "line one\n\nline two")

    def test_read_body_reads_stdin_for_a_dash(self):
        with mock.patch("sys.stdin", io.StringIO("from the pipe")):
            self.assertEqual(cli.read_body("-"), "from the pipe")


class TestUsage(unittest.TestCase):
    def test_the_usage_text_names_exactly_the_registered_verbs(self):
        # Task 1 advertised ten verbs with none registered. Now that the verbs
        # exist, the help text and the table must not drift apart.
        cli.load_verbs()
        listed = [line.split()[0] for line in cli.USAGE.splitlines()
                  if line.startswith("  ")]
        self.assertEqual(sorted(listed), sorted(cli.VERBS))


class TestGuarded(unittest.TestCase):
    def run_raising(self, error):
        @cli.guarded
        def boom(argv):
            raise error

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = boom([])
        return code, json.loads(out.getvalue())

    def test_a_corrupt_profile_makes_resolve_print_json_and_exit_one(self):
        # resolve is the first verb the engine calls on every run, and it was
        # the one verb with no guard. A traceback here lands at the moment the
        # agent is working out which project it is in.
        root = self.enterContext(tempfile.TemporaryDirectory())
        target = pathlib.Path(root, "projects", "globex")
        target.mkdir(parents=True)
        (target / "config.json").write_text("{ not json", encoding="utf-8")
        self.enterContext(mock.patch.object(config, "ROOT", root))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.VERBS["resolve"](["DIST-1"])
        payload = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "profile")
        self.assertIn("config.json", payload["message"])

    def test_every_error_class_below_becomes_exit_one_and_one_json_line(self):
        # Each one comes from a real failure: a bad --render directory, a
        # profile that misses a key, a corrupt secrets file, and the GitHub page
        # walk at its bound. The code names the class, and the sentence sits
        # under message, the shape resolve already answers.
        errors = [(OSError("no such directory: /tmp/gone"), "filesystem"),
                  (urllib.error.URLError("name or service not known"), "network"),
                  (KeyError("repo_id"), "profile"),
                  (config.BadProfile("config.json is not valid JSON"), "profile"),
                  (UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad start byte"),
                   "encoding"),
                  (RuntimeError("answered 50 full pages"), "incomplete"),
                  (ValueError("pass --bucket <name> or --gate"), "usage"),
                  (config.Unresolved("no profile matches the ticket 1"), "unresolved"),
                  (secrets.SecretsError("no secrets file"), "secrets"),
                  (http.HttpError(401, "unauthorized"), "http"),
                  # A truncated body used to match no entry at all, so the run
                  # printed a traceback and no JSON. A reset and a timeout are
                  # both an OSError, so both used to print filesystem for a
                  # fault on the wire.
                  (IncompleteRead(b""), "network"),
                  (RemoteDisconnected("Remote end closed connection without"
                                      " response"), "network"),
                  (TimeoutError("timed out"), "network")]
        for error, code_name in errors:
            with self.subTest(error=type(error).__name__):
                code, payload = self.run_raising(error)
                self.assertEqual(code, 1)
                self.assertEqual(payload["error"], code_name)
                self.assertTrue(payload["message"])

    def test_only_an_ambiguous_ticket_exits_two(self):
        code, payload = self.run_raising(config.Ambiguous(["globex", "northwind"]))
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"], "ambiguous")
        self.assertEqual(payload["slugs"], ["globex", "northwind"])
        self.assertIn("globex", payload["message"])

    def test_a_guarded_verb_and_resolve_answer_the_same_error_shape(self):
        # resolve states the contract: a caller switches on the code under
        # error and prints the sentence under message. Every verb must answer
        # that shape, or the engine reads two.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.enterContext(mock.patch.object(verbs.config, "load_all", lambda: {}))
            resolved = cli.VERBS["resolve"](["59644"])
        from_resolve = json.loads(out.getvalue())
        guarded_code, from_guarded = self.run_raising(
            config.Unresolved("no profile matches the ticket 59644"))
        self.assertEqual(resolved, guarded_code)
        self.assertEqual(sorted(from_resolve), sorted(from_guarded))
        self.assertEqual(from_resolve["error"], from_guarded["error"])

    def test_an_argparse_failure_never_takes_the_ambiguous_code(self):
        # parser.error raises SystemExit(2), which is no Exception. Without a
        # catch it leaves no JSON at all, and its 2 reads to a caller as an
        # ambiguous ticket.
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.VERBS["show"]([])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue())["error"], "usage")

    def test_a_verb_help_exits_zero(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.VERBS["show"](["--help"])
        self.assertEqual(code, 0)
        self.assertIn("--attachments", out.getvalue())

    def test_the_message_goes_through_the_scrubber(self):
        secrets.SCRUB.append("patpatpatpat1234")
        self.addCleanup(secrets.SCRUB.remove, "patpatpatpat1234")
        code, payload = self.run_raising(ValueError("sent patpatpatpat1234 to the api"))
        self.assertEqual(code, 1)
        self.assertNotIn("patpatpatpat1234", payload["message"])
        self.assertIn("***", payload["message"])


class TestGitVerb(unittest.TestCase):
    def patch_profile(self):
        self.enterContext(mock.patch.object(
            verbs, "_profile", lambda slug=None, arg=None: (AZ, VALUES, arg)))

    def test_a_nonzero_git_code_becomes_exit_one(self):
        # git answers 128 for a fatal error. This CLI documents three codes, so
        # any nonzero git code maps to 1.
        self.patch_profile()
        self.enterContext(mock.patch.object(verbs.gitcmd, "run", lambda *a, **k: 128))
        self.assertEqual(cli.VERBS["git"](["--slug", "northwind", "--", "status"]), 1)

    def test_a_clean_git_run_exits_zero_and_passes_the_arguments(self):
        self.patch_profile()
        seen = {}

        def run(profile, values, args):
            seen["args"] = args
            return 0

        self.enterContext(mock.patch.object(verbs.gitcmd, "run", run))
        self.assertEqual(cli.VERBS["git"](["--slug", "northwind", "--", "push", "origin"]), 0)
        self.assertEqual(seen["args"], ["push", "origin"])

    def test_a_git_run_needs_no_tracker_secret(self):
        # The live globex profile is a Jira tracker beside a GitHub host. A verb
        # that built the tracker here would ask for a Jira token to run a git
        # command that never touches Jira, and an expired Jira token would then
        # break git push. The secrets hold the GitHub token only.
        seen = {}

        def run(profile, values, args):
            # Build the credential here. It must come from the host block
            # alone, with no Jira value in the secrets at all.
            seen["env"] = gitcmd.env_for(profile, values)
            seen["args"] = args
            return 0

        self.enterContext(mock.patch.object(verbs.secrets, "load", lambda: GH_ONLY))
        self.enterContext(mock.patch.object(verbs.config, "load_all",
                                            lambda: {"globex": MIXED}))
        self.enterContext(mock.patch.object(verbs.gitcmd, "run", run))
        self.assertEqual(cli.VERBS["git"](["--slug", "globex", "--", "status"]), 0)
        self.assertEqual(seen["args"], ["status"])
        self.assertEqual(seen["env"]["GIT_CONFIG_KEY_0"],
                         "http.https://github.com/.extraheader")

    def test_an_unknown_slug_names_the_ones_it_knows(self):
        self.enterContext(mock.patch.object(verbs.secrets, "load", lambda: GH_ONLY))
        self.enterContext(mock.patch.object(verbs.config, "load_all",
                                            lambda: {"globex": MIXED}))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.VERBS["git"](["--slug", "nope", "--", "status"])
        self.assertEqual(code, 1)
        self.assertIn("globex", json.loads(out.getvalue())["message"])

    def test_no_separator_names_the_usage(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.VERBS["git"](["--slug", "northwind"])
        self.assertEqual(code, 1)
        self.assertIn("tk git", json.loads(out.getvalue())["message"])


class TestFigmaVerb(unittest.TestCase):
    def test_the_figma_verb_builds_the_client_with_no_profile(self):
        # Figma takes the secrets only. It is not a tracker, so it is not in
        # the adapter table and it needs no project profile.
        seen = {}

        class FakeFigma:
            def __init__(self, values, client=None):
                seen["values"] = values

            def specs(self, url):
                seen["url"] = url
                return [{"id": "1:2", "size": "24x24"}]

        self.enterContext(mock.patch.object(verbs.secrets, "load",
                                            lambda: {"FIGMA_TOKEN": "figd_token"}))
        self.enterContext(mock.patch.object(verbs.figma, "Figma", FakeFigma))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.VERBS["figma"](["https://www.figma.com/design/A/x?node-id=1-2"])
        self.assertEqual(code, 0)
        self.assertEqual(seen["values"], {"FIGMA_TOKEN": "figd_token"})
        self.assertEqual(json.loads(out.getvalue())["specs"][0]["size"], "24x24")


class FakeHost:
    """The pull request half of an adapter. It records what the verb sent.

    Each answer defaults to success, in the shape the real adapters return. A
    test that drives the failure path sets the matching attribute first.
    """

    def __init__(self):
        self.calls = []
        self.reply = {"ok": True, "stored": "text"}
        self.attachment = {"url": "u", "ok": True, "markdown": "![a](u)"}

    def pr_create(self, head, title, body, base=None, links=(), reviewer=None):
        self.calls.append(("create", head, title, body, base, list(links), reviewer))
        return {"id": 7, "url": "u", "linked": [], "unlinked": [], "refused": [],
                "reviewer_ok": None}

    def pr_threads(self, pr, me=None):
        self.calls.append(("threads", pr, me))
        return []

    def pr_describe(self, pr, body):
        self.calls.append(("describe", pr, body))
        return {"ok": True, "stored": body, "unlinked": []}

    def pr_comment(self, pr, text, reply_to=None):
        self.calls.append(("comment", pr, text, reply_to))
        return dict(self.reply)

    def pr_attach(self, pr, path):
        self.calls.append(("attach", pr, path))
        return dict(self.attachment)


class TestPrVerb(unittest.TestCase):
    def setUp(self):
        self.host = FakeHost()
        self.enterContext(mock.patch.object(verbs.secrets, "load", lambda: GH_ONLY))
        self.enterContext(mock.patch.object(verbs.config, "load_all",
                                            lambda: {"globex": MIXED}))
        self.enterContext(mock.patch.object(
            verbs.cli, "host_adapter_for", lambda p, v, c=None: self.host))

    def no_tracker(self):
        """Fails the test when the verb builds the tracker adapter."""
        def build(*args, **kwargs):
            raise AssertionError("the pr verb built the tracker adapter")

        self.enterContext(mock.patch.object(verbs.cli, "adapter_for", build))

    def body_file(self, text):
        path = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()), "b.md")
        path.write_text(text, encoding="utf-8")
        return str(path)

    def run_pr(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.VERBS["pr"](argv)
        return code, json.loads(out.getvalue())

    def test_the_pr_verb_never_builds_the_tracker(self):
        # The tracker here is Jira, which holds no pr_describe. Building it
        # would need a Jira token, and calling it would raise an AttributeError
        # that no guard catches.
        self.no_tracker()
        code, _ = self.run_pr(["describe", "--slug", "globex", "--pr", "6453",
                               "--body-file", self.body_file("new text")])
        self.assertEqual(code, 0)
        self.assertEqual(self.host.calls, [("describe", "6453", "new text")])

    def test_a_link_that_names_its_type_reads_nothing_back(self):
        # The suffix is the type the caller knows. Reading it back costs a full
        # work item read on Azure, with every comment page.
        self.no_tracker()
        code, _ = self.run_pr(["create", "--slug", "globex", "--head", "fix/1",
                               "--title", "Fix it", "--link", "59644:Bug",
                               "--body-file", self.body_file("why")])
        self.assertEqual(code, 0)
        self.assertEqual(self.host.calls[0][5], [{"id": "59644", "type": "Bug"}])

    def test_a_link_with_no_type_reads_it_from_the_tracker(self):
        seen = {}

        class Tracker:
            def show(self, ticket, attachments_dir=None):
                seen["ticket"] = ticket
                return {"type": "Task"}

        self.enterContext(mock.patch.object(verbs.cli, "adapter_for",
                                            lambda *a, **k: Tracker()))
        code, _ = self.run_pr(["create", "--slug", "globex", "--head", "fix/1",
                               "--title", "Fix it", "--link", "59644",
                               "--body-file", self.body_file("why")])
        self.assertEqual(code, 0)
        self.assertEqual(seen["ticket"], "59644")
        self.assertEqual(self.host.calls[0][5], [{"id": "59644", "type": "Task"}])

    def test_a_reviewer_role_resolves_against_the_host(self):
        # pr create is a host verb, so every role it names belongs to the host.
        # A Jira account id sent as a GitHub reviewer names nobody there, and
        # this is the same seam that left pr threads unfiltered.
        self.no_tracker()
        code, _ = self.run_pr(["create", "--slug", "globex", "--head", "fix/1",
                               "--title", "Fix it", "--reviewer", "reviewer",
                               "--body-file", self.body_file("why")])
        self.assertEqual(code, 0)
        self.assertEqual(self.host.calls[0][6], "lee-gh")

    def test_a_reviewer_the_profile_never_names_goes_out_as_it_came_in(self):
        # A login typed on the command line is a name the host reads already.
        self.no_tracker()
        code, _ = self.run_pr(["create", "--slug", "globex", "--head", "fix/1",
                               "--title", "Fix it", "--reviewer", "octocat",
                               "--body-file", self.body_file("why")])
        self.assertEqual(code, 0)
        self.assertEqual(self.host.calls[0][6], "octocat")

    def with_rules(self, rules=None):
        profile = LINKED if rules is None else dict(MIXED, link_rules=rules)
        self.enterContext(mock.patch.object(verbs.config, "load_all",
                                            lambda: {"globex": profile}))

    def create_with(self, link):
        return self.run_pr(["create", "--slug", "globex", "--head", "fix/1",
                            "--title", "Fix it", "--link", link,
                            "--body-file", self.body_file("why")])

    def test_a_link_type_folds_to_the_spelling_the_profile_holds(self):
        # never_link_types compares the exact spelling. A caller who writes bug
        # where the profile writes Bug used to pass the refusal, so the bug
        # linked, completed on merge, and skipped its test pass in silence.
        self.no_tracker()
        self.with_rules()
        code, _ = self.create_with("59644:bug")
        self.assertEqual(code, 0)
        self.assertEqual(self.host.calls[0][5], [{"id": "59644", "type": "Bug"}])

    def test_a_link_type_the_profile_never_names_is_refused(self):
        # A type nobody listed is a typo, and a typo lands outside
        # never_link_types, which is where the harm is.
        self.no_tracker()
        self.with_rules()
        code, payload = self.create_with("59644:Epic")
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "usage")
        self.assertIn("Epic", payload["message"])
        self.assertIn("Bug", payload["message"])
        self.assertEqual(self.host.calls, [])

    def test_one_type_spelled_two_ways_in_the_rules_is_refused(self):
        # Two spellings fold to one key, and the one this resolves to decides
        # whether the work item completes on merge. That is a coin flip.
        self.no_tracker()
        self.with_rules({"link_types": ["task"], "never_link_types": ["Task"]})
        code, payload = self.create_with("59644:Task")
        self.assertEqual(code, 1)
        self.assertIn("one spelling", payload["message"])
        self.assertEqual(self.host.calls, [])

    def test_describe_with_no_body_file_writes_nothing(self):
        # A null description PATCHed over the stored one destroys text a human
        # wrote, and the answer reads ok.
        self.no_tracker()
        code, payload = self.run_pr(["describe", "--slug", "globex", "--pr", "6453"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "usage")
        self.assertIn("--body-file", payload["message"])
        self.assertEqual(self.host.calls, [])

    def test_threads_sends_the_name_the_host_knows_me_by(self):
        # The host filters my own threads on this name. A Jira account id never
        # equals a GitHub login, so the tracker identity alone filtered nothing
        # and a resume run answered its own comments.
        self.no_tracker()
        code, _ = self.run_pr(["threads", "--slug", "globex", "--pr", "907"])
        self.assertEqual(code, 0)
        action, pr, me = self.host.calls[0]
        self.assertEqual((action, pr), ("threads", "907"))
        self.assertIn("devuser", me)

    def test_threads_on_a_profile_with_no_host_self_calls_nothing(self):
        # No name means no filter in both adapters, so the verb would answer
        # with my own threads and a resume run would answer itself. Stop
        # instead: one JSON line, exit 1, and no call.
        self.no_tracker()
        bare = dict(MIXED, host={key: value
                                 for key, value in MIXED["host"].items()
                                 if key not in ("identity", "people")})
        self.enterContext(mock.patch.object(verbs.config, "load_all",
                                            lambda: {"globex": bare}))
        code, payload = self.run_pr(["threads", "--slug", "globex", "--pr", "907"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "usage")
        self.assertIn("host.identity.name", payload["message"])
        self.assertEqual(self.host.calls, [])

    def test_threads_with_no_pr_number_calls_nothing(self):
        # Without this the route reads pullRequests/None/threads.
        self.no_tracker()
        code, payload = self.run_pr(["threads", "--slug", "globex"])
        self.assertEqual(code, 1)
        self.assertIn("--pr", payload["message"])
        self.assertEqual(self.host.calls, [])

    def test_attach_with_no_file_calls_nothing(self):
        self.no_tracker()
        code, payload = self.run_pr(["attach", "--slug", "globex", "--pr", "6453"])
        self.assertEqual(code, 1)
        self.assertIn("--file", payload["message"])
        self.assertEqual(self.host.calls, [])

    def test_an_unknown_action_lists_the_known_ones(self):
        code, payload = self.run_pr(["frobnicate", "--slug", "globex"])
        self.assertEqual(code, 1)
        self.assertIn("describe", payload["message"])
        self.assertEqual(self.host.calls, [])

    def test_a_stored_pr_comment_exits_zero(self):
        self.no_tracker()
        code, payload = self.run_pr(["comment", "--slug", "globex", "--pr", "6453",
                                     "--body-file", self.body_file("review reply")])
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(self.host.calls,
                         [("comment", "6453", "review reply", None)])

    def test_a_pr_comment_the_server_did_not_store_exits_one(self):
        self.no_tracker()
        self.host.reply = {"ok": False, "stored": None}
        code, payload = self.run_pr(["comment", "--slug", "globex", "--pr", "6453",
                                     "--body-file", self.body_file("review reply")])
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])

    def test_an_upload_that_matches_the_bytes_exits_zero(self):
        self.no_tracker()
        code, payload = self.run_pr(["attach", "--slug", "globex", "--pr", "6453",
                                     "--file", self.body_file("shot")])
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(self.host.calls[0][0], "attach")

    def test_a_short_upload_exits_one(self):
        # A short upload still answers with a url, and the markdown then points
        # at a broken image. The adapter compares the bytes and says so.
        self.no_tracker()
        self.host.attachment = {"url": "u", "ok": False, "markdown": "![a](u)"}
        code, payload = self.run_pr(["attach", "--slug", "globex", "--pr", "6453",
                                     "--file", self.body_file("shot")])
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])

    def test_an_answer_with_no_ok_key_exits_zero(self):
        # pr create answers six keys and no ok on purpose, so the verb tests
        # `is False` rather than truthiness. A simplification to `not ok` would
        # turn every successful pull request into exit 1.
        self.no_tracker()
        code, payload = self.run_pr(["create", "--slug", "globex",
                                     "--head", "feature/x", "--title", "t",
                                     "--body-file", self.body_file("body")])
        self.assertEqual(code, 0)
        self.assertNotIn("ok", payload)


class FakeProvider:
    """The two calls doctor makes on any adapter."""

    def __init__(self, ok=True):
        self.ok = ok

    def whoami(self):
        if not self.ok:
            raise RuntimeError("401 unauthorized")
        return {"name": "devuser", "id": "id-1"}

    def repo_check(self):
        return {"ok": True}


class TestDoctorVerb(unittest.TestCase):
    def run_doctor(self, profiles, host_ok=True):
        self.built = []

        def tracker(profile, values, client=None):
            self.built.append(("tracker", profile["slug"]))
            return FakeProvider()

        def host(profile, values, client=None):
            self.built.append(("host", profile["slug"]))
            return FakeProvider(ok=host_ok)

        self.enterContext(mock.patch.object(verbs.secrets, "load", lambda: GH_ONLY))
        self.enterContext(mock.patch.object(verbs.config, "load_all",
                                            lambda: profiles))
        self.enterContext(mock.patch.object(verbs.cli, "adapter_for", tracker))
        self.enterContext(mock.patch.object(verbs.cli, "host_adapter_for", host))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.VERBS["doctor"]([])
        return code, json.loads(out.getvalue())

    def test_a_host_on_another_provider_gets_its_own_row(self):
        # The globex profile is a Jira tracker beside a GitHub host, so its
        # GitHub token reached no check here. A dead token then first showed up
        # at tk pr create, which is the moment this verb comes before.
        code, report = self.run_doctor({"globex": MIXED})
        self.assertEqual(code, 0)
        self.assertEqual([(row["role"], row["provider"])
                          for row in report["projects"]],
                         [("tracker", "jira"), ("host", "github")])
        self.assertTrue(report["providers"]["github"])

    def test_an_azure_repos_host_adds_no_second_check(self):
        # azure-repos is the host spelling of azure: one organization, one
        # token, one API. A second row there tests the same token twice.
        code, report = self.run_doctor({"northwind": AZ_HOSTED})
        self.assertEqual(code, 0)
        self.assertEqual([row["provider"] for row in report["projects"]], ["azure"])
        self.assertEqual(self.built, [("tracker", "northwind")])

    def test_a_dead_host_token_fails_its_own_row_and_names_its_setup(self):
        code, report = self.run_doctor({"globex": MIXED}, host_ok=False)
        self.assertEqual(code, 1)
        rows = {row["role"]: row for row in report["projects"]}
        self.assertTrue(rows["tracker"]["ok"])
        self.assertFalse(rows["host"]["ok"])
        self.assertIn("setup.sh github", " ".join(report["fix"]))



class TestMineVerb(unittest.TestCase):
    def run_mine(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.VERBS["mine"](argv)
        return code, json.loads(out.getvalue())

    def patch_two(self):
        self.enterContext(mock.patch.object(verbs.secrets, "load", lambda: GH_ONLY))
        self.enterContext(mock.patch.object(
            verbs.config, "load_all", lambda: {"globex": MIXED, "web": GH}))

    def test_an_unknown_slug_lists_the_ones_it_knows(self):
        # A bare key repr tells the reader nothing. Name every slug on disk.
        self.patch_two()
        code, payload = self.run_mine(["--slug", "vwfps"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "unresolved")
        self.assertIn("globex", payload["message"])
        self.assertIn("web", payload["message"])

    def test_one_broken_profile_does_not_hide_the_other(self):
        # doctor keeps going when one project has no token. This verb must too,
        # or one stale token hides every ticket on every other project.
        self.patch_two()

        class Working:
            def mine(self):
                return [{"id": "1", "slug": "web"}]

        def build(profile, values, client=None):
            if profile["slug"] == "globex":
                raise secrets.SecretsError("JIRA_TOKEN is not set in secrets.env")
            return Working()

        self.enterContext(mock.patch.object(verbs.cli, "adapter_for", build))
        code, payload = self.run_mine([])
        self.assertEqual(code, 1)
        self.assertEqual(payload["tickets"], [{"id": "1", "slug": "web"}])
        self.assertEqual(payload["failed"][0]["slug"], "globex")
        self.assertIn("JIRA_TOKEN", payload["failed"][0]["error"])


class TestStateVerb(unittest.TestCase):
    def run_state(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.VERBS["state"](argv)
        return code, json.loads(out.getvalue())

    def test_the_gate_and_a_bucket_together_are_refused(self):
        # The gate is the one state the engine sets on a human's word. A
        # command asking for both used to drop the bucket in silence.
        code, payload = self.run_state(["59644", "--gate", "--bucket", "fixable-here"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "usage")
        self.assertIn("both", payload["message"])

    def test_neither_the_gate_nor_a_bucket_is_refused_before_any_call(self):
        # No secrets are loaded here, so the refusal must come before the
        # profile read. A network call for a command that cannot run is waste.
        code, payload = self.run_state(["59644"])
        self.assertEqual(code, 1)
        self.assertIn("--bucket", payload["message"])


class TestTrackerWriteVerbs(unittest.TestCase):
    """Every verb that changes a ticket turns the adapter's ok into an exit code.

    That line was untested on all four verbs. The routine reads the exit code to
    decide whether the write landed, so an exit 0 on a refused write would have
    the agent record a comment the server never stored and move on.
    """

    def setUp(self):
        self.rec = Recorder()
        self.enterContext(mock.patch.object(verbs.secrets, "load", lambda: VALUES))
        self.enterContext(mock.patch.object(verbs.config, "load_all",
                                            lambda: {"northwind": PROFILE}))
        self.enterContext(mock.patch.object(
            verbs.cli, "adapter_for", lambda p, v, c=None: self.rec))

    def run_verb(self, name, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.VERBS[name](argv)
        return code, json.loads(out.getvalue())

    def body_file(self, text):
        path = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()), "b.md")
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_a_stored_comment_exits_zero(self):
        code, payload = self.run_verb(
            "comment", ["59644", "--slug", "northwind",
                        "--body-file", self.body_file("hello")])
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(self.rec.calls, [("comment", "59644", "hello")])

    def test_a_comment_the_server_did_not_store_exits_one(self):
        self.rec.commented = {"ok": False, "stored": None, "id": 1}
        code, payload = self.run_verb(
            "comment", ["59644", "--slug", "northwind",
                        "--body-file", self.body_file("hello")])
        self.assertEqual(code, 1)
        # The answer still prints. The routine reads stored to see what landed.
        self.assertFalse(payload["ok"])
        self.assertIn("stored", payload)

    def test_a_bucket_that_lands_exits_zero(self):
        code, payload = self.run_verb(
            "state", ["59644", "--slug", "northwind", "--bucket", "fixable-here",
                      "--type", "Task"])
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])

    def test_a_bucket_the_server_refused_exits_one(self):
        self.rec.written = False
        code, payload = self.run_verb(
            "state", ["59644", "--slug", "northwind", "--bucket", "fixable-here",
                      "--type", "Task"])
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])

    def test_the_gate_that_lands_exits_zero(self):
        code, payload = self.run_verb(
            "state", ["59614", "--slug", "northwind", "--gate", "--type", "Bug"])
        self.assertEqual(code, 0)
        self.assertEqual(self.rec.calls[0][2], {"Bug": "Ready for Test"})

    def test_a_gate_the_server_refused_exits_one(self):
        self.rec.written = False
        code, payload = self.run_verb(
            "state", ["59614", "--slug", "northwind", "--gate", "--type", "Bug"])
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])

    def test_no_type_argument_reads_the_type_once(self):
        # That read is a full ticket fetch on Azure, every comment page
        # included. A change that made it unconditional would be expensive and
        # silent.
        code, _ = self.run_verb(
            "state", ["59644", "--slug", "northwind", "--bucket", "fixable-here"])
        self.assertEqual(code, 0)
        self.assertEqual([call[0] for call in self.rec.calls].count("show"), 1)

    def test_a_type_argument_reads_nothing_back(self):
        self.run_verb("state", ["59644", "--slug", "northwind",
                                "--bucket", "fixable-here", "--type", "Task"])
        self.assertNotIn("show", [call[0] for call in self.rec.calls])

    def test_an_assign_that_lands_exits_zero(self):
        code, payload = self.run_verb(
            "assign", ["59644", "--slug", "northwind", "--owner", "self"])
        self.assertEqual(code, 0)
        # The role resolves to the identity the people block holds.
        self.assertEqual(self.rec.calls, [("assign", "59644", "guid-me")])
        self.assertTrue(payload["ok"])

    def test_an_assign_the_server_refused_exits_one(self):
        self.rec.written = False
        code, payload = self.run_verb(
            "assign", ["59644", "--slug", "northwind", "--owner", "self"])
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])


if __name__ == "__main__":
    unittest.main()
