"""The normalised ticket shape. Every tracker returns this."""
import re

KEYS = ("slug", "tracker", "id", "key", "url", "type", "state", "assignee", "title",
        "description_text", "comments", "attachments", "links", "figma_urls",
        "parent", "children")
LIST_KEYS = ("comments", "attachments", "links", "figma_urls", "children")
SUMMARY_KEYS = ("slug", "tracker", "id", "key", "url", "type", "state", "title")

_FIGMA = re.compile(r"https://(?:www\.)?figma\.com/(?:design|proto|file)/[^\s\"'<>)\]]+")
# A url that ends a sentence takes the sentence punctuation with it. Task 12
# reads the node id from the url, and a full stop makes a node id the API does
# not know. A trailing question mark is safe to drop, because a figma url can
# only end in one when the query string is empty. The url character class above
# already stops at a bracket, so no bracket belongs in this set.
_SENTENCE_END = ".,;:!?"


def ticket(**fields):
    out = {key: fields.get(key) for key in KEYS}
    for key in LIST_KEYS:
        out[key] = list(fields.get(key) or [])
    return out


def summary(item):
    return {key: item.get(key) for key in SUMMARY_KEYS}


def figma_urls(*texts):
    """Collects every figma link, in first-seen order, with no repeat.

    The url stays as the ticket wrote it. The node id keeps its hyphen, because
    Task 12 owns the change to a colon.
    """
    found = []
    for text in texts:
        for url in _FIGMA.findall(text or ""):
            url = url.rstrip(_SENTENCE_END)
            if url not in found:
                found.append(url)
    return found
