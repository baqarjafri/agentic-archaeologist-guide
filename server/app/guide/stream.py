"""Turn the language model's streamed text into whole sentences with their citations."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.abbreviations import is_abbreviation

_ID = re.compile(r"\d+(?:\.\d+)*#[A-Za-z0-9_]+")  # a passage ID, such as 13.181#p6
_GROUP = re.compile(r"[\[(【]([^\[\]()【】]*)[\])】]")  # one bracketed group, in [], () or 【】
_STRAY = re.compile(r"[\[\]【】*]")
_TRAILING_OPEN = re.compile(r"[\[【]([^\[\]【】]{0,60})$")  # a group cut off before its closing bracket
_CLOSERS = "\"'’”)"
_OPENERS = "\"'‘“("
_ENDS = ".!?…"
_MAX_OPEN = 60  # a "[" left open this long is not a citation, so it stops holding the stream back


@dataclass(frozen=True)
class Sentence:
    text: str
    citations: list[str] = field(default_factory=list)


def to_sentence(raw: str) -> Sentence:
    """Split one sentence into its spoken text and its passage IDs; no ID or bracket is left in the text.

    A group that looks like a citation but holds no valid ID ("[13.181 #p8]", a cut-off "[13.18") is kept as an
    attempted citation, so the check drops the sentence rather than letting the voice read the numbers.
    """
    ids: list[str] = []

    def attempted(content: str) -> None:
        content = content.strip()
        if content and content not in ids:
            ids.append(content)

    def take(match: re.Match) -> str:
        content = match.group(1)
        found = _ID.findall(content)
        if found:
            ids.extend(i for i in found if i not in ids)
            return " "
        if "#" in content or (match.group(0)[0] != "(" and re.fullmatch(r"[\d.\s]+", content)):
            attempted(content)
            return " "
        # not a citation: keep a round-bracket aside as written, and the words of any other group
        return match.group(0) if match.group(0)[0] == "(" else f" {content} "

    text = _GROUP.sub(take, raw)
    trailing = _TRAILING_OPEN.search(text)
    if trailing:
        found = _ID.findall(trailing.group(1))
        if found:
            ids.extend(i for i in found if i not in ids)
        else:
            attempted(trailing.group(1))
        text = text[:trailing.start()]
    ids.extend(i for i in _ID.findall(text) if i not in ids)  # an ID written without brackets
    text = _STRAY.sub(" ", _ID.sub(" ", text))
    text = " ".join(text.split())
    text = re.sub(r"\s+([.,!?;:…])", r"\1", text)
    return Sentence(text, ids)


def _last_word(b: str, end: int) -> str:
    """The ASCII word just before `end`, found by walking back a few characters rather than searching the whole buffer."""
    start = end
    while start > 0 and end - start < 12 and b[start - 1].isascii() and b[start - 1].isalpha():
        start -= 1
    return b[start:end]


def _after_citations(b: str, k: int) -> int | None:
    """Index just after a run of [..][..] groups starting at k, or None if more may still arrive."""
    pos = k
    while True:
        start = pos
        close = b.find("]", pos, start + _MAX_OPEN + 1)  # a group's "]" must come within _MAX_OPEN characters of its "["
        if close == -1:
            return start if len(b) - start > _MAX_OPEN else None  # a "[" left open this long is not a citation
        pos = close + 1
        nxt = pos
        while nxt < len(b) and b[nxt].isspace():
            nxt += 1
        if nxt >= len(b):
            return None
        if b[nxt] != "[":
            return pos
        pos = nxt


class SentenceStream:
    def __init__(self) -> None:
        self._buf = ""

    def feed(self, delta: str) -> list[Sentence]:
        self._buf += delta
        return self._drain(final=False)

    def close(self) -> list[Sentence]:
        return self._drain(final=True)

    def _drain(self, final: bool) -> list[Sentence]:
        out: list[Sentence] = []
        while (cut := self._find_cut()) is not None:
            raw, self._buf = self._buf[:cut], self._buf[cut:]
            sentence = to_sentence(raw)
            if sentence.text:
                out.append(sentence)
        if final:
            sentence = to_sentence(self._buf)
            self._buf = ""
            if sentence.text:
                out.append(sentence)
        return out

    def _find_cut(self) -> int | None:
        b = self._buf
        depth, opened = 0, 0
        for i, ch in enumerate(b):
            if ch == "[":
                if depth == 0:
                    opened = i
                depth += 1
                continue
            if ch == "]":
                depth = max(0, depth - 1)
                if depth == 0:
                    j = i + 1
                    while j < len(b) and b[j].isspace():
                        j += 1
                    if j >= len(b):
                        return None  # the next character decides whether a sentence ends here
                    if j > i + 1 and b[j].isupper():
                        return i + 1  # a citation run with no full stop before it still ends its sentence
                continue
            if depth and i - opened > _MAX_OPEN:
                depth = 0  # a "[" left open this long is not a citation, so stop waiting for its "]"
            if ch in _ENDS and depth == 0:
                if ch == "." and is_abbreviation(_last_word(b, i)):
                    continue
                j = i + 1
                while j < len(b) and b[j] in _CLOSERS:
                    j += 1
                k = j
                while k < len(b) and b[k].isspace():
                    k += 1
                if k >= len(b):
                    return None
                if b[k] == "[":
                    return _after_citations(b, k)
                if b[k].isupper() or b[k] in _OPENERS or (b[k].isdigit() and k > j):
                    return j
        return None
