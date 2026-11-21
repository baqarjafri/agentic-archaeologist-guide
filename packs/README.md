# Content packs

A pack holds everything the guide may say about a set of pieces. It is built from a museum's own online records.

## Folder layout:
- `curation.json`: written by hand, as described below.
- `pack.json`, `objects/<id>.json`, `images/`, `distractors/`: written by the builder.
- `embeddings.npy`, `embeddings.json`: written by `builder.embeddings` from the reference photos.

## Building a pack:
From `server/`:

    uv run python -m builder.build_pack ../packs/<pack>
    uv run python -m builder.embeddings ../packs/<pack> models/dinov2-small-int8.onnx
    uv run python -m builder.calibrate ../packs/<pack> models/dinov2-small-int8.onnx --write

The builder fetches every record and checks the whole curation before it downloads or writes anything. It lists any image files the new build no longer uses; remove them before committing. Re-run the embeddings and the calibration after any change to images or their roles.

## curation.json:
- `objects`: one entry per piece.
  - `id`: the museum's ID Number, exactly as the record shows it. The build fails if the two differ.
  - `record_id`: the record number in the online collection's URL.
  - `title`, and `meta`: two short lines for the card.
  - `images`: `reference` and `test` list photo positions, counted from 1 in the record's photo-number order, and each photo has one role. Photos in neither list are not downloaded, and image files are named by position, not by the museum's photo number. `display` is the card photo and must be one of them. `synthetic_test: true` adds a stand-in test photo, cropped and tilted from the display photo, for a piece with only one usable photograph; report its recognition results apart from real photographs.
  - `story`: the parts of the piece's story, each with a `title` and `anchors`.
  - `pronunciations`: optional respellings for the voice, used when `RESPELL_NAMES=1`. Each key matches whole words only, so list plural and unaccented forms separately.
- `relations`: links between two pieces, each with a `theme` and `anchors` for both sides. Choose anchors that state the link on both sides, because the guide may only say what its passages support.
- `distractors`: look-alike pieces outside the pack, with photo positions. They are used only to test recognition.
- `recognition`: the model, the score `threshold` (set by calibration) and the `margin` the best piece needs over the runner-up.

## Anchors:
An anchor is a short piece of text that occurs in exactly one sentence of a piece's description, matched exactly, including case and the record's own punctuation such as curly apostrophes. The builder resolves it to that sentence's passage ID, such as `13.181#p4`, which the guide cites. `#date`, `#place` and `#materials` name the record's metadata passages instead. The build fails if an anchor matches no sentence or several. Anchors survive the museum adding or editing sentences, which numbered positions would not.
