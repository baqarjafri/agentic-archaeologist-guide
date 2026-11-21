"""Compute reference embeddings for a pack.

Usage (from server/): uv run python -m builder.embeddings ../packs/burrell-pilot models/dinov2-small-int8.onnx
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from app.recognition import ImageEmbedder


def reference_images(pack_root: Path) -> list[tuple[str, Path]]:
    pack = json.loads((pack_root / "pack.json").read_text(encoding="utf-8"))
    items: list[tuple[str, Path]] = []
    for object_id in pack["objects"]:
        obj = json.loads((pack_root / "objects" / f"{object_id}.json").read_text(encoding="utf-8"))
        references = [(object_id, pack_root / i["file"]) for i in obj["images"] if i["role"] == "reference"]
        if not references:
            raise ValueError(f"{object_id}: no reference photo, so it could never be recognised")
        items += references
    return items


def build_embeddings(pack_root: Path, embedder: ImageEmbedder) -> int:
    pack = json.loads((pack_root / "pack.json").read_text(encoding="utf-8"))
    items = reference_images(pack_root)
    vectors = np.stack([embedder.embed(Image.open(path)) for _, path in items]).astype(np.float32)
    np.save(pack_root / "embeddings.npy", vectors)
    meta = {
        "model": pack["recognition"]["model"],
        "labels": [object_id for object_id, _ in items],
        "files": [path.relative_to(pack_root).as_posix() for _, path in items],
    }
    (pack_root / "embeddings.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return len(items)


if __name__ == "__main__":
    from app.recognition import Embedder

    root, model = Path(sys.argv[1]), Path(sys.argv[2])
    print(f"embedded {build_embeddings(root, Embedder(model))} reference images")
