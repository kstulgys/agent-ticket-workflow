import io
import unittest
import urllib.error
import urllib.request

import helpers  # noqa: F401
from helpers import FakeResponse

from tk_lib import http, secrets


def opener_returning(*items):
    queue = list(items)

    def opener(request, timeout=None):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return opener


def http_error(code, body=b"boom", headers=None):
    # Close the object. HTTPError derives from a tempfile wrapper, and an open
    # one prints a ResourceWarning into the test output when the collector
    # reaches it, at whatever point in the run that happens. The read below is
    # a lambda, so closing the stream costs the test nothing.
    error = urllib.error.HTTPError("http://x", code, "err", headers or {},
                                   io.BytesIO(body))
    error.close()
    error.read = lambda: body
    return error


class TestHttp(unittest.TestCase):
    def setUp(self):
        secrets.SCRUB.clear()

    def test_json_decodes_the_body(self):
        client = http.Http(opener=opener_returning(FakeResponse(200, {"id": 7})))
        self.assertEqual(client.json("GET", "http://x")["id"], 7)

    def test_an_empty_body_becomes_an_empty_dict(self):
        client = http.Http(opener=opener_returning(FakeResponse(204, b"")))
        self.assertEqual(client.json("POST", "http://x", {"a": 1}), {})

    def test_a_dict_body_is_sent_as_json(self):
        seen = []

        def opener(request, timeout=None):
            seen.append(request)
            return FakeResponse(200, {})

        http.Http(opener=opener).json("POST", "http://x", {"a": 1})
        self.assertEqual(seen[0].data, b'{"a": 1}')
        self.assertEqual(seen[0].get_header("Content-type"), "application/json")

    def test_a_bytes_body_passes_through_untouched(self):
        seen = []

        def opener(request, timeout=None):
            seen.append(request)
            return FakeResponse(200, {})

        http.Http(opener=opener).raw("POST", "http://x", b"\x89PNG",
                                     {"Content-Type": "application/octet-stream"})
        self.assertEqual(seen[0].data, b"\x89PNG")
        self.assertEqual(seen[0].get_header("Content-type"), "application/octet-stream")

    def test_a_lowercase_content_type_keeps_the_caller_value(self):
        seen = []

        def opener(request, timeout=None):
            seen.append(request)
            return FakeResponse(200, {})

        http.Http(opener=opener).json("PATCH", "http://x", [{"op": "add"}],
                                      {"content-type": "application/json-patch+json"})
        self.assertEqual(seen[0].get_header("Content-type"),
                         "application/json-patch+json")

    def test_retries_on_503_then_succeeds(self):
        slept = []
        client = http.Http(
            opener=opener_returning(http_error(503), FakeResponse(200, {"ok": True})),
            sleep=slept.append)
        self.assertTrue(client.json("GET", "http://x")["ok"])
        self.assertEqual(len(slept), 1)

    def test_honours_retry_after(self):
        slept = []
        client = http.Http(
            opener=opener_returning(http_error(429, headers={"Retry-After": "3"}),
                                    FakeResponse(200, {})),
            sleep=slept.append)
        client.json("GET", "http://x")
        self.assertEqual(slept, [3.0])

    def test_honours_a_lowercase_retry_after(self):
        slept = []
        client = http.Http(
            opener=opener_returning(http_error(429, headers={"retry-after": "3"}),
                                    FakeResponse(200, {})),
            sleep=slept.append)
        client.json("GET", "http://x")
        self.assertEqual(slept, [3.0])

    def test_does_not_retry_a_401(self):
        client = http.Http(opener=opener_returning(http_error(401)), sleep=lambda s: None)
        with self.assertRaises(http.HttpError) as cm:
            client.json("GET", "http://x")
        self.assertEqual(cm.exception.status, 401)

    def test_does_not_retry_a_post_on_500(self):
        slept = []
        client = http.Http(
            opener=opener_returning(http_error(500), FakeResponse(200, {"ok": True})),
            sleep=slept.append)
        with self.assertRaises(http.HttpError) as cm:
            client.json("POST", "http://x", {"text": "hi"})
        self.assertEqual(cm.exception.status, 500)
        self.assertEqual(slept, [])

    def test_retries_a_post_on_429(self):
        slept = []
        client = http.Http(
            opener=opener_returning(http_error(429), FakeResponse(200, {"ok": True})),
            sleep=slept.append)
        self.assertTrue(client.json("POST", "http://x", {"text": "hi"})["ok"])
        self.assertEqual(len(slept), 1)

    def test_still_retries_a_get_on_500(self):
        slept = []
        client = http.Http(
            opener=opener_returning(http_error(500), FakeResponse(200, {"ok": True})),
            sleep=slept.append)
        self.assertTrue(client.json("GET", "http://x")["ok"])
        self.assertEqual(len(slept), 1)

    def test_an_error_body_is_scrubbed(self):
        secrets.SCRUB.append("supersecrettoken")
        client = http.Http(opener=opener_returning(http_error(400, b"bad supersecrettoken")))
        with self.assertRaises(http.HttpError) as cm:
            client.json("GET", "http://x")
        self.assertNotIn("supersecrettoken", str(cm.exception))
        self.assertIn("***", cm.exception.body)

    def test_basic_builds_an_authorization_value(self):
        self.assertEqual(http.basic("", "pat"), "Basic OnBhdA==")

    def test_every_request_carries_the_deadline(self):
        # urlopen with no timeout waits for ever. tk runs as a subprocess under
        # an agent, so a provider that accepts the connection and then sends
        # nothing would hang the run with nothing on stdout.
        seen = []

        def opener(request, timeout=None):
            seen.append(timeout)
            return FakeResponse(200, {})

        http.Http(opener=opener).json("GET", "http://x")
        self.assertEqual(seen, [http.TIMEOUT])

    def test_a_long_retry_after_is_clamped(self):
        # A provider can ask for minutes. retries defaults to 2, so an unclamped
        # value sleeps it twice and the run looks dead.
        slept = []
        client = http.Http(
            opener=opener_returning(http_error(429, headers={"Retry-After": "600"}),
                                    FakeResponse(200, {})),
            sleep=slept.append)
        client.json("GET", "http://x")
        self.assertEqual(slept, [float(http.MAX_RETRY_AFTER)])

    def test_a_2xx_that_is_not_json_reports_the_status(self):
        # An Azure PAT that lost its scope answers 203 with a sign-in page.
        # json.loads then raised ValueError, which the error table reads as a
        # usage mistake, so a dead token reported a wrong command line.
        client = http.Http(opener=opener_returning(
            FakeResponse(203, b"<html>sign in</html>")))
        with self.assertRaises(http.HttpError) as cm:
            client.json("GET", "http://x")
        self.assertEqual(cm.exception.status, 203)
        self.assertIn("sign in", cm.exception.body)


class TestRedirectCredentials(unittest.TestCase):
    """The handler under the default opener, driven the way urllib drives it."""

    def following(self, before, after):
        request = urllib.request.Request(before)
        request.add_header("Authorization", "Basic secret")
        request.add_header("X-Figma-Token", "figd_secret")
        request.add_header("Cookie", "tenant.session.token=abc")
        request.add_header("Accept", "application/json")
        handler = http._StripAuthAcrossHosts()
        return handler.redirect_request(request, None, 302, "Found", {}, after)

    def test_a_hop_to_another_host_drops_every_credential(self):
        # The standard library copies every header but the two content headers
        # into the redirected request, so the token used to follow the hop. The
        # Jira attachment route answers 303 to a media host.
        out = self.following("https://globex.atlassian.net/a",
                             "https://api.media.atlassian.com/x")
        # Read the dict, not get_header, so a header under another spelling
        # cannot pass this test.
        self.assertEqual(out.headers, {"Accept": "application/json"})

    def test_a_hop_on_the_same_host_keeps_them(self):
        out = self.following("https://globex.atlassian.net/a",
                             "https://globex.atlassian.net/b")
        self.assertEqual(out.get_header("Authorization"), "Basic secret")
        self.assertEqual(out.get_header("Cookie"), "tenant.session.token=abc")

    def test_a_downgrade_to_http_counts_as_another_host(self):
        # Same name, no encryption. Sending the credential there is the same
        # mistake as sending it to a stranger.
        out = self.following("https://dev.azure.com/a", "http://dev.azure.com/a")
        self.assertIsNone(out.get_header("Authorization"))

    def test_the_default_opener_uses_the_handler(self):
        # A test that only drives the class would still pass if the opener were
        # never wired up.
        kinds = [type(h).__name__ for h in http._OPENER.handlers]
        self.assertIn("_StripAuthAcrossHosts", kinds)
        self.assertNotIn("HTTPRedirectHandler", kinds)
