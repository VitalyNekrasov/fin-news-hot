import argparse
import asyncio
import os
from typing import Iterable, List

from .ingest import SessionLocal, _ensure_schema, upsert_event  # type: ignore
from ..services.social_sources import SocialConfig, collect_social_posts

DEFAULT_LIMIT = 10


async def _store_posts(posts: Iterable, source_type: str) -> None:
    async with SessionLocal() as session:  # type: ignore
        try:
            session.sync_session.autoflush = False
            session.sync_session.expire_on_commit = False
        except Exception:
            pass
        for post in posts:
            title = post.title or post.text[:120] or "Social update"
            link = post.url
            if not link:
                continue
            entry = {
                "summary": post.text,
                "title": title,
                "published": post.created_at.isoformat() if post.created_at else None,
            }
            async with session.begin():
                await upsert_event(session, title, link, source_type, entry=entry)


def _split_env(name: str) -> List[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_int(name: str, default: int) -> int:
    try:
        raw = os.getenv(name)
        if raw is None:
            return default
        return int(raw.strip())
    except Exception:
        return default


def _env_str(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


async def run(config: SocialConfig) -> None:
    await _ensure_schema()
    posts = collect_social_posts(config)
    twitter_posts = [p for p in posts if p.platform == "social_twitter"]
    linkedin_posts = [p for p in posts if p.platform == "social_linkedin"]

    if twitter_posts:
        await _store_posts(twitter_posts, "social_twitter")
    if linkedin_posts:
        await _store_posts(linkedin_posts, "social_linkedin")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest social posts (Twitter, LinkedIn) into the radar pipeline")
    parser.add_argument("--twitter-query", action="append", default=[], help="Twitter search query (can repeat)")
    parser.add_argument("--linkedin-query", action="append", default=[], help="LinkedIn search query (via DuckDuckGo)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Max posts per query")
    parser.add_argument("--linkedin-region", default=None, help="DuckDuckGo region code, e.g. us-en, ru-ru")
    args = parser.parse_args()

    twitter_queries = args.twitter_query or _split_env("SOCIAL_TWITTER_QUERIES")
    linkedin_queries = args.linkedin_query or _split_env("SOCIAL_LINKEDIN_QUERIES")
    limit = args.limit
    if args.limit == DEFAULT_LIMIT:
        limit = _env_int("SOCIAL_LIMIT", DEFAULT_LIMIT)
    region = args.linkedin_region or _env_str("SOCIAL_LINKEDIN_REGION")

    if not twitter_queries and not linkedin_queries:
        print("[social_ingest] no twitter/linkedin queries configured; nothing to do", flush=True)
        raise SystemExit(0)

    config = SocialConfig(
        twitter_queries=twitter_queries,
        linkedin_queries=linkedin_queries,
        limit_per_query=limit,
        linkedin_region=region,
    )
    asyncio.run(run(config))
