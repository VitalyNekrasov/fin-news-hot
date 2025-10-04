# api/app/services/generate.py
import os, json, re, textwrap, difflib
import httpx, certifi

# ---------- утилиты извлечения текста ----------

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FinNewsHot/0.1; +http://localhost)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def _clean(text: str, limit: int | None = None) -> str:
    if not text: return ""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] if limit else text

def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", html or "")
    text = re.sub(r"(?is)<[^>]+>", " ", html)
    return _clean(text, 4000)

def _meta_desc(html: str) -> str:
    m = re.search(r'(?is)<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html or "")
    if m: return _clean(m.group(1), 400)
    m = re.search(r'(?is)<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html or "")
    return _clean(m.group(1), 400) if m else ""

def _sentences(txt: str) -> list[str]:
    s = re.split(r"(?<=[.!?])\s+", txt or "")
    return [x.strip() for x in s if 40 <= len(x.strip()) <= 220]

def _fetch_context(sources: list[dict], max_sources=2, max_chars=2000) -> tuple[str, list[str]]:
    urls, seen = [], set()
    for s in (sources or []):
        u = s.get("url")
        if u and u not in seen:
            seen.add(u); urls.append(u)
            if len(urls) >= max_sources: break
    if not urls: return "", []

    # trafilatura как «лучше», html+meta — фолбэк
    try:
        try:
            from trafilatura import extract as trafi_extract  # lazy import
        except Exception:
            trafi_extract = None
        parts = []
        with httpx.Client(follow_redirects=True, timeout=20, verify=certifi.where(), headers=HEADERS) as c:
            for u in urls:
                try:
                    r = c.get(u)
                    txt = (trafi_extract(r.content) if trafi_extract else "") or _meta_desc(r.text) or _strip_html(r.text)
                    if txt:
                        parts.append(f"[{u}]\n{_clean(txt, max_chars//max_sources)}")
                except Exception:
                    continue
        return ("\n\n".join(parts)[:max_chars], urls)
    except Exception:
        return "", urls

# ---------- эвристика оформления черновика ----------

def _paraphrase_title(headline: str) -> str:
    h = headline.strip()
    h = re.sub(r"^\s*(U\.?S\.?\s+)?(Securities and Exchange Commission|SEC)\s+(announces|issues|seeks|charges|approves|names)\s+",
               r"SEC \3 ", h, flags=re.I)
    h = re.sub(r"^\s*(Federal Reserve Board|Board of Governors of the Federal Reserve System)\s+(announces|issues|seeks|approves)\s+",
               r"Fed \2 ", h, flags=re.I)
    h = re.sub(r"\s*-\s*Press Release$", "", h, flags=re.I)
    return (h[:87] + "…") if len(h) > 90 else h

def _key_sents(ctx: str) -> list[str]:
    sents = _sentences(ctx)
    if not sents: return []
    pat = re.compile(r"\b(enforcement|fine|penalt|investig|order|settle|merg|acquisit|dividend|buyback|guidance|approval|agenda|panel|conference|termination|appointment|charged)\b", re.I)
    scored = []
    for s in sents:
        score = 0
        if pat.search(s): score += 2
        if len(s) > 120: score += 1
        scored.append((score, s))
    scored.sort(reverse=True, key=lambda x: x[0])
    return [s for _, s in (scored[:5] or [(0, sents[0])])]

def _heuristic(headline: str, seed: str, ctx: str, urls: list[str]) -> dict:
    ks = _key_sents(seed + " " + ctx)
    lede = " ".join(ks[:2]) if ks else (seed or "Кратко: детали из первоисточника уточняются.")
    bullets = ks[:3] or [seed or "Обновление от первоисточника.", "Подтверждение: есть", "Следим за обновлениями"]
    return {
        "why_now": seed or "Важно сейчас: обновление от регулятора/первоисточника.",
        "draft": {
            "title": _paraphrase_title(headline),
            "lede": lede,
            "bullets": bullets[:3],
            "quote": "",
            "attribution": urls[:3],
        }
    }

def _too_similar(a: str, b: str) -> bool:
    return difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio() >= 0.88

# ---------- основная функция ----------

def gen_why_now_and_draft(headline: str, sources: list[dict], seed_text: str | None = None) -> dict:
    # 1) контекст + seed
    ctx, used_urls = _fetch_context(sources, max_sources=2, max_chars=2000)
    seed = (seed_text or "").strip()
    combined = (seed + ("\n\n" + ctx if ctx else "")).strip()

    # базовая эвристика — уже даёт приличный результат
    base = _heuristic(headline, seed, ctx, used_urls)

    # 2) если нет ключа — отдаём эвристику
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return base

    # 3) вызов LLM как «редактор» поверх нашей заготовки
    try:
        from openai import OpenAI
    except Exception:
        return base

    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("OPENAI_MODEL", "openai/gpt-4o-mini")
    default_headers = {"HTTP-Referer": "http://localhost:5173", "X-Title": "Fin News Hot"} if "openrouter.ai" in base_url else None
    client = OpenAI(api_key=api_key, base_url=base_url, default_headers=default_headers)

    system = "Ты финансовый редактор. Лаконично, фактологично, без воды."
    user = textwrap.dedent(f"""
    Headline: {headline}

    Контекст (сначала наша аннотация, потом фрагменты страниц):
    <<<CONTEXT
    {combined or "нет текста"}
    CONTEXT>>>

    Исходный черновик (отредактируй его — не переписывай с нуля):
    {json.dumps(base, ensure_ascii=False)}

    Требования:
    - Не повторяй headline дословно. Title ≤ 90 символов.
    - Факты только из CONTEXT/ссылок. Никаких выдуманных чисел.
    - Верни ТОЛЬКО JSON с полями why_now и draft (title, lede, bullets, quote, attribution).
    """)

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role":"system","content":system},{"role":"user","content":user}],
            temperature=0.2,
        )
        raw = resp.choices[0].message.content
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else json.loads(raw)
        dr = data.get("draft", {}) if isinstance(data, dict) else {}

        # страховки
        if not dr.get("title") or _too_similar(dr.get("title",""), headline):
            dr["title"] = base["draft"]["title"]
        if not dr.get("lede"): dr["lede"] = base["draft"]["lede"]
        if not dr.get("bullets"): dr["bullets"] = base["draft"]["bullets"]
        if not dr.get("attribution"): dr["attribution"] = base["draft"]["attribution"]

        return {"why_now": data.get("why_now") or base["why_now"], "draft": dr}
    except Exception as e:
        print("[generate] LLM error:", repr(e), flush=True)
        return base