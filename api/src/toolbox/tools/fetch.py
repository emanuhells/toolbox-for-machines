"""POST /v1/fetch — Stealth web fetch via Camoufox + content extraction."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from toolbox.services import ToolboxError
from toolbox.services import fetch as fetch_service

router = APIRouter()


class FetchRequest(BaseModel):
    url: str
    format: str = Field(default="markdown", pattern="^(markdown|text)$")
    screenshot: bool = False
    wait_for: Optional[str] = None
    wait_ms: int = Field(default=0, ge=0, le=20000)


@router.post("/fetch")
async def fetch(req: FetchRequest):
    """Fetch a URL via stealth browser, return clean extracted content."""
    try:
        return await fetch_service(req.url, req.format, req.screenshot, req.wait_for, req.wait_ms)
    except ToolboxError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
