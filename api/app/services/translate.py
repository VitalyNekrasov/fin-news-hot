# api/app/services/translate.py
import os, hashlib, json
from typing import Optional
import redis.asyncio as aioredis
from fastapi.encoders import jsonable_encoder

_client = None
_redis = None

async def _get_client():
    """Возвращает OpenAI-совместимый клиент или None (если ключа/пакета нет)."""
    global _client
    if _client is not None:
        return _client
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except Exception:
        return None
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    headers = {"HTTP-Referer": "http://localhost:5173", "X-Title": "Fin News Hot"} if "openrouter.ai" in base_url else None
    _client = OpenAI(api_key=api_key, base_url=base_url, default_headers=headers)
    return _client

async def _get_redis():
    global _redis
    if _redis is not None:
        return _redis
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    _redis = aioredis.from_url(url, decode_responses=True)
    return _redis

async def translate_text(text: Optional[str], target: str = "ru") -> str:
    """Мягкий перевод: без ключа/ошибки просто возвращает исходный текст."""
    text = (text or "").strip()
    if not text:
        return text

    h = hashlib.sha1(f"{target}:{text}".encode()).hexdigest()
    key = f"tr:{h}"
    r = await _get_redis()
    if r:
        cached = await r.get(key)
        if cached:
            return cached

    client = await _get_client()
    if client is None:
        return text  # нет ключа/пакета — не падаем

    model = os.getenv("OPENAI_MODEL_TRANSLATE", os.getenv("OPENAI_MODEL", "openai/gpt-4o-mini"))
    prompt = f"Переведи на {target} кратко и естественно. Не добавляй ничего и не теряй цифры/имена:\n{text}"
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        out = (resp.choices[0].message.content or "").strip() or text
    except Exception:
        out = text

    if r:
        await r.setex(key, 3600, out)
    return out

async def translate_event_dict(d: dict, target: str = "ru") -> dict:
    """Перевод только текстовых полей. Сначала делаем JSON-safe копию (datetime → str)."""
    d = jsonable_encoder(d)  # безопасная глубокая копия

    d["headline"] = await translate_text(d.get("headline"), target)
    if d.get("why_now"):
        d["why_now"] = await translate_text(d["why_now"], target)

    dr = d.get("draft")
    if dr:
        if dr.get("title"):
            dr["title"] = await translate_text(dr["title"], target)
        if dr.get("lede"):
            dr["lede"] = await translate_text(dr["lede"], target)
        if dr.get("bullets"):
            dr["bullets"] = [await translate_text(b, target) for b in dr["bullets"]]
        if dr.get("quote"):
            dr["quote"] = await translate_text(dr["quote"], target)

    return d