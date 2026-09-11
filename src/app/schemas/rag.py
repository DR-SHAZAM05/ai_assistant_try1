from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any
from src.app.core.config import settings


class RAGChunkSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_id: str
    document_id: str
    filename: str
    academic_year: str
    page: int = 1
    chunk_index: int = 0
    source_path: str
    text: str
    checksum: str
    document_type: str = "txt"  # "pdf", "txt", "md"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RAGQueryResult(BaseModel):
    answer: str
    sources: List[Dict[str, Any]] = []
    confidence_score: float = 0.0
    academic_year: str = Field(default_factory=lambda: settings.CURRENT_ACADEMIC_YEAR)
    chunks_used: int = 0
