"""Helpers for collecting social posts (Twitter/X and LinkedIn) to enrich ingest."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import List

from pydantic import BaseModel

try:  # optional import for Twitter scraping
    from snscrape.modules import twitter as sntwitter
except Exception:  # pragma: no cover - executed when snscrape is missing
    sntwitter = None  # type: ignore

try:  # optional import for DuckDuckGo search
    from duckduckgo_search import DDGS
except Exception:  # pragma: no cover
    DDGS = None  # type: ignore


@dataclass
class SocialPost:
    platform: str
    id: str
    title: str
    text: str
    url: str
    author: str | None
    created_at: dt.datetime | None
    raw: dict


class SocialConfig(BaseModel):
    twitter_queries: List[str] = []
    linkedin_queries: List[str] = []
    limit_per_query: int = 10
    linkedin_region: str | None = None  # e.g. "ru-ru"


def _normalise_title(text: str, fallback_prefix: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return f"{fallback_prefix} update"
    return text if len(text) <= 120 else text[:117] + "..."


def fetch_twitter_posts(query: str, limit: int) -> List[SocialPost]:
    if not query or limit <= 0:
        return []
    if sntwitter is None:
        return []

    results: List[SocialPost] = []
    try:
        scraper = sntwitter.TwitterSearchScraper(query)
        for item in scraper.get_items():
            created = getattr(item, "date", None)
            username = getattr(getattr(item, "user", None), "username", None)
            results.append(
                SocialPost(
                    platform="social_twitter",
                    id=str(getattr(item, "id", "")),
                    title=_normalise_title(getattr(item, "content", ""), "Tweet"),
                    text=(getattr(item, "content", "") or "").strip(),
                    url=f"https://twitter.com/{username or 'i'}/status/{getattr(item, 'id', '')}",
                    author=username,
                    created_at=created,
                    raw={
                        "lang": getattr(item, "lang", None),
                        "replyCount": getattr(item, "replyCount", None),
                        "retweetCount": getattr(item, "retweetCount", None),
                        "likeCount": getattr(item, "likeCount", None),
                    },
                )
            )
            if len(results) >= limit:
                break
    except Exception:
        return []
    return results


def fetch_linkedin_posts(query: str, limit: int, region: str | None = None) -> List[SocialPost]:
    if not query or limit <= 0:
        return []
    if DDGS is None:
        return []

    results: List[SocialPost] = []
    try:
        ddgs_params = {}
        if region:
            ddgs_params["region"] = region
        with DDGS() as ddgs:
            for item in ddgs.news(f"{query} site:linkedin.com", max_results=limit, **ddgs_params):
                link = item.get("url") or item.get("href") or ""
                if "linkedin.com" not in (link or ""):
                    continue
                pub_date = item.get("date")
                created_at = None
                if pub_date:
                    try:
                        created_at = dt.datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                    except Exception:
                        created_at = None
                results.append(
                    SocialPost(
                        platform="social_linkedin",
                        id=item.get("id") or link,
                        title=_normalise_title(item.get("title") or item.get("heading") or "LinkedIn post", "LinkedIn"),
                        text=(item.get("body") or item.get("excerpt") or "").strip(),
                        url=link,
                        author=None,
                        created_at=created_at,
                        raw=item,
                    )
                )
    except Exception:
        return []
    return results


def collect_social_posts(config: SocialConfig) -> List[SocialPost]:
    posts: List[SocialPost] = []
    seen: set[str] = set()

    for query in config.twitter_queries:
        for post in fetch_twitter_posts(query, config.limit_per_query):
            key = post.id or post.url
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            posts.append(post)

    for query in config.linkedin_queries:
        for post in fetch_linkedin_posts(query, config.limit_per_query, region=config.linkedin_region):
            key = post.id or post.url
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            posts.append(post)

    posts.sort(key=lambda p: p.created_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
    return posts
