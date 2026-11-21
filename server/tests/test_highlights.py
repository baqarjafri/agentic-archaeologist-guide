import json
from types import SimpleNamespace

import pytest

from app.packs import load_pack
from builder.curation import CurationError, Passage
from builder.highlights import age_in_years, age_passage, apply, propose, resolve_highlights
from tests.helpers import write_test_pack


@pytest.mark.parametrize("date, age", [
    ("18th Dynasty, reign of Amenhotep III, circa 1390-1352 BC", 3400),
    ("1st part of 22nd Dynasty (probably) (945-900 BC)", 2900),
    ("circa 1200-1210", 820),
    ("Isin-Larsa / Old Babylonian period, circa 2000-1600 BC", 3800),
    ("2nd century", 1900),
    ("19th century", 180),
    ("1950", 80),
    ("3rd century BC", 2300),
    ("Middle Assyrian, 1243–1207 BC", 3300),
])
def test_age_from_the_records_date(date, age):
    assert age_in_years(date, 2026) == age


@pytest.mark.parametrize("date", ["", "unknown", "18th Dynasty"])
def test_an_unreadable_date_gives_no_age(date):
    assert age_in_years(date, 2026) is None


def test_the_age_passage_says_how_it_was_worked_out():
    assert age_passage("13.181", "circa 1390-1352 BC", 2026) == Passage(
        "13.181#age", "Age: about 3,400 years old, worked out from the record's date (circa 1390-1352 BC)", "age")
    assert age_passage("13.181", "unknown", 2026) is None


PASSAGES = [
    Passage("1.1#p1", "Alpha was carved in stone.", "description"),
    Passage("1.1#p2", "It was said to protect the king.", "description"),
    Passage("1.1#date", "Date: circa 1390-1352 BC", "date"),
    Passage("1.1#age", "Age: about 3,400 years old, worked out from the record's date (circa 1390-1352 BC)", "age"),
]


def test_reviewed_key_facts_resolve_to_passage_ids():
    block = {"reviewed": True, "what": ["Alpha was carved"], "when": ["#date", "#age"], "wow": ["protect the king"]}
    assert resolve_highlights("1.1", block, PASSAGES) == {
        "what": ["1.1#p1"], "when": ["1.1#date", "1.1#age"], "wow": ["1.1#p2"], "significance": [], "acquired": []}


def test_unreviewed_key_facts_are_not_used():
    assert resolve_highlights("1.1", {"reviewed": False, "what": ["Alpha was carved"]}, PASSAGES) == {}


def test_a_misspelt_heading_or_a_missing_age_fails():
    with pytest.raises(CurationError, match="unknown key-fact headings"):
        resolve_highlights("1.1", {"reviewed": True, "wowww": []}, PASSAGES)
    with pytest.raises(CurationError, match="no age passage"):
        resolve_highlights("1.1", {"reviewed": True, "when": ["#age"]}, PASSAGES[:3])


def test_apply_adds_the_age_and_the_reviewed_key_facts(tmp_path):
    root = write_test_pack(tmp_path / "pack")
    doc_path = root / "objects" / "1.1.json"
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    doc["fields"] = {"Date": "circa 1390-1352 BC"}
    doc_path.write_text(json.dumps(doc), encoding="utf-8")
    (root / "highlights.json").write_text(json.dumps(
        {"1.1": {"reviewed": True, "what": ["Alpha was carved"], "when": ["#age"], "wow": ["protect the king"]}}),
        encoding="utf-8")
    apply(root, 2026)
    apply(root, 2026)  # running it again changes nothing
    pack = load_pack(root)
    alpha = pack.objects["1.1"]
    assert alpha.highlights == {"what": ("1.1#p1",), "when": ("1.1#age",), "wow": ("1.1#p2",),
                                "significance": (), "acquired": ()}
    assert pack.passages["1.1#age"].text.startswith("Age: about 3,400 years old")
    assert [p.id for p in alpha.passages].count("1.1#age") == 1
    assert pack.objects["2.2"].highlights == {}


def test_key_facts_for_a_piece_not_in_the_pack_fail(tmp_path):
    root = write_test_pack(tmp_path / "pack")
    (root / "highlights.json").write_text(json.dumps({"7.7": {"reviewed": True}}), encoding="utf-8")
    with pytest.raises(CurationError, match="7.7"):
        apply(root, 2026)


class FakeClient:
    def __init__(self, reply):
        self.reply, self.calls = reply, []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.reply)))])


def test_propose_drafts_unreviewed_key_facts_as_anchors(tmp_path):
    root = write_test_pack(tmp_path / "pack")
    (root / "highlights.json").write_text(json.dumps({"2.2": {"reviewed": True, "what": ["Beta guarded"]}}), encoding="utf-8")
    client = FakeClient({"what": ["1.1#p1"], "when": [], "wow": ["1.1#p2"], "significance": [], "acquired": ["1.1#place"]})
    assert propose(root, client, "gemini-3.5-flash") == ["1.1"]
    blocks = json.loads((root / "highlights.json").read_text(encoding="utf-8"))
    assert blocks["1.1"] == {"reviewed": False, "what": ["Alpha was carved in"], "when": [], "wow": ["It was said to"],
                             "significance": [], "acquired": ["#place"]}
    assert blocks["2.2"] == {"reviewed": True, "what": ["Beta guarded"]}  # an existing entry is never touched
    assert len(client.calls) == 1
    assert "1.1#p1: Alpha was carved in stone." in client.calls[0]["messages"][1]["content"]


def test_a_proposal_naming_an_unknown_passage_writes_nothing(tmp_path):
    root = write_test_pack(tmp_path / "pack")
    with pytest.raises(CurationError, match="unknown passages"):
        propose(root, FakeClient({"what": ["1.1#p99"]}), "m")
    assert not (root / "highlights.json").exists()


def test_a_proposal_wrapped_in_a_code_fence_is_read():
    from builder.highlights import parse_reply
    assert parse_reply('```json\n{"what": ["1.1#p1"]}\n```') == {"what": ["1.1#p1"]}
