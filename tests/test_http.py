import io
import unittest
import urllib.error

import helpers  # noqa: F401
from helpers import FakeResponse

from tk_lib import http, secrets


def opener_returning(*items):
    queue = list(items)

    def opener(request):
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

        def opener(request):
            seen.append(request)
            return FakeResponse(200, {})

        http.Http(opener=opener).json("POST", "http://x", {"a": 1})
        self.assertEqual(seen[0].data, b'{"a": 1}')
        self.assertEqual(seen[0].get_header("Content-type"), "application/json")

    def test_a_bytes_body_passes_through_untouched(self):
        seen = []

        def opener(request):
            seen.append(request)
            return FakeResponse(200, {})

        http.Http(opener=opener).raw("POST", "http://x", b"\x89PNG",
                                     {"Content-Type": "application/octet-stream"})
        self.assertEqual(seen[0].data, b"\x89PNG")
        self.assertEqual(seen[0].get_header("Content-type"), "application/octet-stream")

    def test_a_lowercase_content_type_keeps_the_caller_value(self):
        seen = []

        def opener(request):
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
