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

    # Email OTP via Resend
    resend_api_key: str = ""
    resend_from: str = ""
