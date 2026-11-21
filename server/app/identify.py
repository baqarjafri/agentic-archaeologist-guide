"""POST /api/identify: one camera frame in, the recognised piece (or none) out."""
import io

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from PIL import Image, UnidentifiedImageError
from starlette.datastructures import UploadFile

from app.access import require_code
from app.recognition import ImageEmbedder, decide

router = APIRouter()
MAX_BYTES = 2_000_000
MAX_PIXELS = 4_000_000  # a phone frame is about 0.1 megapixels; a small file can still decode to a huge picture, so refuse it before decoding
FORMATS = ["JPEG", "PNG", "WEBP"]  # the phone sends JPEG; no other decoder needs to be reachable


def embed_upload(data: bytes, embedder: ImageEmbedder) -> np.ndarray:
    """Decode and embed one upload. It runs in a worker thread, so a large picture never holds up other sessions."""
    try:
        picture = Image.open(io.BytesIO(data), formats=FORMATS)
        if picture.width * picture.height > MAX_PIXELS:
            raise HTTPException(status_code=413, detail="image too large")
        picture.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError):
        raise HTTPException(status_code=400, detail="not an image")
    return embedder.embed(picture)


@router.post("/api/identify")
async def identify(request: Request) -> dict:
    # Check the code and the declared size before reading the body, so a refused upload costs nothing.
    require_code(request)
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_BYTES + 64_000:
        raise HTTPException(status_code=413, detail="image too large")
    async with request.form(max_files=1, max_fields=1) as form:  # closes the uploaded file as soon as it is read
        image = form.get("image")
        if not isinstance(image, UploadFile):
            raise HTTPException(status_code=400, detail="send the frame as the form field 'image'")
        data = await image.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="image too large")
    state = request.app.state
    vector = await run_in_threadpool(embed_upload, data, state.embedder)
    decision = decide(state.index.rank(vector), state.pack.threshold, state.pack.margin)
    return {
        "accepted": decision.accepted,
        "object_id": decision.object_id,
        "score": round(decision.score, 4),
        "candidates": [{"object_id": c.object_id, "score": round(c.score, 4)} for c in decision.candidates],
    }
