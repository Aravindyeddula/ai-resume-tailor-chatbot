# Architecture Overview

## Goal
Build a practical web/CLI chatbot with:
1. File-grounded answers with citations (Feature A)
2. Selective durable memory in markdown (Feature B)
3. Safe sandboxed weather analytics using Open-Meteo (Feature C)

## High-Level Flow

### 0) Interfaces
- Web app: `app/web.py` + `app/templates/index.html`
- CLI: `app/cli.py`
- Both call shared backend modules (`ingest`, `retrieval`, `qa`, `memory`)

### 1) Ingestion (Upload -> Parse -> Chunk)
- Supported formats:
  - txt, md, html/htm, pdf
- Parsing:
  - text/markdown: direct read
  - html: strip tags with `html.parser`
  - pdf: `pypdf` extraction
- Chunking:
  - paragraph-aware
  - max chunk size 700 chars
  - 120-char overlap for split long paragraphs
- Chunk metadata:
  - `chunk_id`
  - `source`
  - `locator`
  - `text`

### 2) Indexing / Storage
- Persisted in `data/`:
  - `index.json` (chunk records)
  - `vectorizer.pkl` (TF-IDF vocab + idf)
  - `matrix.npz` (serialized dense vectors)
- Design choice:
  - local file artifacts for reproducibility and easy debugging

### 3) Retrieval + Grounded Answering
- Retrieval strategy:
  - TF-IDF cosine score
  - BM25 score
  - weighted hybrid score (0.55 cosine + 0.45 normalized BM25)
- Query behavior:
  - default `top_k=1` for precision
  - auto-expand to 3 for explanatory/list style prompts
- Grounding:
  - deterministic answer extraction from retrieved chunks
  - citations built from retrieved chunks (`source`, `locator`, `snippet`)
- Failure mode:
  - return: `I cannot find this in the uploaded documents.`

### 4) Memory System (Selective)
- Decision shape:
  - `should_write`
  - `target` (`USER` or `COMPANY`)
  - `summary`
  - `confidence`
- Write policy:
  - high-signal user preferences/roles -> `USER_MEMORY.md`
  - reusable workflow learnings -> `COMPANY_MEMORY.md`
- Safety:
  - do not store passwords/api keys/secrets/ssn/credit-card data
  - avoid transcript dumping
- Storage behavior:
- append timestamped bullet
- skip duplicate lines

### 5) Feature C: Safe Python Sandbox + Open-Meteo
- Data source:
  - Open-Meteo geocoding + weather APIs (no key required)
- Tool entrypoint:
  - `python -m app.cli weather-analyze --location ... --start-date ... --end-date ... --hourly-var ...`
- Safety boundary:
  - time-series analytics execute in isolated Python subprocess (`python -I`)
  - sandbox timeout enforced
  - bounded date range and output size checks
- Analytics computed:
  - missingness rate
  - mean/min/max
  - volatility (std dev)
  - 24h rolling average trend
  - anomaly flags (outside +/-2.5 std dev)
- Output:
  - machine-readable JSON + human-readable explanation

## Sanity / Evaluation Flow
- `make sanity` runs `python -m app.cli sanity`
- It:
  - ingests `sample_docs/`
  - runs deterministic QA prompts with citations
  - writes memory entries
  - generates `artifacts/sanity_output.json`
- Validation:
  - `python scripts/verify_output.py artifacts/sanity_output.json`

## Tradeoffs & Next Steps
- Why this design:
  - deterministic, local, reproducible for development and testing
  - robust enough for varied question phrasing without external vector DB
- Limitations:
  - still lexical-first; semantic recall can be improved
- Next improvements:
  - add embedding rerank stage
  - add source-span level citation snippets
  - add optional per-project index namespaces
