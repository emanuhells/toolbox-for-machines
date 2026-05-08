"""POST /v1/extract — Schema-guided structured data extraction via LLM."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from toolbox.services import ToolboxError
from toolbox.services import extract as extract_service

router = APIRouter()


class ExtractRequest(BaseModel):
    text: str
    schema: dict  # JSON Schema the output must match


@router.post("/extract")
async def extract(req: ExtractRequest):
    """Extract structured JSON data from text using a provided schema."""
    try:
        return await extract_service(req.text, req.schema)
    except ToolboxError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
