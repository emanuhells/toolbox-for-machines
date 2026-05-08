"""MCP server — exposes Toolbox tools via Model Context Protocol.

Mounted as a sub-application on the FastAPI app at /mcp.
Uses stateless HTTP mode (no session affinity required).
"""

import json
import logging

from mcp.server.fastmcp import FastMCP

from toolbox.services import (
    ToolboxError,
    describe,
    extract,
    fetch,
    search,
    summarize,
    transcribe,
)

log = logging.getLogger("toolbox.mcp")

# ── MCP Server Instance ───────────────────────────────────────────────────────

mcp = FastMCP(
    name="toolbox",
    instructions=(
        "Toolbox provides 6 tools for AI agents: web search, web fetch (stealth browser), "
        "image/screenshot description (vision), audio transcription, text summarization, "
        "and structured data extraction. All tools are stateless — fire a request, get a result."
    ),
    stateless_http=True,
)


# ── Tool: search ──────────────────────────────────────────────────────────────


@mcp.tool(
    name="search",
    description=(
        "Search the web using a private meta-search engine (SearXNG). "
        "Returns structured results with title, URL, snippet, and source engine.\n\n"
        "Use when: You need to find URLs, discover information, or identify sources for a topic.\n"
        "Do NOT use when: You already have the URL you need (use fetch instead)."
    ),
    annotations={"readOnlyHint": True, "openWorldHint": True},
)
async def tool_search(query: str, limit: int = 10, categories: str = "general") -> str:
    """Search the web. Returns JSON with results array."""
    try:
        result = await search(query, limit, categories)
    except ToolboxError as e:
        raise ValueError(str(e))
    return json.dumps(result)


# ── Tool: fetch ───────────────────────────────────────────────────────────────


@mcp.tool(
    name="fetch",
    description=(
        "Fetch a URL using a stealth browser (anti-bot detection bypass). "
        "Returns clean extracted content as markdown or plain text. "
        "Handles JavaScript-rendered pages, paywalls, and bot-protected sites.\n\n"
        "Use when: You need the content of a specific URL.\n"
        "Do NOT use when: You need to find URLs first (use search). "
        "You need structured data from a page (use fetch + extract)."
    ),
    annotations={"readOnlyHint": True, "openWorldHint": True},
)
async def tool_fetch(url: str, format: str = "markdown", wait_for: str | None = None, wait_ms: int = 0) -> str:
    """Fetch a URL and return extracted content."""
    try:
        result = await fetch(url, format, screenshot=False, wait_for=wait_for, wait_ms=wait_ms)
    except ToolboxError as e:
        raise ValueError(str(e))
    return json.dumps(result)


# ── Tool: describe ────────────────────────────────────────────────────────────


@mcp.tool(
    name="describe",
    description=(
        "Describe an image or webpage screenshot using a vision model. "
        "Three input modes:\n"
        "- page_url: Screenshot a webpage and describe it (RECOMMENDED for agents)\n"
        "- image_url: Direct URL to an image file\n"
        "- image_b64: Base64-encoded image data (UNRELIABLE through tool-call mechanisms — prefer page_url)\n\n"
        "Use when: You need to understand visual content — images, screenshots, charts, UI layouts.\n"
        "Do NOT use when: You need text content from a webpage (use fetch instead).\n\n"
        "⚠️ PREFER page_url — it keeps large base64 data server-side. image_b64 gets corrupted in transit."
    ),
    annotations={"readOnlyHint": True, "openWorldHint": True},
)
async def tool_describe(
    prompt: str = "Describe this image concisely.",
    image_url: str | None = None,
    image_b64: str | None = None,
    page_url: str | None = None,
    wait_for: str | None = None,
    wait_ms: int = 0,
) -> str:
    """Describe an image using vision model."""
    try:
        result = await describe(prompt, image_url, image_b64, page_url, wait_for, wait_ms)
    except ToolboxError as e:
        raise ValueError(str(e))
    return json.dumps(result)


# ── Tool: transcribe ──────────────────────────────────────────────────────────


@mcp.tool(
    name="transcribe",
    description=(
        "Transcribe audio to text using whisper.cpp. "
        "Supports audio via URL or base64-encoded data.\n\n"
        "Use when: You have an audio file that needs to be converted to text.\n"
        "Do NOT use when: You have text content already."
    ),
    annotations={"readOnlyHint": True, "openWorldHint": False},
)
async def tool_transcribe(
    audio_url: str | None = None,
    audio_b64: str | None = None,
    mime_type: str = "audio/wav",
    language: str = "en",
) -> str:
    """Transcribe audio to text."""
    try:
        result = await transcribe(audio_url, audio_b64, mime_type, language)
    except ToolboxError as e:
        raise ValueError(str(e))
    return json.dumps(result)


# ── Tool: summarize ───────────────────────────────────────────────────────────


@mcp.tool(
    name="summarize",
    description=(
        "Summarize long text into a concise version using an LLM. "
        "Supports brief, detailed, and bullet-point styles. "
        "Maximum input: ~6800 characters.\n\n"
        "Use when: You have text longer than 500 characters that needs condensing.\n"
        "Do NOT use when: Text is already short enough to use directly."
    ),
    annotations={"readOnlyHint": True, "openWorldHint": False},
)
async def tool_summarize(text: str, max_tokens: int = 200, style: str = "brief") -> str:
    """Summarize text."""
    try:
        result = await summarize(text, max_tokens, style)
    except ToolboxError as e:
        raise ValueError(str(e))
    return json.dumps(result)


# ── Tool: extract ─────────────────────────────────────────────────────────────


@mcp.tool(
    name="extract",
    description=(
        "Extract structured JSON data from unstructured text using an LLM with schema constraints. "
        "Provide a JSON Schema describing the desired output structure. "
        "Maximum input: ~4800 characters.\n\n"
        "Use when: You need to pull specific structured fields from messy text (articles, HTML, logs, etc.)\n"
        "Do NOT use when: You just need a summary (use summarize). You need the raw text (use fetch)."
    ),
    annotations={"readOnlyHint": True, "openWorldHint": False},
)
async def tool_extract(text: str, schema: dict) -> str:
    """Extract structured data from text."""
    try:
        result = await extract(text, schema)
    except ToolboxError as e:
        raise ValueError(str(e))
    return json.dumps(result)
