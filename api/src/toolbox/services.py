"""Pure async service functions shared by REST and MCP handlers.

Each function:
- Accepts plain parameters (no Request objects or Pydantic models)
- Returns a plain dict
- Raises ToolboxError on validation or backend errors
"""

import asyncio
import base64
import hashlib
import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

from toolbox.cache import cache
from toolbox.config import settings
from toolbox.errors import ToolboxError
from toolbox.http_client import get_http_client
from toolbox.llm import chat
from toolbox.prompts import DESCRIBE, EXTRACT, SUMMARIZE
from toolbox.url_validator import validate_external_url

log = logging.getLogger("toolbox.services")


# ── Internal helpers ───────────────────────────────────────────────────────────

_SLOW_CATEGORIES = {"it", "science", "files", "social media"}
_SLOW_TIMEOUT = 20
_DEFAULT_TIMEOUT = 10


def _extract_html_content(html: str, output_format: str) -> str:
    """Extract main content from HTML using trafilatura."""
    try:
        import trafilatura

        result = trafilatura.extract(
            html,
            include_links=True,
            include_formatting=(output_format == "markdown"),
            output_format="txt" if output_format == "text" else "markdown",
        )
        return result or ""
    except Exception as e:
        log.warning("trafilatura extraction failed: %s", e)
        return ""


# ── search ─────────────────────────────────────────────────────────────────────


async def search(query: str, limit: int = 10, categories: str = "general") -> dict:
    """Search the web via SearXNG. Returns empty results on backend failure."""
    if not query.strip():
        return {"results": [], "query": query, "count": 0}

    cache_key = cache.make_key("search", {"query": query, "limit": limit, "categories": categories})
    cached = cache.get(cache_key)
    if cached:
        return cached

    http = get_http_client()
    params = {"q": query, "format": "json", "categories": categories}
    timeout = _SLOW_TIMEOUT if categories.lower() in _SLOW_CATEGORIES else _DEFAULT_TIMEOUT

    try:
        r = await http.get(f"{settings.searxng_url}/search", params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.error("SearXNG request failed (category=%s, timeout=%ds): %s", categories, timeout, e)
        if categories.lower() in _SLOW_CATEGORIES:
            log.info("Retrying with 'general' category as fallback for query: %s", query)
            params["categories"] = "general"
            try:
                r = await http.get(f"{settings.searxng_url}/search", params=params, timeout=_DEFAULT_TIMEOUT)
                r.raise_for_status()
                data = r.json()
            except Exception as e2:
                log.error("SearXNG fallback also failed: %s", e2)
                return {"results": [], "query": query, "count": 0}
        else:
            return {"results": [], "query": query, "count": 0}

    raw_results = data.get("results", [])[:limit]

    # Retry once if empty (upstream engines may be rate-limiting)
    if not raw_results and len(query.strip()) > 2:
        await asyncio.sleep(1)
        try:
            r = await http.get(f"{settings.searxng_url}/search", params=params, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            raw_results = data.get("results", [])[:limit]
        except Exception:
            pass  # If retry also fails, return empty

    results = [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
            "engine": item.get("engine", "unknown"),
        }
        for item in raw_results
    ]

    response = {"results": results, "query": query, "count": len(results)}
    cache.set(cache_key, response, ttl_seconds=300)
    return response


# ── fetch ──────────────────────────────────────────────────────────────────────


async def fetch(
    url: str,
    format: str = "markdown",
    screenshot: bool = False,
    wait_for: str | None = None,
    wait_ms: int = 0,
) -> dict[str, Any]:
    """Fetch a URL via Camoufox, falling back to direct HTTP. Raises ToolboxError on failure."""
    validate_external_url(url)
    cache_key = None
    if not screenshot:
        cache_params: dict[str, Any] = {"url": url, "format": format}
        if wait_for:
            cache_params["wait_for"] = wait_for
        if wait_ms:
            cache_params["wait_ms"] = wait_ms
        cache_key = cache.make_key("fetch", cache_params)
        cached = cache.get(cache_key)
        if cached:
            return cached

    http = get_http_client()
    payload = {"url": url, "screenshot": screenshot, "wait_for": wait_for, "wait_ms": wait_ms}

    title = ""
    final_url = url
    content = ""
    screenshot_b64 = None

    try:
        r = await http.post(
            f"{settings.camoufox_url}/fetch",
            json=payload,
            timeout=settings.fetch_timeout_seconds,
        )
        r.raise_for_status()
        data = r.json()

        html = data.get("html", "")
        title = data.get("title", "")
        final_url = data.get("final_url", url)
        screenshot_b64 = data.get("screenshot_b64")

        content = _extract_html_content(html, format)
        if not content:
            content = data.get("text", "")

    except Exception as e:
        error_str = str(e).lower()
        is_connection_error = any(term in error_str for term in [
            "timed out", "timeout", "unreachable", "connection refused",
            "name or service not known", "no route", "network is unreachable",
            "connect call failed", "502 bad gateway",
        ])
        if is_connection_error:
            log.warning("Camoufox connection failed for %s: %s — skipping fallback", url, e)
            raise ToolboxError(
                "Unable to fetch this URL. The page may be unreachable.",
                status_code=502,
            )
        log.warning("Camoufox fetch failed for %s: %s — trying lightweight fallback", url, e)
        screenshot_b64 = None
        try:
            fallback_r = await http.get(
                url,
                timeout=5,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            fallback_r.raise_for_status()
            html = fallback_r.text
            title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            title = title_match.group(1).strip() if title_match else ""
            final_url = str(fallback_r.url)
            content = _extract_html_content(html, format)
            if not content or len(content) <= 50:
                raise ToolboxError(
                    "Unable to fetch this URL. The page may be unreachable or blocking automated access.",
                    status_code=502,
                )
            log.info("Lightweight fallback succeeded for %s (%d words)", url, len(content.split()))
        except ToolboxError:
            raise
        except Exception as fallback_err:
            log.debug("Lightweight fallback also failed for %s: %s", url, fallback_err)
            raise ToolboxError(
                "Unable to fetch this URL. The page may be unreachable or blocking automated access.",
                status_code=502,
            ) from fallback_err

    response: dict[str, Any] = {
        "url": url,
        "final_url": final_url,
        "title": title,
        "content": content,
        "format": format,
        "word_count": len(content.split()),
    }
    response["screenshot_b64"] = screenshot_b64 if screenshot else None

    if cache_key:
        cache.set(cache_key, response, ttl_seconds=1800)

    return response


# ── describe ───────────────────────────────────────────────────────────────────


async def describe(
    prompt: str = "Describe this image concisely.",
    image_url: str | None = None,
    image_b64: str | None = None,
    page_url: str | None = None,
    wait_for: str | None = None,
    wait_ms: int = 0,
) -> dict:
    """Describe an image via vision model. Raises ToolboxError on failure."""
    if not image_url and not image_b64 and not page_url:
        raise ToolboxError("One of image_url, image_b64, or page_url is required.", status_code=400)

    http = get_http_client()
    image_data_url: str

    if page_url:
        validate_external_url(page_url)
        cache_key = cache.make_key("describe", {"page_url": page_url, "prompt": prompt})
        cached = cache.get(cache_key)
        if cached:
            return cached
        try:
            r = await http.post(
                f"{settings.camoufox_url}/fetch",
                json={"url": page_url, "screenshot": True, "wait_for": wait_for, "wait_ms": wait_ms},
                timeout=settings.fetch_timeout_seconds,
            )
            r.raise_for_status()
            screenshot_b64 = r.json().get("screenshot_b64")
            if not screenshot_b64:
                raise ToolboxError("No screenshot returned from browser", status_code=502)
            image_data_url = f"data:image/png;base64,{screenshot_b64}"
        except ToolboxError:
            raise
        except Exception as e:
            log.error("Failed to screenshot page %s: %s", page_url, e)
            raise ToolboxError(f"Failed to screenshot page: {e}", status_code=502) from e

    elif image_url:
        validate_external_url(image_url)
        cache_key = cache.make_key("describe", {"url": image_url, "prompt": prompt})
        cached = cache.get(cache_key)
        if cached:
            return cached
        parsed = urlparse(image_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        headers = {
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": origin + "/",
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "same-origin",
        }
        try:
            r = await http.get(image_url, timeout=15, headers=headers)
            r.raise_for_status()
            content_type = r.headers.get("content-type", "image/png").split(";")[0]
            if not content_type.startswith("image/"):
                raise ValueError(f"Response is not an image: {content_type}")
            b64 = base64.b64encode(r.content).decode("ascii")
            image_data_url = f"data:{content_type};base64,{b64}"
        except Exception as e:
            log.warning("Direct image download failed for %s: %s — trying browser fallback", image_url, e)
            try:
                r = await http.post(
                    f"{settings.camoufox_url}/fetch",
                    json={"url": image_url, "screenshot": True},
                    timeout=settings.fetch_timeout_seconds,
                )
                r.raise_for_status()
                screenshot_b64 = r.json().get("screenshot_b64")
                if not screenshot_b64:
                    raise ToolboxError("Browser fallback returned no screenshot", status_code=502)
                image_data_url = f"data:image/png;base64,{screenshot_b64}"
            except ToolboxError:
                raise
            except Exception as e2:
                log.error("Browser fallback also failed for image %s: %s", image_url, e2)
                raise ToolboxError(
                    "Failed to download image: direct download and browser fallback both failed",
                    status_code=502,
                ) from e2

    else:
        cache_key = cache.make_key(
            "describe",
            {"b64_hash": hashlib.sha256(image_b64.encode()).hexdigest(), "prompt": prompt},
        )
        cached = cache.get(cache_key)
        if cached:
            return cached
        image_data_url = image_b64 if image_b64.startswith("data:") else f"data:image/png;base64,{image_b64}"

    messages = [
        {"role": "system", "content": DESCRIBE},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]

    try:
        description = await chat(messages, max_tokens=300)
    except Exception as e:
        log.error("LLM vision request failed: %s", e)
        raise ToolboxError(f"Vision model error: {e}", status_code=502) from e

    response = {"description": description}
    cache.set(cache_key, response, ttl_seconds=3600)
    return response


# ── transcribe ─────────────────────────────────────────────────────────────────


async def transcribe(
    audio_url: str | None = None,
    audio_b64: str | None = None,
    mime_type: str = "audio/wav",
    language: str = "en",
) -> dict:
    """Transcribe audio via whisper.cpp. Raises ToolboxError on failure."""
    if not audio_url and not audio_b64:
        raise ToolboxError("Either audio_url or audio_b64 is required.", status_code=400)

    http = get_http_client()

    if audio_url:
        validate_external_url(audio_url)
        try:
            r = await http.get(audio_url, timeout=30)
            r.raise_for_status()
            audio_bytes = r.content
        except Exception as e:
            log.error("Failed to download audio %s: %s", audio_url, e)
            raise ToolboxError(f"Failed to download audio: {e}", status_code=502) from e
    else:
        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception as e:
            raise ToolboxError(f"Invalid base64 audio: {e}", status_code=400) from e

    try:
        files = {"file": ("audio.wav", audio_bytes, mime_type)}
        data = {"language": language, "response_format": "json"}
        r = await http.post(
            f"{settings.whisper_url}/inference",
            files=files,
            data=data,
            timeout=120,
        )
        r.raise_for_status()
        result = r.json()
    except Exception as e:
        log.error("Whisper request failed: %s", e)
        raise ToolboxError(f"Whisper transcription error: {e}", status_code=502) from e

    transcript = result.get("text", "").strip()
    return {"transcript": transcript, "language": language}


# ── summarize ──────────────────────────────────────────────────────────────────


async def summarize(text: str, max_tokens: int = 200, style: str = "brief") -> dict:
    """Summarize text via LLM. Raises ToolboxError on failure."""
    if not text.strip():
        raise ToolboxError("Text cannot be empty.", status_code=400)

    cache_key = cache.make_key(
        "summarize",
        {"text_hash": hashlib.sha256(text.encode()).hexdigest(), "max_tokens": max_tokens, "style": style},
    )
    cached = cache.get(cache_key)
    if cached:
        return cached

    max_input_chars = 6800
    input_text = text[:max_input_chars]
    if len(text) > max_input_chars:
        input_text += "\n\n[... text truncated ...]"

    style_hint = ""
    if style == "bullets":
        style_hint = " Use bullet points."
    elif style == "detailed":
        style_hint = " Include supporting details."

    system_prompt = SUMMARIZE.format(max_tokens=max_tokens) + style_hint
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": input_text},
    ]

    try:
        summary = await chat(messages, max_tokens=max_tokens)
    except Exception as e:
        log.error("LLM summarize failed: %s", e)
        raise ToolboxError(f"Summarization error: {e}", status_code=502) from e

    response = {"summary": summary}
    cache.set(cache_key, response, ttl_seconds=3600)
    return response


# ── extract ────────────────────────────────────────────────────────────────────


async def extract(text: str, schema: dict) -> dict:
    """Extract structured data from text via LLM. Raises ToolboxError on failure."""
    if not text.strip():
        raise ToolboxError("Text cannot be empty.", status_code=400)
    if not schema:
        raise ToolboxError("Schema cannot be empty.", status_code=400)

    schema_str = json.dumps(schema, indent=2)
    if len(schema_str) > 2000:
        raise ToolboxError(
            f"Schema too large ({len(schema_str)} chars, max 2000). Reduce properties or descriptions.",
            status_code=400,
        )

    cache_key = cache.make_key(
        "extract",
        {"text_hash": hashlib.sha256(text.encode()).hexdigest(), "schema": schema},
    )
    cached = cache.get(cache_key)
    if cached:
        return cached

    max_input_chars = 4800
    input_text = text[:max_input_chars]
    system_prompt = EXTRACT.format(schema=schema_str)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": input_text},
    ]

    try:
        result = await chat(messages, max_tokens=400, response_format={"type": "json_object"})
    except Exception as e:
        log.error("LLM extract failed: %s", e)
        raise ToolboxError(f"Extraction error: {e}", status_code=502) from e

    try:
        cleaned = result.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1])
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        try:
            start = result.index("{")
            end = result.rindex("}") + 1
            data = json.loads(result[start:end])
        except (ValueError, json.JSONDecodeError):
            raise ToolboxError(f"LLM returned invalid JSON: {result[:300]}", status_code=502)

    response = {"data": data}
    cache.set(cache_key, response, ttl_seconds=3600)
    return response
