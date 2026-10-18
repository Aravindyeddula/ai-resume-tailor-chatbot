# AI Resume Tailor

A Python and Streamlit prototype that takes a resume and a job description, generates tailored text, and exports a document or LaTeX source.

The project combines LLM integration with document parsing and output generation. It currently runs locally and supports an OpenAI-backed mode and a heuristic fallback.

## Features

- Upload PDF, DOCX, TXT, Markdown, or HTML resumes.
- Paste a target job description in the Streamlit interface.
- Request an OpenAI rewrite and view a change summary.
- Generate output in the input format where supported, with a text fallback when a writer is unavailable.
- Generate LaTeX source with the bundled `resume.cls` template.
- View which generation mode was used.

## Architecture

```text
Resume upload + job description
              |
        Streamlit interface
              |
        Document text extraction
              |
    +---------+------------------+
    |                            |
Resume tailoring           Structured extraction
    |                            |
OpenAI / heuristic         OpenAI / heuristic
    |                            |
Document writer            LaTeX renderer
    |                            |
artifacts/                 artifacts/latex/
```

| File | Responsibility |
| --- | --- |
| [streamlit_app.py](streamlit_app.py) | Uploads, job-description input, generation controls, and downloads |
| [app/resume_tailor.py](app/resume_tailor.py) | Text extraction, OpenAI calls, heuristic tailoring, and document writers |
| [app/latex_resume.py](app/latex_resume.py) | Structured extraction and LaTeX rendering |
| [templates/latex/](templates/latex/) | Resume class and reference template |
| [requirements.txt](requirements.txt) | Pinned application dependencies |

The OpenAI calls use Python's standard-library HTTP client; the OpenAI Python SDK is not required.

## Run locally

Clone the repository and create a virtual environment:

```bash
git clone https://github.com/Aravindyeddula/ai-resume-tailor-chatbot.git
cd ai-resume-tailor-chatbot
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

For OpenAI mode, set the API key in the same terminal before starting Streamlit:

```powershell
# Windows PowerShell
$env:OPENAI_API_KEY="your_api_key_here"
```

```bash
# macOS / Linux
export OPENAI_API_KEY="your_api_key_here"
```

Start the application:

```bash
streamlit run streamlit_app.py
```

## Use the application

1. Upload a resume and paste a job description.
2. Keep **Require OpenAI rewrite** enabled to request model-backed output. An API key is required.
3. Select **Generate Tailored Resume** or **Generate LaTeX Resume (.tex)**.
4. Check the reported mode, change summary, and generated document before downloading.

To explore the heuristic fallback without an API key, turn off **Require OpenAI rewrite**. If model generation fails while the checkbox is enabled, the interface reports the fallback instead of presenting it as an OpenAI result.

## Outputs and data handling

- Uploaded files are saved under `uploads/`.
- Tailored documents are written under `artifacts/`.
- LaTeX output is written under `artifacts/latex/`, including the generated `.tex` file and copied template assets.
- OpenAI mode sends extracted resume text and the job description to the OpenAI API.
- The app does not automatically remove saved uploads or generated files.

The generated LaTeX source needs a separate LaTeX environment to compile into a PDF.

## Current scope and limitations

This is a prototype. The repository does not yet include an automated test suite or a published evaluation benchmark.

- PDF and DOCX layout preservation is best effort; compare the output with the original.
- Heuristic mode uses templated summaries and keyword alignment. Its wording can introduce unsupported assumptions; review all generated claims.
- OpenAI output also requires factual review. Missing job-description keywords do not establish that the applicant has those skills.
- Scanned or image-only PDFs may not yield usable text because there is no dedicated OCR pipeline.
- No ATS score, hiring outcome, or factuality guarantee is claimed.

## Next improvements

- Add synthetic resume and job-description fixtures with factuality and export checks.
- Measure generation latency, API usage, and document-format success rates.
- Improve upload isolation and cleanup before considering a shared deployment.
- Add a short demo using synthetic personal information.
