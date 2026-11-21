import io
import json
from pathlib import Path

import numpy as np
from PIL import Image


class ColourEmbedder:
    """Fake embedder: the unit vector of the image's mean colour."""

    def embed(self, image: Image.Image) -> np.ndarray:
        v = np.asarray(image.convert("RGB"), dtype=np.float32).reshape(-1, 3).mean(axis=0)
        return v / np.linalg.norm(v)


def jpeg_bytes(colour: tuple[int, int, int]) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 40), colour).save(out, format="JPEG")
    return out.getvalue()


def write_test_pack(root: Path) -> Path:
    """Two pieces (Alpha 1.1, Beta 2.2), one relation, one distractor; red = Alpha, blue = Beta."""
    for d in ("objects", "images", "distractors"):
        (root / d).mkdir(parents=True, exist_ok=True)
    for name, colour in (("1.1_01.jpg", (200, 10, 10)), ("1.1_02.jpg", (190, 20, 20)), ("2.2_01.jpg", (10, 10, 200))):
        Image.new("RGB", (32, 32), colour).save(root / "images" / name)
    Image.new("RGB", (32, 32), (10, 200, 10)).save(root / "distractors" / "9.9_01.jpg")
    alpha = {
        "id": "1.1", "record_id": 101, "record_url": "https://x/101", "title": "Alpha",
        "meta": ["Here · then", "Stone · 1.1"], "fields": {},
        "passages": [
            {"id": "1.1#p1", "text": "Alpha was carved in stone.", "field": "description"},
            {"id": "1.1#p2", "text": "It was said to protect the king.", "field": "description"},
            {"id": "1.1#p3", "text": "It came to Glasgow in 1950.", "field": "description"},
            {"id": "1.1#place", "text": "Place: Egypt, Thebes", "field": "place"},
        ],
        "story": [{"title": "Who it is", "passages": ["1.1#p1", "1.1#p2"]},
                  {"title": "How it came", "passages": ["1.1#p3"]}],
        "pronunciations": {"Alpha": "Al-fa"},
        "display_image": "images/1.1_01.jpg",
        "images": [{"file": "images/1.1_01.jpg", "role": "reference", "source_url": None, "synthetic": False},
                   {"file": "images/1.1_02.jpg", "role": "test", "source_url": None, "synthetic": False}],
    }
    beta = {
        "id": "2.2", "record_id": 202, "record_url": "https://x/202", "title": "Beta",
        "meta": ["There · now", "Clay · 2.2"], "fields": {},
        "passages": [{"id": "2.2#p1", "text": "Beta guarded a temple.", "field": "description"},
                     {"id": "2.2#p2", "text": "It has red paint.", "field": "description"}],
        "story": [{"title": "A guardian", "passages": ["2.2#p1", "2.2#p2"]}],
        "pronunciations": {},
        "display_image": "images/2.2_01.jpg",
        "images": [{"file": "images/2.2_01.jpg", "role": "reference", "source_url": None, "synthetic": False}],
    }
    for doc in (alpha, beta):
        (root / "objects" / f"{doc['id']}.json").write_text(json.dumps(doc), encoding="utf-8")
    pack = {
        "id": "test-pack", "version": "0.0.1", "title": "Test pack", "institution": "Test Museum",
        "credit": "Test credit", "language": "en-GB", "objects": ["1.1", "2.2"],
        "relations": [{"a": "1.1", "b": "2.2", "theme": "Guardians", "passages": ["1.1#p2", "2.2#p1"]}],
        "distractors": [{"id": "9.9", "title": "Gamma", "record_url": "https://x/909", "files": ["distractors/9.9_01.jpg"]}],
        "recognition": {"model": "fake", "threshold": 0.9, "margin": 0.02},
    }
    (root / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
    np.save(root / "embeddings.npy", np.array([[1, 0, 0], [0, 0, 1]], dtype=np.float32))
    (root / "embeddings.json").write_text(json.dumps(
        {"model": "fake", "labels": ["1.1", "2.2"], "files": ["images/1.1_01.jpg", "images/2.2_01.jpg"]}), encoding="utf-8")
    return root


def add_key_facts(root: Path) -> Path:
    """Give Alpha (1.1) an age passage and reviewed key facts, as `builder.highlights apply` would."""
    path = root / "objects" / "1.1.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["passages"].append({"id": "1.1#age", "field": "age",
                            "text": "Age: about 3,400 years old, worked out from the record's date (circa 1390-1352 BC)"})
    doc["highlights"] = {"what": ["1.1#p1"], "when": ["1.1#age"], "wow": ["1.1#p2"], "significance": [], "acquired": ["1.1#p3"]}
    path.write_text(json.dumps(doc), encoding="utf-8")
    return root


PACKS = Path(__file__).resolve().parents[2] / "packs"
MAA_FIXTURES = Path(__file__).parent / "fixtures" / "maa"


def needs_pack(name: str):
    """Skip a test that reads a real museum pack when the checkout does not include it (museum content is not public)."""
    import pytest
    return pytest.mark.skipif(not (PACKS / name / "pack.json").exists(), reason=f"museum pack {name} is not in this checkout")


def needs_maa_fixtures():
    import pytest
    return pytest.mark.skipif(not MAA_FIXTURES.is_dir(), reason="saved MAA record pages are not in this checkout")
