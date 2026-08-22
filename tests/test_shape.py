import os
import tempfile
import unittest

import helpers  # noqa: F401

from tk_lib import shape, util


class TestShape(unittest.TestCase):
    def test_ticket_always_carries_every_key(self):
        item = shape.ticket(slug="northwind", id="59644")
        self.assertEqual(set(item), set(shape.KEYS))
        self.assertIsNone(item["title"])

    def test_list_fields_default_to_empty_lists(self):
        item = shape.ticket()
        for field in ("comments", "attachments", "links", "figma_urls", "children"):
            self.assertEqual(item[field], [])

    def test_summary_drops_the_heavy_fields(self):
        item = shape.ticket(slug="globex", id="1", key="DIST-1", title="x", state="To Do",
                            type="Bug", url="u", tracker="jira", comments=[{"text": "c"}])
        got = shape.summary(item)
        self.assertEqual(set(got),
                         {"slug", "tracker", "id", "key", "url", "type", "state", "title"})
        self.assertEqual(got["key"], "DIST-1")
        self.assertEqual(got["title"], "x")


class TestFigmaUrls(unittest.TestCase):
    def test_finds_design_proto_and_file_links(self):
        text = ("see https://www.figma.com/design/ABC123/Name?node-id=15114-38905 and "
                "https://figma.com/proto/ABC123/Name?node-id=14466-9472 plus "
                "https://www.figma.com/file/DEF456/Old")
        self.assertEqual(shape.figma_urls(text), [
            "https://www.figma.com/design/ABC123/Name?node-id=15114-38905",
            "https://figma.com/proto/ABC123/Name?node-id=14466-9472",
            "https://www.figma.com/file/DEF456/Old",
        ])

    def test_dedupes_across_several_texts_and_keeps_order(self):
        one = "https://www.figma.com/design/A/x?node-id=1-2"
        self.assertEqual(shape.figma_urls(one, None, one), [one])

    def test_reads_a_description_then_a_comment_in_first_seen_order(self):
        # The description url sorts after the comment url, so a sorted result
        # cannot pass this test by luck.
        first = "https://www.figma.com/proto/ZED/Later?node-id=15114-38905"
        second = "https://www.figma.com/design/ABC/Early?node-id=14466-9472"
        self.assertEqual(
            shape.figma_urls(f"description says {first}", None, f"comment adds {second}"),
            [first, second])

    def test_keeps_two_urls_that_differ_only_by_node_id(self):
        one = "https://www.figma.com/design/ABC/Name?node-id=15114-38905"
        two = "https://www.figma.com/design/ABC/Name?node-id=14466-9472"
        self.assertEqual(shape.figma_urls(f"first {one}", f"second {two}"), [one, two])

    def test_stops_at_a_closing_bracket_or_quote(self):
        url = "https://www.figma.com/design/A/x?node-id=1-2"
        self.assertEqual(shape.figma_urls(f'<a href="{url}">link</a>'), [url])
        self.assertEqual(shape.figma_urls(f"[design]({url})"), [url])

    def test_drops_sentence_punctuation_that_touches_the_url(self):
        url = "https://www.figma.com/design/A/x?node-id=1-2"
        for sentence in (f"see {url}.", f"{url}, and more", f"{url}; next",
                         f"the design is here {url}:", f"is this the right frame {url}?",
                         f"look at {url}!"):
            self.assertEqual(shape.figma_urls(sentence), [url])

    def test_drops_punctuation_when_a_bracket_also_touches_the_url(self):
        url = "https://www.figma.com/design/A/x?node-id=1-2"
        self.assertEqual(shape.figma_urls(f"(see {url}.)"), [url])
        self.assertEqual(shape.figma_urls(f"[{url},]"), [url])


class TestUtil(unittest.TestCase):
    def test_readback_ignores_trailing_whitespace_only(self):
        self.assertTrue(util.readback_ok("hello world\n", "hello world"))
        self.assertFalse(util.readback_ok("hello world", "hello  world"))

    def test_readback_catches_the_shell_escape_mangling(self):
        sent = chr(33) + "[shot](https://example.com/a.png)"
        stored = '__omp_shell("[shot](https://example.com/a.png)")'
        self.assertFalse(util.readback_ok(sent, stored))

    def test_readback_accepts_a_changed_line_ending(self):
        self.assertTrue(util.readback_ok("a\r\nb", "a\nb"))
        self.assertTrue(util.readback_ok("a\nb", "a\r\nb"))
        self.assertTrue(util.readback_ok("a\rb", "a\nb"))

    def test_readback_accepts_a_changed_blank_line_count(self):
        # A rendered comment can come back with one newline where we sent two.
        # A false failure there makes the caller post the comment again, and a
        # duplicate comment is the failure the read-back exists to prevent. No
        # comment means anything different because of its blank line count.
        self.assertTrue(util.readback_ok("a\n\nb", "a\nb"))
        self.assertTrue(util.readback_ok("a\nb", "a\n\nb"))
        self.assertTrue(util.readback_ok("a\n\n\nb", "a\nb"))
        self.assertTrue(util.readback_ok("a\r\n\r\nb", "a\nb"))

    def test_readback_still_catches_a_lost_or_changed_paragraph(self):
        self.assertFalse(util.readback_ok("a\n\nb", "a"))
        self.assertFalse(util.readback_ok("a\n\nb", "a\nb\nc"))
        self.assertFalse(util.readback_ok("a\n\nb", "a\nb!"))
        self.assertFalse(util.readback_ok("a\n\nb c", "a\nb  c"))

    def test_readback_still_catches_a_near_miss(self):
        self.assertFalse(util.readback_ok("hello world", "hello wor"))
        self.assertFalse(util.readback_ok("hello", "hello!"))
        self.assertFalse(util.readback_ok("a\nb", "a\n b"))

    def test_slugify_lowercases_and_limits_words(self):
        self.assertEqual(
            util.slugify("GTM hidden fields are missing from the payload", words=4),
            "gtm-hidden-fields-are")

    def test_slugify_drops_punctuation_and_collapses_dashes(self):
        self.assertEqual(util.slugify("Fix: the  form's label!"), "fix-the-form-s-label")

    def test_slugify_keeps_an_accented_word_whole(self):
        self.assertEqual(util.slugify("Financi\u00eble gegevens ontbreken"),
                         "financiele-gegevens-ontbreken")

    def test_slugify_spends_one_slot_on_an_accented_word(self):
        self.assertEqual(
            util.slugify("Financi\u00eble gegevens ontbreken op het formulier", words=3),
            "financiele-gegevens-ontbreken")

    def test_slugify_returns_an_empty_string_when_nothing_survives(self):
        self.assertEqual(util.slugify("!!! ??? ..."), "")
        self.assertEqual(util.slugify(""), "")
        self.assertEqual(util.slugify(None), "")

    def test_slugify_leaves_no_dash_at_either_end(self):
        self.assertEqual(util.slugify("  -- Fix the form -- "), "fix-the-form")

    def test_expand_fills_named_holes(self):
        self.assertEqual(util.expand("feature/{id}-{slug}", id="59644", slug="gtm"),
                         "feature/59644-gtm")

    def test_expand_leaves_an_unknown_hole_alone(self):
        self.assertEqual(util.expand("[{id}] {area} | {summary}", id="1"),
                         "[1] {area} | {summary}")

    def test_expand_never_rescans_a_substituted_value(self):
        self.assertEqual(util.expand("{title}", title="{id} stays", id="59644"),
                         "{id} stays")

    def test_expand_does_not_depend_on_argument_order(self):
        self.assertEqual(util.expand("{a}/{b}", a="{b}", b="x"), "{b}/x")
        self.assertEqual(util.expand("{a}/{b}", b="x", a="{b}"), "{b}/x")


class TestSafeName(unittest.TestCase):
    def test_a_plain_name_stays_whole(self):
        self.assertEqual(util.safe_name("shot.png"), "shot.png")

    def test_a_directory_part_is_dropped(self):
        self.assertEqual(util.safe_name("../../etc/passwd"), "passwd")
        self.assertEqual(util.safe_name("/tmp/absolute.png"), "absolute.png")
        self.assertEqual(util.safe_name("C:\\Users\\me\\shot.png"), "shot.png")

    def test_a_name_that_is_no_file_name_falls_back(self):
        for name in ("", "   ", ".", "..", None, "some/dir/"):
            self.assertEqual(util.safe_name(name), util.FALLBACK_NAME, repr(name))


class TestFreePath(unittest.TestCase):
    def test_a_free_name_keeps_its_own_path(self):
        target = self.enterContext(tempfile.TemporaryDirectory())
        self.assertEqual(util.free_path(target, "shot.png"),
                         os.path.join(target, "shot.png"))

    def test_a_taken_name_gets_a_number_before_the_extension(self):
        target = self.enterContext(tempfile.TemporaryDirectory())
        for expected in ("shot.png", "shot-1.png", "shot-2.png"):
            path = util.free_path(target, "shot.png")
            self.assertEqual(path, os.path.join(target, expected))
            with open(path, "wb") as fh:
                fh.write(b"x")
