from builder.sentences import split_sentences


def test_splits_plain_sentences():
    assert split_sentences("One fact. Two facts! Three?") == ["One fact.", "Two facts!", "Three?"]


def test_keeps_quoted_names_together():
    text = "The name Sekhmet means ‘She who is Powerful’ or 'Powerful Woman'. She was the goddess of fire."
    assert split_sentences(text) == [
        "The name Sekhmet means ‘She who is Powerful’ or 'Powerful Woman'.",
        "She was the goddess of fire.",
    ]


def test_does_not_split_abbreviations_or_page_references():
    text = "Owned by Horace Walpole (sale catalogue 1842, p.137, no.83). Drawn in 1792 (see Add. MS.5841.149, p.151.)"
    assert split_sentences(text) == [
        "Owned by Horace Walpole (sale catalogue 1842, p.137, no.83).",
        "Drawn in 1792 (see Add. MS.5841.149, p.151.)",
    ]


def test_roman_numerals_end_sentences():
    text = "It was recognised by Pope Alexander III. His canonisation followed."
    assert split_sentences(text) == ["It was recognised by Pope Alexander III.", "His canonisation followed."]


def test_decimal_numbers_do_not_split():
    assert split_sentences("It weighs 2.5 kg. It is small.") == ["It weighs 2.5 kg.", "It is small."]


def test_collapses_whitespace_and_ignores_empty_input():
    assert split_sentences("  A  first.\n\nSecond   one. ") == ["A first.", "Second one."]
    assert split_sentences("   ") == []


def test_full_stop_inside_brackets_or_quotes_ends_sentence():
    text = ("Drawn in 1792 (see Add. MS.5841.149, p.151.) It was sold in 1842. "
            "The inscription reads ‘Pray for me.’ It is in Latin.")
    assert split_sentences(text) == [
        "Drawn in 1792 (see Add. MS.5841.149, p.151.)",
        "It was sold in 1842.",
        "The inscription reads ‘Pray for me.’",
        "It is in Latin.",
    ]


def test_initials_do_not_split_but_regnal_numerals_do():
    assert split_sentences("Painted by J. M. W. Turner. It hangs here.") == ["Painted by J. M. W. Turner.", "It hangs here."]
    assert split_sentences("It was made for Henry V. It is gilded.") == ["It was made for Henry V.", "It is gilded."]
