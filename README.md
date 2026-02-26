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

1. Upload your resume file from local system (`.pdf`, `.docx`, `.txt`, `.md`, `.html`, `.htm`).
2. Paste the target JD text in the job description box.
3. Keep `Require OpenAI rewrite` enabled if you want strict model-based tailoring.
4. Click `Generate Tailored Resume`.
5. Download the tailored output.

## LaTeX Template Output (New)

- Upload a resume and paste the JD text (same inputs).
- Click `Generate LaTeX Resume (.tex)`.
- The app extracts roles/responsibilities and renders a LaTeX resume in the `resume.cls` style.
- Output files are written to `artifacts/latex/`:
  - `<resume_name>_templated.tex`
  - `resume.cls`
  - `resume_faangpath.tex` (reference template you provided)

Template assets copied into project:
- `templates/latex/resume.cls`
- `templates/latex/resume_faangpath.tex`

Output format follows the uploaded resume extension when supported.  
If a writer dependency is missing, app falls back to `.txt`.

Notes:
- If `OPENAI_API_KEY` is missing/unavailable, app uses heuristic mode.
- Heuristic mode now always adds a visible `Targeted JD Alignment` section so output is not identical to input.
- For `.docx`, the app reuses the uploaded document structure to preserve heading/font styles.
- For `.pdf`, the app now generates a tailored-only PDF using the original page size and style cues.
- For LaTeX mode, OpenAI is recommended for better section extraction from PDF text.
