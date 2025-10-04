import os, re, json, asyncio
import httpx, certifi

# ===== эвристики на случай отсутствия ключа / проблем сети =====
KW_EVENT = [
    (r"\b(merger|acquisition|acquire|merge|takeover|buyout|combination)\b", "M&A"),
    (r"\b(dividend|buyback|repurchase)\b", "dividend/buyback"),
    (r"\b(sanction|embargo)\b", "sanctions"),
    (r"\b(investigation|probe|enforcement|charge|charged|settlement)\b", "investigation"),
    (r"\b(fine|penalty)\b", "fine"),
    (r"\b(delisting|delist|suspension)\b", "delisting"),
    (r"\b(guidance|outlook|forecast)\b", "guidance"),
    (r"\b(approval|rule|ruling|order|directive)\b", "regulatory"),
]

def _heur_event_type(text: str) -> str:
    t = (text or "").lower()
    for pat, tag in KW_EVENT:
        if re.search(pat, t): return tag
    return "other"

def _heur_materiality(text: str) -> float:
    t = (text or "").lower()
    if any(k in t for k,_ in KW_EVENT[:1]): return 0.85
    if any(k in t for k,_ in KW_EVENT[1:3]): return 0.75
    if "investigation" in t or "enforcement" in t: return 0.7
    if "guidance" in t or "forecast" in t: return 0.6
    return 0.4

def _heur_impact(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ["upgrade","approval","record","beat","exceed"]): return "pos"
    if any(k in t for k in ["downgrade","fine","penalty","charge","sanction","delisting","miss","probe"]): return "neg"
    return "uncertain"

def _extract_tickers(text: str) -> list[dict]:
    # очень простая эвристика — до интеграции нормального тикер-маппера
    tick = re.findall(r"\b[A-Z]{1,5}\b", text or "")
    ban = {"CEO","CFO","SEC","FOMC","FRB","EC","ECB","FCA","ESMA","EU","US","UK","USD","JPM"}
    uniq = []
    for t in tick:
        if t in ban: continue
        if t not in uniq: uniq.append(t)
    return [{"name": x, "ticker": x} for x in uniq[:8]]

def _risk_flags_from_context(teaser: str, urls: list[str]) -> list[str]:
    flags = []
    if len(set(urls)) < 1: flags.append("no_url")
    if len(set(urls)) == 1: flags.append("single_source")
    if not teaser or len(teaser) < 60: flags.append("low_context")
    return flags

async def _call_llm(headline: str, teaser: str, urls: list[str]) -> dict | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except Exception:
        return None

    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("OPENAI_MODEL_CLASSIFIER", os.getenv("OPENAI_MODEL","openai/gpt-4o-mini"))
    headers = {"HTTP-Referer":"http://localhost:5173","X-Title":"Fin News Hot"} if "openrouter.ai" in base_url else None
    client = OpenAI(api_key=api_key, base_url=base_url, default_headers=headers)

    srcs = "\n".join(f"- {u}" for u in urls[:5])
    prompt = f"""
Ты финансовый редактор. Верни ТОЛЬКО JSON с полями:
{{"event_type":"guidance|M&A|sanctions|investigation|fine|delisting|dividend/buyback|regulatory|other",
  "materiality_ai":0..1,
  "impact_side":"pos|neg|uncertain",
  "entities":[{{"name":"...","ticker":"..."}}],
  "risk_flags":["...","..."]}}

Headline: {headline}
Teaser: {teaser[:600]}
Links:
{srcs}
Без выдумок; если не уверен — impact_side="uncertain".
"""

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role":"user","content":prompt}],
            temperature=0.1,
            timeout=20,
        )
        raw = resp.choices[0].message.content
        # мягкий JSON-парсер
        import re as _re
        m = _re.search(r"\{.*\}", raw, _re.S)
        data = json.loads(m.group(0) if m else raw)
        # базовая валидация
        if "event_type" not in data or "materiality_ai" not in data:
            return None
        return data
    except Exception:
        return None

async def classify_event(headline: str, teaser: str, urls: list[str]) -> dict:
    # 1) LLM, если доступен
    data = await _call_llm(headline, teaser, urls)
    if data:
        # страховки
        data["event_type"] = (data.get("event_type") or "other")
        try:
            data["materiality_ai"] = max(0.0, min(1.0, float(data.get("materiality_ai", 0.4))))
        except Exception:
            data["materiality_ai"] = 0.4
        data["impact_side"] = (data.get("impact_side") or "uncertain")
        data["entities"] = data.get("entities") or _extract_tickers(headline + " " + teaser)
        rf = set(data.get("risk_flags") or [])
        data["risk_flags"] = list(rf | set(_risk_flags_from_context(teaser, urls)))
        return data

    # 2) эвристика (фолбэк)
    base_text = f"{headline}. {teaser or ''}"
    return {
        "event_type": _heur_event_type(base_text),
        "materiality_ai": _heur_materiality(base_text),
        "impact_side": _heur_impact(base_text),
        "entities": _extract_tickers(base_text),
        "risk_flags": _risk_flags_from_context(teaser, urls),
    }