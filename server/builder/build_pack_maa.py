"""Build a content pack from MAA (Cambridge) records with the standard pack builder.

curation.json objects take, besides the usual keys:
  accession      the record's Accession No, checked against the page
  extra_records  more MAA record numbers whose text joins this piece's description (e.g. a coffin's skeleton)
  web_quotes     [{"url", "quote", "label"?}]: a sentence from the museum's website, checked word for word on the
                 page, added as "Museum website: <quote>"
  frames         paths, inside the pack folder, of video frames used as extra photos after the record's own
  drop           text fragments a curator ruled out; sentences containing one are left out of the description
  date_from_period  false when the record's period (e.g. "20th century") would give a misleading derived age

Usage (from server/): uv run python -m builder.build_pack_maa ../packs/cambridge-maa-2026
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from urllib.request import url2pathname

from builder.build_pack import Download, Fetch, build_pack
from builder.curation import CurationError
from builder.records import RecordData
from builder.records_maa import (
    MaaRecord, compose_description, download_jpeg, fetch_maa, fetch_page, maa_fields, verify_quote,
)


def make_fetch(pack_dir: Path, curation: dict, get: Callable[[int], MaaRecord] = fetch_maa,
               get_page: Callable[[str], str] = fetch_page) -> Fetch:
    entries = {e["record_id"]: e for e in curation["objects"]}

    def fetch(record_id: int) -> RecordData:
        entry = entries.get(record_id, {})
        main = get(record_id)
        if entry.get("accession") and main.fields.get("Accession No") != entry["accession"]:
            raise CurationError(f"{record_id}: page has accession {main.fields.get('Accession No')!r}, "
                                f"curation.json says {entry['accession']!r}")
        quotes = []
        for q in entry.get("web_quotes", []):
            if not verify_quote(q["quote"], get_page(q["url"])):
                raise CurationError(f"{record_id}: quote not found word for word on {q['url']}: {q['quote']!r}")
            quote = " ".join(q["quote"].split())
            quotes.append(f"{q.get('label', 'Museum website')}: {quote}" + ("" if quote.endswith(".") else "."))
        records = [main, *(get(r) for r in entry.get("extra_records", []))]
        fields = {**maa_fields(main, str(record_id)), "Description": compose_description(records, quotes, entry.get("drop", []))}
        if entry.get("date_from_period") is False:
            fields["Date"] = ""  # no #date passage and no derived age
        frames = [(pack_dir / f).resolve().as_uri() for f in entry.get("frames", [])]
        return RecordData(record_id=record_id, url=main.url, fields=fields, image_urls=[*main.image_urls, *frames])

    return fetch


def make_fetch_image(download: Download = download_jpeg) -> Download:
    def fetch_image(url: str) -> bytes:
        if url.startswith("file:"):
            return Path(url2pathname(urlparse(url).path)).read_bytes()  # a video frame inside the pack folder
        return download(url)

    return fetch_image


def main(argv: list[str] | None = None) -> int:
    pack_dir = Path((argv or sys.argv[1:])[0])
    curation = json.loads((pack_dir / "curation.json").read_text(encoding="utf-8"))
    pack = build_pack(pack_dir, fetch=make_fetch(pack_dir, curation), fetch_image=make_fetch_image())
    print(f"built {pack['id']} with {len(pack['objects'])} objects")
    return 0


if __name__ == "__main__":
    sys.exit(main())
