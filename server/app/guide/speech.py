"""Prepare caption text for the voice: regnal numbers, date ranges, optional respellings."""
from __future__ import annotations

import re
import unicodedata

_ORDINALS = ["", "First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth", "Tenth",
             "Eleventh", "Twelfth", "Thirteenth", "Fourteenth", "Fifteenth", "Sixteenth", "Seventeenth",
             "Eighteenth", "Nineteenth", "Twentieth"]
_NUMERALS = {"II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11,
             "XII": 12, "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20}
# Words a numeral can follow without naming a ruler ("World War II", "Type IV"). "I" is left out: it is usually the pronoun.
_NOT_RULERS = frozenset({"War", "Type", "Part", "Phase", "Class", "Grade", "Mark", "Act", "Volume", "Chapter",
                         "Book", "Room", "Gallery", "Level", "Stage", "Dynasty", "Period",
                         "Section", "Appendix", "Figure", "Plate", "Table", "Case"})
_REGNAL_RE = re.compile(r"\b([A-Z][a-z]+) (" + "|".join(sorted(_NUMERALS, key=len, reverse=True)) + r")\b")
_ORDINAL_RANGE_RE = re.compile(r"\b(\d+(?:st|nd|rd|th))\s*[–-]\s*(\d+(?:st|nd|rd|th))\b")
_RANGE_RE = re.compile(r"(?<![\d–-])(\d{1,4})\s*[–-]\s*(\d{1,4})(?![\d–-])")  # not inside a longer chain, such as a phone number


def _regnal(m: re.Match) -> str:
    name, numeral = m.group(1), m.group(2)
    return m.group(0) if name in _NOT_RULERS else f"{name} the {_ORDINALS[_NUMERALS[numeral]]}"


def _respell(text: str, pronunciations: dict[str, str]) -> str:
    """Replace whole words in one pass, longest first, ignoring case and how accents are encoded."""
    spoken = {unicodedata.normalize("NFC", k).lower(): v for k, v in pronunciations.items() if k.strip()}
    if not spoken:
        return text
    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(spoken, key=len, reverse=True)) + r")\b",
                         re.IGNORECASE)
    return pattern.sub(lambda m: spoken[m.group(1).lower()], text)


def speech_text(text: str, pronunciations: dict[str, str] | None = None, respell: bool = False) -> str:
    out = unicodedata.normalize("NFC", text)
    out = _REGNAL_RE.sub(_regnal, out)
    out = _ORDINAL_RANGE_RE.sub(r"\1 to \2", out)
    out = _RANGE_RE.sub(r"\1 to \2", out)
    if respell and pronunciations:
        out = _respell(out, pronunciations)
    return out
