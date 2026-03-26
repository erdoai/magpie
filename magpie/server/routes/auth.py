"""Auth routes — email OTP login, sessions, user profile."""

import logging
import secrets

import httpx
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth")

SESSION_COOKIE = "magpie_session"


class SendCodeRequest(BaseModel):
    email: str


class VerifyCodeRequest(BaseModel):
    email: str
    code: str


class UpdateProfileRequest(BaseModel):
    display_name: str


@router.post("/send-code")
async def send_code(body: SendCodeRequest, request: Request):
    """Send a 6-digit OTP code to the email address."""
    db = request.app.state.db
    settings = request.app.state.settings

    if not settings.resend_api_key:
        return {"error": "Email not configured"}, 503

    code = f"{secrets.randbelow(1000000):06d}"
    await db.create_email_token(body.email, code)

    # Send via Resend
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": settings.resend_from,
                    "to": [body.email],
                    "subject": f"magpie sign-in code: {code}",
                    "text": f"Your sign-in code is: {code}\n\nThis code expires in 10 minutes.",
                },
                timeout=10,
            )
            if resp.status_code != 200:
                logger.error("Resend error %s: %s", resp.status_code, resp.text)
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=502,
                    content={"error": f"Email service error: {resp.text}"},
                )
    except Exception:
        logger.exception("Failed to send email")
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=502, content={"error": "Failed to send email"})

    return {"ok": True}


@router.post("/verify-code")
async def verify_code(body: VerifyCodeRequest, request: Request, response: Response):
    """Verify OTP code and create session."""
    db = request.app.state.db

    valid = await db.verify_email_token(body.email, body.code)
    if not valid:
        return {"error": "Invalid or expired code"}

    user = await db.get_or_create_user(body.email)
    session_id = await db.create_session(user["id"])

    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,  # 30 days
    )

    # Get user's orgs
    orgs = await db.list_user_orgs(user["id"])

    return {
        "user": {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
        },
        "orgs": orgs,
    }


@router.get("/me")
async def get_me(request: Request):
    """Get current user from session cookie."""
    db = request.app.state.db
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return {"user": None}

    session = await db.get_session(session_id)
    if not session:
        return {"user": None}

    orgs = await db.list_user_orgs(session["user_id"])

    return {
        "user": {
            "id": session["user_id"],
            "email": session["email"],
            "display_name": session["display_name"],
        },
        "orgs": orgs,
    }


@router.post("/logout")
async def logout(request: Request, response: Response):
    db = request.app.state.db
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        await db.delete_session(session_id)
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.put("/profile")
async def update_profile(body: UpdateProfileRequest, request: Request):
    db = request.app.state.db
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return {"error": "Not authenticated"}

    session = await db.get_session(session_id)
    if not session:
        return {"error": "Not authenticated"}

    await db.update_user(session["user_id"], body.display_name)
    return {"ok": True}


@router.get("/check")
async def auth_check():
    """Validate the current API key or session. Returns 200 if valid."""
    return {"ok": True}
