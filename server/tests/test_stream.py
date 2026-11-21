from app.guide.speech import speech_text
from app.guide.stream import SentenceStream, to_sentence
from app.guide.validate import check, keep
from app.packs import load_pack


def feed_all(chunks):
    stream = SentenceStream()
    out = []
    for chunk in chunks:
        out += stream.feed(chunk)
    return out + stream.close()


def test_sentences_with_trailing_citations():
    out = feed_all(["She was a goddess of fire. [13.181#p6] Her name means ",
                    "power. [13.181#p5][13.181#p1] Look closely."])
    assert [(x.text, x.citations) for x in out] == [
        ("She was a goddess of fire.", ["13.181#p6"]),
        ("Her name means power.", ["13.181#p5", "13.181#p1"]),
        ("Look closely.", []),
    ]


def test_waits_for_citations_split_across_chunks():
    stream = SentenceStream()
    assert stream.feed("She was fierce. [13.18") == []
    assert stream.feed("1#p8]") == []
    out = stream.feed(" Next sentence")
    assert [(x.text, x.citations) for x in out] == [("She was fierce.", ["13.181#p8"])]
    assert [x.text for x in stream.close()] == ["Next sentence"]


def test_citation_before_the_full_stop_with_a_comma_list():
    out = feed_all(["Both were protectors [13.181#p8, 28.37#p1]. Done."])
    assert out[0].text == "Both were protectors."
    assert out[0].citations == ["13.181#p8", "28.37#p1"]


def test_decimals_and_lowercase_words_do_not_split():
    out = feed_all(["It weighs 2.5 kg and dates to c. 1200. Then it moved."])
    assert [x.text for x in out] == ["It weighs 2.5 kg and dates to c. 1200.", "Then it moved."]


def test_closing_quotes_and_questions():
    out = feed_all(["She was called ‘She who is Powerful’. [13.181#p5] Can you see the slot?"])
    assert out[0].text == "She was called ‘She who is Powerful’."
    assert out[1].text == "Can you see the slot?"


def test_check_marks_unknown_ids_and_other_pieces(test_pack):
    pack = load_pack(test_pack)
    linked = check(to_sentence("Like Alpha, Beta guarded. [1.1#p2][2.2#p1]"), pack, "2.2")
    assert (linked.citations, linked.show, linked.unknown) == (["1.1#p2", "2.2#p1"], ["1.1"], [])
    invented = check(to_sentence("Invented. [1.1#p99]"), pack, "1.1")
    assert invented.unknown == ["1.1#p99"]
    assert keep(invented, strict=False) == (False, "unknown citation 1.1#p99")


def test_a_real_passage_the_model_was_not_shown_counts_as_unknown(test_pack):
    pack = load_pack(test_pack)
    guessed = check(to_sentence("Guessed. [1.1#p3]"), pack, "2.2", allowed={"2.2#p1", "1.1#p2"})
    assert guessed.unknown == ["1.1#p3"] and guessed.citations == []


def test_strict_mode_drops_long_uncited_statements_but_not_questions(test_pack):
    pack = load_pack(test_pack)
    claim = check(to_sentence("This piece was made by a famous sculptor in the great city long ago."), pack, "1.1")
    assert keep(claim, strict=False) == (True, "")
    assert keep(claim, strict=True)[0] is False
    question = check(to_sentence("Would you like to hear how it came here, in the end, after all?"), pack, "1.1")
    assert keep(question, strict=True) == (True, "")


def test_speech_text_reads_regnal_numbers_ranges_and_respellings():
    assert speech_text("Made for Amenhotep III, about 1390–1352 BC.") == "Made for Amenhotep the Third, about 1390 to 1352 BC."
    assert speech_text("Sekhmet stood here.", {"Sekhmet": "Sek-met"}, respell=True) == "Sek-met stood here."
    assert speech_text("Sekhmet stood here.", {"Sekhmet": "Sek-met"}, respell=False) == "Sekhmet stood here."


def test_any_chunking_gives_the_same_sentences():
    reply = ("Look at her face. [13.181#p1] Her name means power, she was said to protect the pharaoh. "
             "[13.181#p5][13.181#p8] Can you see the slot? Like the lion, she guarded. [13.181#p8][28.37#p1]")
    whole = [(s.text, s.citations) for s in feed_all([reply])]
    by_char = [(s.text, s.citations) for s in feed_all(list(reply))]
    assert whole == by_char and len(whole) == 4


def test_a_finished_sentence_is_released_by_the_next_letter():
    stream = SentenceStream()
    assert [s.text for s in stream.feed("She was fierce. [13.181#p8] H")] == ["She was fierce."]


def test_abbreviations_and_initials_do_not_split():
    out = feed_all(["Saint Thomas, or St. Thomas Becket, was killed. [26.6#p19] W. Cole drew it in 1792. [26.6#p26]"])
    assert [x.text for x in out] == ["Saint Thomas, or St. Thomas Becket, was killed.", "W. Cole drew it in 1792."]


def test_malformed_citations_never_reach_the_voice():
    out = feed_all(["She was fierce (13.181#p8). Her name 【13.181#p5】 means power. It was lost [[13.181#p9]]. Cut off [13.181#p"])
    assert all("#" not in x.text and "[" not in x.text and "【" not in x.text for x in out)
    assert out[0].citations == ["13.181#p8"]


def test_a_citation_without_a_full_stop_still_ends_its_sentence():
    out = feed_all(["She was fierce [13.181#p8] Her name means power. [13.181#p5]"])
    assert [(x.text, x.citations) for x in out] == [("She was fierce", ["13.181#p8"]), ("Her name means power.", ["13.181#p5"])]


def test_an_unclosed_bracket_does_not_hold_back_the_story():
    stream = SentenceStream()
    out = stream.feed("It was [lost for a very long time in the stores of a castle in the north of England. Then it was found. Now")
    assert out and out[0].text.startswith("It was")


def test_a_sentence_with_one_unknown_id_is_dropped_whole(test_pack):
    pack = load_pack(test_pack)
    mixed = check(to_sentence("Partly real. [1.1#p1][1.1#p99]"), pack, "1.1")
    assert keep(mixed, strict=False)[0] is False


def test_strict_mode_drops_short_uncited_facts(test_pack):
    pack = load_pack(test_pack)
    for text in ("It was made by Ur-Nammu.", "It dates to 1390 BC.", "Did you know Ur-Nammu carved it?"):
        assert keep(check(to_sentence(text), pack, "1.1"), strict=True)[0] is False
    assert keep(check(to_sentence("Shall we look closer?"), pack, "1.1"), strict=True)[0] is True


def test_speech_text_reads_rulers_but_not_wars_or_phone_numbers():
    assert speech_text("Henry V met Louis XIV.") == "Henry the Fifth met Louis the Fourteenth."
    assert speech_text("After World War II, in the 1st-2nd century.") == "After World War II, in the 1st to 2nd century."
    assert speech_text("Call 0141-287-2550.") == "Call 0141-287-2550."


def test_respellings_cover_accents_case_possessives_and_backslashes():
    p = {"champlevé": "shom-pluh-vay", "Piranesi": "Pee-ra-nay-zee", "Sekhmet": "Sek\\1met"}
    assert speech_text("Champlevé enamel, Piranesi's design.", p, respell=True) == "shom-pluh-vay enamel, Pee-ra-nay-zee's design."
    assert speech_text("Sekhmet.", p, respell=True) == "Sek\\1met."


def test_truncated_or_spaced_ids_are_never_spoken(test_pack):
    pack = load_pack(test_pack)
    for reply in ("Her name means power. [1.1#", "Her name means power. [1.1", "Her name means power [1.1 #p1]."):
        sentences = feed_all([reply])
        assert all("1.1" not in s.text for s in sentences)
        assert [s for s in sentences if keep(check(s, pack, "1.1"), strict=False)[0]] == []


def test_a_long_uncut_reply_stays_fast():
    import time
    stream, text = SentenceStream(), "St. " * 900
    start = time.perf_counter()
    for i in range(0, len(text), 7):
        stream.feed(text[i:i + 7])
    assert time.perf_counter() - start < 3


def test_random_replies_cut_the_same_whole_or_by_character():
    import random
    rng = random.Random(7)
    pieces = ["She was fierce.", " [1.1#p1]", " [1.1#p2", "]", " Then", " it", " moved.", " [[1.1#p3]]", " (aside)",
              " St.", " W.", " 2.5", " …", " [lost", "?", " Yes."]
    for _ in range(200):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(3, 30)))
        whole = [(s.text, s.citations) for s in feed_all([text])]
        assert whole == [(s.text, s.citations) for s in feed_all(list(text))], text


def test_a_year_in_round_brackets_is_kept_as_written(test_pack):
    pack = load_pack(test_pack)
    [sentence] = feed_all(["Alpha was carved (1170). [1.1#p1]"])
    assert sentence.text == "Alpha was carved (1170)." and sentence.citations == ["1.1#p1"]
    assert keep(check(sentence, pack, "1.1"), strict=False) == (True, "")
