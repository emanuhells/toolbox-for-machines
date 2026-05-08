"""Shared HTTP client accessible to both REST and MCP handlers."""

import httpx

_client: httpx.AsyncClient | None = None


def init_http_client(timeout: float = 30.0) -> httpx.AsyncClient:
    """Initialize the shared HTTP client. Called during app lifespan startup."""
    global _client
    _client = httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    return _client


async def close_http_client() -> None:
    """Close the shared HTTP client. Called during app lifespan shutdown."""
    global _client
    if _client:
        await _client.aclose()
        _client = None


def get_http_client() -> httpx.AsyncClient:
    """Get the shared HTTP client. Raises if not initialized."""
    if _client is None:
        raise RuntimeError("HTTP client not initialized. App lifespan not started.")
    return _client
