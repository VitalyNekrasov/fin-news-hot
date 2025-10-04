def hotness(novelty: float, credibility: float, confirmation: float,
            velocity: float, materiality: float, scope: float) -> float:
    weights = {
        "novelty": 0.25,
        "credibility": 0.20,
        "confirmation": 0.20,
        "velocity": 0.15,
        "materiality": 0.10,
        "scope": 0.10,
    }
    values = {
        "novelty": float(novelty),
        "credibility": float(credibility),
        "confirmation": float(confirmation),
        "velocity": float(velocity),
        "materiality": float(materiality),
        "scope": float(scope),
    }
    score = sum(weights[k] * values[k] for k in weights)
    # бизнес-правило: без подтверждения/низкой достоверности не поднимаем высоко
    if values["confirmation"] < 0.5 and values["credibility"] < 0.7:
        score = min(score, 0.49)
    # в разумные границы
    score = max(0.0, min(1.0, score))
    return round(score, 3)
