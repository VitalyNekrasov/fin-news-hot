import argparse
import asyncio
import hashlib
import datetime as dt
import sys
import re
import os, glob
from urllib.parse import urlparse, urljoin
from functools import partial
from ..services.ai_filter import classify_event

import yaml
import feedparser
import httpx
import certifi
from sqlalchemy import select, func, text
from rapidfuzz import fuzz

try:
    # может быть не установлен — тогда используем фолбэк
    from trafilatura import extract as trafi_extract
except Exception:
    trafi_extract = None

try:
    from bs4 import BeautifulSoup  # optional HTML fallback
except Exception:
    BeautifulSoup = None

from ..db import SessionLocal, engine, Base
from ..models import Event, Source
from ..services.hotness import hotness
from ..services.keyphrases import extract_keyphrases, score_phrase_hotness

def _harvest_html_index(html: str, base: str, limit: int = 20) -> list[dict]:
    """
    Very lightweight fallback: extract likely article links from a homepage and
    return as pseudo feed entries [{title, link}].
    Prefers anchors that mention 'news', 'press', 'article', 'business', 'markets' in href.
    """
    entries: list[dict] = []
    seen: set[str] = set()

    def _push(href: str, text: str):
        href_abs = urljoin(base, href)
        if href_abs in seen:
            return
        text = (text or "").strip()
        # короткие заголовки отсеиваем
        if len(text) < 30:
            return
        seen.add(href_abs)
        entries.append({"title": text, "link": href_abs})

    try:
        if BeautifulSoup:
            soup = BeautifulSoup(html, "html.parser")
            # сначала — кандидаты с ключевыми словами
            keywords = ("news", "press", "article", "business", "markets")
            for a in soup.find_all("a", href=True):
                href = a.get("href") or ""
                text = a.get_text(" ", strip=True)
                if any(k in href.lower() for k in keywords):
                    _push(href, text)
                    if len(entries) >= limit:
                        return entries
            # затем — просто верхние заголовки
            for sel in ["h1 a", "h2 a", "h3 a", "a"]:
                for a in soup.select(sel):
                    href = a.get("href") or ""
                    text = a.get_text(" ", strip=True)
                    _push(href, text)
                    if len(entries) >= limit:
                        return entries
        else:
            # простой регэксп-фолбэк, если bs4 не установлен
            import re as _re
            for m in _re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, flags=_re.I|_re.S):
                href, inner = m.group(1), _re.sub(r"<[^>]+>", " ", m.group(2))
                _push(href, inner)
                if len(entries) >= limit:
                    break
    except Exception:
        return entries
    return entries

# ---------- HTTP / FEEDS ----------

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FinNewsHot/0.1; +http://localhost)",
    "Accept": "application/rss+xml, application/xml;q=0.9, text/html;q=0.8, */*;q=0.7",
}

def _discover_feed_link(html: str, base: str) -> str | None:
    try:
        # <link rel="alternate" type="application/rss+xml|application/atom+xml" href="...">
        m = re.findall(
            r'<link[^>]+rel=["\']alternate["\'][^>]+type=["\'](application/(rss|atom)\+xml|application/xml|text/xml)["\'][^>]+href=["\']([^"\']+)["\']',
            html, flags=re.I
        )
        if m:
            href = m[0][-1]
            return urljoin(base, href)
        # Иногда без type — берём первый rel=alternate
        m2 = re.findall(r'<link[^>]+rel=["\']alternate["\'][^>]+href=["\']([^"\']+)["\']', html, flags=re.I)
        if m2:
            return urljoin(base, m2[0])
        return None
    except Exception:
        return None

def fetch_feed(url: str):
    """Загружаем ленту; если дали homepage — пробуем autodiscovery."""
    try:
        with httpx.Client(follow_redirects=True, timeout=20.0, verify=certifi.where(), headers=HEADERS) as c:
            r = c.get(url)
        # 1) попробуем распарсить как фид
        fp = feedparser.parse(r.content)
        if getattr(fp, "entries", []):
            print(f"[feed] {url} -> items={len(fp.entries)}", flush=True)
            return fp
        # 2) если HTML — попробуем найти ссылку на RSS/Atom, иначе HTML-harvest
        ct = r.headers.get("content-type","").lower()
        if "html" in ct or (not ct):
            found = _discover_feed_link(r.text, str(r.url))
            if found:
                with httpx.Client(follow_redirects=True, timeout=20.0, verify=certifi.where(), headers=HEADERS) as c:
                    r2 = c.get(found)
                fp2 = feedparser.parse(r2.content)
                print(f"[feed] {url} -> discovered {found} -> items={len(getattr(fp2,'entries',[]))}", flush=True)
                if getattr(fp2, "entries", []):
                    return fp2
            # HTML-извлечение (псевдо-фид)
            pseudo_entries = _harvest_html_index(r.text, str(r.url), limit=20)
            if pseudo_entries:
                print(f"[feed] {url} -> harvested {len(pseudo_entries)} items from HTML", flush=True)
                return {"entries": pseudo_entries}
        # 3) запасной вариант — пусть feedparser сам попробует по URL
        fp3 = feedparser.parse(url, request_headers=HEADERS)
        print(f"[feed] {url} -> items={len(getattr(fp3,'entries',[]))}", flush=True)
        return fp3
    except Exception as e:
        print(f"[feed][ERR] {url}: {e}", file=sys.stderr, flush=True)
        return feedparser.parse(b"")

# ---------- SMALL TEXT UTILITIES ----------

from urllib.parse import parse_qsl, urlencode, urlunparse

def clean_url(u: str) -> str:
    try:
        p = urlparse(u)
        qs = [(k, v) for (k, v) in parse_qsl(p.query, keep_blank_values=True)
              if not k.lower().startswith(("utm_", "ref", "gclid", "ncid", "cmp"))]
        return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(qs), ""))
    except Exception:
        return u

def _strip_html(html: str | None) -> str:
    html = html or ""
    html = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", html)
    text = re.sub(r"(?is)<[^>]+>", " ", html)
    return " ".join(text.split())

def _meta_desc(html: str) -> str:
    m = re.search(r'(?is)<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html or "")
    if m:
        return " ".join(m.group(1).split())
    m = re.search(r'(?is)<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html or "")
    return " ".join(m.group(1).split()) if m else ""

def _first_sents(text: str, n=2, maxlen=260) -> str:
    sents = re.split(r"(?<=[.!?])\s+", text or "")
    out = []
    for s in sents:
        s = s.strip()
        if len(s) < 40:
            continue
        out.append(s)
        if len(out) >= n:
            break
    teaser = " ".join(out).strip()
    return teaser[:maxlen] if teaser else ""

def teaser_for(entry: dict, link: str) -> str:
    """Формируем короткую аннотацию (why_now) из RSS summary или контента страницы."""
    # 1) summary/description из RSS
    s = (entry or {}).get("summary") or (entry or {}).get("description") or ""
    s = _strip_html(s)
    if len(s) >= 60:
        return _first_sents(s)

    # 2) Подтянуть страницу целиком
    try:
        with httpx.Client(follow_redirects=True, timeout=20.0, verify=certifi.where(),
                          headers={"User-Agent": HEADERS["User-Agent"]}) as c:
            r = c.get(link)
            raw = r.text
            txt = (trafi_extract(r.content) if trafi_extract else "") or _meta_desc(raw) or _strip_html(raw)
            return _first_sents(txt) if txt else ""
    except Exception:
        return ""

# ---------- SIMPLE FEATURES / SCORING ----------

TYPE_SCORE = {"regulator": 1.0, "exchange": 0.95, "ir": 0.9, "news": 0.8, "aggregator": 0.6, "social_twitter": 0.55, "social_linkedin": 0.6}

MATERIALITY_KEYS = {
    "m&a": 0.9, "merger": 0.9, "acquisition": 0.9, "purchase": 0.7,
    "guidance": 0.8, "outlook": 0.7, "forecast": 0.6,
    "downgrade": 0.8, "upgrade": 0.6, "rating": 0.5,
    "dividend": 0.7, "buyback": 0.7, "repurchase": 0.7,
    "sanction": 0.8, "investigation": 0.8, "fine": 0.7, "penalty": 0.7,
    "bankruptcy": 1.0, "insolvency": 0.9, "restatement": 0.9, "delisting": 0.9,
    "enforcement": 0.7, "order": 0.6, "settlement": 0.8, "approval": 0.6,
}


KEYPHRASE_IMPORTANCE_THRESHOLD = 0.55
TIMELINE_KEYWORD_MATCH_THRESHOLD = 0.2
TIMELINE_WINDOW_DAYS = 7

def _collect_important_keywords(items, threshold=KEYPHRASE_IMPORTANCE_THRESHOLD):
    keywords = set()
    for item in items or []:
        name = (item.get("name") or "").strip().lower()
        if not name:
            continue
        try:
            score = float(item.get("score") or 0.0)
        except Exception:
            score = 0.0
        if score >= threshold:
            keywords.add(name)
    return keywords


def _fallback_keywords(text, limit=6, min_len=4):
    tokens = re.findall(r"[\wЀ-ӿ]+", (text or "").lower())
    picked = []
    for token in tokens:
        if len(token) < min_len:
            continue
        if token in picked:
            continue
        picked.append(token)
        if len(picked) >= limit:
            break
    return set(picked)


def _parse_timeline_ts(raw):
    if not raw:
        return None
    try:
        return dt.datetime.fromisoformat(raw)
    except ValueError:
        try:
            return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None


def _append_timeline_if_applicable(ev, existing_keywords, new_keywords, now, teaser, title, stype):
    if not existing_keywords or not new_keywords:
        return False
    overlap = len(existing_keywords & new_keywords)
    if not overlap:
        return False
    ratio = overlap / max(len(new_keywords), 1)
    if ratio < TIMELINE_KEYWORD_MATCH_THRESHOLD:
        return False

    last_ts = None
    for item in reversed(ev.timeline or []):
        if isinstance(item, dict):
            last_ts = _parse_timeline_ts(item.get("t"))
        if last_ts:
            break
    if last_ts is None:
        last_ts = getattr(ev, "first_seen", None)
    if last_ts and (now - last_ts) > dt.timedelta(days=TIMELINE_WINDOW_DAYS):
        return False

    snippet = (teaser or title or "").strip()
    if len(snippet) > 180:
        snippet = snippet[:177].rstrip() + "..."
    label = stype.replace("_", " ") if stype else "update"
    description = f"{label}: {snippet}" if snippet else label

    timeline = list(ev.timeline or [])
    if any(entry.get("what") == description for entry in timeline if isinstance(entry, dict)):
        return False
    timeline.append({"t": now.isoformat(), "what": description})
    ev.timeline = timeline
    return True

def score_materiality(text: str) -> float:
    t = (text or "").lower()
    if not t:
        return 0.3
    s = max((w for k, w in MATERIALITY_KEYS.items() if k in t), default=0.3)
    return float(min(1.0, max(0.0, s)))

def domain(u: str) -> str:
    try:
        return urlparse(u).netloc.lower()
    except Exception:
        return ""

utcnow = lambda: dt.datetime.now(dt.timezone.utc)

def dedup_key(title: str, link: str) -> str:
    """
    Prefer a stable key from the canonicalized link; if it's absent, fallback to title.
    This prevents over-deduplication when many different links share similar titles.
    """
    try:
        lk = (clean_url(link) or "").strip().lower()
    except Exception:
        lk = ""
    base = lk or title.strip().lower()
    return hashlib.sha1(base.encode()).hexdigest()

# ---------- MAIN UPSERT ----------

async def upsert_event(session, title: str, link: str, stype: str, entry=None):
    dk = dedup_key(title, link)
    res = await session.execute(select(Event).where(Event.dedup_group == dk))
    ev = res.scalars().first()
    now = utcnow()
    created_event = False
    existing_keywords_before = set()
    if ev:
        existing_keywords_before = _collect_important_keywords(getattr(ev, "entities", None))
        if not existing_keywords_before:
            existing_keywords_before = _fallback_keywords(" ".join(filter(None, [ev.headline, getattr(ev, "why_now", "") or ""])))

    new_source = False

    # Новизна = 1 - максимальная схожесть с последними 200 заголовками
    prev = (await session.execute(
        select(Event.headline).order_by(Event.first_seen.desc()).limit(200)
    )).scalars().all()
    sim = max([fuzz.partial_ratio(title, t) / 100.0 for t in prev] or [0.0])
    novelty = max(0.0, 1.0 - sim)

    # Аннотация
    teaser = teaser_for(entry or {}, link)

    context_text = " ".join(filter(None, [title, teaser]))
    phrases = extract_keyphrases(context_text)
    phrase_hotness = score_phrase_hotness(phrases)
    new_keywords = _collect_important_keywords(phrases)
    if not new_keywords:
        new_keywords = _fallback_keywords(context_text)

    # ==== AI-фильтр (LLM + эвристика) ====
    ev_event_type = None
    ev_materiality_ai = 0.0
    ev_impact_side = None
    ev_ai_entities = []
    ev_risk_flags = []
    try:
        cls = await classify_event(title, teaser, [link])
        ev_event_type = cls.get("event_type")
        ev_materiality_ai = float(cls.get("materiality_ai") or 0.0)
        ev_impact_side = cls.get("impact_side")
        ev_ai_entities = cls.get("entities") or []
        ev_risk_flags = cls.get("risk_flags") or []
    except Exception:
        # тихий фолбэк — оставим эвристики/пустые значения
        pass

    if not ev:
        ev = Event(
            headline=title,
            hotness=0.0,
            why_now=teaser or "Обновление от первоисточника/регулятора.",
            entities=phrases or [],
            ai_entities=ev_ai_entities,
            risk_flags=ev_risk_flags,
            event_type=ev_event_type,
            materiality_ai=ev_materiality_ai,
            impact_side=ev_impact_side,
            timeline=[{"t": now.isoformat(), "what": "first_seen"}],
            confirmed=(stype in ("regulator", "exchange")),
            dedup_group=dk,
            first_seen=now,
        )
        session.add(ev)
        await session.flush()
        created_event = True
    else:
        # если аннотации ещё нет — дополним
        if not ev.why_now and teaser:
            ev.why_now = teaser

        if phrases:
            merged = {}
            for item in (ev.entities or []):
                name = (item.get("name") or "").strip()
                if not name:
                    continue
                merged[name.lower()] = item
            for item in phrases:
                name = (item.get("name") or "").strip()
                if not name:
                    continue
                key = name.lower()
                existing = merged.get(key)
                if existing:
                    existing_score = float(existing.get("score") or 0.0)
                    incoming_score = float(item.get("score") or 0.0)
                    if incoming_score > existing_score:
                        existing.update(item)
                else:
                    merged[key] = item
            ev.entities = list(merged.values())

        # дополним AI-поля (мягко)
        if ev_event_type and not ev.event_type:
            ev.event_type = ev_event_type
        if ev_impact_side and not ev.impact_side:
            ev.impact_side = ev_impact_side
        if (not getattr(ev, "materiality_ai", None)) and ev_materiality_ai:
            ev.materiality_ai = ev_materiality_ai
        if ev_ai_entities:
            ev.ai_entities = (ev.ai_entities or []) + ev_ai_entities
        if ev_risk_flags:
            ev.risk_flags = list(set((ev.risk_flags or []) + ev_risk_flags))

    # не добавляем одинаковую ссылку второй раз
    exists_q = await session.execute(
        select(func.count()).select_from(Source).where(Source.event_id == ev.id, Source.url == link)
    )
    if exists_q.scalar_one() == 0:
        session.add(Source(event_id=ev.id, url=link, type=stype, first_seen=now))
        new_source = True
        if not created_event:
            _append_timeline_if_applicable(ev, existing_keywords_before, new_keywords, now, teaser, title, stype)

    # собрать все источники события для пересчёта
    srcs = (await session.execute(select(Source).where(Source.event_id == ev.id))).scalars().all()
    dset = {domain(s.url) for s in srcs if s.url}
    has_reg = any(s.type in ("regulator", "exchange") for s in srcs)
    confirmation = 1.0 if has_reg or len(dset) >= 2 else 0.3
    credibility = max([TYPE_SCORE.get(s.type, 0.7) for s in srcs] or [0.7])
    velocity = min(1.0, len(dset) / 5.0)  # 5 доменов = максимум
    materiality_kw = score_materiality(f"{title} {teaser}")
    materiality_phrase = phrase_hotness
    materiality_combined = max(materiality_kw, float(getattr(ev, "materiality_ai", 0.0) or 0.0), materiality_phrase)
    scope = min(1.0, len(dset) / 3.0)

    ev.confirmed = confirmation >= 0.5
    ev.hotness = hotness(novelty, credibility, confirmation, velocity, materiality_combined, scope)

    return ev, created_event, new_source

async def _ensure_schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='event_type')
            THEN ALTER TABLE events ADD COLUMN event_type VARCHAR(64); END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='materiality_ai')
            THEN ALTER TABLE events ADD COLUMN materiality_ai DOUBLE PRECISION; END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='impact_side')
            THEN ALTER TABLE events ADD COLUMN impact_side VARCHAR(16); END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='risk_flags')
            THEN ALTER TABLE events ADD COLUMN risk_flags JSONB DEFAULT '[]'::jsonb; END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='ai_entities')
            THEN ALTER TABLE events ADD COLUMN ai_entities JSONB DEFAULT '[]'::jsonb; END IF;
        END $$;
        """))

async def _fetch_feed_async(url: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(fetch_feed, url))

def _load_sources(maybe_path: str) -> list[dict]:
    if os.path.isdir(maybe_path):
        out = []
        for p in sorted(glob.glob(os.path.join(maybe_path, "*.yaml"))):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    out.extend(yaml.safe_load(f) or [])
            except Exception:
                pass
        return out
    else:
        with open(maybe_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or []

async def run(sources_path: str, concurrency: int = 10, max_per_feed: int = 25):
    await _ensure_schema()
    sources = _load_sources(sources_path)
    total = 0
    new_events = 0
    new_sources = 0
    sem = asyncio.Semaphore(concurrency)

    async def _process_src(src):
        nonlocal total, new_events, new_sources
        url = src["url"]
        stype = src.get("type", "news")
        async with sem:
            # 1) тянем фид/страницу ПАРАЛЛЕЛЬНО
            fp = await _fetch_feed_async(url)
            entries = getattr(fp, "entries", [])[:max_per_feed]

            # 2) а в БД пишем в ОДНОЙ сессии на источник
            async with SessionLocal() as session:
                # reduce autoflush side effects during heavy ingest
                try:
                    session.sync_session.autoflush = False
                    session.sync_session.expire_on_commit = False
                except Exception:
                    pass
                for it in entries:
                    title = it.get("title") or ""
                    link = clean_url(it.get("link") or "")
                    if not title or not link:
                        continue
                    try:
                        # commit/rollback per item to avoid long-running transactions
                        async with session.begin():
                            _, ce, cs = await upsert_event(session, title, link, stype, entry=it)
                        total += 1
                        if ce: new_events += 1
                        if cs: new_sources += 1
                    except asyncio.CancelledError:
                        # do not try to rollback on cancellation – connection may be busy
                        print(f"[db][CANCEL] {url}", file=sys.stderr, flush=True)
                        raise
                    except Exception as e:
                        # fail this item but continue the rest
                        print(f"[db][ERR item] {url}: {e}", file=sys.stderr, flush=True)

    await asyncio.gather(*(_process_src(s) for s in sources))
    print(f"[ingest] done, processed ~{total} items; new_events={new_events}, new_sources={new_sources}", flush=True)

# ---------- CLI ----------

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True, help="YAML file or directory with *.yaml (RSS/Atom or homepages with autodiscovery/HTML fallback)")
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--max-per-feed", type=int, default=25)
    args = ap.parse_args()
    asyncio.run(run(args.sources, args.concurrency, args.max_per_feed))
