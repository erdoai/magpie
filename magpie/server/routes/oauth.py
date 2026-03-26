"""OAuth consent page — user authenticates and approves MCP client access."""

import logging
import secrets

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oauth")

SESSION_COOKIE = "magpie_session"


@router.get("/authorize")
async def authorize_page(
    request: Request,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    redirect_uri_provided_explicitly: str = "true",
    state: str | None = None,
    scope: str | None = None,
    resource: str | None = None,
):
    """Show consent page. If user has a session, show approve/deny.
    Otherwise show email login form."""
    db = request.app.state.db

    # Check existing session
    session_id = request.cookies.get(SESSION_COOKIE)
    session = None
    if session_id:
        session = await db.get_session(session_id)

    # Look up client name
    client_row = await db._pool.fetchrow(
        "SELECT client_name FROM oauth_clients WHERE client_id = $1", client_id
    )
    client_name = client_row["client_name"] if client_row else client_id

    # Build hidden fields for the form
    hidden = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "redirect_uri_provided_explicitly": redirect_uri_provided_explicitly,
    }
    if state:
        hidden["state"] = state
    if scope:
        hidden["scope"] = scope
    if resource:
        hidden["resource"] = resource

    hidden_inputs = "\n".join(
        f'<input type="hidden" name="{k}" value="{_esc(v)}">' for k, v in hidden.items()
    )

    if session:
        # User is logged in — show consent
        user_email = session["email"]
        return HTMLResponse(_consent_html(client_name, user_email, hidden_inputs))
    else:
        # User not logged in — show email form first
        return HTMLResponse(_login_html(client_name, hidden_inputs))


@router.post("/authorize/login")
async def authorize_login(request: Request):
    """Handle email submission — send OTP code, show code entry form."""
    form = await request.form()
    email = form["email"]
    db = request.app.state.db
    settings = request.app.state.settings

    # Generate and send OTP
    code = f"{secrets.randbelow(1000000):06d}"
    await db.create_email_token(email, code)

    if settings.resend_api_key:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                    json={
                        "from": settings.resend_from,
                        "to": [email],
                        "subject": f"magpie sign-in code: {code}",
                        "text": f"Your sign-in code is: {code}\n\nThis code expires in 10 minutes.",
                    },
                    timeout=10,
                )
        except Exception:
            logger.exception("Failed to send email")

    # Carry forward all OAuth params + email
    hidden = {}
    for key in ("client_id", "redirect_uri", "code_challenge",
                "redirect_uri_provided_explicitly", "state", "scope", "resource"):
        val = form.get(key)
        if val:
            hidden[key] = val
    hidden["email"] = email

    hidden_inputs = "\n".join(
        f'<input type="hidden" name="{k}" value="{_esc(v)}">' for k, v in hidden.items()
    )

    client_row = await db._pool.fetchrow(
        "SELECT client_name FROM oauth_clients WHERE client_id = $1", form["client_id"]
    )
    client_name = client_row["client_name"] if client_row else form["client_id"]

    return HTMLResponse(_verify_html(client_name, email, hidden_inputs))


@router.post("/authorize/verify")
async def authorize_verify(request: Request):
    """Verify OTP code, create session, show consent."""
    form = await request.form()
    email = form["email"]
    code = form["code"]
    db = request.app.state.db

    valid = await db.verify_email_token(email, code)
    if not valid:
        # Re-show verify form with error
        hidden = {}
        for key in ("client_id", "redirect_uri", "code_challenge",
                    "redirect_uri_provided_explicitly", "state", "scope", "resource", "email"):
            val = form.get(key)
            if val:
                hidden[key] = val
        hidden_inputs = "\n".join(
            f'<input type="hidden" name="{k}" value="{_esc(v)}">' for k, v in hidden.items()
        )
        client_row = await db._pool.fetchrow(
            "SELECT client_name FROM oauth_clients WHERE client_id = $1", form["client_id"]
        )
        client_name = client_row["client_name"] if client_row else form["client_id"]
        return HTMLResponse(
            _verify_html(client_name, email, hidden_inputs, error="Invalid or expired code")
        )

    # Create user + session
    user = await db.get_or_create_user(email)
    session_id = await db.create_session(user["id"])

    # Now show consent page
    hidden = {}
    for key in ("client_id", "redirect_uri", "code_challenge",
                "redirect_uri_provided_explicitly", "state", "scope", "resource"):
        val = form.get(key)
        if val:
            hidden[key] = val
    hidden_inputs = "\n".join(
        f'<input type="hidden" name="{k}" value="{_esc(v)}">' for k, v in hidden.items()
    )
    client_row = await db._pool.fetchrow(
        "SELECT client_name FROM oauth_clients WHERE client_id = $1", form["client_id"]
    )
    client_name = client_row["client_name"] if client_row else form["client_id"]

    response = HTMLResponse(_consent_html(client_name, email, hidden_inputs))
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return response


@router.post("/authorize/approve")
async def authorize_approve(request: Request):
    """User approved — create authorization code and redirect."""
    form = await request.form()
    db = request.app.state.db

    # Get user from session
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return HTMLResponse("<h1>Session expired</h1><p>Please try again.</p>", status_code=401)

    session = await db.get_session(session_id)
    if not session:
        return HTMLResponse("<h1>Session expired</h1><p>Please try again.</p>", status_code=401)

    oauth_provider = request.app.state.oauth_provider
    scopes = form.get("scope", "").split() if form.get("scope") else []

    redirect_url = await oauth_provider.create_authorization_code(
        client_id=form["client_id"],
        user_id=session["user_id"],
        redirect_uri=form["redirect_uri"],
        redirect_uri_provided_explicitly=(
            form.get("redirect_uri_provided_explicitly", "true") == "true"
        ),
        code_challenge=form["code_challenge"],
        scopes=scopes,
        state=form.get("state"),
        resource=form.get("resource"),
    )

    return RedirectResponse(url=redirect_url, status_code=302)


@router.post("/authorize/deny")
async def authorize_deny(request: Request):
    """User denied — redirect with error."""
    form = await request.form()
    from mcp.server.auth.provider import construct_redirect_uri

    redirect_url = construct_redirect_uri(
        form["redirect_uri"],
        error="access_denied",
        error_description="User denied the authorization request",
        state=form.get("state"),
    )
    return RedirectResponse(url=redirect_url, status_code=302)


# -- HTML templates --

def _esc(v: str) -> str:
    """Escape HTML attribute value."""
    return v.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


_STYLE = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f5f5f5; display: flex; justify-content: center;
         align-items: center; min-height: 100vh; padding: 1rem; }
  .card { background: #fff; border-radius: 12px; padding: 2rem;
          max-width: 400px; width: 100%; box-shadow: 0 2px 8px rgba(0,0,0,.08); }
  h1 { font-size: 1.25rem; margin-bottom: .5rem; }
  .sub { color: #666; font-size: .9rem; margin-bottom: 1.5rem; }
  .client-name { font-weight: 600; color: #111; }
  input[type=email], input[type=text] {
    width: 100%; padding: .75rem; border: 1px solid #ddd; border-radius: 8px;
    font-size: 1rem; margin-bottom: 1rem; }
  input:focus { outline: none; border-color: #0066ff; }
  .btn { width: 100%; padding: .75rem; border: none; border-radius: 8px;
         font-size: 1rem; cursor: pointer; font-weight: 500; }
  .btn-primary { background: #0066ff; color: #fff; margin-bottom: .5rem; }
  .btn-primary:hover { background: #0052cc; }
  .btn-deny { background: #f5f5f5; color: #666; }
  .btn-deny:hover { background: #eee; }
  .error { color: #e00; font-size: .85rem; margin-bottom: 1rem; }
  .user { background: #f0f4ff; border-radius: 8px; padding: .75rem;
          margin-bottom: 1.5rem; font-size: .9rem; }
</style>
"""


def _consent_html(client_name: str, user_email: str, hidden_inputs: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Authorize — magpie</title>{_STYLE}</head>
<body><div class="card">
  <h1>Authorize access</h1>
  <p class="sub"><span class="client-name">{_esc(client_name)}</span>
    wants to access your magpie knowledge base.</p>
  <div class="user">Signed in as <strong>{_esc(user_email)}</strong></div>
  <form method="post" action="/oauth/authorize/approve">
    {hidden_inputs}
    <button type="submit" class="btn btn-primary">Approve</button>
  </form>
  <form method="post" action="/oauth/authorize/deny">
    {hidden_inputs}
    <button type="submit" class="btn btn-deny">Deny</button>
  </form>
</div></body></html>"""


def _login_html(client_name: str, hidden_inputs: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in — magpie</title>{_STYLE}</head>
<body><div class="card">
  <h1>Sign in to magpie</h1>
  <p class="sub"><span class="client-name">{_esc(client_name)}</span>
    wants to access your knowledge base. Sign in to continue.</p>
  <form method="post" action="/oauth/authorize/login">
    {hidden_inputs}
    <input type="email" name="email" placeholder="you@example.com" required autofocus>
    <button type="submit" class="btn btn-primary">Send code</button>
  </form>
</div></body></html>"""


def _verify_html(client_name: str, email: str, hidden_inputs: str, error: str | None = None) -> str:
    error_html = f'<p class="error">{_esc(error)}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Verify — magpie</title>{_STYLE}</head>
<body><div class="card">
  <h1>Check your email</h1>
  <p class="sub">We sent a code to <strong>{_esc(email)}</strong></p>
  {error_html}
  <form method="post" action="/oauth/authorize/verify">
    {hidden_inputs}
    <input type="text" name="code" placeholder="000000" pattern="[0-9]{{6}}" maxlength="6"
           inputmode="numeric" autocomplete="one-time-code" required autofocus>
    <button type="submit" class="btn btn-primary">Verify</button>
  </form>
</div></body></html>"""
