"""GET /test-gallery: held-out photos and look-alikes, full screen on a laptop, for testing from home."""
import json
from pathlib import PurePosixPath

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.packs import Pack

router = APIRouter()

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Test gallery</title>
<style>
html,body{margin:0;height:100%;background:#111;color:#ddd;font:14px system-ui,sans-serif}
#stage{position:fixed;inset:0;display:flex;align-items:center;justify-content:center}
#stage img{width:100vw;height:100vh;object-fit:contain}
#label{position:fixed;left:12px;bottom:10px;opacity:.75}
#hint{position:fixed;right:12px;bottom:10px;opacity:.5}
.hidden{display:none}
</style></head><body>
<div id="stage"><img id="photo" alt=""></div>
<div id="label" class="hidden"></div><div id="hint">Arrow keys or click: next. L: label. H: this hint. F: full screen.</div>
<script type="application/json" id="slides">__SLIDES__</script>
<script>
const slides = JSON.parse(document.getElementById('slides').textContent);
const photo = document.getElementById('photo');
const label = document.getElementById('label');
const hint = document.getElementById('hint');
let i = 0;
function show() {
  photo.src = slides[i].src;
  photo.alt = slides[i].label;
  label.textContent = (i + 1) + ' / ' + slides.length + ': ' + slides[i].label + ' [' + slides[i].name + ']';
}
function step(by) { i = (i + by + slides.length) % slides.length; show(); }
if (slides.length === 0) {
  label.textContent = 'No test photos in this pack.';
  label.classList.remove('hidden');
} else {
  document.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowRight' || e.key === ' ') step(1);
    if (e.key === 'ArrowLeft') step(-1);
    const key = e.key.toLowerCase();
    if (key === 'l') label.classList.toggle('hidden');
    if (key === 'h') hint.classList.toggle('hidden');
    if (key === 'f' && document.documentElement.requestFullscreen) document.documentElement.requestFullscreen();
  });
  document.getElementById('stage').addEventListener('click', () => step(1));
  show();
}
</script></body></html>"""


def gallery_slides(pack: Pack) -> list[dict]:
    """The slides in their fixed order: each piece's test photos in pack order, then the look-alikes.

    Task 23a names its phone photos from this list, so the order must stay stable.
    """
    slides = []
    for o in pack.objects.values():
        for image in o.images:
            if image["role"] == "test":
                note = " [synthetic]" if image.get("synthetic") else ""
                slides.append({"src": "/pack-assets/" + image["file"], "name": PurePosixPath(image["file"]).stem,
                               "object_id": o.id, "label": f"{o.title} ({o.id}){note}"})
    for d in pack.distractors:
        for file in d["files"]:
            slides.append({"src": "/pack-assets/" + file, "name": PurePosixPath(file).stem, "object_id": None,
                           "label": f"Not in the pack: {d['title']} ({d['id']})"})
    return slides


@router.get("/test-gallery", response_class=HTMLResponse)
def test_gallery(request: Request) -> str:
    slides = gallery_slides(request.app.state.pack)
    return PAGE.replace("__SLIDES__", json.dumps(slides).replace("<", "\\u003c"))
