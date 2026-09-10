from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime


class NewsArticleSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    title: str
    url: str
    source_name: str
    topic: str
    published_at: Optional[datetime] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    relevance_score: float = 0.0
    fingerprint: Optional[str] = None


class NewsTopicConfig(BaseModel):
    name: str
    keywords: List[str]
