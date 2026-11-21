"""Access codes: a code in the QR link protects the pilot's API budget. No accounts."""
from fastapi import HTTPException, Request

from app.config import Settings


def code_allowed(code: str | None, settings: Settings) -> bool:
    return not settings.access_codes or (code or "") in settings.access_codes


def require_code(request: Request) -> None:
    code = request.query_params.get("code") or request.headers.get("x-access-code")
    if not code_allowed(code, request.app.state.settings):
        raise HTTPException(status_code=401, detail="access code required")
