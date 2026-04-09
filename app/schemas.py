from pydantic import BaseModel
from typing import List, Optional

class NewsBase(BaseModel):
    title: str
    link: str
    summary: str
    published: str

class NewsCreate(NewsBase):
    pass

class News(NewsBase):
    id: int

    class Config:
        orm_mode = True

class NewsList(BaseModel):
    news: List[News]