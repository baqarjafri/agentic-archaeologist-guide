import io
import json

import pytest
from PIL import Image

from builder.build_pack import build_pack, unused_files
from builder.curation import CurationError
from builder.records import RecordData


def fake_image(url: str) -> bytes:
    """A small JPEG whose colour depends on the URL, so a mix-up between photos shows."""
    out = io.BytesIO()
    Image.new("RGB", (64, 48), (sum(url.encode()) % 256, 80, 40)).save(out, format="JPEG")
    return out.getvalue()


def curation() -> dict:
    return {
        "id": "test-pack", "version": "0.0.1", "title": "Test", "institution": "Test Museum",
        "credit": "Test credit", "language": "en-GB",
        "objects": [
            {"id": "1.1", "record_id": 101, "title": "Alpha", "meta": ["Here · then", "Stone · 1.1"],
             "images": {"reference": [1], "test": [2], "display": 1, "synthetic_test": False},
             "story": [{"title": "First", "anchors": ["Alpha was carved", "#place"]}],
             "pronunciations": {"Alpha": "Al-fa"}},
            {"id": "2.2", "record_id": 202, "title": "Beta", "meta": ["There · now", "Clay · 2.2"],
             "images": {"reference": [1], "test": [], "display": 1, "synthetic_test": True},
             "story": [{"title": "Only", "anchors": ["Beta guarded"]}]},
        ],
        "relations": [{"a": "1.1", "b": "2.2", "theme": "Guardians",
                       "anchors": {"1.1": ["protect the king"], "2.2": ["Beta guarded"]}}],
        "distractors": [{"id": "9.9", "record_id": 909, "title": "Gamma", "images": [1]}],
        "recognition": {"model": "dinov2-small-int8", "threshold": 0.45, "margin": 0.03},
    }


RECORDS = {
    101: RecordData(101, "https://x/101", {"ID Number": "1.1",
                                           "Description": "Alpha was carved in stone. It was said to protect the king.",
                                           "Place Associated": "Egypt, Thebes"},
                    ["https://img/101_1.jpg", "https://img/101_2.jpg"]),
    202: RecordData(202, "https://x/202", {"ID Number": "2.2", "Description": "Beta guarded a temple. It has red paint."},
                    ["https://img/202_1.jpg"]),
    909: RecordData(909, "https://x/909", {"ID Number": "9.9", "Description": "Gamma is elsewhere."},
                    ["https://img/909_1.jpg"]),
}


def write_curation(tmp_path, data):
    (tmp_path / "curation.json").write_text(json.dumps(data), encoding="utf-8")


def build(tmp_path, data=None, fetch_image=fake_image):
    write_curation(tmp_path, data or curation())
    return build_pack(tmp_path, fetch=RECORDS.__getitem__, fetch_image=fetch_image)


def test_build_pack_writes_objects_relations_images_and_distractors(tmp_path):
    pack = build(tmp_path)

    assert pack["objects"] == ["1.1", "2.2"]
    assert pack["relations"] == [{"a": "1.1", "b": "2.2", "theme": "Guardians", "passages": ["1.1#p2", "2.2#p1"]}]
    alpha = json.loads((tmp_path / "objects" / "1.1.json").read_text(encoding="utf-8"))
    assert [p["id"] for p in alpha["passages"]] == ["1.1#p1", "1.1#p2", "1.1#place"]
    assert alpha["passages"][2]["text"] == "Place: Egypt, Thebes"
    assert alpha["story"] == [{"title": "First", "passages": ["1.1#p1", "1.1#place"]}]
    assert [i["role"] for i in alpha["images"]] == ["reference", "test"]
    assert alpha["images"][1]["source_url"] == "https://img/101_2.jpg"
    assert (tmp_path / "images" / "1.1_02.jpg").read_bytes() == fake_image("https://img/101_2.jpg")
    assert alpha["display_image"] == "images/1.1_01.jpg"
    beta = json.loads((tmp_path / "objects" / "2.2.json").read_text(encoding="utf-8"))
    assert beta["images"][-1] == {"file": "images/2.2_synthetic_test.jpg", "role": "test", "source_url": None, "synthetic": True}
    assert (tmp_path / "images" / "2.2_synthetic_test.jpg").exists()
    assert pack["distractors"][0]["files"] == ["distractors/9.9_01.jpg"]
    assert (tmp_path / "pack.json").exists()


def test_anchor_that_matches_nothing_fails(tmp_path):
    data = curation()
    data["objects"][0]["story"][0]["anchors"] = ["Nonexistent words"]
    with pytest.raises(CurationError, match="matched 0"):
        build(tmp_path, data)


def test_anchor_that_matches_twice_fails(tmp_path):
    data = curation()
    data["objects"][0]["story"][0]["anchors"] = ["was"]
    with pytest.raises(CurationError, match="matched 2"):
        build(tmp_path, data)


def test_record_of_another_piece_fails(tmp_path):
    data = curation()
    data["objects"][1]["record_id"] = 101
    with pytest.raises(CurationError, match="ID Number '1.1'"):
        build(tmp_path, data)


def test_image_position_outside_the_record_fails(tmp_path):
    data = curation()
    data["objects"][0]["images"]["test"] = [3]
    with pytest.raises(CurationError, match=r"positions \[3\]"):
        build(tmp_path, data)


def test_a_misspelt_image_role_fails(tmp_path):
    data = curation()
    data["objects"][0]["images"] = {"reference": [1], "tests": [2], "display": 1, "synthetic_test": False}
    with pytest.raises(CurationError, match="unknown image-role keys"):
        build(tmp_path, data)


def test_a_photo_in_two_roles_fails(tmp_path):
    data = curation()
    data["objects"][0]["images"]["test"] = [1, 2]
    with pytest.raises(CurationError, match="both reference and test"):
        build(tmp_path, data)


def test_a_hash_anchor_must_name_a_metadata_field(tmp_path):
    data = curation()
    data["objects"][0]["story"][0]["anchors"] = ["#p1"]
    with pytest.raises(CurationError, match="not a metadata anchor"):
        build(tmp_path, data)


def test_a_late_mistake_downloads_and_writes_nothing(tmp_path):
    data = curation()
    data["relations"][0]["anchors"]["2.2"] = ["Beta guardd"]
    fetched = []
    with pytest.raises(CurationError, match="matched 0"):
        build(tmp_path, data, fetch_image=lambda url: fetched.append(url) or fake_image(url))
    assert fetched == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["curation.json"]


def test_unused_files_are_listed(tmp_path):
    build(tmp_path)
    (tmp_path / "images" / "1.1_09.jpg").write_bytes(fake_image("old"))
    assert unused_files(tmp_path) == ["images/1.1_09.jpg"]


def test_build_pack_adds_the_age_and_reviewed_key_facts(tmp_path):
    records = dict(RECORDS)
    alpha_record = RECORDS[101]
    records[101] = RecordData(101, alpha_record.url, {**alpha_record.fields, "Date": "circa 1390-1352 BC"},
                              alpha_record.image_urls)
    (tmp_path / "highlights.json").write_text(json.dumps(
        {"1.1": {"reviewed": True, "what": ["Alpha was carved"], "when": ["#date", "#age"], "wow": ["protect the king"]}}),
        encoding="utf-8")
    write_curation(tmp_path, curation())
    build_pack(tmp_path, fetch=records.__getitem__, fetch_image=fake_image, year=2026)
    alpha = json.loads((tmp_path / "objects" / "1.1.json").read_text(encoding="utf-8"))
    assert alpha["passages"][-1]["id"] == "1.1#age"
    assert alpha["highlights"]["when"] == ["1.1#date", "1.1#age"]
    beta = json.loads((tmp_path / "objects" / "2.2.json").read_text(encoding="utf-8"))
    assert beta["highlights"] == {} and not any(p["id"] == "2.2#age" for p in beta["passages"])


def test_museum_labels_and_accession_numbers_pass_through_only_when_set(tmp_path):
    (tmp_path / "plain").mkdir()
    (tmp_path / "labelled").mkdir()
    plain = build(tmp_path / "plain")
    assert not {"venue", "short_name", "record_label"} & set(plain)
    assert "accession" not in json.loads((tmp_path / "plain" / "objects" / "1.1.json").read_text(encoding="utf-8"))
    data = curation()
    data.update(venue="the Test Museum, Testville", short_name="Test Museum", record_label="TM record")
    data["objects"][0]["accession"] = "X 1"
    labelled = build(tmp_path / "labelled", data)
    assert (labelled["venue"], labelled["short_name"], labelled["record_label"]) == ("the Test Museum, Testville", "Test Museum", "TM record")
    stored = json.loads((tmp_path / "labelled" / "pack.json").read_text(encoding="utf-8"))
    assert stored["record_label"] == "TM record"
    assert json.loads((tmp_path / "labelled" / "objects" / "1.1.json").read_text(encoding="utf-8"))["accession"] == "X 1"
