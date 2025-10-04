"""Utilities for extracting key phrases with a BERT-based NER model
and estimating their contribution to the hotness score.
The pipeline is optional: if `transformers` or the model is not available
we fall back to an empty result, keeping the ingest flow intact.
"""
from __future__ import annotations
import os
from functools import lru_cache
from typing import Dict, List, Optional
_LABEL_WEIGHTS: Dict[str, float] = {
    "ORG": 1.0,
    "MISC": 0.7,
    "PER": 0.6,
    "LOC": 0.5,
}
_DEFAULT_MODEL = os.getenv("FINNEWS_NER_MODEL", "dslim/bert-base-NER")
_DEFAULT_MIN_SCORE = float(os.getenv("FINNEWS_NER_MIN_SCORE", "0.55"))
try:  # optional dependency
    from transformers import (
        AutoModelForTokenClassification,
        AutoTokenizer,
        pipeline,
    )
except Exception:  # pragma: no cover - executed when transformers is missing
    AutoModelForTokenClassification = None
    AutoTokenizer = None
    pipeline = None
def _is_disabled() -> bool:
    return os.getenv("FINNEWS_DISABLE_BERT_NER", "0").lower() in {"1", "true", "yes"}
@lru_cache(maxsize=1)
def _ner_pipeline():
    """Lazily initialise the transformers NER pipeline."""
    if _is_disabled():
        return None
    if AutoModelForTokenClassification is None or AutoTokenizer is None or pipeline is None:
        return None
    model_name = os.getenv("FINNEWS_NER_MODEL", _DEFAULT_MODEL)
    device = os.getenv("FINNEWS_NER_DEVICE", "cpu").lower()
    device_id = 0 if device not in {"cpu", "-1"} else -1
    try:
        model = AutoModelForTokenClassification.from_pretrained(model_name)
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        return pipeline(
            "ner",
            model=model,
            tokenizer=tokenizer,
            aggregation_strategy="simple",
            device=device_id,
        )
    except Exception:
        # If the model cannot be downloaded or initialised we silently disable NER.
        return None
def extract_keyphrases(text: str, min_score: Optional[float] = None) -> List[dict]:
    """Return aggregated NER phrases in the FinNews JSON flavour.
    Each item looks like::
        {"name": "Federal Reserve", "type": "ORG", "score": 0.91, "source": "bert-ner"}
    """
    text = (text or "").strip()
    if not text:
        return []
    ner = _ner_pipeline()
    if ner is None:
        return []
    min_score = _DEFAULT_MIN_SCORE if min_score is None else float(min_score)
    results = ner(text)
    phrases: Dict[str, dict] = {}
    for item in results:
        score = float(item.get("score") or 0.0)
        if score < min_score:
            continue
        raw = item.get("word") or item.get("text") or ""
        if not raw:
            continue
        phrase = raw.replace("##", "").strip()
        if not phrase:
            continue
        entity = item.get("entity_group") or item.get("entity") or "MISC"
        entry = {
            "name": phrase,
            "type": entity,
            "score": round(min(1.0, score), 4),
            "source": "bert-ner",
        }
        key = phrase.lower()
        if key not in phrases or phrases[key]["score"] < entry["score"]:
            phrases[key] = entry
    return list(phrases.values())
def score_phrase_hotness(phrases: List[dict]) -> float:
    """Estimate how much the extracted phrases strengthen the hotness signal."""
    if not phrases:
        return 0.0
    values = []
    for ph in phrases:
        label = ph.get("type") or "MISC"
        weight = _LABEL_WEIGHTS.get(label, 0.4)
        score = float(ph.get("score") or 0.0)
        values.append(weight * score)
    if not values:
        return 0.0
    top = max(values)
    average = sum(values) / len(values)
    diversity = min(1.0, len(values) / 5.0)
    combined = 0.6 * top + 0.25 * average + 0.15 * diversity
    return round(min(1.0, max(0.0, combined)), 3)
__all__ = ["extract_keyphrases", "score_phrase_hotness"]

