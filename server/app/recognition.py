"""Instance recognition: DINOv2-small embeddings matched against a pack's reference photos."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image

MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class ImageEmbedder(Protocol):
    """Anything that turns a picture into a unit-length 1-D vector; tests use small fakes."""

    def embed(self, image: Image.Image) -> np.ndarray: ...


def preprocess(image: Image.Image) -> np.ndarray:
    """Resize the short side to 256 (bicubic), centre-crop 224, normalise. Returns 1x3x224x224 float32.

    Only the 224x224 window that survives the crop is resampled, so a long, thin upload costs no more than a square one.
    """
    image = image.convert("RGB")
    w, h = image.size
    scale = 256 / min(w, h)
    rw, rh = round(w * scale), round(h * scale)
    left, top = (rw - 224) // 2, (rh - 224) // 2
    sx, sy = w / rw, h / rh
    image = image.resize((224, 224), Image.BICUBIC, box=(left * sx, top * sy, (left + 224) * sx, (top + 224) * sy))
    x = (np.asarray(image, dtype=np.float32) / 255.0 - MEAN) / STD
    return x.transpose(2, 0, 1)[None, ...].astype(np.float32)


def normalise(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-12)


class Embedder:
    """Runs the ONNX model and returns a unit-length CLS embedding."""

    def __init__(self, model_path: Path, threads: int = 2) -> None:
        import onnxruntime as ort  # imported here so tests with a fake embedder need no model

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads  # a small container may see many cores but have a small CPU quota
        self._session = ort.InferenceSession(str(model_path), options, providers=["CPUExecutionProvider"])
        self._input = self._session.get_inputs()[0].name

    def embed(self, image: Image.Image) -> np.ndarray:
        # Asking for the output by name makes a different model export fail loudly instead of returning the wrong token.
        hidden = self._session.run(["last_hidden_state"], {self._input: preprocess(image)})[0]
        return normalise(hidden[0, 0, :].astype(np.float32))  # the CLS token


@dataclass(frozen=True)
class Candidate:
    object_id: str
    score: float


@dataclass(frozen=True)
class Decision:
    accepted: bool
    object_id: str | None
    score: float
    candidates: list[Candidate]


class ReferenceIndex:
    def __init__(self, vectors: np.ndarray, labels: list[str]):
        self.vectors = np.asarray(vectors, dtype=np.float32)
        if self.vectors.ndim != 2 or len(self.vectors) != len(labels):
            raise ValueError("vectors must be a 2-D array with one row per label")
        self.labels = list(labels)

    @classmethod
    def from_pack(cls, pack_root: Path) -> "ReferenceIndex":
        meta = json.loads((pack_root / "embeddings.json").read_text(encoding="utf-8"))
        return cls(np.load(pack_root / "embeddings.npy"), meta["labels"])

    def rank(self, vector: np.ndarray) -> list[Candidate]:
        scores = self.vectors @ vector
        best: dict[str, float] = {}
        for label, score in zip(self.labels, scores):
            if score > best.get(label, float("-inf")):
                best[label] = float(score)
        return [Candidate(k, v) for k, v in sorted(best.items(), key=lambda kv: kv[1], reverse=True)]


def decide(candidates: list[Candidate], threshold: float, margin: float) -> Decision:
    """Accept the best object only if it is confident and clearly ahead of the next object."""
    if not candidates:
        return Decision(False, None, 0.0, [])
    best = candidates[0]
    runner_up = candidates[1].score if len(candidates) > 1 else -1.0
    accepted = best.score >= threshold and (best.score - runner_up) >= margin
    return Decision(accepted, best.object_id if accepted else None, best.score, candidates[:3])
