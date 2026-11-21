"""Fetch and parse Glasgow Museums online collection records."""
from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

BASE = "https://collections.glasgowmuseums.com"
RECORD_URL = BASE + "/mwebcgi/mweb?request=record;id={record_id};type=101"
USER_AGENT = "Mozilla/5.0 (research prototype; non-commercial; University of Stirling)"
# The site's own JavaScript sets these cookies before it serves record pages.
# Captured from a browser session on 2026-10-07. To refresh: open any record page in a
# browser, copy the Cookie request header from DevTools > Network, and paste it here.
COOKIE = "user=1791377283553592; realname=; permissions=18540412070606010105; screen=1920"

_FIELD = re.compile(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", re.S)
_THUMB = re.compile(r"/MWEBimages/thumb/[^'\"\s]+?_(\d+)_T\.jpg")


class RecordError(RuntimeError):
    """Raised when the museum site does not return a usable record or image."""


@dataclass(frozen=True)
class RecordData:
    record_id: int
    url: str
    fields: dict[str, str]
    image_urls: list[str] = field(default_factory=list)

    @property
    def description(self) -> str:
        return self.fields.get("Description", "")


def clean(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    return " ".join(html.unescape(text).split())


def parse_record(record_id: int, page: str) -> RecordData:
    """Parse one record page; image_urls are screen-size URLs in ascending photo number, and curation.json indexes image positions into this list."""
    fields = {clean(k): clean(v) for k, v in _FIELD.findall(page)}
    if "ID Number" not in fields:
        raise RecordError(
            f"record {record_id}: no record fields on the page; the site probably served "
            "its landing page instead. Refresh COOKIE from a browser session."
        )
    numbered: dict[int, str] = {}
    for match in _THUMB.finditer(page):
        number = int(match.group(1))
        screen = BASE + match.group(0).replace("/thumb/", "/screen/").replace("_T.jpg", "_S.jpg")
        numbered.setdefault(number, screen)
    images = [numbered[n] for n in sorted(numbered)]
    return RecordData(record_id=record_id, url=RECORD_URL.format(record_id=record_id), fields=fields, image_urls=images)


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cookie": COOKIE})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RecordError(f"GET {url} failed: {exc}") from exc


def fetch_record(record_id: int, pause: float = 1.0) -> RecordData:
    """Fetch one record page politely (one request, then a pause)."""
    page = _get(RECORD_URL.format(record_id=record_id)).decode("utf-8")
    time.sleep(pause)
    return parse_record(record_id, page)


def download(url: str, pause: float = 0.6) -> bytes:
    """Download one image politely."""
    data = _get(url)
    if not data.startswith(b"\xff\xd8\xff"):
        raise RecordError(f"{url} did not return a JPEG image")
    time.sleep(pause)
    return data
