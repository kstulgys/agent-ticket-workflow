"""Read a figma frame: the picture and the exact values."""
import re
import urllib.parse

from . import http, secrets

API = "https://api.figma.com"
_KEY = re.compile(r"figma\.com/(?:design|proto|file)/([A-Za-z0-9]+)")
# Read the whole node-id value. A node id holds more than two halves: a layer
# inside an instance is I2445-15974;2445-15881, and the browser sends the
# semicolon encoded. A pattern that captures two halves stops at the first one,
# which is the parent instance. That parent is a real node, so the API answers
# the wrong frame. The class holds only what a node id holds, so a backtick or
# an asterisk that touches the link stays out. A jira and a github comment are
# both markdown, so a url inside backticks is ordinary input.
_NODE = re.compile(r"[?&]node-id=([A-Za-z0-9%:;-]+)")
# The url writes a hyphen where the API wants a colon. Only a hyphen between
# two digits is that separator, so a name like I2445 keeps its letter.
_HALVES = re.compile(r"(?<=\d)-(?=\d)")


def parse_url(url):
    """The file key, and the node id in the form the API wants.

    The url writes the node id with a hyphen. The API wants a colon. One rule
    covers all four shapes: the plain hyphen, the colon a hand-written link
    holds, the encoded colon, and the two halves of an instance layer.
    """
    key = _KEY.search(url or "")
    if not key:
        raise ValueError(f"no figma file key in {url}")
    node = _NODE.search(url)
    if not node:
        return key.group(1), None
    return key.group(1), _HALVES.sub(":", urllib.parse.unquote(node.group(1)))


def _target(url):
    """The key and the node, or a clear error.

    The image route needs an ids value. Without this guard the word None goes
    to the API as the node id, and the answer then names a node nobody asked
    for.
    """
    key, node = parse_url(url)
    if not node:
        raise ValueError(
            f"no node-id in {url}. Copy the link from the frame, or run "
            "--specs on this url to list the frames of the file.")
    return key, node


def _node_url(key, node):
    """A link to one node, in the form parse_url reads back.

    The frame list answers with these, so the run reads a sibling frame with
    the same verb and no hand-built url.
    """
    if not node:
        return None
    return f"https://www.figma.com/design/{key}/?node-id={node}"


def hexc(color, opacity=None):
    red, green, blue = [round(color.get(k, 0) * 255) for k in ("r", "g", "b")]
    alpha = color.get("a", 1) if opacity is None else opacity
    suffix = f" @{round(alpha, 3)}" if abs(alpha - 1) > 0.001 else ""
    return f"#{red:02X}{green:02X}{blue:02X}{suffix}"


class Figma:
    def __init__(self, values, client=None):
        self.token = secrets.get("FIGMA_TOKEN", values)
        self.http = client or http.Http()

    def _headers(self):
        return {"X-Figma-Token": self.token}

    def render(self, url, out_path, scale=2):
        key, node = _target(url)
        query = urllib.parse.urlencode({"ids": node, "format": "png", "scale": scale})
        found = self.http.json("GET", f"{API}/v1/images/{key}?{query}",
                               headers=self._headers())
        image = (found.get("images") or {}).get(node)
        if not image:
            # One shape on both paths. A caller that reads node or bytes on the
            # answer it expects must not raise on the other answer.
            return {"path": None, "node": node, "bytes": None,
                    "error": f"no render for node {node}"}
        _, payload, _ = self.http.raw("GET", image)
        with open(out_path, "wb") as fh:
            fh.write(payload)
        return {"path": out_path, "node": node, "bytes": len(payload), "error": None}

    def specs(self, url):
        """The spec rows of one node, or the frame list of a whole file.

        A ticket usually links one breakpoint, and the component holds a
        sibling frame for the other. A url with no node id therefore answers
        with the pages of the file and the frames on them, each with a url this
        same verb takes. So the run finds that sibling itself.
        """
        key, node = parse_url(url)
        if not node:
            return self._frames(key)
        query = urllib.parse.urlencode({"ids": node})
        found = self.http.json("GET", f"{API}/v1/files/{key}/nodes?{query}",
                               headers=self._headers())
        rows = []
        for entry in (found.get("nodes") or {}).values():
            # The API writes null for a node id the file does not hold, and a
            # stale link is enough to send one.
            _walk((entry or {}).get("document") or {}, rows)
        return rows

    def _frames(self, key):
        """One row per page of the file, and one per node on that page.

        depth=2 keeps the answer to the pages and their own children. depth=3
        on a real file is 1.6 MB and 1300 nodes, and a name is all this call
        needs.

        A page carries no url, because reading a page returns every node in it.
        Every other row carries one. A row of type SECTION or GROUP is a
        container, so read it by that url when the sibling frame sits inside
        it: its own rows name the frames it holds.
        """
        found = self.http.json("GET", f"{API}/v1/files/{key}?depth=2",
                               headers=self._headers())
        rows = []
        for page in ((found.get("document") or {}).get("children") or []):
            rows.append({"id": page.get("id"), "name": page.get("name"),
                         "type": page.get("type"), "page": None, "url": None})
            for node in page.get("children") or []:
                rows.append({"id": node.get("id"), "name": node.get("name"),
                             "type": node.get("type"), "page": page.get("name"),
                             "url": _node_url(key, node.get("id"))})
        return rows


def _walk(node, rows):
    if not node:
        return
    style = node.get("style") or {}
    box = node.get("absoluteBoundingBox") or {}
    fills = node.get("fills") or []
    strokes = node.get("strokes") or []
    rows.append({
        "id": node.get("id"), "name": node.get("name"), "type": node.get("type"),
        "size": _size(box),
        "radius": node.get("cornerRadius") or node.get("rectangleCornerRadii"),
        "fill": (hexc(fills[0]["color"], fills[0].get("opacity"))
                 if fills and fills[0].get("color") else None),
        "stroke": hexc(strokes[0]["color"]) if strokes and strokes[0].get("color") else None,
        "stroke_width": node.get("strokeWeight"),
        "padding": [node.get("paddingTop"), node.get("paddingRight"),
                    node.get("paddingBottom"), node.get("paddingLeft")],
        "gap": node.get("itemSpacing"), "layout": node.get("layoutMode"),
        "font": _font(style),
        "text": node.get("characters"), "opacity": node.get("opacity"),
    })
    for child in node.get("children") or []:
        _walk(child, rows)


def _num(value):
    """The number the frame holds. Keeps a half pixel, drops float noise.

    A designer draws a 13.5 px type size and a 1.5 px border. Rounding to a
    whole number turns both into a value the design does not hold, and the
    engineer then builds the wrong one. Figma also answers 471.99998474121094
    for a 472 px frame, so cut the number at two decimals first.
    """
    if value is None:
        return None
    number = round(float(value), 2)
    return int(number) if number.is_integer() else number


def _font(style):
    """The type spec as one line, from the parts the frame holds.

    A part the frame does not hold stays out. A zero in place of a line height
    reads as a real value, and the engineer then builds a line height of zero.
    """
    size = _num(style.get("fontSize"))
    if size is None:
        return None
    line = _num(style.get("lineHeightPx"))
    parts = [str(part) for part in
             (style.get("fontFamily"), style.get("fontWeight")) if part]
    parts.append(f"{size}/{line}" if line is not None else f"{size}")
    return " ".join(parts)


def _size(box):
    """Width by height. A half the box does not hold shows as a question mark.

    absoluteBoundingBox holds both values in every answer the API sends. The
    guard is here so one short box gives a row, and not a KeyError that ends
    the whole spec list.
    """
    width, height = _num(box.get("width")), _num(box.get("height"))
    if width is None and height is None:
        return None
    return f"{'?' if width is None else width}x{'?' if height is None else height}"
