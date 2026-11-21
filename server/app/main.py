"""FastAPI application factory.

Run locally (from server/): uv run uvicorn app.main:create_app --factory --env-file .env --port 8000
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

from app.access import require_code
from app.config import Settings, load_settings
from app.guide.llm import LLMClient, make_llm
from app.guide.tts import TTSClient, make_tts
from app.packs import client_view, load_pack
from app.recognition import Embedder, ImageEmbedder, ReferenceIndex

log = logging.getLogger("app")


class WebApp(StaticFiles):
    """The built web app. Its HTML is never cached, so a phone picks up a new deploy's bundles at once."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


def _routers() -> list[APIRouter]:
    from app.gallery import router as gallery_router
    from app.guide.socket import router as socket_router
    from app.identify import router as identify_router

    return [identify_router, gallery_router, socket_router]


def create_app(settings: Settings | None = None, *, embedder: ImageEmbedder | None = None,
               index: ReferenceIndex | None = None, llm: LLMClient | None = None, tts: TTSClient | None = None) -> FastAPI:
    settings = settings or load_settings()
    if not settings.access_codes:
        log.warning("ACCESS_CODES is empty: the API is open to anyone with the URL")
    pack = load_pack(settings.pack_dir)
    app = FastAPI(title="Agentic Archaeologist", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.pack = pack
    app.state.embedder = embedder if embedder is not None else Embedder(settings.model_path)
    app.state.index = index if index is not None else ReferenceIndex.from_pack(settings.pack_dir)
    app.state.llm = llm if llm is not None else make_llm(settings)
    app.state.tts = tts if tts is not None else make_tts(settings)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "pack": pack.id, "objects": len(pack.objects)}

    @app.get("/api/pack", dependencies=[Depends(require_code)])
    def pack_view() -> dict:
        return client_view(pack)

    for router in _routers():
        app.include_router(router)
    app.mount("/pack-assets/images", StaticFiles(directory=settings.pack_dir / "images"), name="pack-images")
    if (settings.pack_dir / "distractors").is_dir():
        app.mount("/pack-assets/distractors", StaticFiles(directory=settings.pack_dir / "distractors"), name="pack-distractors")
    if settings.demo_dir is not None:
        # Laptop demos only: footage that plays as the camera view. Railway never sets DEMO_DIR.
        app.mount("/demo-media", StaticFiles(directory=settings.demo_dir), name="demo-media")
    # The web app is mounted last, at "/": a route added to `app` after this line is unreachable, so add routes in _routers().
    if (settings.web_dist / "index.html").is_file():
        app.mount("/", WebApp(directory=settings.web_dist, html=True), name="web")
    return app
