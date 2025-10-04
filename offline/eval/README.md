# Evaluation Dataset Guidelines

This folder hosts manual annotations used to measure the quality of our BERT NER keyphrases and their contribution to hotness/materiality.

## File format

Create a JSON Lines file (one JSON object per line), e.g. `offline/eval/ner_hotness_labels.jsonl`. Each record must contain:

```json
{
  "id": "evt-2024-08-13-sec-001",
  "headline": "SEC fines Broker X over reporting failures",
  "teaser": "The regulator imposed penalties after multiple late filings.",
  "ground_phrases": [
    {"name": "SEC", "type": "ORG", "importance": 0.95},
    {"name": "Broker X", "type": "ORG", "importance": 0.7},
    {"name": "reporting failures", "type": "MISC", "importance": 0.6}
  ],
  "phrase_hotness_label": 0.88
}
```

### Field definitions

- `id`: free-form identifier so we can cross-reference the sample with raw data.
- `headline`, `teaser`: the exact strings fed into the ingest pipeline.
- `ground_phrases`: list of key phrases that should be recognised. Use uppercase type tags compatible with the NER model (`ORG`, `PER`, `LOC`, `MISC`). `importance` is a manual 0..1 weight reflecting how strongly the phrase should influence hotness/materiality.
- `phrase_hotness_label`: optional manual 0..1 estimate of how "hot" the article feels after considering the key phrases. If missing, the evaluator will skip the MAE/RMSE calculation for that sample.

### Annotation tips

- Focus on entities and phrases that drive market relevance: regulators, listed companies, products, sanctions, deal names, etc.
- Keep `importance` relative within the article. If everything is equally relevant, keep them close (e.g. 0.7 / 0.65). Outliers (0.9+) should represent dominant signals.
- If a phrase contains multiple tokens but refers to one entity, annotate it as a single entry (e.g. "Federal Reserve" rather than two separate words).

## Exporting samples

Run `offline/eval/export_samples.py` to dump recent events into a JSON Lines skeleton before you start annotating. The script pulls the latest items from your database, keeps the headline, the cached why_now teaser, and copies current model outputs so annotators can compare against them.

```
python offline/eval/export_samples.py offline/eval/ner_hotness_samples.jsonl --limit 40 --min-hotness 0.4
```

Key fields:
- `ground_phrases` and `phrase_hotness_label` stay empty for the human labeler.
- `predicted_phrases`, `ai_entities`, and `hotness_model` show the current pipeline outputs for reference.
- `sources` and `metadata` help trace the original URLs and timestamps if you need extra context.

Once the file is labeled, feed it to `run_eval.py` as described below.

## Minimum dataset size

For a meaningful snapshot start with at least 50 documents (roughly 150–200 phrases). The metrics stabilise when precision and recall become less sensitive to single errors.

## Storing labels

Place curated datasets in this folder; name them by date or domain, e.g.:

```
offline/eval/
  ner_hotness_labels.2025-03-finreg.jsonl
```

Large or private datasets can stay outside the repo — the evaluation script accepts an arbitrary path.

