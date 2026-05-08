"""GET /v1/harness-prompt — Generate a ready-to-use integration guide for agents/harnesses."""

from typing import Optional

from fastapi import APIRouter, Query, Request

router = APIRouter()


def _build_prompt(toolbox_url: str) -> str:
    return f"""# Toolbox — Tool Service for Agents

Base URL: {toolbox_url}

You have 6 tools. All are POST requests returning JSON.

## Tools

### search
`POST /v1/search`
Find URLs and information on the web.
```json
{{"query": "your search terms", "limit": 5}}
→ {{"results": [{{"title": "...", "url": "...", "snippet": "..."}}], "count": N}}
```
Categories: general (default), news, images, science, it

### fetch
`POST /v1/fetch`
Get clean text/markdown from any URL. Handles JS and bot protection.
```json
{{"url": "https://...", "format": "markdown"}}
→ {{"content": "...", "title": "...", "word_count": N}}
```
Optional: `screenshot: true`, `wait_for: ".css-selector"` (3s timeout), `wait_ms: 2000`

### describe
`POST /v1/describe`
Describe images or screenshot webpages using vision AI.
```json
{{"page_url": "https://...", "prompt": "What is shown?"}}
→ {{"description": "The page shows..."}}
```
⚠️ PREFER `page_url` over `image_b64` — base64 gets corrupted through tool-call mechanisms.
Also accepts: `image_url` for direct image files.

### transcribe
`POST /v1/transcribe`
Audio to text. Processing ≈ realtime (5 min audio → 5 min wait).
```json
{{"audio_url": "https://...", "language": "en"}}
→ {{"transcript": "...", "language": "en"}}
```
Also accepts: `audio_b64`, `mime_type`

### summarize
`POST /v1/summarize`
Condense long text. Input truncated to ~6800 chars.
```json
{{"text": "...", "max_tokens": 100, "style": "brief"}}
→ {{"summary": "..."}}
```
Styles: brief (default), detailed, bullets

### extract
`POST /v1/extract`
Pull structured JSON from text. Guaranteed valid output matching your schema.
```json
{{"text": "John, 34, NYC, engineer at Google", "schema": {{"type": "object", "properties": {{"name": {{"type": "string"}}, "age": {{"type": "integer"}}}}}}}}
→ {{"data": {{"name": "John", "age": 34}}}}
```
Input truncated to ~4800 chars. Schema must be <2000 chars serialized (~20 fields max). Missing fields return null.

## Concurrency Rules

- **search, fetch, transcribe** → run in parallel, no limits
- **describe, summarize, extract** → share ONE slot, queue serially
- Don't fire describe+summarize+extract in parallel expecting speed — they queue anyway

## Common Patterns

**Research a topic:**
search → pick best URLs → fetch each → summarize content

**Visual verification:**
describe with page_url → read description

**Data extraction pipeline:**
fetch page → extract with schema → use structured data

## Errors

- 400: Bad input (missing required field, schema too large)
- 502: Backend failed (URL unreachable, LLM timeout)
- All errors include `{{"detail": "human-readable message"}}`

## MCP

Also available via Model Context Protocol: `POST {toolbox_url}/mcp/` (Streamable HTTP, stateless).
Same 6 tools, same parameters, same behavior."""


@router.get("/harness-prompt")
async def harness_prompt(
    request: Request,
    toolbox_url: Optional[str] = Query(default=None, description="Override the Toolbox base URL"),
):
    """Return a ready-to-use markdown integration guide for agents and harnesses."""
    if toolbox_url is None:
        toolbox_url = f"{request.url.scheme}://{request.url.netloc}"
    toolbox_url = toolbox_url.rstrip("/")
    return {"prompt": _build_prompt(toolbox_url)}
