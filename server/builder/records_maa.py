"""Fetch and parse Museum of Archaeology and Anthropology (Cambridge) collection records, and turn one or more of
them into the single description the pack builder splits into citable passages.

What goes into the description, in page order: the Description field, then every event's text except references,
conservation notes and CMS context. Of a display event, only the display dates and the quoted label are kept, without
the label's heading. Sentences that repeat an earlier one, or are mostly measurements, are dropped. The Cultural
Affliation field (sic, as the site spells it) becomes "Cultural affiliation: ...", so a people's own name is citable.
"""
from __future__ import annotations

import html
import io
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from PIL import Image

from builder.records import RecordError
from builder.sentences import split_sentences

BASE = "https://collections.maa.cam.ac.uk"
RECORD_URL = BASE + "/objects/{record_id}/"
USER_AGENT = "Mozilla/5.0 (research prototype; non-commercial; University of Stirling)"
SKIP_SUBTYPES = frozenset({"References", "CMS Context"})
SKIP_TYPES = frozenset({"Conservation"})
MEASURE_WORDS = frozenset({"extern", "int", "length", "width", "depth", "height", "diam", "diameter", "cm", "mm", "in", "ft", "x"})

_FIELD = re.compile(r'<p class="col-12 col-md-4 fw-bold">(.*?)</p>\s*<p\s+class="col-12 col-md-8">(.*?)</p>', re.S)
_EVENT = re.compile(r'\s*<b>(.*?)</b>\s*\((.*?)\)\s*<br\s*/>(.*?)<br\s*/>\s*<strong>Event Date</strong>', re.S)
_IMAGE = re.compile(r'href="(/media/library_images/web/[^"]+)"')
_LABEL = re.compile(r"Display label reads,\s*'(.*?[.!?])'(?=\s|$)", re.S)  # ends at .' so "hunter's" stays inside


def text_of(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


@dataclass(frozen=True)
class MaaEvent:
    kind: str  # Description, Context, Conservation
    sub: str  # Physical description, Display, References, ...
    text: str


@dataclass(frozen=True)
class MaaRecord:
    record_id: int
    url: str
    fields: dict[str, str]
    events: list[MaaEvent] = field(default_factory=list)
    image_urls: list[str] = field(default_factory=list)


def parse_maa(record_id: int, page: str) -> MaaRecord:
    fields = {text_of(k): text_of(v) for k, v in _FIELD.findall(page)}
    if "Accession No" not in fields:
        raise RecordError(f"MAA record {record_id}: no record fields on the page")
    events = []
    for block in re.findall(r'<p class="col-12">(.*?)</p>', page, re.S):
        if m := _EVENT.match(block):
            events.append(MaaEvent(text_of(m[1]), text_of(m[2]), text_of(m[3])))
    images = list(dict.fromkeys(BASE + p for p in _IMAGE.findall(page)))
    return MaaRecord(record_id, RECORD_URL.format(record_id=record_id), fields, events, images)


def mostly_measurements(sentence: str) -> bool:
    words = sentence.split()
    counted = sum(1 for w in words if re.search(r"\d", w) or w.lower().strip(".,;:'\"") in MEASURE_WORDS)
    return len(words) >= 4 and counted * 2 > len(words)


_ENDED = re.compile(r"[.!?][)'\"’”]*$")


def _finished(text: str) -> str:
    """End a field's text with a full stop, so it never runs into the next field's first sentence."""
    text = re.sub(r"\s\.(?=[A-Z])", ". ", text.strip())  # catalogue cards write "11\" .Analysis"
    return text if not text or _ENDED.search(text) else text + "."


def _lines(text: str) -> str:
    """Catalogue cards and labels mark line breaks with " / "; each line ends as a sentence."""
    return " ".join(_finished(line) for line in text.split(" / ") if line.strip())


def _display_text(text: str) -> str:
    before, _, _ = text.partition("Display label reads")
    kept = [before.strip()]
    if m := _LABEL.search(text):
        chunks = [c.strip() for c in m[1].split(" / ") if c.strip()]
        if chunks and len(chunks[0].split()) <= 4:
            chunks = chunks[1:]  # the label's heading, such as "Protective Demon" or "Kayak"
        kept += [c if c.endswith((".", "!", "?")) else c + "." for c in chunks]
    return " ".join(_finished(k) for k in kept if k)


def _texts(record: MaaRecord) -> list[str]:
    out = [_finished(record.fields.get("Description", ""))]
    for e in record.events:
        if e.kind in SKIP_TYPES or e.sub in SKIP_SUBTYPES:
            continue
        out.append(_display_text(e.text) if e.sub == "Display" else _lines(e.text))
    culture = [c.strip() for c in record.fields.get("Cultural Affliation", "").split(";") if c.strip()]
    if culture:
        out.append("Cultural affiliation: " + ", ".join(culture) + ".")
    return out


def _key(sentence: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()


def compose_description(records: list[MaaRecord], quotes: list[str], drop: list[str] | tuple[str, ...] = ()) -> str:
    """`drop`: text fragments a curator ruled out (cataloguing history, storage notes); any sentence containing one is left out."""
    kept: list[str] = []
    seen: set[str] = set()
    for text in [t for r in records for t in _texts(r)] + quotes:
        for sentence in split_sentences(text):
            k = _key(sentence)
            repeat = k in seen or any(k in s for s in seen if len(k) > 40)
            if not k or repeat or mostly_measurements(sentence) or any(d in sentence for d in drop):
                continue
            seen.add(k)
            kept.append(sentence)
    return " ".join(kept)


def maa_fields(record: MaaRecord, object_id: str) -> dict[str, str]:
    """MAA fields under the names the pack builder reads. ID Number is the object ID (the MAA record number),
    because passage IDs must be digits and dots; the accession number is checked against curation.json separately."""
    place = [p.strip() for p in record.fields.get("Place", "").split(";") if p.strip()]
    return {
        "ID Number": object_id,
        "Accession No": record.fields.get("Accession No", ""),
        "Date": record.fields.get("Period", ""),
        "Place Associated": ", ".join(reversed(place[-3:])),
        "Materials": ", ".join(m.strip() for m in record.fields.get("Material", "").split(";") if m.strip()),
        "Location": "",
        "Credit Line/Donor": record.fields.get("Source", ""),
    }


def verify_quote(quote: str, page: str) -> bool:
    return " ".join(quote.split()) in text_of(page)


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RecordError(f"GET {url} failed: {exc}") from exc


def fetch_maa(record_id: int, pause: float = 1.0) -> MaaRecord:
    page = _get(RECORD_URL.format(record_id=record_id)).decode("utf-8")
    time.sleep(pause)
    return parse_maa(record_id, page)


def fetch_page(url: str, pause: float = 1.0) -> str:
    page = _get(url).decode("utf-8", "replace")
    time.sleep(pause)
    return page


def download_jpeg(url: str, pause: float = 0.6) -> bytes:
    """MAA serves PNG photos; the pack stores JPEG."""
    data = _get(url)
    time.sleep(pause)
    if data.startswith(b"\xff\xd8\xff"):
        return data
    out = io.BytesIO()
    Image.open(io.BytesIO(data)).convert("RGB").save(out, format="JPEG", quality=90)
    return out.getvalue()
