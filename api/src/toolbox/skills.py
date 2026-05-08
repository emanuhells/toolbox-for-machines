"""Skill cards — machine-readable tool definitions for agent discovery."""

from fastapi import APIRouter

router = APIRouter()

SKILLS = {
    "version": "1.1.0",
    "skills": [
        {
            "id": "search",
            "endpoint": "POST /v1/search",
            "description": "Search the web via SearXNG. Returns structured results as JSON.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "default": 10, "description": "Max results (1-50)"},
                    "categories": {"type": "string", "default": "general", "description": "Category: general, news, images, science, it"},
                },
                "required": ["query"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "results": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "url": {"type": "string"}, "snippet": {"type": "string"}, "engine": {"type": "string"}}}},
                    "query": {"type": "string"},
                    "count": {"type": "integer"},
                },
            },
            "when_to_use": "You need to find URLs, discover information, or identify sources on a topic.",
            "when_not_to_use": "You already have the URL (use fetch). You need page content (use fetch).",
            "examples": [
                {
                    "request": {"query": "fastapi websocket tutorial", "limit": 3},
                    "response": {"results": [{"title": "WebSockets - FastAPI", "url": "https://fastapi.tiangolo.com/advanced/websockets/", "snippet": "WebSocket endpoint documentation...", "engine": "google"}], "query": "fastapi websocket tutorial", "count": 1}
                }
            ],
            "constraints": [
                "Returns 0 results if upstream engines rate-limit (retries once automatically)",
                "Science/IT categories are slower (up to 20s vs 10s for general)",
                "Results are cached for 5 minutes"
            ],
        },
        {
            "id": "fetch",
            "endpoint": "POST /v1/fetch",
            "description": "Fetch a URL using a stealth browser. Returns clean extracted content as markdown or plain text. Handles JS-rendered pages and bot-protected sites.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                    "format": {"type": "string", "enum": ["markdown", "text"], "default": "markdown", "description": "Output format"},
                    "screenshot": {"type": "boolean", "default": False, "description": "Include base64 PNG screenshot in response"},
                    "wait_for": {"type": "string", "description": "CSS selector to wait for before extracting (3s timeout)"},
                    "wait_ms": {"type": "integer", "default": 0, "maximum": 20000, "description": "Extra wait time in ms after page load"},
                },
                "required": ["url"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "final_url": {"type": "string", "description": "URL after redirects"},
                    "title": {"type": "string"},
                    "content": {"type": "string", "description": "Clean extracted text/markdown"},
                    "format": {"type": "string"},
                    "word_count": {"type": "integer"},
                    "screenshot_b64": {"type": "string", "description": "PNG screenshot as base64 (only if requested)"},
                },
            },
            "when_to_use": "You need the content of a specific URL. The page uses JavaScript. The site blocks bots.",
            "when_not_to_use": "You need to find URLs first (use search). You only need structured data (use fetch then extract).",
            "examples": [
                {
                    "request": {"url": "https://blog.rust-lang.org/", "format": "markdown"},
                    "response": {"url": "https://blog.rust-lang.org/", "final_url": "https://blog.rust-lang.org/", "title": "Rust Blog", "content": "# Rust Blog\n\n## Latest Posts\n...", "format": "markdown", "word_count": 1523, "screenshot_b64": None}
                },
                {
                    "request": {"url": "https://example.com", "screenshot": True},
                    "response": {"url": "https://example.com", "final_url": "https://example.com", "title": "Example Domain", "content": "...", "format": "markdown", "word_count": 17, "screenshot_b64": "iVBORw0KGgo..."}
                }
            ],
            "constraints": [
                "Requests are serialized (one page at a time) — don't fire 10 fetches in parallel expecting speed",
                "wait_for selector times out after 3 seconds if not found (non-fatal, page still returned)",
                "Unreachable URLs take ~20s to fail",
                "Returns 502 for unreachable URLs",
                "Cached for 30 minutes (screenshots bypass cache)",
                "Max page load timeout: 20 seconds"
            ],
        },
        {
            "id": "describe",
            "endpoint": "POST /v1/describe",
            "description": "Describe an image or webpage screenshot using a vision model. Returns a text description of visual content.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "page_url": {"type": "string", "description": "URL of webpage to screenshot and describe (RECOMMENDED for agents)"},
                    "image_url": {"type": "string", "description": "Direct URL to an image file"},
                    "image_b64": {"type": "string", "description": "Base64-encoded image (unreliable through agent tool calls — prefer page_url)"},
                    "prompt": {"type": "string", "default": "Describe this image concisely.", "description": "Custom prompt for the vision model"},
                    "wait_for": {"type": "string", "description": "CSS selector to wait for before screenshotting (only with page_url)"},
                    "wait_ms": {"type": "integer", "default": 0, "maximum": 20000, "description": "Extra wait in ms after page load (only with page_url)"},
                },
            },
            "output_schema": {
                "type": "object",
                "properties": {"description": {"type": "string"}},
            },
            "when_to_use": "You need to understand visual content: screenshots, charts, diagrams, UI layouts, photos.",
            "when_not_to_use": "You need text content from a page (use fetch). You already have text (use summarize).",
            "examples": [
                {
                    "description": "Screenshot and describe a webpage (recommended)",
                    "request": {"page_url": "https://news.ycombinator.com", "prompt": "What stories are on the front page?"},
                    "response": {"description": "The Hacker News front page shows 30 stories. Top stories include..."}
                },
                {
                    "description": "Describe an image by URL",
                    "request": {"image_url": "https://example.com/chart.png", "prompt": "What data does this chart show?"},
                    "response": {"description": "A bar chart showing quarterly revenue from Q1-Q4 2024..."}
                }
            ],
            "constraints": [
                "PREFER page_url over image_b64 — base64 data gets corrupted passing through most agent tool-call mechanisms",
                "Shares LLM concurrency slot with summarize and extract — may queue behind them",
                "Slowest endpoint: 4-6s per call (screenshot + vision model inference)",
                "Cached for 1 hour (same page_url + prompt = cache hit)",
                "If image_url returns a non-image content-type, falls back to browser screenshot"
            ],
        },
        {
            "id": "transcribe",
            "endpoint": "POST /v1/transcribe",
            "description": "Transcribe audio to text using whisper.cpp. Processing time is roughly 1x realtime (5 min audio ≈ 5 min processing).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "audio_url": {"type": "string", "description": "URL of audio file to download and transcribe"},
                    "audio_b64": {"type": "string", "description": "Base64-encoded audio data"},
                    "mime_type": {"type": "string", "default": "audio/wav", "description": "MIME type: audio/wav, audio/mp3, audio/ogg, audio/webm, audio/flac"},
                    "language": {"type": "string", "default": "en", "description": "Language hint (ISO 639-1: en, es, fr, de, pt, ja, zh...)"},
                },
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "transcript": {"type": "string"},
                    "language": {"type": "string"},
                },
            },
            "when_to_use": "You have an audio file (URL or base64) and need the spoken content as text.",
            "when_not_to_use": "You already have text. The audio is music (not speech).",
            "examples": [
                {
                    "request": {"audio_url": "https://example.com/meeting.mp3", "language": "en"},
                    "response": {"transcript": "Welcome everyone to today's standup. Let's start with...", "language": "en"}
                }
            ],
            "constraints": [
                "Processing time ≈ audio duration (5 min audio takes ~5 min)",
                "Timeout: 120 seconds (limits practical audio length to ~2 min)",
                "Not cached (each audio file is unique)",
                "CPU-only — does not use GPU, does not block LLM endpoints"
            ],
        },
        {
            "id": "summarize",
            "endpoint": "POST /v1/summarize",
            "description": "Summarize long text into a concise version. Supports brief, detailed, and bullet-point styles.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to summarize (max ~6800 chars, truncated if longer)"},
                    "max_tokens": {"type": "integer", "default": 200, "minimum": 20, "maximum": 500, "description": "Maximum tokens in the summary"},
                    "style": {"type": "string", "enum": ["brief", "detailed", "bullets"], "default": "brief", "description": "Output style"},
                },
                "required": ["text"],
            },
            "output_schema": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
            },
            "when_to_use": "You have text longer than ~500 chars and need a shorter version preserving key information.",
            "when_not_to_use": "You need structured data from text (use extract). Text is already short enough to use directly.",
            "examples": [
                {
                    "request": {"text": "Python is a high-level programming language created by Guido van Rossum in 1991. It emphasizes code readability...", "max_tokens": 50, "style": "brief"},
                    "response": {"summary": "Python is a readable, multi-paradigm language created in 1991 by Guido van Rossum, known for its comprehensive standard library."}
                },
                {
                    "request": {"text": "[long article text]", "max_tokens": 150, "style": "bullets"},
                    "response": {"summary": "- Key point one\n- Key point two\n- Key point three"}
                }
            ],
            "constraints": [
                "Input truncated to ~6800 characters (longer text is cut, not rejected)",
                "Shares LLM concurrency slot with describe and extract — may queue",
                "Cached for 1 hour (same text + style + max_tokens = cache hit)",
                "Latency scales with input size: ~1s for 100 chars, ~4s for 6800 chars"
            ],
        },
        {
            "id": "extract",
            "endpoint": "POST /v1/extract",
            "description": "Extract structured JSON from text using a provided schema. Output is guaranteed valid JSON matching your schema.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to extract data from (max ~4800 chars, truncated if longer)"},
                    "schema": {"type": "object", "description": "JSON Schema the output must match (max ~2000 chars when serialized)"},
                },
                "required": ["text", "schema"],
            },
            "output_schema": {
                "type": "object",
                "properties": {"data": {"type": "object", "description": "Extracted data matching your schema"}},
            },
            "when_to_use": "You need specific structured fields from unstructured text (articles, profiles, listings, logs).",
            "when_not_to_use": "You need a general summary (use summarize). Data is already structured JSON.",
            "examples": [
                {
                    "request": {
                        "text": "John Smith, 34, lives in San Francisco. Senior Engineer at Google. Email: john@gmail.com",
                        "schema": {"type": "object", "properties": {"name": {"type": "string"}, "age": {"type": "integer"}, "city": {"type": "string"}, "company": {"type": "string"}, "email": {"type": "string"}}}
                    },
                    "response": {"data": {"name": "John Smith", "age": 34, "city": "San Francisco", "company": "Google", "email": "john@gmail.com"}}
                },
                {
                    "request": {
                        "text": "Product: Widget Pro, $29.99, available in red and blue, weighs 0.5kg",
                        "schema": {"type": "object", "properties": {"name": {"type": "string"}, "price": {"type": "number"}, "colors": {"type": "array", "items": {"type": "string"}}, "weight_kg": {"type": "number"}}}
                    },
                    "response": {"data": {"name": "Widget Pro", "price": 29.99, "colors": ["red", "blue"], "weight_kg": 0.5}}
                }
            ],
            "constraints": [
                "Input truncated to ~4800 characters",
                "Schema must serialize to <2000 characters (returns 400 if too large, ~20 fields max)",
                "Fields not found in text are returned as null",
                "Shares LLM concurrency slot with describe and summarize",
                "Cached for 1 hour",
                "Supports nested objects and arrays in schema"
            ],
        },
    ],
}


@router.get("/skills")
async def get_skills():
    """Return machine-readable skill cards for all available tools."""
    return SKILLS
