"""Prepare gallery footage for the laptop demo: one tour.mp4 and a tour.json of walk and hover segments.

Usage (from server/):
  uv run python scripts/make_tour.py CUTS_JSON OUT_DIR

CUTS_JSON names the source videos (relative to its own folder) and, per video, walk and hover ranges in seconds.
A hover becomes a ping-pong loop (the range forwards, then reversed), so the app can loop it without a visible jump.
Needs ffmpeg and ffprobe on the PATH.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

WIDTH, HEIGHT, FPS = 1080, 1920, 30
# A keyframe every half second keeps the loop's seek back to its start quick.
ENCODE = ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-g", "15", "-pix_fmt", "yuv420p", "-r", str(FPS)]
PICTURE = f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},fps={FPS}"


@dataclass(frozen=True)
class Part:
    source: Path
    kind: str  # "walk" or "hover"
    start: float
    end: float
    piece: str | None


def read_cuts(cuts_path: Path) -> list[Part]:
    cuts = json.loads(cuts_path.read_text(encoding="utf-8"))
    parts: list[Part] = []
    for clip in cuts["clips"]:
        source = cuts_path.parent / clip["video"]
        previous_end: float | None = None
        for seg in clip["segments"]:
            kind, start, end = seg["kind"], float(seg["start"]), float(seg["end"])
            if kind not in ("walk", "hover"):
                raise ValueError(f"{clip['video']}: unknown segment kind {kind!r}")
            if end <= start:
                raise ValueError(f"{clip['video']}: segment {start}-{end} ends before it starts")
            if previous_end is not None and start < previous_end:
                raise ValueError(f"{clip['video']}: segment {start}-{end} overlaps the one before")
            piece = seg.get("piece")
            if kind == "hover" and not piece:
                raise ValueError(f"{clip['video']}: hover {start}-{end} names no piece")
            parts.append(Part(source, kind, start, end, piece if kind == "hover" else None))
            previous_end = end
    if not parts:
        raise ValueError("the cut list has no segments")
    return parts


def ffmpeg_args(part: Part, out: Path) -> list[str]:
    # -ss before -i seeks fast in the 8K source; the re-encode keeps the cut frame-accurate.
    seek = ["-ss", f"{part.start:.3f}", "-t", f"{part.end - part.start:.3f}", "-i", str(part.source)]
    if part.kind == "walk":
        return ["ffmpeg", "-v", "error", "-y", *seek, "-vf", PICTURE, *ENCODE, str(out)]
    # Scale before reverse: reverse holds every frame in memory, which is ~280 MB for 3 s at 1080x1920.
    loop = f"[0:v]{PICTURE},split[f][b];[b]reverse[r];[f][r]concat=n=2:v=1:a=0[v]"
    return ["ffmpeg", "-v", "error", "-y", *seek, "-filter_complex", loop, "-map", "[v]", *ENCODE, str(out)]


def timeline(parts: list[Part], durations: list[float]) -> list[dict]:
    segments: list[dict] = []
    at = 0.0
    for part, length in zip(parts, durations, strict=True):
        seg: dict = {"kind": part.kind, "start": round(at, 3), "end": round(at + length, 3)}
        if part.piece:
            seg["piece"] = part.piece
        segments.append(seg)
        at += length
    return segments


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return float(out.strip())


def make_tour(cuts_path: Path, out_dir: Path) -> dict:
    parts = read_cuts(cuts_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        files: list[Path] = []
        for i, part in enumerate(parts):
            file = Path(tmp) / f"part_{i:03d}.mp4"
            print(f"{part.kind} {part.source.name} {part.start}-{part.end} s", flush=True)
            subprocess.run(ffmpeg_args(part, file), check=True)
            files.append(file)
        listing = Path(tmp) / "parts.txt"
        listing.write_text("".join(f"file '{f.as_posix()}'\n" for f in files), encoding="utf-8")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
             "-movflags", "+faststart", str(out_dir / "tour.mp4")],
            check=True,
        )
        tour = {"video": "tour.mp4", "segments": timeline(parts, [duration(f) for f in files])}
    (out_dir / "tour.json").write_text(json.dumps(tour, indent=1), encoding="utf-8")
    return tour


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare gallery footage for the laptop demo.")
    parser.add_argument("cuts", type=Path)
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args(argv)
    tour = make_tour(args.cuts, args.out_dir)
    print(f"wrote {args.out_dir / 'tour.mp4'} with {len(tour['segments'])} segments")
    return 0


if __name__ == "__main__":
    sys.exit(main())
