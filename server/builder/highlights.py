"""Each piece's key facts, prepared before the visit: what it is, how old, the wow, why it matters, how it got here.

  apply    adds the derived age passage and the reviewed key facts to a built pack (offline)
  propose  drafts key facts for pieces that have none, for a person to review (needs the Gemini key)

Usage (from server/):
  uv run python -m builder.highlights apply ../packs/burrell-pilot
  uv run python -m builder.highlights propose ../packs/burrell-pilot
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

from builder.curation import CurationError, Passage, resolve_anchor

HEADINGS = ("what", "when", "wow", "significance", "acquired")
_RANGE = re.compile(r"(\d{1,4})\s*(BC|AD)?\s*[-–]\s*(\d{1,4})\s*(BC|AD)?", re.IGNORECASE)
_CENTURY = re.compile(r"(\d{1,2})(?:st|nd|rd|th)\s+century(?:\s*(BC|AD))?", re.IGNORECASE)
_YEAR = re.compile(r"\b(\d{3,4})\b\s*(BC|AD)?", re.IGNORECASE)


def _signed(year: int, era: str | None) -> int:
    return -year if era and era.upper() == "BC" else year


def years_of(date: str) -> tuple[int, int] | None:
    """The span a record's date allows, as signed years (BC is negative), or None when it cannot be read."""
    if m := _RANGE.search(date):
        era = m[2] or m[4]
        return _signed(int(m[1]), era), _signed(int(m[3]), m[4] or era)
    if m := _CENTURY.search(date):
        n = int(m[1])
        if m[2] and m[2].upper() == "BC":
            return -(n * 100), -((n - 1) * 100 + 1)
        return (n - 1) * 100 + 1, n * 100
    if m := _YEAR.search(date):
        year = _signed(int(m[1]), m[2])
        return year, year
    return None


def age_in_years(date: str, now_year: int) -> int | None:
    """About how old a piece is, from the middle of its dated span: to the nearest 100 years past 1,000, else 10."""
    span = years_of(date)
    if span is None:
        return None
    age = now_year - (span[0] + span[1]) / 2
    if age < 1:
        return None
    step = 100 if age >= 1000 else 10
    return int(round(age / step) * step)


def age_passage(object_id: str, date: str, now_year: int) -> Passage | None:
    age = age_in_years(date, now_year)
    if age is None:
        return None
    return Passage(f"{object_id}#age", f"Age: about {age:,} years old, worked out from the record's date ({date})", "age")


def _resolve(object_id: str, anchor: str, passages: list[Passage]) -> str:
    if anchor == "#age":
        wanted = f"{object_id}#age"
        if any(p.id == wanted for p in passages):
            return wanted
        raise CurationError(f"{object_id}: no age passage, because the record's date could not be read")
    return resolve_anchor(object_id, anchor, passages)


def resolve_highlights(object_id: str, block: dict, passages: list[Passage]) -> dict[str, list[str]]:
    """Reviewed key-fact anchors as passage IDs, by heading; an unreviewed block is not used."""
    unknown = sorted(set(block) - set(HEADINGS) - {"reviewed"})
    if unknown:
        raise CurationError(f"{object_id}: unknown key-fact headings {unknown}; use " + ", ".join(HEADINGS))
    if block.get("reviewed") is not True:
        return {}
    return {heading: [_resolve(object_id, a, passages) for a in block.get(heading, [])] for heading in HEADINGS}


def enrich(doc: dict, passages: list[Passage], block: dict | None, now_year: int) -> list[Passage]:
    """Add the age passage and the reviewed key facts to one object document; returns its passages, age included."""
    passages = [p for p in passages if p.field != "age"]
    age = age_passage(doc["id"], doc.get("fields", {}).get("Date", ""), now_year)
    if age is not None:
        passages.append(age)
    doc["passages"] = [{"id": p.id, "text": p.text, "field": p.field} for p in passages]
    doc["highlights"] = resolve_highlights(doc["id"], block or {}, passages)
    return passages


def read_highlights(pack_dir: Path, object_ids: list[str]) -> dict:
    path = pack_dir / "highlights.json"
    blocks = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    stray = sorted(set(blocks) - set(object_ids))
    if stray:
        raise CurationError(f"highlights.json names pieces that are not in the pack: {stray}")
    return blocks


def apply(pack_dir: Path, now_year: int) -> None:
    """Add the age and the reviewed key facts to every object of a built pack: check them all, then write."""
    object_ids = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))["objects"]
    blocks = read_highlights(pack_dir, object_ids)
    done = []
    for object_id in object_ids:
        path = pack_dir / "objects" / f"{object_id}.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        passages = [Passage(p["id"], p["text"], p["field"]) for p in doc["passages"]]
        enrich(doc, passages, blocks.get(object_id), now_year)
        done.append((path, doc))
    for path, doc in done:
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        has_age = any(p["field"] == "age" for p in doc["passages"])
        print(f"{doc['id']}: age {'added' if has_age else 'unreadable'}, key facts {'used' if doc['highlights'] else 'not reviewed'}")


PROPOSE_PROMPT = """You prepare a museum guide's key facts about one object. You are given the object's passages from the museum's own record, one per line as "ID: text".
For each heading, choose the IDs of the one or two passages that answer it best, using only the IDs given:
- what: what the object is.
- when: when it was made: the date passage, and the age passage if there is one.
- wow: the single most exciting or surprising fact or incident, the one a visitor would most want to hear first.
- significance: why it matters.
- acquired: how it came to the collector or the museum.
Leave a heading as an empty list if no passage answers it. Reply with JSON only, for example:
{"what": ["0.0#p1"], "when": ["0.0#date", "0.0#age"], "wow": ["0.0#p4"], "significance": ["0.0#p6"], "acquired": ["0.0#p9"]}"""


def parse_reply(text: str) -> dict:
    """The model's JSON, with any code fence around it removed."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


def anchor_for(passage_id: str, passages: list[dict]) -> str:
    """A curation anchor for a passage: its # name for a metadata or age passage, else its shortest unique opening."""
    suffix = passage_id.split("#", 1)[1]
    if not re.fullmatch(r"p\d+", suffix):
        return "#" + suffix
    words = next(p["text"] for p in passages if p["id"] == passage_id).split()
    descriptions = [p["text"] for p in passages if p["field"] == "description"]
    for n in range(4, len(words) + 1):
        anchor = " ".join(words[:n])
        if sum(anchor in text for text in descriptions) == 1:
            return anchor
    return " ".join(words)


def propose(pack_dir: Path, client, model: str) -> list[str]:
    """Draft key facts, unreviewed, for every piece with no entry in highlights.json; returns the pieces drafted."""
    object_ids = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))["objects"]
    blocks = read_highlights(pack_dir, object_ids)
    drafted = []
    for object_id in object_ids:
        if object_id in blocks:
            continue
        doc = json.loads((pack_dir / "objects" / f"{object_id}.json").read_text(encoding="utf-8"))
        known = {p["id"] for p in doc["passages"]}
        reply = client.chat.completions.create(model=model, messages=[
            {"role": "system", "content": PROPOSE_PROMPT},
            {"role": "user", "content": "\n".join(f"{p['id']}: {p['text']}" for p in doc["passages"])},
        ])
        picked = parse_reply(reply.choices[0].message.content)
        bad = sorted({pid for heading in HEADINGS for pid in picked.get(heading, [])} - known)
        if bad:
            raise CurationError(f"{object_id}: the model proposed unknown passages {bad}")
        blocks[object_id] = {"reviewed": False} | {
            heading: [anchor_for(pid, doc["passages"]) for pid in picked.get(heading, [])] for heading in HEADINGS}
        drafted.append(object_id)
        print(f"\n{object_id} {doc['title']}")
        texts = {p["id"]: p["text"] for p in doc["passages"]}
        for heading in HEADINGS:
            for pid in picked.get(heading, []):
                print(f"  {heading:12} {texts[pid]}")
    (pack_dir / "highlights.json").write_text(json.dumps(blocks, ensure_ascii=False, indent=1), encoding="utf-8")
    return drafted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare each piece's key facts.")
    parser.add_argument("command", choices=["apply", "propose"])
    parser.add_argument("pack_dir", type=Path)
    parser.add_argument("--model", default="gemini-3.5-flash", help="the model that drafts key facts (propose only)")
    args = parser.parse_args(argv)
    if args.command == "apply":
        apply(args.pack_dir, datetime.date.today().year)
        return 0
    from openai import OpenAI

    from app.config import load_settings

    settings = load_settings()
    if not settings.llm_api_key:
        print("set GEMINI_API_KEY (or LLM_API_KEY) to propose key facts", file=sys.stderr)
        return 2
    client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key, timeout=60.0, max_retries=1)
    drafted = propose(args.pack_dir, client, args.model)
    print(f'\ndrafted key facts for {len(drafted)} pieces; review highlights.json, set "reviewed": true, then run apply')
    return 0


if __name__ == "__main__":
    sys.exit(main())
