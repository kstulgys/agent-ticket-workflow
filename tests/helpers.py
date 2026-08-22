import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))


class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None):
        self.status = status
        if isinstance(body, bytes):
            self._body = body
        elif isinstance(body, str):
            # A str body is text already. json.dumps would add two quote bytes,
            # which breaks a test that models a non-JSON error page.
            self._body = body.encode("utf-8")
        else:
            self._body = json.dumps(body).encode()
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeHttp:
    """Records requests and replays queued responses.

    json() and raw() ignore the response status on purpose. A test drives an
    error path by queueing a callable that raises. The callable raises the same
    error type the real adapter catches, so the adapter handles it. This file
    imports nothing from tk_lib, so the harness works before http.py exists.
    """

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def _next(self, method, url, body, headers):
        self.calls.append({"method": method, "url": url, "body": body,
                           "headers": headers or {}})
        if not self.responses:
            raise AssertionError(f"no queued response for {method} {url}")
        item = self.responses.pop(0)
        return item() if callable(item) else item

    def json(self, method, url, body=None, headers=None):
        response = self._next(method, url, body, headers)
        payload = response.read()
        return json.loads(payload) if payload.strip() else {}

    def raw(self, method, url, body=None, headers=None):
        response = self._next(method, url, body, headers)
        return response.status, response.read(), response.headers

    def assert_drained(self):
        """Fails when a queued response was never used."""
        if not self.responses:
            return
        last = self.calls[-1] if self.calls else None
        where = f"{last['method']} {last['url']}" if last else "no request made"
        raise AssertionError(
            f"{len(self.responses)} queued response(s) never used. "
            f"Last request: {where}")


def tmp_profile(config, root, notes="notes\n"):
    """Writes projects/<slug>/config.json under a root. Returns the root."""
    target = pathlib.Path(root, "projects", config["slug"])
    target.mkdir(parents=True, exist_ok=True)
    (target / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (target / "notes.md").write_text(notes, encoding="utf-8")
    return root
