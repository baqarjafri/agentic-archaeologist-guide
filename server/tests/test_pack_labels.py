import json
from pathlib import Path

from app.guide.prompts import MASTER_PROMPT, master_prompt
from app.packs import client_view, load_pack
from tests.helpers import needs_pack


def test_without_a_venue_the_prompt_is_the_burrell_prompt_word_for_word():
    assert master_prompt(None) == MASTER_PROMPT
    assert "a piece in the Burrell Collection, Glasgow." in MASTER_PROMPT


def test_a_venue_replaces_only_the_museum_name():
    prompt = master_prompt("the Museum of Archaeology and Anthropology, Cambridge")
    assert "a piece in the Museum of Archaeology and Anthropology, Cambridge." in prompt
    assert "Burrell" not in prompt
    assert prompt.replace("the Museum of Archaeology and Anthropology, Cambridge", "the Burrell Collection, Glasgow") == MASTER_PROMPT


def test_a_pack_without_labels_has_none_and_its_client_view_is_unchanged(test_pack):
    pack = load_pack(test_pack)
    assert (pack.venue, pack.short_name, pack.record_label) == (None, None, None)
    view = client_view(pack)
    assert "record_label" not in view and "short_name" not in view
    assert all("accession" not in o for o in view["objects"])


def test_labels_and_accessions_reach_the_client_view(test_pack):
    meta = json.loads((test_pack / "pack.json").read_text(encoding="utf-8"))
    meta.update(venue="the Museum of Archaeology and Anthropology, Cambridge", short_name="MAA Cambridge", record_label="MAA record")
    (test_pack / "pack.json").write_text(json.dumps(meta), encoding="utf-8")
    first = meta["objects"][0]
    doc_path = test_pack / "objects" / f"{first}.json"
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    doc["accession"] = "1926.226"
    doc_path.write_text(json.dumps(doc), encoding="utf-8")
    pack = load_pack(test_pack)
    assert pack.venue == "the Museum of Archaeology and Anthropology, Cambridge"
    assert pack.objects[first].accession == "1926.226"
    view = client_view(pack)
    assert view["short_name"] == "MAA Cambridge" and view["record_label"] == "MAA record"
    assert view["objects"][0]["accession"] == "1926.226"


@needs_pack("burrell-pilot")
def test_the_burrell_pilot_prompt_is_unchanged():
    pack = load_pack(Path(__file__).resolve().parents[2] / "packs" / "burrell-pilot")
    assert master_prompt(pack.venue) == MASTER_PROMPT
