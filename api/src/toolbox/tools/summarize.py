"""POST /v1/summarize — Text summarization via LLM."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from toolbox.services import ToolboxError
from toolbox.services import summarize as summarize_service

router = APIRouter()


class SummarizeRequest(BaseModel):
    text: str
    max_tokens: int = Field(default=200, ge=20, le=500)
    style: str = Field(default="brief", pattern="^(brief|detailed|bullets)$")


@router.post("/summarize")
async def summarize(req: SummarizeRequest):
    """Summarize text using the LLM."""
    try:
        return await summarize_service(req.text, req.max_tokens, req.style)
    except ToolboxError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
