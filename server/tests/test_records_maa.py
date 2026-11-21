from pathlib import Path

import pytest

from builder.records import RecordError
from builder.sentences import split_sentences
from builder.records_maa import (
    compose_description, maa_fields, mostly_measurements, parse_maa, verify_quote,
)

FIX = Path(__file__).parent / "fixtures" / "maa"
pytestmark = pytest.mark.skipif(not FIX.is_dir(), reason="saved MAA record pages are not in this checkout")


def rec(record_id: int):
    return parse_maa(record_id, (FIX / f"rec_{record_id}.html").read_text(encoding="utf-8"))


def test_parse_reads_fields_events_and_photos():
    r = rec(487620)
    assert r.fields["Accession No"] == "1926.226"
    assert r.fields["Description"].startswith("House post carved in the form of an upstanding bear")
    assert any(e.sub == "Related Documents" and "grizzly bear" in e.text for e in r.events)
    assert len(r.image_urls) == 7 and all(u.startswith("https://collections.maa.cam.ac.uk/media/library_images/web/") for u in r.image_urls)
    assert r.url == "https://collections.maa.cam.ac.uk/objects/487620/"


def test_a_page_without_record_fields_fails_loudly():
    with pytest.raises(RecordError, match="no record fields"):
        parse_maa(1, "<html><body>Cookies</body></html>")


def test_measurement_sentences_are_recognised():
    assert mostly_measurements("Extern. length 6' 11.5\" int. length 6' 2\" extern. width at head 2' 5\"")
    assert not mostly_measurements("The coffin contained the body of a woman about 5' 2\" tall.")


def test_the_description_keeps_story_text_and_drops_references_conservation_and_repeats():
    text = compose_description([rec(495875)], [])
    assert "folds almost flat to pack for travel" in text  # from the display label
    assert "riveted tightly together" in text  # from the physical description
    assert "Surface Clean" not in text  # conservation
    assert text.count("Suit of armour made of lacquered iron") <= 1


def test_a_display_event_keeps_its_dates_and_label_and_drops_the_label_heading_and_notes():
    text = compose_description([rec(555823)], [])
    assert "On display on the Asia plinth in the Maudslay Hall, from May 2012." in text
    assert "He is one of the demon soldiers in the army of Ravana" in text
    assert "Protective Demon." not in text
    assert "Cf. Photograph" not in text


def test_extra_records_add_their_story_without_repeating_and_without_measurements():
    text = compose_description([rec(461657), rec(568926), rec(568925)], [])
    assert "The skeleton of a woman about 5' 2\" tall, found in the coffin." in text
    assert "gnawed" in text
    assert "Extern. length" not in text
    assert "Fell, Clare" not in text  # references are skipped


def test_cultural_affiliation_becomes_a_sentence():
    text = compose_description([rec(487620)], [])
    assert "Cultural affiliation: Wuikinuxv, Oowekeeno, Rivers Inlet, Northwest Coast." in text


def test_web_quotes_are_appended_with_their_label():
    text = compose_description([rec(470026)], ["Museum website: the famous kayak."])
    assert text.endswith("Museum website: the famous kayak.")


def test_fields_map_to_the_builders_names():
    f = maa_fields(rec(461657), "461657")
    assert f["ID Number"] == "461657"
    assert f["Accession No"] == "1952.445 A"
    assert f["Date"] == "Roman"
    assert f["Place Associated"] == "Arbury, Cambridge, Cambridgeshire"
    assert f["Materials"] == "Stone, Barnack Rag"


def test_a_quote_must_appear_word_for_word_on_the_page():
    page = "<p>the famous <b>Arbury Coffin</b> ,\n containing the bones</p>"
    assert verify_quote("the famous Arbury Coffin , containing the bones", page)
    assert not verify_quote("the famous Arbury coffin containing bones", page)


def test_texts_from_different_fields_never_run_together():
    sentences = split_sentences(compose_description([rec(487620)], []))
    assert "House post carved in the form of an upstanding bear with outstretched paws and an open toothy mouth." in sentences
    assert any(s.startswith("The figure is known informally in the Museum as 'Hector'") for s in sentences)


def test_catalogue_line_breaks_become_sentence_breaks():
    sentences = split_sentences(compose_description([rec(487620)], []))
    assert "It was one of a pair of house poles." in sentences
    assert "The other was sent to the Royal Ontario Museum in Toronto." in sentences


def test_a_curator_can_drop_admin_sentences():
    text = compose_description([rec(470026)], [], drop=["Stored with Greenland material"])
    assert "Greenland storage binder" not in text
    assert "stored upside down on a rack" in text
