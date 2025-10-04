import datetime as dt, uuid
from sqlalchemy import Column, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from .db import Base

utcnow = lambda: dt.datetime.now(dt.timezone.utc)

class Event(Base):
    __tablename__ = "events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    headline = Column(String, nullable=False)
    hotness = Column(Float, nullable=False, default=0.0)
    why_now = Column(Text, nullable=True)
    entities = Column(JSONB, nullable=False, default=list)
    timeline = Column(JSONB, nullable=False, default=list)
    draft = Column(JSONB, nullable=True)
    confirmed = Column(Boolean, default=False)
    dedup_group = Column(String, index=True)
    first_seen = Column(DateTime(timezone=True), default=utcnow)
    sources = relationship("Source", back_populates="event", cascade="all, delete-orphan")
    event_type = Column(String(64), nullable=True,
                        index=True)  # guidance|M&A|sanctions|investigation|fine|delisting|dividend|buyback|regulatory|...
    materiality_ai = Column(Float, nullable=True)  # 0..1
    impact_side = Column(String(16), nullable=True, index=True)  # pos|neg|uncertain
    risk_flags = Column(JSONB, nullable=False, default=list)  # ["single_source","old","repost",...]
    ai_entities = Column(JSONB, nullable=False, default=list)  # [{"name":"...","ticker":"..."}]

class Source(Base):
    __tablename__ = "sources"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    url = Column(String, nullable=False)
    type = Column(String, nullable=False, default="news")
    first_seen = Column(DateTime(timezone=True), default=utcnow)
    event = relationship("Event", back_populates="sources")
