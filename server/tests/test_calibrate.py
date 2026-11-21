import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.recognition import ReferenceIndex
from builder.calibrate import accepted, operating_point, score_frames, suggest_threshold, write_threshold
from builder.embeddings import build_embeddings, reference_images
from tests.helpers import needs_pack

MODEL = Path(__file__).resolve().parents[1] / "models" / "dinov2-small-int8.onnx"
PACK = Path(__file__).resolve().parents[2] / "packs" / "burrell-pilot"


class ColourEmbedder:
    """Fake embedder: the unit vector of the image's mean colour."""

    def embed(self, image):
        v = np.asarray(image.convert("RGB"), dtype=np.float32).reshape(-1, 3).mean(axis=0)
        return v / np.linalg.norm(v)


def test_build_embeddings_writes_vectors_and_labels(tmp_path):
    (tmp_path / "objects").mkdir()
    (tmp_path / "images").mkdir()
    for name, colour in (("a1", (200, 10, 10)), ("a2", (190, 20, 10)), ("b1", (10, 10, 200))):
        Image.new("RGB", (32, 32), colour).save(tmp_path / "images" / f"{name}.jpg")
    (tmp_path / "pack.json").write_text(json.dumps({"objects": ["A", "B"], "recognition": {"model": "fake"}}), encoding="utf-8")
    (tmp_path / "objects" / "A.json").write_text(json.dumps({"images": [
        {"file": "images/a1.jpg", "role": "reference"}, {"file": "images/a2.jpg", "role": "test"}]}), encoding="utf-8")
    (tmp_path / "objects" / "B.json").write_text(json.dumps({"images": [
        {"file": "images/b1.jpg", "role": "reference"}]}), encoding="utf-8")

    assert build_embeddings(tmp_path, ColourEmbedder()) == 2
    assert np.load(tmp_path / "embeddings.npy").shape == (2, 3)
    meta = json.loads((tmp_path / "embeddings.json").read_text(encoding="utf-8"))
    assert meta["model"] == "fake"
    assert meta["labels"] == ["A", "B"]
    assert meta["files"] == ["images/a1.jpg", "images/b1.jpg"]


def test_a_piece_without_a_reference_photo_is_refused(tmp_path):
    (tmp_path / "objects").mkdir()
    (tmp_path / "pack.json").write_text(json.dumps({"objects": ["A"], "recognition": {"model": "fake"}}), encoding="utf-8")
    (tmp_path / "objects" / "A.json").write_text(json.dumps({"images": [{"file": "images/a2.jpg", "role": "test"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="A: no reference photo"):
        build_embeddings(tmp_path, ColourEmbedder())


def test_suggest_threshold_when_separable():
    rows = [
        {"kind": "test", "truth": "A", "top": "A", "score": 0.80, "second": 0.30},
        {"kind": "test", "truth": "B", "top": "B", "score": 0.70, "second": 0.30},
        {"kind": "distractor", "truth": None, "top": "A", "score": 0.40, "second": 0.10},
    ]
    assert suggest_threshold(rows, margin=0.03) == (0.55, True)


def test_suggest_threshold_reports_overlap():
    rows = [
        {"kind": "test", "truth": "A", "top": "A", "score": 0.50, "second": 0.20},
        {"kind": "distractor", "truth": None, "top": "A", "score": 0.60, "second": 0.20},
    ]
    assert suggest_threshold(rows, margin=0.03) == (0.55, False)


def test_suggest_threshold_ignores_look_alikes_the_margin_already_rejects():
    rows = [
        {"kind": "test", "truth": "A", "top": "A", "score": 0.80, "second": 0.30},
        {"kind": "distractor", "truth": None, "top": "A", "score": 0.60, "second": 0.59},
        {"kind": "distractor", "truth": None, "top": "B", "score": 0.40, "second": 0.10},
    ]
    assert suggest_threshold(rows, margin=0.03) == (0.6, True)
    assert not accepted(rows[1], 0.6, 0.03)


def test_when_the_margin_rejects_every_look_alike_the_suggestion_is_safe():
    rows = [
        {"kind": "test", "truth": "A", "top": "A", "score": 0.50, "second": 0.20},
        {"kind": "distractor", "truth": None, "top": "A", "score": 0.60, "second": 0.58},
    ]
    assert suggest_threshold(rows, margin=0.03) == (0.55, True)


def test_no_threshold_without_look_alikes():
    rows = [{"kind": "test", "truth": "A", "top": "A", "score": 0.80, "second": 0.30}]
    assert suggest_threshold(rows, margin=0.03) == (None, False)


def test_suggest_threshold_ignores_correct_matches_the_margin_rejects():
    rows = [
        {"kind": "test", "truth": "A", "top": "A", "score": 0.80, "second": 0.30},
        {"kind": "test", "truth": "B", "top": "B", "score": 0.45, "second": 0.44},
        {"kind": "distractor", "truth": None, "top": "A", "score": 0.40, "second": 0.10},
    ]
    assert suggest_threshold(rows, margin=0.03) == (0.6, True)


def test_operating_point_counts_real_hits_and_wrong_accepts():
    rows = [
        {"kind": "test", "truth": "A", "top": "A", "score": 0.80, "second": 0.30, "synthetic": False},
        {"kind": "test", "truth": "A", "top": "A", "score": 0.90, "second": 0.30, "synthetic": True},
        {"kind": "test", "truth": "B", "top": "A", "score": 0.70, "second": 0.20, "synthetic": False},
        {"kind": "distractor", "truth": None, "top": "B", "score": 0.65, "second": 0.10, "synthetic": False},
    ]
    assert operating_point(rows, 0.6, 0.03) == (1, 2, 2, 2)


def test_score_frames_tags_photos_of_the_synthetic_slide(tmp_path):
    Image.new("RGB", (900, 600), (200, 10, 10)).save(tmp_path / "1.1_synthetic_30.jpg")
    Image.new("RGB", (900, 600), (200, 10, 10)).save(tmp_path / "1.1_01_30.jpg")
    index = ReferenceIndex(np.array([[1, 0, 0], [0, 0, 1]], dtype=np.float32), ["1.1", "2.2"])
    rows = score_frames(tmp_path, ["1.1", "2.2"], ColourEmbedder(), index)
    assert [(r["file"], r["synthetic"]) for r in rows] == [("1.1_01_30.jpg", False), ("1.1_synthetic_30.jpg", True)]


def test_write_threshold_can_also_set_the_margin(tmp_path):
    (tmp_path / "pack.json").write_text(json.dumps({"recognition": {"threshold": 0.45, "margin": 0.03}}), encoding="utf-8")
    curation = '{\n  "recognition": {"model": "m", "threshold": 0.45, "margin": 0.03}\n}\n'
    (tmp_path / "curation.json").write_text(curation, encoding="utf-8")
    write_threshold(tmp_path, 0.5, margin=0.11)
    assert json.loads((tmp_path / "pack.json").read_text(encoding="utf-8"))["recognition"] == {"threshold": 0.5, "margin": 0.11}
    assert (tmp_path / "curation.json").read_text(encoding="utf-8") == '{\n  "recognition": {"model": "m", "threshold": 0.5, "margin": 0.11}\n}\n'


def test_write_threshold_keeps_the_curation_layout(tmp_path):
    (tmp_path / "pack.json").write_text(json.dumps({"recognition": {"threshold": 0.45, "margin": 0.03}}), encoding="utf-8")
    curation = ('{\n  "objects": [{"id": "A", "images": {"reference": [1, 2]}}],\n'
                '  "recognition": {"model": "m", "threshold": 0.45, "margin": 0.03}\n}\n')
    (tmp_path / "curation.json").write_text(curation, encoding="utf-8")

    write_threshold(tmp_path, 0.512)

    assert json.loads((tmp_path / "pack.json").read_text(encoding="utf-8"))["recognition"]["threshold"] == 0.512
    assert (tmp_path / "curation.json").read_text(encoding="utf-8") == curation.replace('"threshold": 0.45', '"threshold": 0.512')


def test_write_threshold_edits_only_the_recognition_threshold(tmp_path):
    (tmp_path / "pack.json").write_text(json.dumps({"recognition": {"threshold": 0.45, "margin": 0.03}}), encoding="utf-8")
    curation = ('{\n  "objects": [{"id": "A", "threshold": 0.9}],\n'
                '  "recognition": {"model": "m", "threshold": 0.45, "margin": 0.03}\n}\n')
    (tmp_path / "curation.json").write_text(curation, encoding="utf-8")
    write_threshold(tmp_path, 0.512)
    assert (tmp_path / "curation.json").read_text(encoding="utf-8") == curation.replace('"threshold": 0.45', '"threshold": 0.512')


def test_write_threshold_changes_nothing_when_curation_has_no_threshold(tmp_path):
    pack = json.dumps({"recognition": {"threshold": 0.45, "margin": 0.03}})
    (tmp_path / "pack.json").write_text(pack, encoding="utf-8")
    (tmp_path / "curation.json").write_text('{"recognition": {"model": "m"}}', encoding="utf-8")
    with pytest.raises(ValueError, match="no recognition threshold"):
        write_threshold(tmp_path, 0.512)
    assert (tmp_path / "pack.json").read_text(encoding="utf-8") == pack


def test_score_frames_reads_the_truth_from_file_names(tmp_path):
    for name, colour in (("1.1_near.jpg", (200, 10, 10)), ("2.2_far.jpg", (10, 10, 200)), ("none_queen.jpg", (10, 200, 10))):
        Image.new("RGB", (900, 600), colour).save(tmp_path / name)
    (tmp_path / "notes.txt").write_text("not a photo", encoding="utf-8")
    index = ReferenceIndex(np.array([[1, 0, 0], [0, 0, 1]], dtype=np.float32), ["1.1", "2.2"])
    rows = score_frames(tmp_path, ["1.1", "2.2"], ColourEmbedder(), index)
    assert [(r["file"], r["kind"], r["truth"]) for r in rows] == [
        ("1.1_near.jpg", "test", "1.1"), ("2.2_far.jpg", "test", "2.2"), ("none_queen.jpg", "distractor", None)]
    assert [r["top"] for r in rows[:2]] == ["1.1", "2.2"]


def test_score_frames_refuses_an_unknown_piece(tmp_path):
    Image.new("RGB", (10, 10)).save(tmp_path / "9.9_x.jpg")
    index = ReferenceIndex(np.array([[1, 0, 0]], dtype=np.float32), ["1.1"])
    with pytest.raises(ValueError, match="9.9_x.jpg"):
        score_frames(tmp_path, ["1.1"], ColourEmbedder(), index)


@needs_pack("burrell-pilot")
def test_committed_embeddings_match_the_pack():
    meta = json.loads((PACK / "embeddings.json").read_text(encoding="utf-8"))
    refs = reference_images(PACK)
    assert meta["files"] == [p.relative_to(PACK).as_posix() for _, p in refs]
    assert meta["labels"] == [object_id for object_id, _ in refs]
    assert np.load(PACK / "embeddings.npy").shape == (len(refs), 384)


@pytest.mark.slow
@pytest.mark.skipif(not MODEL.exists(), reason="model not downloaded")
def test_the_pack_operating_point_accepts_its_photos_and_rejects_the_look_alikes():
    from app.recognition import Embedder
    from builder.calibrate import score_set

    pack = json.loads((PACK / "pack.json").read_text(encoding="utf-8"))
    threshold, margin = pack["recognition"]["threshold"], pack["recognition"]["margin"]
    rows = score_set(PACK, Embedder(MODEL), ReferenceIndex.from_pack(PACK))
    real = [r for r in rows if r["kind"] == "test" and not r["synthetic"]]
    assert all(r["top"] == r["truth"] and accepted(r, threshold, margin) for r in real)
    assert not any(accepted(r, threshold, margin) for r in rows if r["kind"] == "distractor")
