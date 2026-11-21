import urllib.error

import pytest

from builder import records
from builder.records import RECORD_URL, RecordError, clean, download, fetch_record, parse_record

PAGE = """
<main><dl>
<dt>Title</dt><dd><p class="sliceVal">Warwick Vase</p></dd>
<dt>ID Number</dt><dd><p class="sliceVal">42.20</p></dd>
<dt>Description</dt><dd><input type="checkbox" class="read-more-state" id="post-1" />
<div id="descriptionDiv"><p class="sliceVal">The Warwick Vase was found in fragments.</p><p>It was restored in 1772&ndash;1774.</p></div>
<label id="descriptionTrigger" for="post-1" class="read-more-trigger"> </label></dd>
</dl>
<img id='image1' src='/MWEBimages/screen/photolib_batch_0303/42.20_07_S.jpg'>
<img src='/MWEBimages/thumb/photolib_batch_0303/42.20_10_T.jpg'>
<img src='/MWEBimages/thumb/photolib_batch_0303/42.20_07_T.jpg'>
<img src='/MWEBimages/thumb/photolib_batch_0303/42.20_10_T.jpg'>
</main>
"""


def test_parse_record_reads_fields_and_description():
    rec = parse_record(40016, PAGE)
    assert rec.fields["Title"] == "Warwick Vase"
    assert rec.fields["ID Number"] == "42.20"
    assert rec.description == "The Warwick Vase was found in fragments. It was restored in 1772–1774."
    assert rec.url.endswith("request=record;id=40016;type=101")


def test_parse_record_lists_screen_images_once_in_number_order():
    rec = parse_record(40016, PAGE)
    assert rec.image_urls == [
        "https://collections.glasgowmuseums.com/MWEBimages/screen/photolib_batch_0303/42.20_07_S.jpg",
        "https://collections.glasgowmuseums.com/MWEBimages/screen/photolib_batch_0303/42.20_10_S.jpg",
    ]


def test_clean_strips_tags_and_entities():
    assert clean("<p>A&amp;B <b>bold</b></p>") == "A&B bold"


def test_parse_record_raises_when_page_has_no_record_fields():
    with pytest.raises(RecordError, match="no record fields"):
        parse_record(34524, "<html><body>Loading</body></html>")


def test_fetch_record_raises_record_error_naming_url_on_network_failure(monkeypatch):
    def fake_urlopen(*args, **kwargs):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(records.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RecordError) as exc_info:
        fetch_record(1, pause=0)
    assert RECORD_URL.format(record_id=1) in str(exc_info.value)


def test_download_raises_when_response_is_not_a_jpeg(monkeypatch):
    monkeypatch.setattr(records, "_get", lambda url: b"<html></html>")
    with pytest.raises(RecordError, match="did not return a JPEG image"):
        download("https://x/a.jpg", pause=0)
