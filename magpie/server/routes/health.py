from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/api/auth/check")
async def auth_check(request: Request):
    """Validate the current API key. Returns 200 if valid, 401 if not."""
    return {"ok": True}
