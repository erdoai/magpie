"""S3-compatible storage via httpx with AWS Signature V4.

Works with AWS S3, Cloudflare R2, MinIO, and Railway object storage —
anything S3-compatible. Uses path-style URLs (endpoint/bucket/key) for
broad compatibility. No boto3 dependency.
"""

import hashlib
import hmac
import logging
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

import httpx

logger = logging.getLogger(__name__)

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _signature_key(secret: str, date: str, region: str, service: str) -> bytes:
    k = _sign(f"AWS4{secret}".encode(), date)
    k = _sign(k, region)
    k = _sign(k, service)
    return _sign(k, "aws4_request")


def _uri_encode(value: str, encode_slash: bool = True) -> str:
    safe = "" if encode_slash else "/"
    return quote(value, safe=safe + "-_.~")


class S3Storage:
    def __init__(
        self,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        endpoint: str = "",
        region: str = "us-east-1",
    ):
        self._bucket = bucket
        self._access_key = access_key_id
        self._secret_key = secret_access_key
        self._region = region
        self._endpoint = (endpoint or f"https://s3.{region}.amazonaws.com").rstrip("/")
        self._host = urlsplit(self._endpoint).netloc
        self._client = httpx.AsyncClient(timeout=60)

    def _url(self, key: str) -> str:
        return f"{self._endpoint}/{self._bucket}/{_uri_encode(key, encode_slash=False)}"

    def _canonical_path(self, key: str) -> str:
        return f"/{self._bucket}/{_uri_encode(key, encode_slash=False)}"

    def _auth_headers(
        self,
        method: str,
        key: str,
        payload_hash: str,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date = now.strftime("%Y%m%d")

        headers = {
            "host": self._host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if extra_headers:
            headers.update({k.lower(): v for k, v in extra_headers.items()})

        signed_names = ";".join(sorted(headers))
        canonical_headers = "".join(
            f"{name}:{headers[name].strip()}\n" for name in sorted(headers)
        )
        canonical_request = (
            f"{method}\n{self._canonical_path(key)}\n\n"
            f"{canonical_headers}\n{signed_names}\n{payload_hash}"
        )
        scope = f"{date}/{self._region}/s3/aws4_request"
        string_to_sign = (
            f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n"
            f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
        )
        signature = hmac.new(
            _signature_key(self._secret_key, date, self._region, "s3"),
            string_to_sign.encode(),
            hashlib.sha256,
        ).hexdigest()

        headers["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self._access_key}/{scope},"
            f" SignedHeaders={signed_names}, Signature={signature}"
        )
        del headers["host"]  # httpx sets it
        return headers

    async def put(self, key: str, data: bytes, media_type: str) -> None:
        payload_hash = hashlib.sha256(data).hexdigest()
        headers = self._auth_headers(
            "PUT", key, payload_hash, {"content-type": media_type}
        )
        resp = await self._client.put(self._url(key), content=data, headers=headers)
        resp.raise_for_status()

    async def get(self, key: str) -> bytes | None:
        headers = self._auth_headers("GET", key, EMPTY_SHA256)
        resp = await self._client.get(self._url(key), headers=headers)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.content

    async def delete(self, key: str) -> None:
        headers = self._auth_headers("DELETE", key, EMPTY_SHA256)
        resp = await self._client.delete(self._url(key), headers=headers)
        if resp.status_code not in (200, 204, 404):
            resp.raise_for_status()

    async def signed_url(self, key: str, ttl_seconds: int = 3600) -> str | None:
        """Presigned GET URL (SigV4 query-string auth)."""
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date = now.strftime("%Y%m%d")
        scope = f"{date}/{self._region}/s3/aws4_request"

        params = {
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": f"{self._access_key}/{scope}",
            "X-Amz-Date": amz_date,
            "X-Amz-Expires": str(ttl_seconds),
            "X-Amz-SignedHeaders": "host",
        }
        canonical_query = "&".join(
            f"{_uri_encode(k)}={_uri_encode(v)}" for k, v in sorted(params.items())
        )
        canonical_request = (
            f"GET\n{self._canonical_path(key)}\n{canonical_query}\n"
            f"host:{self._host}\n\nhost\nUNSIGNED-PAYLOAD"
        )
        string_to_sign = (
            f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n"
            f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
        )
        signature = hmac.new(
            _signature_key(self._secret_key, date, self._region, "s3"),
            string_to_sign.encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"{self._url(key)}?{canonical_query}&X-Amz-Signature={signature}"

    async def close(self) -> None:
        await self._client.aclose()
