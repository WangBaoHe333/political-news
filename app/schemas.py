from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class NewsBase(BaseModel):
    title: str
    link: str
    summary: str
    published: str
    source: str = "gov_cn"
    category: str = "时政"
    content: str = ""


class NewsCreate(NewsBase):
    published_at: datetime
    year: int
    month: int


class News(NewsBase):
    id: int
    published_at: datetime
    year: int
    month: int
    source: str = "gov_cn"
    category: str = "时政"
    content: str = ""

    class Config:
        from_attributes = True  # 替代 orm_mode=True for Pydantic v2


class NewsList(BaseModel):
    news: List[News]


class NewsGroupedByMonth(BaseModel):
    month: str  # 格式: "2024年01月"
    count: int
    items: List[News]


class NewsResponse(BaseModel):
    years: List[int]
    items: List[News]
    grouped_by_month: Optional[Dict[str, List[News]]] = None


class Question(BaseModel):
    type: str
    stem: str
    options: List[str] = []
    answer: str
    analysis: str


class QuestionsResponse(BaseModel):
    questions: List[Question]


class SummaryResponse(BaseModel):
    summary: List[str]


class SyncStatus(BaseModel):
    in_progress: bool
    scope: str
    message: str
    started_at: str
    finished_at: str
    last_result: str


class SyncRequest(BaseModel):
    year: Optional[int] = None
    months: int = Field(default=12, ge=1, le=36)
    max_pages: Optional[int] = Field(default=None, ge=1, le=500)
    max_items: Optional[int] = Field(default=None, ge=1, le=1000)


class BackfillRequest(BaseModel):
    months: int = Field(default=24, ge=1, le=36)
    batch_size: int = Field(default=3, ge=1, le=6)
    max_items: int = Field(default=150, ge=20, le=400)