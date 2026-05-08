# Toolbox Architecture

## Overview

Toolbox is a **dumb-muscle tool service** for AI agents. It does not think, plan, or orchestrate. An agent calls a specific endpoint, the toolbox executes the task using the appropriate backend, and returns a clean result.

## Design Principles

1. **Stateless** — No sessions, no conversation memory. Each request is independent.
2. **Explicit routing** — The calling agent decides which tool to use. No AI-based request routing.
3. **Token-efficient** — Responses are always the minimum useful result. Raw HTML is never returned.
4. **Self-contained** — One `docker compose up` brings everything needed (except the remote LLM).
5. **Model-agnostic** — The LLM is accessed via OpenAI-compatible API. Swap models by changing env vars.

## Component Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  Toolbox Docker Stack                                            │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  toolbox-api (FastAPI)                                    │   │
│  │                                                           │   │
│  │  REST Routers ─┐                                         │   │
│  │                ├─► services.py ──► backends               │   │
│  │  MCP Handlers ─┘       │                                 │   │
│  │                       cache                              │   │
│  │                                                           │   │
│  └──────────────────────────────────────────────────────────┘   │
│       │              │              │                │            │
│  ┌────┴────┐   ┌────┴────┐   ┌────┴────┐          │            │
│  │ searxng │   │camoufox │   │ whisper │          │            │
│  │  :8080  │   │  :8790  │   │  :8200  │          │            │
│  └─────────┘   └─────────┘   └─────────┘          │            │
└────────────────────────────────────────────────────┼────────────┘
                                                     │ LAN
                                              ┌──────┴──────┐
                                              │ llama.cpp   │
                                              │ Vision LLM  │
                                              │ (OpenAI API)│
                                              │ :8080 (GPU) │
                                              └─────────────┘
```

## Request Flow

```
Agent → HTTP POST → FastAPI Router → Check Cache
                                         │
                                    ┌────┴────┐
                                    │  HIT    │  MISS
                                    │         │
                                    ▼         ▼
                              Return      Call Backend
                              cached      (SearXNG/Camoufox/LLM/Whisper)
                              result           │
                                              ▼
                                        Format Response
                                              │
                                              ▼
                                        Store in Cache
                                              │
                                              ▼
                                        Return JSON
```

### Search Retry

If SearXNG returns 0 results for a non-trivial query (>2 chars), toolbox retries once after a 1 second delay. This handles upstream engine rate-limiting under parallel load.

### Fetch Error Handling

When Camoufox fails, the API inspects the error type:

- **Connection-level error** (timeout, unreachable host, DNS failure, 502) → return immediately, no fallback. The target is unreachable regardless of how you fetch it.
- **Other error** → attempt a lightweight direct HTTP fallback with a 5 second timeout.

This reduces the worst-case latency for unreachable targets from ~35s to ~20s.

## Backend Responsibilities

| Backend | What it does | Why it exists |
|---------|-------------|---------------|
| **SearXNG** | Meta-search across Google, Bing, DuckDuckGo, etc. | Privacy-respecting, self-hosted, JSON API |
| **Camoufox** | Stealth headless Firefox with anti-detection | Bypasses bot protection, renders JS pages |
| **whisper.cpp** | Audio transcription (CPU, small model) | Purpose-built speech-to-text, no GPU needed |
| **Vision LLM** | Vision, summarization, structured extraction | Any OpenAI-compatible multimodal model |

## LLM Integration

The LLM is accessed via the OpenAI-compatible chat completions API:

```python
POST {LLM_URL}/chat/completions
Authorization: Bearer {LLM_API_KEY}
{
  "model": "qwen3-vl-8b",
  "messages": [...],
  "max_tokens": 512,
  "temperature": 0.1
}
```

### Concurrency Control

Only one LLM request runs at a time (asyncio Semaphore). This prevents VRAM OOM errors on the 8GB GPU. Non-LLM endpoints (search, fetch, transcribe) run fully parallel.

### System Prompts

Each LLM endpoint uses a rigid system prompt stored in `prompts.py`:
- **describe**: Focus on text, UI elements, data. Plain text output.
- **summarize**: Condense to N tokens. No preamble.
- **extract**: Output ONLY valid JSON matching the schema. No explanation.

### Context Limit

The LLM runs with `-c 2048`. Each toolbox request uses ~1500-2500 tokens:
- System prompt: ~150 tokens
- Input content: ~500-1500 tokens (truncated by the API if larger)
- Output: ~200-500 tokens

## Caching

SQLite database at `/data/cache.db` (Docker volume):

```sql
CREATE TABLE cache (
    key TEXT PRIMARY KEY,        -- SHA-256 of endpoint + params
    response TEXT NOT NULL,      -- JSON response
    created_at INTEGER NOT NULL, -- Unix timestamp
    ttl_seconds INTEGER NOT NULL -- Per-endpoint TTL
);
```

| Endpoint | TTL | Rationale |
|----------|-----|-----------|
| search | 5 min | Search results change frequently |
| fetch | 30 min | Page content is relatively stable |
| describe | 1 hour | Same image → same description |
| summarize | 1 hour | Same text → same summary |
| extract | 1 hour | Same text + schema → same result |
| transcribe | None | Audio files are unique |

### Background Cleanup

A background asyncio task runs cache cleanup every 10 minutes. On startup, if more than 100 expired entries exist, cleanup runs immediately followed by `VACUUM`. This prevents unbounded cache growth without manual intervention.

## Content Extraction Pipeline

For `/v1/fetch`:

```
URL → Camoufox (stealth fetch, renders JS)
    → Raw HTML
    → trafilatura (algorithmic content extraction)
    → Clean markdown/text
    → Response
```

The extraction pipeline is entirely algorithmic (no LLM involved), making it fast and free.

## Security Model

- **No authentication** — designed for trusted LAN only
- **No port exposure** except 9600 — backends are internal-only
- **Scoped internet access** — The API container accesses the internet only as fallback when Camoufox fails (direct HTTP) and for downloading audio/image files from URLs provided in requests
- **No persistent state** except the cache (can be wiped anytime)

## MCP Layer

The MCP server is implemented using `FastMCP` from the `mcp` Python package. It is mounted as a sub-application on the FastAPI app at `/mcp/`.

```
toolbox-api:9600
├── FastAPI (/v1/* REST endpoints, /healthz)
└── FastMCP (/mcp/ — Streamable HTTP, stateless)
    ├── tool: search
    ├── tool: fetch
    ├── tool: describe
    ├── tool: transcribe
    ├── tool: summarize
    └── tool: extract
```

Key design decisions:

- **Stateless HTTP transport** — `stateless_http=True` on the `FastMCP` instance; no WebSocket, no session affinity
- **Shared service layer** — MCP tool handlers call into the same `services.py` as REST handlers; business logic lives in one place and is not duplicated across transports
- **Shared cache** — Cache hits are shared across both interfaces; a REST fetch and an MCP fetch for the same URL return the same cached result
- **Shared LLM semaphore** — The single `asyncio.Semaphore` controlling LLM concurrency is shared; REST and MCP calls queue together, preventing VRAM exhaustion
- **Tools return JSON strings** — MCP convention; each tool serializes its result dict to JSON before returning

## Service Layer

All business logic lives in `api/src/toolbox/services.py`. Both REST routers and MCP handlers are thin wrappers that validate input, call a service function, and format the response for their transport.

This eliminates code duplication and guarantees identical behavior regardless of how a tool is called. A search via REST and a search via MCP go through exactly the same code path.

Error propagation uses the `ToolboxError` exception class:

- REST handlers catch `ToolboxError` and convert it to an `HTTPException` with the appropriate status code.
- MCP handlers catch `ToolboxError` and raise `ValueError`, which the MCP framework translates to `isError=true` in the tool result.
