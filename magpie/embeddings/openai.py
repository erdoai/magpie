import logging

import httpx

from magpie.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class OpenAIEmbeddings(EmbeddingProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        dims: int = 1536,
    ):
        self._api_key = api_key
        self._model = model
        self._dims = dims
        self._client = httpx.AsyncClient(
            base_url="https://api.openai.com",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )

    @property
    def dimensions(self) -> int:
        return self._dims

    async def embed(self, text: str) -> list[float]:
        resp = await self._client.post(
            "/v1/embeddings",
            json={"model": self._model, "input": text},
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        resp = await self._client.post(
            "/v1/embeddings",
            json={"model": self._model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        # Sort by index to maintain order
        data.sort(key=lambda x: x["index"])
        return [d["embedding"] for d in data]

    async def close(self) -> None:
        await self._client.aclose()
