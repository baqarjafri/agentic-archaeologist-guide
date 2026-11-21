"""Download DINOv2-small (int8 ONNX, Apache-2.0) for recognition, pinned to one exact file.

Usage (from server/): uv run python scripts/fetch_model.py [--out models/dinov2-small-int8.onnx]

The pack's embeddings were computed with this exact file, so the URL is pinned to a repository commit
and the download is checked against its SHA-256.
"""
import argparse
import hashlib
import socket
import sys
import urllib.request
from pathlib import Path

REVISION = "08c606e3123472a388efa59181b677d428f69bbd"  # onnx-community/dinov2-small-ONNX, checked 2026-10-08
URL = f"https://huggingface.co/onnx-community/dinov2-small-ONNX/resolve/{REVISION}/onnx/model_quantized.onnx"
SHA256 = "7cfc69bd1874d20b9dbecdab057f21aeac7b90c2f560bd0fb66af86c78024f62"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "models" / "dinov2-small-int8.onnx"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    out = parser.parse_args().out
    if out.exists() and sha256(out) == SHA256:
        print(f"already present: {out}")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_suffix(".part")
    socket.setdefaulttimeout(60)  # per read, so a stalled connection fails instead of hanging the build
    urllib.request.urlretrieve(URL, partial)
    digest = sha256(partial)
    if digest != SHA256:
        partial.unlink()
        print(f"unexpected SHA-256 {digest}; expected {SHA256}", file=sys.stderr)
        return 1
    partial.replace(out)
    print(f"downloaded {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
