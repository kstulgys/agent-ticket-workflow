"""Rendered HTML to readable text. Table rows keep their shape."""
import html as html_module
import re

_DROP = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)
# A link keeps its target in the href, and the tag strip below deletes it. A
# ticket that links a design as a smart card then holds no url in its text, and
# shape.figma_urls, which reads this text, finds nothing. So write the target
# beside the words first.
_ANCHOR = re.compile(r"(?is)<a\b[^>]*\bhref=([\"'])(.*?)\1[^>]*>(.*?)</a>")
_SPAN = re.compile(r"<t[dh]\b[^>]*>.*?</t[dh]>", re.S | re.I)
_INNER = re.compile(r"(?i)</?(p|div|br|h[1-6])\b[^>]*>")
_CELL = re.compile(r"(?i)</t[dh]>")
_ROW = re.compile(r"(?i)</tr>")
_BREAK = re.compile(r"(?i)<br\s*/?>")
_ITEM = re.compile(r"(?i)<li\b[^>]*>")
_BLOCK = re.compile(r"(?i)</(p|div|ul|ol|h[1-6]|tr|table)>")
_TAG = re.compile(r"<[^>]+>")


def _anchor(match):
    """The words, then the target in brackets.

    A target already inside the words stays once. Azure auto-links a pasted
    url, so there the words are the url itself. A second copy would read as two
    links to a person, and as one repeat to the scanner.
    """
    href, inner = match.group(2).strip(), match.group(3)
    if not href or href in inner:
        return inner
    return f"{inner} ({href})"


def html_to_text(html):
    if not html:
        return ""
    text = _DROP.sub("", html)
    text = _ANCHOR.sub(_anchor, text)
    # The Azure Boards editor wraps the text of a cell in <div> or <p>. A block
    # end becomes a newline later, which splits the cell from its pair. So
    # flatten a block boundary inside a cell to a space first. List tags stay
    # out of this step. A list in a cell is rare, and if one comes the row
    # splits but the text stays whole.
    text = _SPAN.sub(lambda m: _INNER.sub(" ", m.group(0)), text)
    text = _CELL.sub(" | ", text)
    text = _ROW.sub("\n", text)
    text = _BREAK.sub("\n", text)
    # A new line before the item keeps a nested item off the line above it.
    text = _ITEM.sub("\n- ", text)
    text = _BLOCK.sub("\n", text)
    text = _TAG.sub("", text)
    text = html_module.unescape(text).replace("\xa0", " ")
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line.endswith("|"):
            line = line[:-1].strip()
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
