"""E2E tests for Toolbox endpoints. Requires the service running at localhost:9600."""

import os

import httpx
import pytest

BASE_URL = "http://localhost:9600"


# Skip LLM-dependent tests when no LLM is available
def _llm_available():
    """Check if LLM backend is reachable."""
    try:
        r = httpx.get(f"{BASE_URL}/healthz", timeout=5)
        backends = r.json().get("backends", {})
        return backends.get("llm") == "healthy"
    except Exception:
        return False


skip_no_llm = pytest.mark.skipif(
    os.environ.get("SKIP_LLM_TESTS", "").lower() in ("1", "true", "yes") or not _llm_available(),
    reason="LLM backend not available"
)


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=60) as c:
        yield c


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("ok", "degraded")
    assert "backends" in data
    assert set(data["backends"].keys()) == {"searxng", "camoufox", "whisper", "llm"}


def test_search(client):
    r = client.post("/v1/search", json={"query": "python programming", "limit": 3})
    assert r.status_code == 200
    data = r.json()
    assert "results" in data
    assert "count" in data
    assert data["query"] == "python programming"
    # Results may be empty due to rate limiting, but structure must be correct
    if data["count"] > 0:
        result = data["results"][0]
        assert "title" in result
        assert "url" in result
        assert "snippet" in result


def test_search_empty_query(client):
    r = client.post("/v1/search", json={"query": "", "limit": 5})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    assert data["results"] == []


def test_fetch(client):
    r = client.post("/v1/fetch", json={"url": "https://example.com", "format": "markdown"})
    assert r.status_code == 200
    data = r.json()
    assert data["url"] == "https://example.com"
    assert "content" in data
    assert data["word_count"] > 0
    assert data["format"] == "markdown"
    assert "screenshot_b64" in data
    assert data["screenshot_b64"] is None  # Not requested


def test_fetch_screenshot(client):
    r = client.post("/v1/fetch", json={"url": "https://example.com", "screenshot": True})
    assert r.status_code == 200
    data = r.json()
    assert data["screenshot_b64"] is not None
    assert len(data["screenshot_b64"]) > 100


def test_fetch_unreachable(client):
    r = client.post("/v1/fetch", json={"url": "http://192.0.2.1/unreachable"}, timeout=30)
    # Should return 502 for unreachable
    assert r.status_code == 502
    data = r.json()
    assert "detail" in data


@skip_no_llm
def test_describe_page_url(client):
    r = client.post("/v1/describe", json={"page_url": "https://example.com", "prompt": "What text is on this page?"})
    assert r.status_code == 200
    data = r.json()
    assert "description" in data
    assert len(data["description"]) > 10


def test_describe_no_input(client):
    r = client.post("/v1/describe", json={"prompt": "test"})
    assert r.status_code == 400
    data = r.json()
    assert "detail" in data


@skip_no_llm
def test_summarize(client):
    text = "The Python programming language was created by Guido van Rossum and first released in 1991. Python emphasizes code readability with its notable use of significant whitespace."
    r = client.post("/v1/summarize", json={"text": text, "max_tokens": 50, "style": "brief"})
    assert r.status_code == 200
    data = r.json()
    assert "summary" in data
    assert len(data["summary"]) > 10


def test_summarize_empty(client):
    r = client.post("/v1/summarize", json={"text": "  ", "max_tokens": 50})
    assert r.status_code == 400


@skip_no_llm
def test_extract(client):
    r = client.post("/v1/extract", json={
        "text": "Alice is 28 years old and lives in London. She works at DeepMind.",
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "city": {"type": "string"},
                "company": {"type": "string"}
            }
        }
    })
    assert r.status_code == 200
    data = r.json()
    assert "data" in data
    assert data["data"]["name"] == "Alice"
    assert data["data"]["age"] == 28


def test_extract_schema_too_large(client):
    big_schema = {
        "type": "object",
        "properties": {f"field_{i}": {"type": "string", "description": f"This is a very long description for field number {i} to make the schema exceed the limit"} for i in range(50)}
    }
    r = client.post("/v1/extract", json={"text": "hello", "schema": big_schema})
    assert r.status_code == 400
    assert "too large" in r.json()["detail"].lower()


def test_transcribe_no_input(client):
    r = client.post("/v1/transcribe", json={"language": "en"})
    assert r.status_code == 400


def test_skills(client):
    r = client.get("/v1/skills")
    assert r.status_code == 200
    data = r.json()
    assert data["version"] == "1.1.0"
    assert len(data["skills"]) == 6
    for skill in data["skills"]:
        assert "id" in skill
        assert "examples" in skill
        assert "constraints" in skill
        assert len(skill["examples"]) >= 1


def test_harness_prompt(client):
    r = client.get("/v1/harness-prompt")
    assert r.status_code == 200
    data = r.json()
    assert "prompt" in data
    assert "POST /v1/search" in data["prompt"]
    assert len(data["prompt"]) < 5000  # Should be compact


def test_mcp_tools_list(client):
    r = client.post("/mcp/", json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list"
    }, headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 200
    # SSE format: "event: message\ndata: {...}\n\n"
    assert "tools" in r.text
    assert "search" in r.text
    assert "fetch" in r.text
