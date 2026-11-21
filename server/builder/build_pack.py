"""Build a content pack from curation.json and the museum's online records.

Two passes: first fetch every record and run every check, writing nothing; then download the images
and write the files, JSON last, so a curation mistake never leaves a half-updated pack.

Usage (from server/): uv run python -m builder.build_pack ../packs/burrell-pilot
"""
from __future__ import annotations

import datetime
import io
import json
import sys
from pathlib import Path
from typing import Callable

from PIL import Image

from builder.curation import (
    Passage, check_images, check_positions, check_record, make_passages, resolve_relation, resolve_story,
)
from builder.highlights import enrich, read_highlights
from builder.records import RecordData, download, fetch_record
from builder.sentences import split_sentences

Fetch = Callable[[int], RecordData]
Download = Callable[[str], bytes]


def image_plan(entry: dict, count: int) -> list[tuple[int, str]]:
    roles = entry["images"]
    plan: list[tuple[int, str]] = []
    for position in range(1, count + 1):
        if position in roles.get("reference", []):
            plan.append((position, "reference"))
        elif position in roles.get("test", []):
            plan.append((position, "test"))
    return plan


def synthetic_test(source: bytes) -> bytes:
    """A stand-in test photo when a piece has one usable photograph: the display photo cropped to 86% and tilted 4 degrees."""
    image = Image.open(io.BytesIO(source)).convert("RGB")
    w, h = image.size
    dx, dy = int(w * 0.07), int(h * 0.07)
    tilted = image.crop((dx, dy, w - dx, h - dy)).rotate(4, resample=Image.BICUBIC, fillcolor=(255, 255, 255))
    out = io.BytesIO()
    tilted.save(out, format="JPEG", quality=90)
    return out.getvalue()


def plan_object(entry: dict, record: RecordData) -> tuple[dict, list[Passage]]:
    """Check one piece and build its document, without downloading or writing anything."""
    object_id = entry["id"]
    roles = entry["images"]
    check_record(object_id, record.record_id, record.fields)
    check_images(object_id, roles, len(record.image_urls))
    passages = make_passages(object_id, split_sentences(record.description), record.fields)
    images = [
        {"file": f"images/{object_id}_{position:02d}.jpg", "role": role,
         "source_url": record.image_urls[position - 1], "synthetic": False}
        for position, role in image_plan(entry, len(record.image_urls))
    ]
    if roles.get("synthetic_test"):
        images.append({"file": f"images/{object_id}_synthetic_test.jpg", "role": "test", "source_url": None, "synthetic": True})
    doc = {
        "id": object_id,
        "record_id": record.record_id,
        "record_url": record.url,
        "title": entry["title"],
        "meta": entry["meta"],
        "fields": {k: record.fields.get(k, "") for k in ("Date", "Place Associated", "Materials", "Location", "Credit Line/Donor")},
        "passages": [{"id": p.id, "text": p.text, "field": p.field} for p in passages],
        "story": resolve_story(object_id, entry["story"], passages),
        "pronunciations": entry.get("pronunciations", {}),
        "display_image": f"images/{object_id}_{roles['display']:02d}.jpg",
        "images": images,
    }
    if entry.get("accession"):
        doc["accession"] = entry["accession"]  # the museum's own number, when the object ID is not it
    return doc, passages


def build_pack(pack_dir: Path, fetch: Fetch = fetch_record, fetch_image: Download = download, year: int | None = None) -> dict:
    curation = json.loads((pack_dir / "curation.json").read_text(encoding="utf-8"))
    blocks = read_highlights(pack_dir, [e["id"] for e in curation["objects"]])
    year = year or datetime.date.today().year

    # Pass 1: fetch the records and run every check. Nothing is downloaded or written yet.
    docs: list[dict] = []
    passages_by_object: dict[str, list[Passage]] = {}
    for entry in curation["objects"]:
        doc, passages = plan_object(entry, fetch(entry["record_id"]))
        passages = enrich(doc, passages, blocks.get(entry["id"]), year)
        print(f"checked {entry['id']} (record {entry['record_id']})")
        docs.append(doc)
        passages_by_object[entry["id"]] = passages
    relations = [resolve_relation(r, passages_by_object) for r in curation["relations"]]
    downloads = [(image["source_url"], image["file"]) for doc in docs for image in doc["images"] if not image["synthetic"]]
    distractors: list[dict] = []
    for d in curation.get("distractors", []):
        record = fetch(d["record_id"])
        check_record(d["id"], record.record_id, record.fields)
        check_positions(d["id"], d["images"], len(record.image_urls))
        files = [f"distractors/{d['id']}_{position:02d}.jpg" for position in d["images"]]
        downloads += [(record.image_urls[position - 1], file) for position, file in zip(d["images"], files)]
        distractors.append({"id": d["id"], "title": d["title"], "record_url": record.url, "files": files})
    pack = {
        "id": curation["id"], "version": curation["version"], "title": curation["title"],
        "institution": curation["institution"], "credit": curation["credit"], "language": curation["language"],
        "objects": [e["id"] for e in curation["objects"]],
        "relations": relations,
        "distractors": distractors,
        "recognition": curation["recognition"],
    }
    pack.update({k: curation[k] for k in ("venue", "short_name", "record_label") if k in curation})  # a pack naming its museum

    # Pass 2: download the images, make the stand-in test photos, then write the JSON files.
    for folder in ("images", "objects", "distractors"):
        (pack_dir / folder).mkdir(parents=True, exist_ok=True)
    print(f"downloading {len(downloads)} images")
    for url, file in downloads:
        (pack_dir / file).write_bytes(fetch_image(url))
    for doc in docs:
        for image in doc["images"]:
            if image["synthetic"]:
                (pack_dir / image["file"]).write_bytes(synthetic_test((pack_dir / doc["display_image"]).read_bytes()))
    for doc in docs:
        (pack_dir / "objects" / f"{doc['id']}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    (pack_dir / "pack.json").write_text(json.dumps(pack, ensure_ascii=False, indent=1), encoding="utf-8")
    return pack


def unused_files(pack_dir: Path) -> list[str]:
    """Image files in the pack folder that the built pack no longer uses, for a person to remove."""
    pack = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    used = {file for d in pack["distractors"] for file in d["files"]}
    for object_id in pack["objects"]:
        doc = json.loads((pack_dir / "objects" / f"{object_id}.json").read_text(encoding="utf-8"))
        used |= {image["file"] for image in doc["images"]}
    found = [p.relative_to(pack_dir).as_posix() for folder in ("images", "distractors") for p in sorted((pack_dir / folder).glob("*.jpg"))]
    return [file for file in found if file not in used]


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "../packs/burrell-pilot")
    built = build_pack(target)
    print(f"built {built['id']}: {len(built['objects'])} objects, {len(built['relations'])} relations")
    stale = unused_files(target)
    if stale:
        print("not used by this build, remove before committing: " + ", ".join(stale))
