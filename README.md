<div align="center">

# toolbox, for machines

**Eyes, ears, and hands for your AI agent.**

Give any agent the ability to search the web, read pages, see images, hear audio, summarize text, and extract structured data — through one endpoint.

[![License](https://img.shields.io/github/license/emanuhells/toolbox-for-machines?style=flat-square)](LICENSE)
[![Stars](https://img.shields.io/github/stars/emanuhells/toolbox-for-machines?style=flat-square)](https://github.com/emanuhells/toolbox-for-machines/stargazers)

</div>

---

## Quick Start

```bash
git clone https://github.com/emanuhells/toolbox-for-machines.git
cd toolbox-for-machines
cp .env.example .env
# Edit .env — point LLM_URL to any OpenAI-compatible vision model
docker compose up -d
```

Verify:

```bash
curl http://localhost:9600/healthz
```

Search, fetch, and transcribe work without an LLM. The vision-dependent tools (describe, summarize, extract) need an OpenAI-compatible endpoint — see [SETUP_LLM_HOST.md](SETUP_LLM_HOST.md).

---

## What's Inside

| | Tool | Endpoint | What it does |
|---|------|----------|--------------|
| 🔍 | Search | `POST /v1/search` | Web search via SearXNG. Structured JSON results. |
| 🌐 | Fetch | `POST /v1/fetch` | Stealth browser fetch → clean markdown. Bypasses bot detection. |
| 👁️ | Describe | `POST /v1/describe` | Describe images or screenshot pages using a vision model. |
| 🎤 | Transcribe | `POST /v1/transcribe` | Audio to text via whisper.cpp. |
| 📝 | Summarize | `POST /v1/summarize` | Condense long text. Brief, detailed, or bullet styles. |
| 🧩 | Extract | `POST /v1/extract` | Pull structured JSON from text using a schema you provide. |

All six tools are available as **REST** (`/v1/*`) and **MCP** (`/mcp/`).

---

## How Agents Connect

### Option A: REST

```bash
# Search
curl -X POST http://localhost:9600/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "rust async runtimes 2025", "limit": 5}'

# Fetch a page
curl -X POST http://localhost:9600/v1/fetch \
  -H "Content-Type: application/json" \
  -d '{"url": "https://blog.rust-lang.org/", "format": "markdown"}'
```
Works with Pi agent.

### Option B: MCP (Model Context Protocol)

Any MCP-compatible client connects with:

```json
{
  "mcpServers": {
    "toolbox": {
      "type": "streamable-http",
      "url": "http://YOUR_HOST:9600/mcp/"
    }
  }
}
```

Works with Claude Code, Cursor, Codex, Hermes, OpenClaw, OpenCode and anything else that speaks MCP.

### Option C: Dynamic discovery

```bash
curl http://localhost:9600/v1/skills
```

Returns machine-readable skill cards with full schemas. Register them programmatically at agent startup.

---

## Tutorial: Search → Fetch → Summarize

A connected example showing how tools chain together:

```bash
# 1. Search for a topic
curl -s -X POST http://localhost:9600/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "what is WebAssembly", "limit": 3}'
# → Returns URLs with snippets. Pick the best one.

# 2. Fetch the page content
curl -s -X POST http://localhost:9600/v1/fetch \
  -H "Content-Type: application/json" \
  -d '{"url": "https://webassembly.org/", "format": "markdown"}'
# → Returns clean markdown. Might be long.

# 3. Summarize it
curl -s -X POST http://localhost:9600/v1/summarize \
  -H "Content-Type: application/json" \
  -d '{"text": "<paste content from step 2>", "max_tokens": 100, "style": "bullets"}'
# → Returns a concise summary.
```

For structured data, replace step 3 with extract:

```bash
# 3b. Extract specific fields instead
curl -s -X POST http://localhost:9600/v1/extract \
  -H "Content-Type: application/json" \
  -d '{
    "text": "<paste content from step 2>",
    "schema": {
      "type": "object",
      "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "use_cases": {"type": "array", "items": {"type": "string"}}
      }
    }
  }'
# → Returns structured JSON matching your schema.
```

---

## Architecture

```
Agents → toolbox-api:9600 (/v1/* REST, /mcp/ MCP)
              │
              ├── searxng      (meta-search, internal)
              ├── camoufox    (stealth browser, internal)
              ├── whisper      (speech-to-text, internal)
              └──────────────→ Vision LLM (any OpenAI-compatible endpoint)
```

| Container | Role | RAM |
|-----------|------|-----|
| toolbox-api | FastAPI service, routing, cache | ~200MB |
| toolbox-searxng | Meta-search engine | ~300MB |
| toolbox-camoufox | Stealth headless Firefox | ~1.5GB |
| toolbox-whisper | Audio transcription (CPU) | ~2GB |

Only port **9600** is exposed. Everything else is internal.

The LLM is **not** part of the Docker stack — it runs separately on a GPU machine (or cloud API). See [SETUP_LLM_HOST.md](SETUP_LLM_HOST.md) for configuration.

---

## Configuration

All via environment variables. Copy `.env.example` and edit:

| Variable | Default | What it does |
|----------|---------|--------------|
| `LLM_URL` | `http://host.docker.internal:8080/v1` | OpenAI-compatible LLM endpoint |
| `LLM_MODEL` | `qwen3-vl-8b` | Model name (must support vision for describe endpoint) |
| `LLM_API_KEY` | *(empty)* | API key if your endpoint requires one |
| `TOOLBOX_PORT` | `9600` | Port exposed to the network |
| `CAMOUFOX_TZ` | `UTC` | Browser timezone for page rendering |

Full reference in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). LLM setup options (llama.cpp, Ollama, OpenAI, etc.) in [SETUP_LLM_HOST.md](SETUP_LLM_HOST.md).

---

## Design Principles

- **Dumb muscle.** No thinking, no planning, no orchestration. Fire a request, get a result.
- **Stateless.** No sessions, no memory. Each request is independent.
- **Model-agnostic.** Swap the LLM by changing one env var.
- **Token-efficient.** Never returns raw HTML. Content is extracted and cleaned before it reaches your agent.

---

## Documentation

| Document | What's in it |
|----------|-------------|
| [docs/API.md](docs/API.md) | Complete endpoint reference with examples |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, data flow, caching |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Setup, configuration, troubleshooting |
| [SETUP_LLM_HOST.md](SETUP_LLM_HOST.md) | LLM options (llama.cpp, Ollama, OpenAI, vLLM), model requirements, critical parameters |
| [HARNESS_PROMPT.md](HARNESS_PROMPT.md) | Auto-generated integration prompt for agents |

---

## Requirements

- Docker Engine 24+ with Compose V2
- ~4GB free RAM
- Network access to an OpenAI-compatible LLM endpoint (for describe/summarize/extract)
- No GPU required on the toolbox host

---

## Contributing

```bash
git clone https://github.com/emanuhells/toolbox-for-machines.git
cd toolbox-for-machines
cp .env.example .env
docker compose up -d
# Make changes, test against localhost:9600
```

PRs welcome. Open an issue first for anything non-trivial.

---

## License

MIT — see [LICENSE](LICENSE)
