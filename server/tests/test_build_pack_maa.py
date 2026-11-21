import json
from pathlib import Path

import pytest

from builder.build_pack_maa import make_fetch, make_fetch_image
from builder.curation import CurationError
from builder.records_maa import parse_maa

FIX = Path(__file__).parent / "fixtures" / "maa"
pytestmark = pytest.mark.skipif(not FIX.is_dir(), reason="saved MAA record pages are not in this checkout")


def get(record_id: int):
    return parse_maa(record_id, (FIX / f"rec_{record_id}.html").read_text(encoding="utf-8"))


PAGE = "<p>the famous Arbury Coffin, containing the bones of a woman</p>"


def curation(**entry):
    return {"objects": [{"id": "461657", "record_id": 461657, "accession": "1952.445 A", **entry}]}


def test_fetch_merges_records_quotes_and_frames(tmp_path):
    (tmp_path / "frames").mkdir()
    (tmp_path / "frames" / "461657_a.jpg").write_bytes(b"\xff\xd8\xffframe")
    fetch = make_fetch(tmp_path, curation(
        extra_records=[568926],
        web_quotes=[{"url": "https://maa.cam.ac.uk/about/galleries", "quote": "the famous Arbury Coffin, containing the bones of a woman"}],
        frames=["frames/461657_a.jpg"],
    ), get=get, get_page=lambda url: PAGE)
    record = fetch(461657)
    assert record.fields["ID Number"] == "461657"
    assert "about 5' 2\" tall" in record.description
    assert record.description.endswith("Museum website: the famous Arbury Coffin, containing the bones of a woman.")
    assert record.image_urls[-1] == (tmp_path / "frames" / "461657_a.jpg").as_uri()
    assert len(record.image_urls) == 2  # the record's one photo, then the frame


def test_a_wrong_accession_number_is_refused(tmp_path):
    fetch = make_fetch(tmp_path, curation(accession="1952.445 B"), get=get, get_page=lambda url: PAGE)
    with pytest.raises(CurationError, match="accession"):
        fetch(461657)


def test_a_quote_that_is_not_on_the_page_is_refused(tmp_path):
    fetch = make_fetch(tmp_path, curation(web_quotes=[{"url": "u", "quote": "inspired a famous novel"}]), get=get, get_page=lambda url: PAGE)
    with pytest.raises(CurationError, match="not found"):
        fetch(461657)


def test_fetch_image_reads_frames_from_disk_and_downloads_the_rest(tmp_path):
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"\xff\xd8\xffdisk")
    fetch_image = make_fetch_image(download=lambda url: b"\xff\xd8\xffweb")
    assert fetch_image(frame.as_uri()) == b"\xff\xd8\xffdisk"
    assert fetch_image("https://collections.maa.cam.ac.uk/media/x.png") == b"\xff\xd8\xffweb"


def test_a_curators_drop_list_leaves_admin_sentences_out(tmp_path):
    fetch = make_fetch(tmp_path, curation(drop=["Annual Report"]), get=get, get_page=lambda url: PAGE)
    assert "Annual Report" not in fetch(461657).description


def test_a_piece_can_opt_out_of_using_its_period_as_a_date(tmp_path):
    fetch = make_fetch(tmp_path, {"objects": [{"id": "470026", "record_id": 470026, "date_from_period": False}]},
                       get=get, get_page=lambda url: PAGE)
    assert fetch(470026).fields["Date"] == ""
    plain = make_fetch(tmp_path, {"objects": [{"id": "470026", "record_id": 470026}]}, get=get, get_page=lambda url: PAGE)
    assert plain(470026).fields["Date"] == "20th century"
