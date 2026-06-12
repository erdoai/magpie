from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    # Database — Postgres with pgvector
    database_url: str = ""

    # Embeddings
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # Server
    host: str = "0.0.0.0"
    port: int = 8200

    # Auth — static API key (empty = no auth for API routes)
    api_key: str = ""
    session_secret: str = ""

    # OAuth — issuer URL for MCP OAuth (e.g. https://magpie.erdo.ai)
    # When set, enables OAuth on the /mcp endpoint
    oauth_issuer_url: str = ""

    # Extra hostnames allowed to reach /mcp (comma-separated). localhost and
    # the OAuth issuer host are always allowed.
    mcp_allowed_hosts: str = ""

    # Email OTP via Resend
    resend_api_key: str = ""
    resend_from: str = ""

    # Attachment storage
    # "local" (filesystem) or "s3" (S3-compatible: AWS, R2, MinIO, Railway)
    storage_provider: str = "local"
    storage_dir: str = "data/attachments"
    storage_bucket: str = ""
    storage_endpoint: str = ""
    storage_access_key_id: str = ""
    storage_secret_access_key: str = ""
    storage_region: str = "us-east-1"
    # Base URL for stable public asset links (e.g. https://magpie.erdo.ai)
    asset_public_base_url: str = ""

    # Inline limit for text/sql attachment content in API/MCP reads
    attachment_inline_limit: int = 16384
