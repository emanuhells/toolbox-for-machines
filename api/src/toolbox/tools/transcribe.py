"""POST /v1/transcribe — Audio transcription via whisper.cpp."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from toolbox.services import ToolboxError
from toolbox.services import transcribe as transcribe_service

router = APIRouter()


class TranscribeRequest(BaseModel):
    audio_url: Optional[str] = None
    audio_b64: Optional[str] = None
    mime_type: str = "audio/wav"
    language: str = "en"


@router.post("/transcribe")
async def transcribe(req: TranscribeRequest):
    """Transcribe audio to text using whisper.cpp."""
    try:
        return await transcribe_service(req.audio_url, req.audio_b64, req.mime_type, req.language)
    except ToolboxError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
