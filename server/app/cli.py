"""Text-mode visit for prompt tuning: real turns against the configured model, with no voice.

Usage (from server/): set -a; . ./.env; set +a; uv run python -m app.cli [--check] [--save visit.json]
The script is chosen by the pack in PACK_DIR.
--check also runs the automatic checks on the visit, and exits with 1 if any fails.
"""
import argparse
import json
from pathlib import Path
import asyncio
import datetime
import sys

from app.config import load_settings
from app.guide.context import TurnRequest
from app.guide.llm import make_llm
from app.guide.tts import SilentTTS
from app.guide.turn import run_turn
from app.packs import Pack, load_pack

# A scripted visit per pack. Questions the records cannot answer test that the guide says so instead of inventing.
SCRIPTS = {
    "burrell-pilot": [
    ("13.181", "tell", None),
    ("13.181", "ask", "What was the slot on top of her head for?"),
    ("13.181", "carry_on", None),
    ("28.37", "tell", None),
    ("28.37", "ask", "Who made it?"),  # the record does not say: the guide must say so, not invent a maker
    ("13.257", "tell", None),
    ("26.6", "tell", None),
    ],
    "cambridge-maa-2026": [
    ("487620", "tell", None),
    ("487620", "ask", "Why is he called Hector?"),
    ("487620", "ask", "How old is he?"),  # the record gives no date of making: the guide must say so
    ("461657", "tell", None),
    ("461657", "ask", "Who was she?"),  # the record does not name her
    ("470026", "tell", None),  # linked to the coffin: found by the Museum's own staff
    ("470026", "ask", "Why was it stored upside down?"),
    ("555823", "tell", None),
    ],
}
INVITATIONS = ("carry on", "would you like", "shall we", "next part", "want to hear", "ask me")


def check_visit(turns: list[dict], pack: Pack) -> list[tuple[str, bool, str]]:
    """The automatic checks on a scripted visit, each as (name, passed, detail)."""
    dropped = [(t["object_id"], e["reason"]) for t in turns for e in t["events"] if e["type"] == "dropped"]
    unknown = [d for d in dropped if "unknown" in d[1]]
    no_hook = []
    for t in turns:
        facts = pack.objects[t["object_id"]].highlights
        if t["kind"] != "tell" or t["part_index"] != 0 or not facts:
            continue
        what = set(facts.get("what", ())) | set(facts.get("when", ()))
        wow = set(facts.get("wow", ()))
        opening = [e for e in t["events"] if e["type"] == "sentence"][:3]
        if not any(what & set(s["citations"]) and wow & set(s["citations"]) for s in opening):
            no_hook.append(t["object_id"])
    no_ending = []
    for t in turns:
        if t["kind"] not in ("tell", "carry_on"):
            continue
        sentences = [e["text"].lower() for e in t["events"] if e["type"] == "sentence"]
        last = sentences[-1] if sentences else ""
        if not (last.endswith("?") or any(phrase in last for phrase in INVITATIONS)):
            no_ending.append(t["object_id"])
    look_ats = sum(e["text"].startswith("Look at")
                   for t in turns if t["kind"] == "tell" for e in t["events"] if e["type"] == "sentence")
    return [
        ("no dropped sentences", not dropped, "; ".join(f"{o}: {r}" for o, r in dropped)),
        ("every citation known", not unknown, f"{len(unknown)} unknown"),
        ("openings cite what or when, and the wow", not no_hook, ", ".join(no_hook)),
        ("every part ends with a question or an invitation", not no_ending, ", ".join(no_ending)),
        ('"Look at" opens a sentence at most once', look_ats <= 1, f"{look_ats} times"),
    ]


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Play the scripted visit in text against the configured model.")
    parser.add_argument("--check", action="store_true", help="run the automatic checks on the visit")
    parser.add_argument("--save", type=Path, help="write every turn's events (sentences, citations, drops) to this JSON file")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # Windows pipes and files default to cp1252; model text may not fit it
    settings = load_settings()
    pack = load_pack(settings.pack_dir)
    llm = make_llm(settings)
    print(f"model {settings.llm_model}, effort {settings.llm_reasoning_effort}, strict citations {settings.strict_citations}, pack {settings.pack_dir.name}")
    visits: dict[str, dict] = {}
    connections: list[str] = []
    recent: dict[str, list[dict]] = {}
    turns: list[dict] = []
    clock = datetime.datetime(2026, 11, 26, 10, 30)
    for object_id, kind, question in SCRIPTS[pack.id]:
        clock += datetime.timedelta(minutes=3)
        visit = visits.setdefault(object_id, {"object_id": object_id, "time": clock.strftime("%H:%M"),
                                              "heard_parts": [], "questions": []})
        if question:
            visit["questions"].append(question)
        req = TurnRequest.model_validate({
            "kind": kind, "object_id": object_id, "question": question, "visits": list(visits.values()),
            "recent": recent.get(object_id, [])[-3:], "connections_made": connections,
        })
        print(f"\n=== {clock:%H:%M} {pack.objects[object_id].title}: {kind}" + (f": {question}" if question else ""))
        events: list[dict] = []

        async def send(item: dict | bytes) -> None:
            if not isinstance(item, dict):
                return
            events.append(item)
            if item["type"] == "turn_started" and item["part_index"] is not None:
                print(f"  [part {item['part_index'] + 1} of {item['part_count']}: {item['part_title']}]")
            elif item["type"] == "sentence":
                shown = f"  SHOW {item['show']}" if item["show"] else ""
                print(f"  {item['text']}  {item['citations']}{shown}")
            elif item["type"] == "connection":
                print(f"  [connection: {item['theme']} with {item['other_object']}]")
            elif item["type"] == "dropped":
                print(f"  !! {item}")

        try:
            # respell changes only the voiced text, which SilentTTS discards
            await run_turn(req, pack, llm, SilentTTS(), send, strict=settings.strict_citations)
        except Exception as exc:  # one failed turn must not end the tuning run
            print(f"  !! turn failed: {exc!r}")
            continue
        started = next((e for e in events if e["type"] == "turn_started"), {"part_index": None})
        turns.append({"object_id": object_id, "kind": kind, "part_index": started["part_index"], "events": events})
        done = next((e for e in events if e["type"] == "turn_done"), {"part_index": None})
        connection = next((e for e in events if e["type"] == "connection"), None)
        if connection is not None:  # as the phone does: remembered only when the turn finishes
            connections.append(connection["key"])
        if kind in ("tell", "carry_on") and done["part_index"] is not None:
            visit["heard_parts"].append(done["part_index"])
        if kind == "ask":
            answer = " ".join(e["text"] for e in events if e["type"] == "sentence")
            recent.setdefault(object_id, []).append({"question": question, "answer": answer})
    if args.save:
        args.save.write_text(json.dumps({"pack": pack.id, "model": settings.llm_model, "strict": settings.strict_citations,
                                         "turns": turns}, ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.check:
        return 0
    results = check_visit(turns, pack)
    print("\nCHECKS")
    for name, passed, detail in results:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not passed else ""))
    return 0 if all(passed for _, passed, _ in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
