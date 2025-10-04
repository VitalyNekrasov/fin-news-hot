import json, os
from typing import Optional

import asyncio
from .services.translate import translate_event_dict

from fastapi import FastAPI, Depends, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .db import engine, Base, SessionLocal
from .models import Event, Source
from .schemas import EventOut, EntityOut, TimelineItem, DraftOut, SourceOut
from .services.generate import gen_why_now_and_draft
app = FastAPI(title="Fin News Hot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("ALLOWED_ORIGINS","*")],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

async def get_db():
    async with SessionLocal() as s:
        yield s

@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Soft migrations for new AI-filter columns
        await conn.execute(text("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='events' AND column_name='event_type'
            ) THEN
                ALTER TABLE events ADD COLUMN event_type VARCHAR(64);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='events' AND column_name='materiality_ai'
            ) THEN
                ALTER TABLE events ADD COLUMN materiality_ai DOUBLE PRECISION;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='events' AND column_name='impact_side'
            ) THEN
                ALTER TABLE events ADD COLUMN impact_side VARCHAR(16);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='events' AND column_name='risk_flags'
            ) THEN
                ALTER TABLE events ADD COLUMN risk_flags JSONB DEFAULT '[]'::jsonb;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='events' AND column_name='ai_entities'
            ) THEN
                ALTER TABLE events ADD COLUMN ai_entities JSONB DEFAULT '[]'::jsonb;
            END IF;
        END $$;
        """))

@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    events = (await db.execute(select(func.count()).select_from(Event))).scalar_one()
    sources = (await db.execute(select(func.count()).select_from(Source))).scalar_one()
    last_source = (await db.execute(select(func.max(Source.first_seen)))).scalar_one()
    return {"ok": True, "events": events, "sources": sources, "last_source": last_source}

@app.get("/events", response_model=list[EventOut])
async def list_events(
    q: Optional[str] = None,
    min_hotness: float = 0.0,
    confirmed: Optional[bool] = None,
    types: Optional[str] = Query(None),
    order: str = "hotness",
    offset: int = 0,
    limit: int = 50,
    # AI-filter params
    event_type: Optional[str] = None,
    impact_side: Optional[str] = None,     # "pos" | "neg" | "uncertain"
    min_materiality_ai: float = 0.0,
    lang: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Event).options(selectinload(Event.sources))
    stmt = stmt.order_by(Event.hotness.desc() if order=="hotness" else Event.first_seen.desc())
    if min_hotness > 0: stmt = stmt.where(Event.hotness >= min_hotness)
    if confirmed is not None: stmt = stmt.where(Event.confirmed == confirmed)
    if q: stmt = stmt.where(Event.headline.ilike(f"%{q}%"))
    if types:
        allowed = [t.strip() for t in types.split(",") if t.strip()]
        if allowed:
            subq = select(1).select_from(Source).where(Source.event_id == Event.id, Source.type.in_(allowed))
            stmt = stmt.where(subq.exists())
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)
    if impact_side:
        stmt = stmt.where(Event.impact_side == impact_side)
    if min_materiality_ai > 0:
        stmt = stmt.where((Event.materiality_ai.is_not(None)) & (Event.materiality_ai >= min_materiality_ai))
    stmt = stmt.offset(offset).limit(limit)

    res = await db.execute(stmt)
    rows = res.scalars().unique().all()

    out = [EventOut(
        id=str(e.id), headline=e.headline, hotness=e.hotness,
        why_now=e.why_now, confirmed=e.confirmed,
        entities=[EntityOut(**x) for x in (e.entities or [])],
        timeline=[TimelineItem(**x) for x in (e.timeline or [])],
        draft=(DraftOut(**e.draft) if e.draft else None),
        sources=[SourceOut(url=s.url, type=s.type, first_seen=s.first_seen) for s in (e.sources or [])],
        event_type=e.event_type,
        materiality_ai=e.materiality_ai,
        impact_side=e.impact_side,
        risk_flags=e.risk_flags or [],
        ai_entities=[
            EntityOut(
                name=(x.get("name") or (x.get("ticker") or "")),
                type=(x.get("type") or ("TICKER" if x.get("ticker") else "ORG")),
                ticker=x.get("ticker"),
                country=x.get("country"),
                sector=x.get("sector"),
            )
            for x in (e.ai_entities or [])
        ],
    ) for e in rows]

    if lang and lang.lower() != "en":
        # переведём параллельно
        translated = await asyncio.gather(*[translate_event_dict(o.model_dump(mode="json"), lang) for o in out])
        return translated
    return out

@app.get("/events/{event_id}", response_model=EventOut)
async def get_event(event_id: str, lang: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Event).options(selectinload(Event.sources)).where(Event.id == event_id))
    e = res.scalars().first()
    if not e:
        raise HTTPException(404, "event not found")
    out = EventOut(
        id=str(e.id), headline=e.headline, hotness=e.hotness,
        why_now=e.why_now, confirmed=e.confirmed,
        entities=[EntityOut(**x) for x in (e.entities or [])],
        timeline=[TimelineItem(**x) for x in (e.timeline or [])],
        draft=(DraftOut(**e.draft) if e.draft else None),
        sources=[SourceOut(url=s.url, type=s.type, first_seen=s.first_seen) for s in (e.sources or [])],
        event_type=e.event_type,
        materiality_ai=e.materiality_ai,
        impact_side=e.impact_side,
        risk_flags=e.risk_flags or [],
        ai_entities=[
            EntityOut(
                name=(x.get("name") or (x.get("ticker") or "")),
                type=(x.get("type") or ("TICKER" if x.get("ticker") else "ORG")),
                ticker=x.get("ticker"),
                country=x.get("country"),
                sector=x.get("sector"),
            )
            for x in (e.ai_entities or [])
        ],
    )
    if lang and lang.lower() != "en":
        return await translate_event_dict(out.model_dump(mode="json"), lang)
    return out

@app.post("/events/{event_id}/generate", response_model=EventOut)
async def generate_event(event_id: str, lang: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(Event).options(selectinload(Event.sources)).where(Event.id == event_id)
    )
    e = res.scalars().first()
    if not e:
        raise HTTPException(404, "event not found")
    try:
        payload = gen_why_now_and_draft(
            e.headline,
            [{"url": s.url} for s in e.sources],
            seed_text=e.why_now,  # <— добавили seed
        )
        e.why_now = payload.get("why_now")
        e.draft = payload.get("draft")
        await db.commit()
    except Exception as ex:
        # фолбэк, чтобы не падать на демо без ключа
        e.why_now = e.why_now or "Важно сейчас: обновление от первоисточника/регулятора."
        e.draft = e.draft or {
            "title": e.headline,
            "lede": "Кратко: ключевые детали и контекст будут уточняться.",
            "bullets": ["Источник: см. ссылки ниже", "Подтверждение: есть", "Следим за обновлениями"],
            "quote": "",
            "attribution": [s.url for s in e.sources[:3]],
        }
        await db.commit()
    return await get_event(event_id=event_id, lang=lang, db=db)

@app.get("/events_offline", response_model=list[EventOut])
async def events_offline():
    p = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "offline", "events.sample.json")
    with open(os.path.normpath(p), "r", encoding="utf-8") as f:
        return json.load(f)