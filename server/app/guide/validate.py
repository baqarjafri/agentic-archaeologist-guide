"""Check a sentence's citations against the pack and decide which other pieces to show."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.guide.stream import Sentence
from app.packs import Pack, object_of

_DIGIT = re.compile(r"\d")
_NAME = re.compile(r"\b(?!I\b)[A-Z]")


@dataclass(frozen=True)
class Checked:
    text: str
    citations: list[str]
    unknown: list[str]
    show: list[str]


def check(sentence: Sentence, pack: Pack, current_object: str, allowed: set[str] | None = None) -> Checked:
    """`allowed` is the set of passage IDs the model was shown this turn (context_ids); any other ID counts as unknown."""
    known_ids = allowed if allowed is not None else set(pack.passages)
    known = [c for c in sentence.citations if c in known_ids]
    unknown = [c for c in sentence.citations if c not in known_ids]
    show: list[str] = []
    for citation in known:
        object_id = object_of(citation)
        if object_id != current_object and object_id not in show:
            show.append(object_id)
    return Checked(sentence.text, known, unknown, show)


def _states_a_fact(text: str) -> bool:
    """A digit, or a capitalised word after the first, usually marks a date, a number or a name: a claim that needs a source."""
    rest = " ".join(text.split()[1:])
    return bool(_DIGIT.search(text) or _NAME.search(rest))


def keep(checked: Checked, strict: bool) -> tuple[bool, str]:
    """Drop sentences citing passages the model was not shown; in strict mode also uncited sentences that state a fact."""
    if checked.unknown:
        return False, "unknown citation " + ", ".join(checked.unknown)
    if strict and not checked.citations:
        long_statement = not checked.text.endswith("?") and len(checked.text.split()) > 8
        if long_statement or _states_a_fact(checked.text):
            return False, "uncited statement"
    return True, ""
