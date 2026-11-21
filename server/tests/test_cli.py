from app.cli import check_visit
from app.packs import load_pack
from tests.helpers import add_key_facts


def turn(object_id, kind, part_index, sentences, dropped=()):
    events = [{"type": "turn_started", "part_index": part_index}]
    events += [{"type": "sentence", "text": text, "citations": cites} for text, cites in sentences]
    events += [{"type": "dropped", "text": text, "reason": reason} for text, reason in dropped]
    return {"object_id": object_id, "kind": kind, "part_index": part_index, "events": events}


def results(turns, pack):
    return {name: passed for name, passed, _ in check_visit(turns, pack)}


def test_a_good_visit_passes_every_check(test_pack):
    pack = load_pack(add_key_facts(test_pack))
    turns = [turn("1.1", "tell", 0, [("Some 3,400 years ago, Alpha was said to protect the king.", ["1.1#age", "1.1#p2"]),
                                     ("Would you like to hear how it came here?", [])])]
    assert all(results(turns, pack).values())


def test_each_check_catches_its_problem(test_pack):
    pack = load_pack(add_key_facts(test_pack))
    turns = [turn("1.1", "tell", 0, [("Look at Alpha.", ["1.1#p1"]), ("Look at it again.", ["1.1#p1"])],
                  dropped=[("Invented.", "unknown citation 1.1#p99")])]
    assert results(turns, pack) == {
        "no dropped sentences": False,
        "every citation known": False,
        "openings cite what or when, and the wow": False,
        "every part ends with a question or an invitation": False,
        '"Look at" opens a sentence at most once': False,
    }


def test_pieces_without_key_facts_skip_the_opening_check(test_pack):
    turns = [turn("1.1", "tell", 0, [("Alpha was carved in stone.", ["1.1#p1"]), ("Shall we carry on?", [])])]
    assert results(turns, load_pack(test_pack))["openings cite what or when, and the wow"] is True


def test_every_packs_script_names_only_its_own_pieces():
    from pathlib import Path

    from app.cli import SCRIPTS

    packs = Path(__file__).resolve().parents[2] / "packs"
    for pack_id, script in SCRIPTS.items():
        if not (packs / pack_id / "pack.json").exists():
            continue  # museum packs are not in a public checkout
        pack = load_pack(packs / pack_id)
        assert pack.id == pack_id
        assert {object_id for object_id, _, _ in script} <= set(pack.objects)
        assert all(question for _, kind, question in script if kind == "ask")
