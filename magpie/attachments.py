"""Attachment helpers shared by REST routes and MCP tools.

Attachments are owned by knowledge entries. Each has a stable handle
``magpie:<attachment_id>`` that downstream tooling can pass around.

Role conventions (so agents get deterministic joins on brand/landing-page
work): logo-primary, logo-mono-white, favicon-32x32, apple-icon-180x180,
hero-*, product-*, customer-logo-*, headshot-*, screenshot-*, query-*, source.
"""

KINDS = ("image", "sql", "text", "pdf", "file")

# Media types safe to serve from /public/assets — images only, no
# SQL/text/PDF/document leakage through the public route.
BROWSER_SAFE_MEDIA = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "image/x-icon",
    "image/vnd.microsoft.icon",
    "image/avif",
}

TEXT_MEDIA_PREFIXES = ("text/",)
TEXT_MEDIA_EXACT = {
    "application/json",
    "application/x-sql",
    "application/sql",
    "application/xml",
    "application/x-yaml",
}


def infer_kind(filename: str, media_type: str) -> str:
    lower = filename.lower()
    if media_type.startswith("image/"):
        return "image"
    if lower.endswith(".sql") or media_type in ("application/sql", "application/x-sql"):
        return "sql"
    if media_type == "application/pdf" or lower.endswith(".pdf"):
        return "pdf"
    if media_type.startswith(TEXT_MEDIA_PREFIXES) or media_type in TEXT_MEDIA_EXACT:
        return "text"
    return "file"


def is_textual(att: dict) -> bool:
    return att["kind"] in ("sql", "text")


def is_browser_safe(media_type: str) -> bool:
    return media_type.lower().split(";")[0].strip() in BROWSER_SAFE_MEDIA


def storage_key_for(org_id: str | None, entry_id: str, att_id: str, filename: str) -> str:
    org_part = org_id or "global"
    return f"{org_part}/{entry_id}/{att_id}/{filename}"


def handle_for(att_id: str) -> str:
    return f"magpie:{att_id}"


def public_url_for(att: dict, settings) -> str | None:
    """Stable public URL for browser-safe, explicitly public attachments.

    Root-relative unless MAGPIE_ASSET_PUBLIC_BASE_URL is set, so generated
    pages don't embed expiring signed URLs.
    """
    if not att.get("public") or not is_browser_safe(att["media_type"]):
        return None
    base = (settings.asset_public_base_url or "").rstrip("/")
    return f"{base}/public/assets/{att['id']}"


async def attachment_payload(
    att: dict, storage, settings, include_content: bool = True
) -> dict:
    """API/MCP-facing view of an attachment: handle, URLs, inline content."""
    payload = {
        "id": att["id"],
        "entry_id": att["entry_id"],
        "handle": handle_for(att["id"]),
        "kind": att["kind"],
        "filename": att["filename"],
        "media_type": att["media_type"],
        "byte_size": att["byte_size"],
        "description": att.get("description"),
        "role": att.get("role"),
        "public": att.get("public", False),
        "created_at": att.get("created_at"),
        "download_url": f"/api/attachments/{att['id']}/download",
        "public_url": public_url_for(att, settings),
        "content_text": None,
    }

    if storage:
        signed = await storage.signed_url(att["storage_key"])
        if signed:
            payload["download_url"] = signed

    if (
        include_content
        and storage
        and is_textual(att)
        and att["byte_size"] <= settings.attachment_inline_limit
    ):
        data = await storage.get(att["storage_key"])
        if data is not None:
            try:
                payload["content_text"] = data.decode("utf-8")
            except UnicodeDecodeError:
                pass

    return payload
