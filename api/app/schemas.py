from pydantic import BaseModel
from typing import List, Optional, Literal
from datetime import datetime

class SourceOut(BaseModel):
    url: str
    type: Literal["regulator","ir","news","exchange","aggregator"]
    first_seen: datetime

class EntityOut(BaseModel):
    name: str
    type: str
    ticker: Optional[str] = None
    country: Optional[str] = None
    sector: Optional[str] = None

class TimelineItem(BaseModel):
    t: datetime
    what: str

class DraftOut(BaseModel):
    title: str
    lede: str
    bullets: list[str]
    quote: str
    attribution: list[str]

class EventOut(BaseModel):
    id: str
    headline: str
    hotness: float
    why_now: Optional[str] = None
    entities: List[EntityOut] = []
    timeline: List[TimelineItem] = []
    draft: Optional[DraftOut] = None
    confirmed: bool
    sources: List[SourceOut] = []
    event_type: Optional[str] = None
    materiality_ai: Optional[float] = None
    impact_side: Optional[str] = None
    risk_flags: list[str] = []
    ai_entities: List[EntityOut] = []
