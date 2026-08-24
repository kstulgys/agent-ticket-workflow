import unittest

import helpers  # noqa: F401

from tk_lib.htmltext import html_to_text


class TestHtmlToText(unittest.TestCase):
    def test_table_rows_survive_as_pipe_separated_lines(self):
        html = ("<table><tr><th>Brand</th><th>Id</th></tr>"
                "<tr><td>Brookfield</td><td>GTM-42</td></tr>"
                "<tr><td>Hillcrest</td><td>GTM-43</td></tr></table>")
        self.assertEqual(html_to_text(html),
                         "Brand | Id\nBrookfield | GTM-42\nHillcrest | GTM-43")

    def test_break_and_paragraph_become_newlines(self):
        self.assertEqual(html_to_text("<p>one</p><p>two<br>three</p>"), "one\ntwo\nthree")

    def test_list_items_get_a_dash(self):
        self.assertEqual(html_to_text("<ul><li>a</li><li>b</li></ul>"), "- a\n- b")

    def test_entities_are_unescaped(self):
        self.assertEqual(html_to_text("<p>a &amp; b &lt;c&gt; &nbsp;d</p>"), "a & b <c> d")

    def test_script_and_style_bodies_are_dropped(self):
        html = "<style>p{color:red}</style><p>keep</p><script>alert(1)</script>"
        self.assertEqual(html_to_text(html), "keep")

    def test_blank_lines_collapse_to_one(self):
        self.assertEqual(html_to_text("<p>a</p><p></p><p></p><p>b</p>"), "a\n\nb")

    def test_none_and_empty_are_safe(self):
        self.assertEqual(html_to_text(None), "")
        self.assertEqual(html_to_text(""), "")

    def test_plain_text_passes_through(self):
        self.assertEqual(html_to_text("already plain"), "already plain")

    def test_a_cell_wrapped_in_a_block_tag_keeps_the_pair(self):
        html = ("<table><tr><td><p>Brand</p></td><td><p>Id</p></td></tr>"
                "<tr><td><div>Brookfield</div></td><td><div>GTM-42</div></td></tr>"
                "</table>")
        self.assertEqual(html_to_text(html), "Brand | Id\nBrookfield | GTM-42")

    def test_a_break_inside_a_cell_stays_on_the_row(self):
        html = "<table><tr><td>a<br>b</td><td>c</td></tr></table>"
        self.assertEqual(html_to_text(html), "a b | c")

    def test_a_nested_list_keeps_one_item_per_line(self):
        self.assertEqual(html_to_text("<ul><li>a<ul><li>b</li></ul></li></ul>"), "- a\n- b")

    # The tag strip used to delete the href, so a ticket that linked a design
    # as a smart card held no url in its text at all. shape.figma_urls reads
    # this text, so the link was lost before the scan ran.
    def test_a_link_keeps_its_target_beside_the_words(self):
        url = "https://www.figma.com/design/ABC123/Checkout?node-id=1204-8891"
        html = f'<p>Design: <a href="{url}">Checkout mobile</a></p>'
        self.assertEqual(html_to_text(html), f"Design: Checkout mobile ({url})")

    def test_a_link_whose_words_are_the_url_keeps_one_copy(self):
        url = "https://example.com/a"
        self.assertEqual(html_to_text(f'<p><a href="{url}">{url}</a></p>'), url)

    def test_a_link_inside_a_cell_keeps_the_row_shape(self):
        html = ('<table><tr><td><a href="https://e.com/a">spec</a></td>'
                "<td>ok</td></tr></table>")
        self.assertEqual(html_to_text(html), "spec (https://e.com/a) | ok")

    # Azure quotes an attribute with ", Jira sends ' for the same markup.
    def test_a_single_quoted_target_is_kept_too(self):
        html = "<p><a href='https://e.com/a'>spec</a></p>"
        self.assertEqual(html_to_text(html), "spec (https://e.com/a)")

    def test_a_link_with_no_target_adds_no_brackets(self):
        self.assertEqual(html_to_text('<p><a name="top">words</a></p>'), "words")