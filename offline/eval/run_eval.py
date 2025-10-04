import argparse
import json
import math
from pathlib import Path
from typing import Dict, List, Tuple

from api.app.services import keyphrases


def _normalise(text: str) -> str:
    return " ".join((text or "").split()).lower()


def _to_map(items: List[dict]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for item in items or []:
        name = item.get("name")
        if not name:
            continue
        key = _normalise(name)
        if not key:
            continue
        out[key] = item
    return out


def _phrase_value(item: dict) -> float:
    label = (item.get("type") or "MISC").upper()
    weight = keyphrases._LABEL_WEIGHTS.get(label, 0.4)  # type: ignore[attr-defined]
    return weight * float(item.get("score") or 0.0)


def evaluate(dataset_path: Path) -> Tuple[dict, List[dict]]:
    tp = fp = fn = 0
    type_tp = 0
    type_total = 0
    importance_abs_err = 0.0
    importance_cnt = 0
    hotness_abs_err = 0.0
    hotness_sq_err = 0.0
    hotness_cnt = 0

    details: List[dict] = []

    with dataset_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            sample = json.loads(line)
            headline = sample.get("headline") or ""
            teaser = sample.get("teaser") or ""
            context_text = " ".join(filter(None, [headline, teaser]))

            predicted = keyphrases.extract_keyphrases(context_text)
            pred_map = _to_map(predicted)
            gt_items = sample.get("ground_phrases") or []
            gt_map = _to_map(gt_items)

            sample_tp = 0
            for key, item in pred_map.items():
                if key in gt_map:
                    sample_tp += 1
                else:
                    fp += 1
            tp += sample_tp
            fn += max(0, len(gt_map) - sample_tp)

            for key, gt_item in gt_map.items():
                type_total += 1
                pred_item = pred_map.get(key)
                if not pred_item:
                    continue
                if (pred_item.get("type") or "").upper() == (gt_item.get("type") or "").upper():
                    type_tp += 1

            for key, gt_item in gt_map.items():
                if "importance" not in gt_item:
                    continue
                pred_item = pred_map.get(key)
                if not pred_item:
                    continue
                pred_value = _phrase_value(pred_item)
                gt_value = float(gt_item.get("importance") or 0.0)
                importance_abs_err += abs(pred_value - gt_value)
                importance_cnt += 1

            label = sample.get("phrase_hotness_label")
            if label is not None:
                pred_hotness = keyphrases.score_phrase_hotness(predicted)
                diff = pred_hotness - float(label)
                hotness_abs_err += abs(diff)
                hotness_sq_err += diff * diff
                hotness_cnt += 1

            details.append({
                "id": sample.get("id"),
                "headline": headline,
                "teaser": teaser,
                "predicted": predicted,
                "ground_phrases": gt_items,
                "phrase_hotness_pred": keyphrases.score_phrase_hotness(predicted),
                "phrase_hotness_label": label,
            })

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    type_accuracy = type_tp / type_total if type_total else 0.0
    importance_mae = importance_abs_err / importance_cnt if importance_cnt else None
    hotness_mae = hotness_abs_err / hotness_cnt if hotness_cnt else None
    hotness_rmse = math.sqrt(hotness_sq_err / hotness_cnt) if hotness_cnt else None

    metrics = {
        "samples": len(details),
        "phrases_gt": sum(len(_to_map(d.get("ground_phrases") or [])) for d in details),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "type_accuracy": round(type_accuracy, 4),
        "importance_mae": round(importance_mae, 4) if importance_mae is not None else None,
        "hotness_mae": round(hotness_mae, 4) if hotness_mae is not None else None,
        "hotness_rmse": round(hotness_rmse, 4) if hotness_rmse is not None else None,
    }
    return metrics, details


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate NER keyphrases and phrase hotness against annotated data")
    parser.add_argument("dataset", help="Path to JSONL file with annotations")
    parser.add_argument("--show", action="store_true", help="Print per-sample predictions")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise SystemExit(f"Dataset not found: {dataset_path}")

    metrics, details = evaluate(dataset_path)

    print("=== Aggregate metrics ===")
    for key, value in metrics.items():
        print(f"{key}: {value}")

    if args.show:
        print("\n=== Sample details ===")
        for item in details:
            print(json.dumps(item, ensure_ascii=False))


if __name__ == "__main__":
    main()
