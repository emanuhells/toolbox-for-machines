"""POST /v1/search — Web search via SearXNG."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from toolbox.services import ToolboxError
from toolbox.services import search as search_service

router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=50)
    categories: str = "general"


@router.post("/search")
async def search(req: SearchRequest):
    """Search the web via SearXNG. Returns structured JSON results."""
    try:
        return await search_service(req.query, req.limit, req.categories)
    except ToolboxError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
