from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class News(Base):
    __tablename__ = "news"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(50), nullable=False, default="gov_cn")
    category = Column(String(50), nullable=False, default="时政")
    title = Column(String, index=True, nullable=False)
    link = Column(String, unique=True, nullable=False)
    summary = Column(Text, nullable=False, default="")
    content = Column(Text, nullable=False, default="")
    published = Column(String, nullable=False, default="")
    published_at = Column(DateTime, index=True, nullable=False)
    year = Column(Integer, index=True, nullable=False)
    month = Column(Integer, index=True, nullable=False)
