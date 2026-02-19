import html
import json
import os
import re
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

from .ingest import _read_supported_file  # Reuse parser for txt/md/html/pdf.


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]{1,}")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
}


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in TOKEN_RE.findall(text)]


def _extract_keywords(text: str, top_n: int = 20) -> List[str]:
    counts = Counter(t for t in _tokenize(text) if t not in STOPWORDS and len(t) >= 3)
    return [w for w, _ in counts.most_common(top_n)]


def _infer_heading_prefix(resume_text: str) -> str:
    for line in resume_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## "):
            return "## "
        if stripped.startswith("# "):
            return "# "
    return ""


def _infer_bullet_prefix(resume_text: str) -> str:
    for line in resume_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            return "- "
        if stripped.startswith("* "):
            return "* "
    return "- "


def _heuristic_tailor(resume_text: str, jd_text: str) -> Tuple[str, List[str]]:
    jd_keywords = _extract_keywords(jd_text, top_n=25)
    resume_tokens = set(_tokenize(resume_text))
    missing = [k for k in jd_keywords if k not in resume_tokens][:8]
    if not missing:
        return resume_text, ["Resume already covers key JD terms."]

    heading_prefix = _infer_heading_prefix(resume_text)
    bullet_prefix = _infer_bullet_prefix(resume_text)
    add_header = f"{heading_prefix}Targeted JD Alignment".strip()
    lines = [resume_text.rstrip(), "", add_header]
    for kw in missing:
        lines.append(f"{bullet_prefix}{kw}")
    updated = "\n".join(lines).strip() + "\n"
    summary = [f"Added {len(missing)} JD-alignment keywords in a dedicated section."]
    return updated, summary


def _extract_json_object(text: str) -> Dict[str, object]:
    text = text.strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def _openai_tailor(resume_text: str, jd_text: str, model: str = "gpt-4.1-mini") -> Tuple[str, List[str], str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": (
                    "You are an expert resume editor. Rewrite the resume for the target JD while preserving "
                    "the original structure style, section order, and concise tone. Do not invent degrees, "
                    "companies, titles, dates, certifications, or years of experience. Improve bullets for ATS "
                    "matching using only plausible reframing from existing resume evidence."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Return STRICT JSON with keys: tailored_resume (string), change_summary (array of strings), notes (string).\n\n"
                    f"RESUME:\n{resume_text}\n\nJOB_DESCRIPTION:\n{jd_text}"
                ),
            },
        ],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    text = str(body.get("output_text", "")).strip()
    parsed = _extract_json_object(text)
    if not parsed:
        all_parts: List[str] = []
        for item in body.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    all_parts.append(str(content["text"]))
        parsed = _extract_json_object("\n".join(all_parts))
    if not parsed:
        raise ValueError("Could not parse model output")

    tailored = str(parsed.get("tailored_resume", "")).strip()
    change_summary = parsed.get("change_summary", [])
    if isinstance(change_summary, list):
        summary = [str(x).strip() for x in change_summary if str(x).strip()]
    else:
        summary = []
    notes = str(parsed.get("notes", "")).strip()
    if not tailored:
        raise ValueError("Model returned empty tailored_resume")
    return tailored, summary, notes


def _render_html_document(text: str) -> str:
    escaped = html.escape(text)
    return (
        "<!doctype html>\n"
        "<html><head><meta charset='utf-8'><title>Tailored Resume</title></head>"
        "<body><pre style='font-family:Arial,Helvetica,sans-serif;white-space:pre-wrap;'>"
        f"{escaped}</pre></body></html>\n"
    )


def _write_output(text: str, output_dir: Path, stem: str, ext: str) -> Tuple[Path, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if ext in {".txt", ".md"}:
        out = output_dir / f"{stem}_tailored{ext}"
        out.write_text(text, encoding="utf-8")
        return out, ext
    if ext in {".html", ".htm"}:
        out = output_dir / f"{stem}_tailored{ext}"
        out.write_text(_render_html_document(text), encoding="utf-8")
        return out, ext
    # PDF output generation is intentionally downgraded unless a PDF writer dependency is added.
    out = output_dir / f"{stem}_tailored.txt"
    out.write_text(text, encoding="utf-8")
    return out, ".txt"


def tailor_resume(resume_path: str, jd_path: str, output_dir: str = "artifacts") -> Dict[str, object]:
    resume_file = Path(resume_path)
    jd_file = Path(jd_path)
    if not resume_file.exists():
        return {"ok": False, "error": f"Resume file not found: {resume_file.as_posix()}"}
    if not jd_file.exists():
        return {"ok": False, "error": f"JD file not found: {jd_file.as_posix()}"}

    resume_text = _read_supported_file(resume_file).strip()
    jd_text = _read_supported_file(jd_file).strip()
    if not resume_text:
        return {"ok": False, "error": "Could not extract resume text from uploaded file."}
    if not jd_text:
        return {"ok": False, "error": "Could not extract job description text from uploaded file."}

    mode = "heuristic"
    notes = ""
    summary: List[str] = []
    try:
        tailored, summary, notes = _openai_tailor(resume_text=resume_text, jd_text=jd_text)
        mode = "openai"
    except Exception as e:
        tailored, summary = _heuristic_tailor(resume_text=resume_text, jd_text=jd_text)
        notes = f"Used heuristic fallback: {e}"

    output_path, output_ext = _write_output(
        text=tailored,
        output_dir=Path(output_dir),
        stem=resume_file.stem,
        ext=resume_file.suffix.lower(),
    )

    return {
        "ok": True,
        "mode": mode,
        "resume_source": resume_file.as_posix(),
        "jd_source": jd_file.as_posix(),
        "output_path": output_path.as_posix(),
        "output_ext": output_ext,
        "format_preserved": output_ext == resume_file.suffix.lower(),
        "change_summary": summary,
        "notes": notes,
    }
