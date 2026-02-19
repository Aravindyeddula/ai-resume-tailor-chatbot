# AI Resume Builder

Simple Streamlit app to tailor a resume against a job description.

## Setup

```powershell
cd c:\Users\aravi\ai-resume-tailor-chatbot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Optional (better rewrite quality):

```powershell
$env:OPENAI_API_KEY="your_api_key_here"
```

## Run

```powershell
streamlit run streamlit_app.py
```

## How It Works

1. Upload one resume file and one JD file.
2. Click `Generate Tailored Resume`.
3. Download the tailored output.

Supported input formats: `.txt`, `.md`, `.html`, `.htm`, `.pdf`  
Output preserves extension for `.txt`, `.md`, `.html`, `.htm`; PDF currently outputs `.txt`.
