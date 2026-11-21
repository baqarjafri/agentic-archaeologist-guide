"""Words that end in a full stop without ending a sentence, shared by the pack builder and the live sentence stream."""

ABBREVIATIONS = frozenset({
    "St", "Mr", "Mrs", "Dr", "c", "ca", "no", "No", "p", "pp", "Add", "MS",
    "Fig", "fig", "vol", "Vol", "ed", "eds", "etc", "cf", "approx",
})


def is_abbreviation(word: str) -> bool:
    """An abbreviation, or a single-capital initial (J. M. W. Turner); the regnal numerals I, V and X still end sentences."""
    return word in ABBREVIATIONS or (len(word) == 1 and word.isupper() and word not in "IVX")
