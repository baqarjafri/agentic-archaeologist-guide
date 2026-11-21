"""Split museum record text into citable sentences."""
import re

from app.abbreviations import is_abbreviation

# A boundary is whitespace after . ! or ? (or after a full stop closed by a bracket or quote),
# followed by something that can start a sentence.
_BOUNDARY = re.compile(r"(?:(?<=[.!?])|(?<=\.[)\]’”'\"]))\s+(?=[A-Z0-9‘“'\"(\[])")
_LAST_WORD = re.compile(r"([A-Za-z]+)\.[)\]’”'\"]?$")


def split_sentences(text: str) -> list[str]:
    """Return the sentences of `text`, keeping abbreviations such as "Add. MS" intact."""
    flat = " ".join(text.split())
    sentences: list[str] = []
    start = 0
    for match in _BOUNDARY.finditer(flat):
        head = flat[start:match.start()]
        word = _LAST_WORD.search(head)
        last = word.group(1) if word else ""
        if is_abbreviation(last):  # abbreviations and initials (J. M. W. Turner) do not end sentences
            continue
        sentences.append(head.strip())
        start = match.end()
    tail = flat[start:].strip()
    if tail:
        sentences.append(tail)
    return [s for s in sentences if s]
