"""Load a built content pack for the running service."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Passage:
    id: str
    text: str
    field: str


@dataclass(frozen=True)
class StoryPart:
    title: str
    passage_ids: tuple[str, ...]


@dataclass(frozen=True)
class PackObject:
    id: str
    title: str
    meta: tuple[str, ...]
    record_url: str
    display_image: str
    passages: tuple[Passage, ...]
    story: tuple[StoryPart, ...]
    pronunciations: dict[str, str]
    images: tuple[dict, ...]
    highlights: dict[str, tuple[str, ...]] = field(default_factory=dict)  # key facts by heading: what, when, wow, significance, acquired
    accession: str | None = None  # the museum's number, shown after the record label


@dataclass(frozen=True)
class Relation:
    a: str
    b: str
    theme: str
    passage_ids: tuple[str, ...]

    @property
    def key(self) -> str:
        return "|".join(sorted((self.a, self.b)))

    def other(self, object_id: str) -> str:
        return self.b if object_id == self.a else self.a


@dataclass
class Pack:
    root: Path
    id: str
    title: str
    credit: str
    objects: dict[str, PackObject]
    relations: tuple[Relation, ...]
    distractors: tuple[dict, ...]
    threshold: float
    margin: float
    passages: dict[str, Passage] = field(default_factory=dict)
    venue: str | None = None  # in the prompt: "a piece in {venue}"
    short_name: str | None = None  # in the visit drawer
    record_label: str | None = None  # on the card and the source sheet: "{record_label} {accession}"

    def relations_of(self, object_id: str) -> list[Relation]:
        return [r for r in self.relations if object_id in (r.a, r.b)]


def object_of(passage_id: str) -> str:
    return passage_id.split("#", 1)[0]


def load_pack(root: Path) -> Pack:
    meta = json.loads((root / "pack.json").read_text(encoding="utf-8"))
    objects: dict[str, PackObject] = {}
    for object_id in meta["objects"]:
        o = json.loads((root / "objects" / f"{object_id}.json").read_text(encoding="utf-8"))
        objects[object_id] = PackObject(
            id=o["id"], title=o["title"], meta=tuple(o["meta"]), record_url=o["record_url"],
            display_image=o["display_image"],
            passages=tuple(Passage(p["id"], p["text"], p["field"]) for p in o["passages"]),
            story=tuple(StoryPart(s["title"], tuple(s["passages"])) for s in o["story"]),
            pronunciations=dict(o.get("pronunciations", {})),
            images=tuple(o["images"]),
            highlights={heading: tuple(ids) for heading, ids in o.get("highlights", {}).items()},
            accession=o.get("accession"),
        )
    pack = Pack(
        root=root, id=meta["id"], title=meta["title"], credit=meta["credit"], objects=objects,
        relations=tuple(Relation(r["a"], r["b"], r["theme"], tuple(r["passages"])) for r in meta["relations"]),
        distractors=tuple(meta.get("distractors", [])),
        threshold=float(meta["recognition"]["threshold"]), margin=float(meta["recognition"]["margin"]),
        venue=meta.get("venue"), short_name=meta.get("short_name"), record_label=meta.get("record_label"),
    )
    pack.passages.update({p.id: p for o in objects.values() for p in o.passages})
    return pack


def client_view(pack: Pack) -> dict:
    """What the phone needs: titles, meta lines, photos, story parts and passage texts for the source sheet.
    Label fields appear only when the pack sets them, so the pilot's view is unchanged."""
    labels = {k: v for k, v in (("short_name", pack.short_name), ("record_label", pack.record_label)) if v}
    return {
        "id": pack.id, "title": pack.title, "credit": pack.credit, **labels,
        "objects": [{
            "id": o.id, "title": o.title, "meta": list(o.meta), "record_url": o.record_url,
            "display_image": f"/pack-assets/{o.display_image}",
            "parts": [{"title": s.title, "passages": list(s.passage_ids)} for s in o.story],
            "passages": {p.id: p.text for p in o.passages},
            **({"accession": o.accession} if o.accession else {}),
        } for o in pack.objects.values()],
        "relations": [{"key": r.key, "a": r.a, "b": r.b, "theme": r.theme, "passages": list(r.passage_ids)}
                      for r in pack.relations],
    }
