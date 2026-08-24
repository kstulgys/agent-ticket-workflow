"""One request path for every provider."""
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from . import secrets

RETRY_STATUS = (429, 500, 502, 503, 504)
# A POST is not idempotent. Every comment this CLI writes is a POST, and a 500
# can arrive after the server stored the comment. The retry then stores a second
# comment, and the read-back cannot catch it, because the last comment still
# matches the text we sent. A 429 is safe to replay, because the server refused
# the request before it did any work. Keep this list at one status. Do not merge
# it back into RETRY_STATUS.
POST_RETRY_STATUS = (429,)
# Every request carries a deadline. urlopen with no timeout waits for ever, and
# tk runs as a subprocess under an agent, so a provider that accepts the
# connection and then sends nothing would hang the whole run with no output.
# Thirty seconds is longer than any call this tool makes, an attachment upload
# included.
TIMEOUT = 30
# A provider can ask for a wait of minutes. retries defaults to 2, so an
# unclamped value sleeps it twice with nothing on stdout. A capped wait can hit
# 429 again and fail, and a clear failure beats a silent stall.
MAX_RETRY_AFTER = 30
# A redirect to another host must not carry the credential. The standard
# library copies every header except the two content headers into the new
# request, so Authorization survives a hop off the vendor. The Jira attachment
# route answers 303 to a media host, and an Azure attachment url comes out of
# the work item payload, so neither target is a value this profile named.
_AUTH_HEADERS = ("authorization", "x-figma-token", "cookie")


class HttpError(Exception):
    def __init__(self, status, body):
        self.status = status
        self.body = secrets.scrub(body)[:500]
        super().__init__(f"HTTP {status}: {self.body}")


def _same_host(before, after):
    """True when scheme and host match, so a credential may travel."""
    one, two = urllib.parse.urlsplit(before), urllib.parse.urlsplit(after)
    return (one.scheme, one.netloc) == (two.scheme, two.netloc)


class _StripAuthAcrossHosts(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        following = super().redirect_request(req, fp, code, msg, headers, newurl)
        if following is None:
            return None
        if _same_host(req.full_url, following.full_url):
            return following
        for name in _AUTH_HEADERS:
            # Request stores a header name under key.capitalize(), both when
            # add_header sets it and when the constructor copies it across a
            # redirect. remove_header does not capitalise, so spell it here.
            following.remove_header(name.capitalize())
        return following


# One opener for the process. build_opener keeps the default handler set and
# replaces the redirect handler with the one above. Building it per request
# would drop connection reuse and add no safety.
_OPENER = urllib.request.build_opener(_StripAuthAcrossHosts())


class Http:
    def __init__(self, opener=None, sleep=None, retries=2, timeout=TIMEOUT):
        self._opener = opener or _OPENER.open
        self._sleep = sleep or time.sleep
        self._retries = retries
        self._timeout = timeout

    def raw(self, method, url, body=None, headers=None):
        headers = dict(headers or {})
        if body is None or isinstance(body, bytes):
            data = body
        else:
            data = json.dumps(body).encode()
            # A caller can spell the name in any case. setdefault sees only the
            # exact spelling, so it would add a second, wrong media type and
            # send application/json for a JSON patch or for an attachment.
            if _find_header(headers, "Content-Type") is None:
                headers["Content-Type"] = "application/json"
        for attempt in range(self._retries + 1):
            request = urllib.request.Request(url, data=data, method=method)
            for key, value in headers.items():
                request.add_header(key, value)
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    return response.status, response.read(), dict(response.headers)
            except urllib.error.HTTPError as error:
                payload = error.read() or b""
                if _may_retry(method, error.code) and attempt < self._retries:
                    self._sleep(_retry_after(error.headers))
                    continue
                raise HttpError(error.code, payload.decode("utf-8", "replace")) from None

    def json(self, method, url, body=None, headers=None):
        """The decoded body, or an HttpError naming the status.

        A 2xx is not proof of a JSON body. An Azure PAT that lost its scope
        answers 203 with a sign-in page, and json.loads then raises ValueError,
        which the error table reads as a usage mistake. So a body that does not
        decode is reported as what it is: an answer from the server.
        """
        status, payload, _ = self.raw(method, url, body, headers)
        if not payload.strip():
            return {}
        try:
            return json.loads(payload)
        except ValueError:
            raise HttpError(status, payload.decode("utf-8", "replace")) from None

    def text(self, method, url, body=None, headers=None):
        _, payload, _ = self.raw(method, url, body, headers)
        return payload.decode("utf-8", "replace")


def _may_retry(method, status):
    if str(method).upper() == "POST":
        return status in POST_RETRY_STATUS
    # GET, HEAD, PUT, PATCH, and DELETE reach the same end state on a replay.
    return status in RETRY_STATUS


def _find_header(headers, name):
    """Returns a header value in any case. Returns None when the name is absent.

    HTTP/2 sends every header name in lowercase, and Azure, Jira, and GitHub all
    serve HTTP/2. A plain dict lookup misses those names, so the server delay
    goes unread and every rate-limited retry waits the default time.
    """
    wanted = name.lower()
    for key, value in dict(headers or {}).items():
        if str(key).lower() == wanted:
            return value
    return None


def _retry_after(headers):
    value = _find_header(headers, "Retry-After")
    try:
        wait = float(1 if value is None else value)
    except (TypeError, ValueError):
        wait = 1.0
    return min(wait, MAX_RETRY_AFTER)


def basic(user, token):
    return "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()
