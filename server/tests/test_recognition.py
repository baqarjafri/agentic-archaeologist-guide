from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.recognition import Candidate, ReferenceIndex, decide, normalise, preprocess

MODEL = Path(__file__).resolve().parents[1] / "models" / "dinov2-small-int8.onnx"


def test_preprocess_shape_and_normalisation():
    x = preprocess(Image.new("RGB", (630, 480), (124, 116, 104)))
    assert x.shape == (1, 3, 224, 224)
    assert x.dtype == np.float32
    assert abs(float(x.mean())) < 0.05


def test_rank_takes_the_best_score_per_object():
    vectors = np.array([[1, 0, 0], [0.6, 0.8, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32)
    index = ReferenceIndex(vectors, ["a", "a", "b", "c"])
    ranked = index.rank(normalise(np.array([0.8, 0.6, 0], dtype=np.float32)))
    assert [c.object_id for c in ranked] == ["a", "b", "c"]
    assert ranked[0].score == pytest.approx(0.96, abs=1e-6)


def test_decide_accepts_a_clear_winner():
    d = decide([Candidate("a", 0.70), Candidate("b", 0.40)], threshold=0.45, margin=0.03)
    assert d.accepted and d.object_id == "a"


def test_decide_rejects_a_low_score():
    d = decide([Candidate("a", 0.40), Candidate("b", 0.10)], threshold=0.45, margin=0.03)
    assert not d.accepted and d.object_id is None and d.score == 0.40


def test_decide_rejects_a_close_call():
    assert not decide([Candidate("a", 0.60), Candidate("b", 0.59)], threshold=0.45, margin=0.03).accepted


def test_decide_handles_no_candidates():
    assert decide([], 0.45, 0.03).accepted is False


@pytest.mark.slow
@pytest.mark.skipif(not MODEL.exists(), reason="model not downloaded")
def test_real_model_returns_unit_vectors():
    from app.recognition import Embedder

    v = Embedder(MODEL).embed(Image.new("RGB", (300, 300), (200, 50, 50)))
    assert v.shape == (384,)
    assert float(np.linalg.norm(v)) == pytest.approx(1.0, abs=1e-4)


def test_preprocess_puts_channels_first_with_imagenet_constants():
    x = preprocess(Image.new("RGB", (300, 300), (255, 0, 0)))
    assert float(x[0, 0].mean()) == pytest.approx((1 - 0.485) / 0.229, abs=1e-3)
    assert float(x[0, 2].mean()) == pytest.approx((0 - 0.406) / 0.225, abs=1e-3)


def test_preprocess_keeps_a_long_thin_upload_cheap():
    assert preprocess(Image.new("L", (10_000_000, 1))).shape == (1, 3, 224, 224)


def test_reference_index_rejects_mismatched_rows():
    with pytest.raises(ValueError):
        ReferenceIndex(np.zeros((2, 3), dtype=np.float32), ["a"])
    with pytest.raises(ValueError):
        ReferenceIndex(np.zeros(3, dtype=np.float32), ["a", "b", "c"])


def test_decide_with_one_candidate_uses_the_threshold_only():
    assert decide([Candidate("a", 0.45)], threshold=0.45, margin=0.03).accepted
    assert not decide([Candidate("a", 0.44)], threshold=0.45, margin=0.03).accepted
