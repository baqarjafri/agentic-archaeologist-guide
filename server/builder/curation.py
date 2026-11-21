"""Turn record text into citable passages and resolve curation anchors to passage IDs."""
from __future__ import annotations

from dataclasses import dataclass

# Metadata fields that also become citable passages: suffix -> (record field, spoken label)
META_FIELDS = {"date": ("Date", "Date"), "place": ("Place Associated", "Place"), "materials": ("Materials", "Materials")}

IMAGE_KEYS = frozenset({"reference", "test", "display", "synthetic_test"})


class CurationError(ValueError):
    pass


@dataclass(frozen=True)
class Passage:
    id: str
    text: str
    field: str


def check_record(object_id: str, record_id: int, fields: dict[str, str]) -> None:
    """Fail when curation.json points an object at another piece's record."""
    found = fields.get("ID Number", "")
    if found != object_id:
        raise CurationError(f"{object_id}: record {record_id} has ID Number {found!r}; check record_id in curation.json")


def check_positions(owner: str, positions: list[int], count: int) -> None:
    """Fail when curation.json names a photograph the record does not have."""
    outside = [p for p in positions if not 1 <= p <= count]
    if outside:
        raise CurationError(f"{owner}: image positions {outside} are outside the record's {count} photographs")


def check_images(object_id: str, images: dict, count: int) -> None:
    """Fail on a misspelt, missing or contradictory image-role block, before anything is downloaded."""
    unknown = sorted(set(images) - IMAGE_KEYS)
    if unknown:
        raise CurationError(f"{object_id}: unknown image-role keys {unknown}")
    missing = sorted({"reference", "test", "display"} - set(images))
    if missing:
        raise CurationError(f"{object_id}: image roles lack {missing}")
    if not images["reference"]:
        raise CurationError(f"{object_id}: needs at least one reference image")
    both = sorted(set(images["reference"]) & set(images["test"]))
    if both:
        raise CurationError(f"{object_id}: image positions {both} are both reference and test")
    if images["display"] not in images["reference"] + images["test"]:
        raise CurationError(f"{object_id}: display image must be a reference or test image")
    check_positions(object_id, images["reference"] + images["test"], count)


def make_passages(object_id: str, sentences: list[str], fields: dict[str, str]) -> list[Passage]:
    passages = [Passage(f"{object_id}#p{i}", text, "description") for i, text in enumerate(sentences, start=1)]
    for suffix, (field_name, label) in META_FIELDS.items():
        value = fields.get(field_name, "").strip()
        if value:
            passages.append(Passage(f"{object_id}#{suffix}", f"{label}: {value}", suffix))
    return passages


def resolve_anchor(object_id: str, anchor: str, passages: list[Passage]) -> str:
    if anchor.startswith("#"):
        if anchor[1:] not in META_FIELDS:
            raise CurationError(f"{object_id}: {anchor!r} is not a metadata anchor; use " + ", ".join("#" + s for s in META_FIELDS))
        wanted = f"{object_id}{anchor}"
        if any(p.id == wanted for p in passages):
            return wanted
        raise CurationError(f"{object_id}: no metadata passage {anchor}")
    hits = [p.id for p in passages if p.field == "description" and anchor in p.text]
    if len(hits) != 1:
        raise CurationError(f"{object_id}: anchor {anchor!r} matched {len(hits)} passages")
    return hits[0]


def resolve_story(object_id: str, story: list[dict], passages: list[Passage]) -> list[dict]:
    return [
        {"title": part["title"], "passages": [resolve_anchor(object_id, a, passages) for a in part["anchors"]]}
        for part in story
    ]


def resolve_relation(relation: dict, passages_by_object: dict[str, list[Passage]]) -> dict:
    ids: list[str] = []
    for object_id in (relation["a"], relation["b"]):
        if object_id not in passages_by_object:
            raise CurationError(f"relation {relation['theme']!r}: unknown object {object_id}")
        ids += [resolve_anchor(object_id, a, passages_by_object[object_id]) for a in relation["anchors"][object_id]]
    return {"a": relation["a"], "b": relation["b"], "theme": relation["theme"], "passages": ids}
