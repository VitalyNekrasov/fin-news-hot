import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.encoders import jsonable_encoder  # type: ignore
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from api.app.db import SessionLocal  # type: ignore
from api.app.models import Event  # type: ignore


@dataclass
class SampleRecord:
    id: str
    headline: str
    teaser: str
    ground_phrases: List[dict]
    phrase_hotness_label: float | None
    predicted_phrases: List[dict]
    ai_entities: List[dict]
    hotness_model: float
    event_type: str | None
    materiality_ai: float | None
    impact_side: str | None
    risk_flags: List[str]
    sources: List[dict]
    metadata: dict

    def to_json(self) -> str:
        payload = jsonable_encoder(asdict(self))
        return json.dumps(payload, ensure_ascii=False)


async def _load_events(limit: int, min_hotness: float, require_teaser: bool) -> List[Event]:
    async with SessionLocal() as session:  # type: ignore
        stmt = (
            select(Event)
            .options(selectinload(Event.sources))
            .order_by(Event.first_seen.desc())
            .limit(limit)
        )
        if min_hotness > 0:
            stmt = stmt.where(Event.hotness >= min_hotness)
        res = await session.execute(stmt)
        events = res.scalars().unique().all()
        if require_teaser:
            events = [e for e in events if (e.why_now or "").strip()]
        return events


def _build_record(event: Event) -> SampleRecord:  # type: ignore
    teaser = (event.why_now or "").strip()
    sources = [
        {
            "url": s.url,
            "type": s.type,
            "first_seen": s.first_seen.isoformat() if s.first_seen else None,
        }
        for s in (event.sources or [])
    ]
    metadata = {
        "first_seen": event.first_seen.isoformat() if event.first_seen else None,
        "hotness_components_hint": "headline + teaser were used for keyphrase extraction",
    }
    return SampleRecord(
        id=str(event.id),
        headline=event.headline,
        teaser=teaser,
        ground_phrases=[],
        phrase_hotness_label=None,
        predicted_phrases=event.entities or [],
        ai_entities=event.ai_entities or [],
        hotness_model=float(event.hotness or 0.0),
        event_type=getattr(event, "event_type", None),
        materiality_ai=getattr(event, "materiality_ai", None),
        impact_side=getattr(event, "impact_side", None),
        risk_flags=getattr(event, "risk_flags", []) or [],
        sources=sources,
        metadata=metadata,
    )


def _write_dataset(path: Path, records: Iterable[SampleRecord], force: bool) -> None:
    if path.exists() and not force:
        raise SystemExit(f"File already exists: {path}. Use --force to overwrite.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(record.to_json())
            fh.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export recent events into a JSONL skeleton for manual keyphrase/hotness labelling",
    )
    parser.add_argument("output", type=Path, help="Destination JSONL file (will be overwritten if --force)")
    parser.add_argument("--limit", type=int, default=50, help="How many recent events to export")
    parser.add_argument(
        "--min-hotness",
        type=float,
        default=0.0,
        help="Only include events with hotness >= this value",
    )
    parser.add_argument(
        "--allow-empty-teaser",
        action="store_true",
        help="Keep events even if why_now/teaser is blank",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output file if it already exists",
    )
    return parser.parse_args()


async def _main() -> None:
    args = parse_args()
    events = await _load_events(
        limit=args.limit,
        min_hotness=args.min_hotness,
        require_teaser=not args.allow_empty_teaser,
    )
    if not events:
        raise SystemExit("No events found with the selected filters")

    records = [_build_record(ev) for ev in events]
    _write_dataset(args.output, records, force=args.force)
    print(f"Exported {len(records)} records to {args.output}")


if __name__ == "__main__":
    asyncio.run(_main())
