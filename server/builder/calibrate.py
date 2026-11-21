"""Score held-out photos (or phone photos) against the reference index, and suggest an operating threshold.

Usage (from server/):
  uv run python -m builder.calibrate ../packs/burrell-pilot models/dinov2-small-int8.onnx [--write]
  uv run python -m builder.calibrate ../packs/burrell-pilot models/dinov2-small-int8.onnx --frames PHOTOS_DIR [--write]

With --frames, the photos are phone pictures of the test-gallery slides, named <object id>_<anything>.jpg, or
none_<anything>.jpg for the look-alikes. They are turned upright and shrunk as the app shrinks camera frames.

Add --margin M to try a different margin (written too with --write), or --threshold T to set the threshold by hand.
--write refuses a suggestion that overlaps or accepts a wrong match, unless --threshold is given.
"""
from __future__ import annotations

import argparse
import datetime
import io
import json
import re
from pathlib import Path

from PIL import Image, ImageOps

from app.recognition import Candidate, Embedder, ImageEmbedder, ReferenceIndex

FRAME_SIDE = 448  # the app sends camera frames whose longer side is at most this (web/src/lib/camera.ts)
PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png"}
SWEEP_MARGINS = (0.03, 0.05, 0.08, 0.11)


def _row(kind: str, truth: str | None, file: str, ranked: list[Candidate], synthetic: bool = False) -> dict:
    second = ranked[1].score if len(ranked) > 1 else -1.0
    return {"kind": kind, "truth": truth, "file": file, "top": ranked[0].object_id, "score": ranked[0].score,
            "second": second, "synthetic": synthetic}


def score_set(pack_root: Path, embedder: ImageEmbedder, index: ReferenceIndex) -> list[dict]:
    pack = json.loads((pack_root / "pack.json").read_text(encoding="utf-8"))
    rows: list[dict] = []
    for object_id in pack["objects"]:
        obj = json.loads((pack_root / "objects" / f"{object_id}.json").read_text(encoding="utf-8"))
        for image in obj["images"]:
            if image["role"] == "test":
                ranked = index.rank(embedder.embed(Image.open(pack_root / image["file"])))
                rows.append(_row("test", object_id, image["file"], ranked, image.get("synthetic", False)))
    for distractor in pack.get("distractors", []):
        for file in distractor["files"]:
            ranked = index.rank(embedder.embed(Image.open(pack_root / file)))
            rows.append(_row("distractor", None, file, ranked))
    return rows


def score_frames(frames_dir: Path, object_ids: list[str], embedder: ImageEmbedder, index: ReferenceIndex) -> list[dict]:
    """Score phone photos named <object id>_<anything>, or none_<anything> for pieces outside the pack.

    Photos of the synthetic stand-in's slide are named <object id>_synthetic_<anything> and reported apart.
    """
    rows: list[dict] = []
    for path in sorted(p for p in frames_dir.iterdir() if p.suffix.lower() in PHOTO_SUFFIXES):
        truth = path.name.split("_", 1)[0]
        if truth != "none" and truth not in object_ids:
            raise ValueError(f"{path.name}: name it <object id>_… with one of {object_ids}, or none_…")
        image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")  # phone photos carry their rotation in EXIF
        image.thumbnail((FRAME_SIDE, FRAME_SIDE))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=80)  # the app sends its frames as JPEG at quality 0.8
        ranked = index.rank(embedder.embed(Image.open(buffer)))
        look_alike = truth == "none"
        synthetic = path.name.split("_")[1:2] == ["synthetic"]  # the slide that shows a stand-in cut from a reference photo
        rows.append(_row("distractor" if look_alike else "test", None if look_alike else truth, path.name, ranked, synthetic))
    return rows


def accepted(row: dict, threshold: float, margin: float) -> bool:
    """The app's rule (app.recognition.decide): a confident score that clearly leads the runner-up."""
    return row["score"] >= threshold and row["score"] - row["second"] >= margin


def operating_point(rows: list[dict], threshold: float, margin: float) -> tuple[int, int, int, int]:
    """Real photographs of the pieces accepted, out of how many; wrong matches accepted, out of how many."""
    real = [r for r in rows if r["kind"] == "test" and not r["synthetic"]]
    negatives = [r for r in rows if r["kind"] == "distractor" or r["top"] != r["truth"]]
    hits = sum(accepted(r, threshold, margin) and r["top"] == r["truth"] for r in real)
    wrong = sum(accepted(r, threshold, margin) for r in negatives)
    return hits, len(real), wrong, len(negatives)


def suggest_threshold(rows: list[dict], margin: float) -> tuple[float | None, bool]:
    """Midpoint between the weakest correct match and the strongest wrong one, and whether it turns every wrong match away.

    A wrong match that the margin rule already rejects does not raise the threshold, unless every wrong match is of
    that kind: then the margin alone keeps them out, and the midpoint against them all is safe. Correct matches that
    the margin rule rejects are left out too, because the app turns them away whatever the threshold. Returns None
    when the rows hold no such correct match or no wrong one, because then no midpoint exists.
    """
    true_scores = [r["score"] for r in rows
                   if r["kind"] == "test" and r["top"] == r["truth"] and r["score"] - r["second"] >= margin]
    negatives = [r for r in rows if r["kind"] == "distractor" or r["top"] != r["truth"]]
    if not true_scores or not negatives:
        return None, False
    low_true = min(true_scores)
    leading = [r["score"] for r in negatives if r["score"] - r["second"] >= margin]
    if not leading:  # the margin rule alone rejects every wrong match
        return round((low_true + max(r["score"] for r in negatives)) / 2, 3), True
    high_false = max(leading)
    return round((low_true + high_false) / 2, 3), low_true > high_false


def _set_recognition_number(text: str, key: str, value: float) -> str:
    """Edit one number inside the "recognition" object of curation.json's text, keeping the layout."""
    pattern = re.compile(rf'("recognition"\s*:\s*\{{[^{{}}]*?"{key}"\s*:\s*)[0-9.]+')
    new_text, count = pattern.subn(rf"\g<1>{value}", text, count=1)
    if count != 1 or json.loads(new_text)["recognition"][key] != value:
        raise ValueError(f"no recognition {key} to update")
    return new_text


def write_threshold(pack_root: Path, threshold: float, margin: float | None = None) -> None:
    """Store the threshold (and a new margin, if given) in pack.json, and in curation.json by editing the numbers in place.

    The new curation text is prepared and checked before either file is written, so the two files never disagree.
    """
    curation_path, pack_path = pack_root / "curation.json", pack_root / "pack.json"
    text = curation_path.read_text(encoding="utf-8")
    try:
        text = _set_recognition_number(text, "threshold", threshold)
        if margin is not None:
            text = _set_recognition_number(text, "margin", margin)
    except ValueError as exc:
        raise ValueError(f"{curation_path}: {exc}") from exc
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    pack["recognition"]["threshold"] = threshold
    if margin is not None:
        pack["recognition"]["margin"] = margin
    pack_path.write_text(json.dumps(pack, ensure_ascii=False, indent=1), encoding="utf-8")
    curation_path.write_text(text, encoding="utf-8")


def write_record(pack_root: Path, source: str, threshold: float, margin: float, rows: list[dict]) -> None:
    """Keep the run that set the threshold beside the pack, for the write-up and the OSF record."""
    record = {"date": datetime.date.today().isoformat(), "source": source, "threshold": threshold, "margin": margin,
              "rows": rows}
    (pack_root / "calibration.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pack")
    parser.add_argument("model")
    parser.add_argument("--frames", type=Path, help="phone photos of the test-gallery slides, scored instead of the pack's test photos")
    parser.add_argument("--margin", type=float, help="use this margin instead of the pack's; --write then stores it too")
    parser.add_argument("--threshold", type=float, help="use this threshold instead of the suggested one")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    root = Path(args.pack)
    pack = json.loads((root / "pack.json").read_text(encoding="utf-8"))
    margin = args.margin if args.margin is not None else float(pack["recognition"]["margin"])
    embedder, index = Embedder(Path(args.model)), ReferenceIndex.from_pack(root)
    rows = score_frames(args.frames, pack["objects"], embedder, index) if args.frames else score_set(root, embedder, index)
    suggested, separable = suggest_threshold(rows, margin)
    threshold = args.threshold if args.threshold is not None else suggested
    for r in rows:
        tag = " [synthetic]" if r["synthetic"] else ""
        verdict = "" if threshold is None else ("accepted" if accepted(r, threshold, margin) else "rejected")
        print(f"{r['kind']:10} {str(r['truth']):8} top={r['top']:8} score={r['score']:.3f} second={r['second']:.3f} "
              f"{verdict:8} {r['file']}{tag}")
    tests = [r for r in rows if r["kind"] == "test"]
    real = [r for r in tests if not r["synthetic"]]  # a synthetic stand-in is cut from a reference photo, so report it apart
    correct = sum(r["top"] == r["truth"] for r in tests)
    real_correct = sum(r["top"] == r["truth"] for r in real)
    print(f"top-1 on held-out photos: {correct}/{len(tests)} (real photographs {real_correct}/{len(real)})")
    print("margin  suggested  separable  real accepted  wrong accepted")
    for m in sorted(set(SWEEP_MARGINS) | {margin}):
        t, sep = suggest_threshold(rows, m)
        if t is None:
            print(f"{m:<7} none")
            continue
        hits, n_real, wrong, n_wrong = operating_point(rows, t, m)
        print(f"{m:<7} {t:<10} {'yes' if sep else 'no':<10} {f'{hits}/{n_real}':<14} {wrong}/{n_wrong}")
    if threshold is None:
        print("no threshold suggested: no correct match leads its runner-up by the margin, or there are no look-alikes")
        if args.write:
            raise SystemExit("nothing written")
        return
    hits, n_real, wrong, n_wrong = operating_point(rows, threshold, margin)
    how = "given" if args.threshold is not None else ("separable" if separable else "OVERLAP: check the photos")
    print(f"threshold {threshold} with margin {margin} ({how}): "
          f"real photographs accepted {hits}/{n_real}, wrong matches accepted {wrong}/{n_wrong}")
    if args.threshold is not None and wrong:
        print("warning: this threshold accepts a wrong match; do not commit it")
    if args.write:
        if args.threshold is None and (not separable or wrong):
            raise SystemExit("not written: this suggestion overlaps or accepts a wrong match; "
                             "choose a margin from the table with --margin, or give --threshold")
        write_threshold(root, threshold, args.margin)
        source = f"phone photos: {args.frames.name}" if args.frames else "catalogue photos"
        write_record(root, source, threshold, margin, rows)
        print("written to pack.json and curation.json; the run is kept in calibration.json")


if __name__ == "__main__":
    main()
