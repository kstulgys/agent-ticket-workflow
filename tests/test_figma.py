import pathlib
import tempfile
import unittest

import helpers  # noqa: F401  its import puts scripts/ on sys.path
from helpers import FakeHttp, FakeResponse

from tk_lib import figma

VALUES = {"FIGMA_TOKEN": "figd_tokentokentoken"}
URL = "https://www.figma.com/design/auAKTjyOBHySKDWQPaoNJQ/Name?node-id=15114-38905"
KEY = "auAKTjyOBHySKDWQPaoNJQ"
# Pin the whole url. A substring match passes for a typo in the route, in the
# format, or in the scale, and every one of those sends back the wrong answer.
IMAGES_URL = (f"https://api.figma.com/v1/images/{KEY}"
              "?ids=15114%3A38905&format=png&scale=2")
NODES_URL = f"https://api.figma.com/v1/files/{KEY}/nodes?ids=15114%3A38905"
FILE_URL = "https://www.figma.com/file/KEY123/N"
FILE_TREE_URL = "https://api.figma.com/v1/files/KEY123?depth=2"


class TestParseUrl(unittest.TestCase):
    def test_a_design_link_gives_the_key_and_a_colon_node(self):
        self.assertEqual(figma.parse_url(URL),
                         ("auAKTjyOBHySKDWQPaoNJQ", "15114:38905"))

    def test_proto_and_file_links_carry_the_same_key(self):
        proto = "https://www.figma.com/proto/KEY123/N?node-id=14466-9472&t=x"
        self.assertEqual(figma.parse_url(proto), ("KEY123", "14466:9472"))
        self.assertEqual(figma.parse_url("https://www.figma.com/file/KEY123/N"),
                         ("KEY123", None))

    def test_a_url_without_a_key_raises(self):
        with self.assertRaises(ValueError):
            figma.parse_url("https://example.com/x")

    def test_a_node_id_that_already_holds_a_colon_survives(self):
        # A link copied from an API answer, or a hand-written one, writes the
        # colon. A parser that only knows the hyphen returns no node, and the
        # caller then reads the whole file instead of the frame.
        plain = "https://www.figma.com/design/KEY123/N?node-id=15114:38905"
        encoded = "https://www.figma.com/design/KEY123/N?node-id=15114%3A38905"
        self.assertEqual(figma.parse_url(plain), ("KEY123", "15114:38905"))
        self.assertEqual(figma.parse_url(encoded), ("KEY123", "15114:38905"))

    def test_an_instance_node_id_keeps_both_halves(self):
        # Figma writes a layer inside an instance as two halves joined by a
        # semicolon, encoded or raw. A parser that stops at the first half
        # names the parent instance. That parent is a real node, so the API
        # answers with the wrong frame and the run reports success.
        encoded = "https://www.figma.com/design/KEY123/N?node-id=I2445-15974%3B2445-15881"
        raw = "https://www.figma.com/design/KEY123/N?node-id=I2445-15974;2445-15881&t=x"
        self.assertEqual(figma.parse_url(encoded), ("KEY123", "I2445:15974;2445:15881"))
        self.assertEqual(figma.parse_url(raw), ("KEY123", "I2445:15974;2445:15881"))

    def test_markdown_around_the_link_stays_out_of_the_node_id(self):
        # shape.figma_urls stops at a quote and a bracket, and it strips
        # trailing sentence punctuation, but it keeps a backtick and an
        # asterisk. A jira and a github comment are both markdown, so a url in
        # backticks is ordinary input, not an edge.
        quoted = "`https://www.figma.com/design/KEY123/N?node-id=15114-38905`"
        bold = "**https://www.figma.com/design/KEY123/N?node-id=15114-38905**"
        self.assertEqual(figma.parse_url(quoted), ("KEY123", "15114:38905"))
        self.assertEqual(figma.parse_url(bold), ("KEY123", "15114:38905"))


class TestHex(unittest.TestCase):
    def test_converts_float_rgba_to_hex(self):
        self.assertEqual(figma.hexc({"r": 1, "g": 0, "b": 0, "a": 1}), "#FF0000")

    def test_notes_a_non_opaque_alpha(self):
        self.assertEqual(figma.hexc({"r": 0, "g": 0, "b": 0, "a": 0.5}), "#000000 @0.5")


class TestRenderAndSpecs(unittest.TestCase):
    def test_render_writes_the_png_and_sends_the_token_header(self):
        root = self.enterContext(tempfile.TemporaryDirectory())
        target = str(pathlib.Path(root, "frame.png"))
        fake = FakeHttp([FakeResponse(200, {"images": {"15114:38905": "https://s3/i.png"}}),
                         FakeResponse(200, b"\x89PNG")])
        got = figma.Figma(VALUES, fake).render(URL, target)
        self.assertEqual(got["path"], target)
        self.assertIsNone(got["error"])
        self.assertEqual(fake.calls[0]["url"], IMAGES_URL)
        self.assertEqual(fake.calls[1]["url"], "https://s3/i.png")
        self.assertEqual(fake.calls[0]["headers"]["X-Figma-Token"], VALUES["FIGMA_TOKEN"])
        # The image url is a signed link. It needs no token, and a token header
        # on that request makes the store refuse it.
        self.assertEqual(fake.calls[1]["headers"], {})
        with open(target, "rb") as fh:
            self.assertEqual(fh.read(), b"\x89PNG")
        fake.assert_drained()

    def test_render_without_an_image_reports_the_node(self):
        fake = FakeHttp([FakeResponse(200, {"images": {}})])
        got = figma.Figma(VALUES, fake).render(URL, "/tmp/none.png")
        self.assertIsNone(got["path"])
        self.assertIn("15114:38905", got["error"])
        # One shape on both paths. A caller that reads a key on the answer it
        # got must not raise on the other answer.
        self.assertEqual(got["node"], "15114:38905")
        self.assertIsNone(got["bytes"])
        self.assertEqual(fake.calls[0]["url"], IMAGES_URL)
        fake.assert_drained()

    def test_specs_flattens_the_subtree_into_rows(self):
        nodes = {"nodes": {"15114:38905": {"document": {
            "id": "15114:38905", "name": "Card", "type": "FRAME",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 472, "height": 100},
            "cornerRadius": 8,
            "fills": [{"color": {"r": 1, "g": 1, "b": 1, "a": 1}}],
            "paddingLeft": 16, "itemSpacing": 8, "layoutMode": "VERTICAL",
            "children": [{
                "id": "1:2", "name": "Title", "type": "TEXT",
                "characters": "Uitvoeringen",
                "style": {"fontFamily": "Navigo", "fontWeight": 700, "fontSize": 24,
                          "lineHeightPx": 32},
                "fills": [{"color": {"r": 0, "g": 0, "b": 0, "a": 1}}]}]}}}}
        fake = FakeHttp([FakeResponse(200, nodes)])
        rows = figma.Figma(VALUES, fake).specs(URL)
        self.assertEqual(rows[0]["name"], "Card")
        self.assertEqual(rows[0]["radius"], 8)
        self.assertEqual(rows[0]["fill"], "#FFFFFF")
        self.assertEqual(rows[0]["size"], "472x100")
        self.assertEqual(rows[1]["text"], "Uitvoeringen")
        self.assertEqual(rows[1]["font"], "Navigo 700 24/32")
        fake.assert_drained()

    def test_the_node_id_reaches_the_api_with_a_colon(self):
        fake = FakeHttp([FakeResponse(200, {"nodes": {}})])
        figma.Figma(VALUES, fake).specs(URL)
        self.assertEqual(fake.calls[0]["url"], NODES_URL)
        fake.assert_drained()

    def test_a_null_entry_in_the_nodes_map_gives_no_rows(self):
        # The API writes null for a node id the file does not hold, so a stale
        # link is enough to trigger it. Every other step in this chain already
        # guards, so a traceback here would be the only unguarded link.
        fake = FakeHttp([FakeResponse(200, {"nodes": {"15114:38905": None}})])
        self.assertEqual(figma.Figma(VALUES, fake).specs(URL), [])
        fake.assert_drained()

    def test_a_render_of_a_url_with_no_node_id_makes_no_request(self):
        # ids is required on the image route. Without the guard the string None
        # goes to the API, and the answer then names a node nobody wrote.
        fake = FakeHttp([])
        with self.assertRaises(ValueError) as caught:
            figma.Figma(VALUES, fake).render(FILE_URL, "/tmp/x.png")
        self.assertIn("node-id", str(caught.exception))
        self.assertEqual(fake.calls, [])

    def test_specs_on_a_file_url_lists_the_pages_and_their_frames(self):
        # A ticket links one breakpoint, and the sibling frame holds the other.
        # Reviewing one is how a desktop regression ships, so this answer names
        # the frames of the file, each with a url this same verb takes.
        tree = {"document": {"children": [
            {"id": "0:1", "name": "Uitvoeringen", "type": "CANVAS", "children": [
                {"id": "15114:38905", "name": "Mobile 375", "type": "FRAME"},
                {"id": "15114:38999", "name": "Desktop 1440", "type": "FRAME"},
                {"id": "7495:36266", "name": "Menu", "type": "SECTION"}]}]}}
        fake = FakeHttp([FakeResponse(200, tree)])
        rows = figma.Figma(VALUES, fake).specs(FILE_URL)
        self.assertEqual(fake.calls[0]["url"], FILE_TREE_URL)
        self.assertEqual(fake.calls[0]["headers"]["X-Figma-Token"], VALUES["FIGMA_TOKEN"])
        self.assertEqual([row["name"] for row in rows],
                         ["Uitvoeringen", "Mobile 375", "Desktop 1440", "Menu"])
        self.assertEqual(rows[2]["page"], "Uitvoeringen")
        self.assertIsNone(rows[0]["url"])
        # The url closes the loop: parse_url reads back the node this row names.
        self.assertEqual(figma.parse_url(rows[2]["url"]),
                         ("KEY123", "15114:38999"))
        # A real file puts the breakpoint frames inside a section, so a
        # container row carries a url as well. Reading it names the frames.
        self.assertEqual(figma.parse_url(rows[3]["url"]), ("KEY123", "7495:36266"))
        fake.assert_drained()

    def test_specs_keeps_a_half_pixel_and_drops_float_noise(self):
        nodes = {"nodes": {"15114:38905": {"document": {
            "id": "1:2", "name": "Label", "type": "TEXT", "characters": "Prijs",
            "absoluteBoundingBox": {"width": 471.5, "height": 471.99998474121094},
            "strokeWeight": 1.5,
            "style": {"fontFamily": "Navigo", "fontWeight": 400, "fontSize": 13.5,
                      "lineHeightPx": 20.0}}}}}
        fake = FakeHttp([FakeResponse(200, nodes)])
        rows = figma.Figma(VALUES, fake).specs(URL)
        self.assertEqual(rows[0]["size"], "471.5x472")
        self.assertEqual(rows[0]["font"], "Navigo 400 13.5/20")
        self.assertEqual(rows[0]["stroke_width"], 1.5)
        fake.assert_drained()

    def test_a_font_with_no_line_height_shows_the_size_alone(self):
        # A zero in place of a line height reads as a real value, and the
        # engineer then builds a line height of zero.
        nodes = {"nodes": {"1:2": {"document": {
            "id": "1:2", "name": "Label", "type": "TEXT",
            "style": {"fontFamily": "Navigo", "fontWeight": 400, "fontSize": 16}}}}}
        fake = FakeHttp([FakeResponse(200, nodes)])
        rows = figma.Figma(VALUES, fake).specs(URL)
        self.assertEqual(rows[0]["font"], "Navigo 400 16")
        fake.assert_drained()

    def test_a_box_with_one_value_still_gives_a_row(self):
        # A short box must not end the whole spec list with a KeyError.
        nodes = {"nodes": {"1:2": {"document": {
            "id": "1:2", "name": "Bar", "type": "RECTANGLE",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 472}}}}}
        fake = FakeHttp([FakeResponse(200, nodes)])
        rows = figma.Figma(VALUES, fake).specs(URL)
        self.assertEqual(rows[0]["size"], "472x?")
        fake.assert_drained()

    def test_a_font_with_no_family_name_starts_at_the_size(self):
        nodes = {"nodes": {"1:2": {"document": {
            "id": "1:2", "type": "TEXT",
            "style": {"fontSize": 16, "lineHeightPx": 20}}}}}
        fake = FakeHttp([FakeResponse(200, nodes)])
        rows = figma.Figma(VALUES, fake).specs(URL)
        self.assertEqual(rows[0]["font"], "16/20")
        fake.assert_drained()
