# Agentic RAG Chatbot

## Overview
This project implements:
- Feature A: file-grounded Q&A with citations
- Feature B: selective persistent memory in markdown
- Feature C: safe Python sandbox weather time-series analytics via Open-Meteo
- Resume Tailor: upload resume + JD and generate a tailored resume output

Interfaces:
- Streamlit chatbot (`streamlit run streamlit_app.py`)
- Web app (`python -m app.web`)
- CLI (`python -m app.cli ...`)

## Quick Start

### 1) Create virtual env (Windows PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

```

### 2) Install dependencies
```powershell
pip install -r requirements.txt
```

### 2.1) (Optional) Enable OpenAI answer generation mode
```powershell
$env:OPENAI_API_KEY="your_api_key_here"
```
When set, RAG answers use OpenAI in grounded mode; otherwise deterministic mode is used.

### 3) Run Streamlit chatbot UI (recommended)
```powershell
streamlit run streamlit_app.py
```
Open: `http://localhost:8501`

### 3.1) Resume Tailor flow (Streamlit sidebar)
1. In `Resume Tailor`, upload:
   - one resume file
   - one job description file
2. Click `Tailor Resume`.
3. Download the generated file from the sidebar.

Notes:
- If `OPENAI_API_KEY` is set, tailoring uses OpenAI for stronger rewriting.
- Without API key, a local heuristic fallback is used.
- Output extension is preserved for `.txt`, `.md`, `.html`, `.htm`.
- For `.pdf` input, output currently falls back to `.txt`.

### 4) Run Flask web app (optional)
```powershell
python -m app.web
```
Open: `http://127.0.0.1:5000`

### 5) Run CLI flow (optional)
```powershell
python -m app.cli ingest --input sample_docs
python -m app.cli ask --question "What is the main contribution?" --top-k 1
python -m app.cli remember --text "I'm a Project Finance Analyst."
python -m app.cli weather-analyze --location "New York" --start-date 2025-01-01 --end-date 2025-01-03 --hourly-var temperature_2m
```

### 6) Run sanity checks
```powershell
make sanity
python scripts/verify_output.py artifacts/sanity_output.json
```

If `make` is unavailable on Windows:
```powershell
python -m app.cli sanity
python scripts/verify_output.py artifacts/sanity_output.json
```

Or:
```powershell
powershell -ExecutionPolicy Bypass -File scripts/sanity_check.ps1
```

## Public Commands
- `streamlit run streamlit_app.py`
- `python -m app.web`
- `python -m app.cli ingest --input <dir>`
- `python -m app.cli ask --question "..." --top-k 1`
- `python -m app.cli remember --text "..."`
- `python -m app.cli weather-analyze --location "..." --start-date YYYY-MM-DD --end-date YYYY-MM-DD --hourly-var temperature_2m`
- `python -m app.cli sanity`
- `python scripts/smoke_test.py`

## Supported File Types
- `.txt`
- `.md`
- `.html` / `.htm`
- `.pdf` (via `pypdf`)

## Data + Artifacts
- Uploaded files: `uploads/`
- Index artifacts: `data/index.json`, `data/vectorizer.pkl`, `data/matrix.npz`
- Sanity output: `artifacts/sanity_output.json`
- Memory files: `USER_MEMORY.md`, `COMPANY_MEMORY.md`

## Feature A (RAG + Citations)
- Ingestion: parse -> chunk -> index
- Retrieval: hybrid lexical ranking (TF-IDF cosine + BM25)
- Answering:
  - deterministic extraction from retrieved content
  - optional OpenAI mode if `OPENAI_API_KEY` exists
- Citations include:
  - `source`
  - `locator`
  - `snippet`
- Out-of-scope behavior:
  - `I cannot find this in the uploaded documents.`

## Feature B (Persistent Memory)
- Internal memory decision:
  - `should_write`
  - `target` (`USER` or `COMPANY`)
  - `summary`
  - `confidence`
- Writes selective, high-signal entries only
- Filters sensitive data (password/api key/secret/ssn/credit card)
- Appends timestamped bullets and avoids duplicates

## Feature C (Safe Sandbox + Open-Meteo)
- Tool interface:
  - `python -m app.cli weather-analyze --location "New York" --start-date 2025-01-01 --end-date 2025-01-03 --hourly-var temperature_2m`
- Fetches weather time series from Open-Meteo (no API key)
- Executes analytics in an isolated Python subprocess (`python -I`) with timeout
- Analytics include:
  - rolling average trend (24h)
  - volatility (std dev)
  - missingness checks
  - anomaly flags (>|2.5 std dev|)
- Returns:
  - structured summary JSON
  - human-readable explanation

## Suggested Evaluation
Use `EVAL_QUESTIONS.md`.

## Video Walkthrough
vedio Link : https://drive.google.com/drive/folders/1IriykY9ToTJEdVlAnOabRukvWgkbHYlh?usp=drive_link
