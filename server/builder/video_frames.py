"""Extract the video frames a pack's curation.json lists: photos of each piece (frames/) and held-out frames for
calibration (calibration-frames/, named <object id>_... or none_... as builder.calibrate --frames expects).

Usage (from server/): uv run python -m builder.video_frames ../packs/cambridge-maa-2026 VIDEOS_DIR
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

LONG_SIDE = 1280


def _name(owner: str, video: str, t: float) -> str:
    stem = Path(video).stem.split("_")[-1]
    return f"{owner}_{stem}_{round(t * 10):03d}.jpg"


def frame_jobs(curation: dict, videos: Path, pack_dir: Path) -> list[tuple[Path, float, Path]]:
    jobs = []
    for folder, key in (("frames", "frame_sources"), ("calibration-frames", "calibration_sources")):
        for owner, sources in curation.get(key, {}).items():
            for s in sources:
                for t in s["t"]:
                    jobs.append((videos / s["video"], float(t), pack_dir / folder / _name(owner, s["video"], float(t))))
    return jobs


def extract(video: Path, t: float, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                    "-vf", f"scale='if(gt(iw,ih),{LONG_SIDE},-2)':'if(gt(iw,ih),-2,{LONG_SIDE})'", "-q:v", "2", str(out)],
                   check=True)


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    pack_dir, videos = Path(args[0]), Path(args[1])
    curation = json.loads((pack_dir / "curation.json").read_text(encoding="utf-8"))
    jobs = frame_jobs(curation, videos, pack_dir)
    for video, t, out in jobs:
        extract(video, t, out)
        print(out.relative_to(pack_dir))
    print(f"{len(jobs)} frames")
    return 0


if __name__ == "__main__":
    sys.exit(main())
