from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class News(Base):
    __tablename__ = "news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="gov_cn")
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="时政")
    title: Mapped[str] = mapped_column(String, index=True, nullable=False)
    link: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    published: Mapped[str] = mapped_column(String, nullable=False, default="")
    published_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    year: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    month: Mapped[int] = mapped_column(Integer, index=True, nullable=False)


class AppState(Base):
    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
