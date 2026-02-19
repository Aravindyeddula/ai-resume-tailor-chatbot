import html
import json
import os
import re
import urllib.request
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Tuple


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]{1,}")
STOPWORDS = {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it", "of", "on", "or", "that", "the", "to", "with"}


class _SimpleHTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)

    def get_text(self) -> str:
        return "\n".join(self.parts)


def _read_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if ext in {".html", ".htm"}:
        parser = _SimpleHTMLTextExtractor()
        parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
        return html.unescape(parser.get_text())
    if ext == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception:
            return ""
        try:
            reader = PdfReader(str(path))
        except Exception:
            return ""
        parts: List[str] = []
        for page in reader.pages:
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            if text.strip():
                parts.append(text.strip())
        return "\n\n".join(parts)
    return ""


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in TOKEN_RE.findall(text)]


def _extract_keywords(text: str, top_n: int = 20) -> List[str]:
    counts = Counter(t for t in _tokenize(text) if t not in STOPWORDS and len(t) >= 3)
    return [w for w, _ in counts.most_common(top_n)]


def _extract_json_object(text: str) -> Dict[str, object]:
    text = text.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return {}
    return {}


def _heuristic_tailor(resume_text: str, jd_text: str) -> Tuple[str, List[str]]:
    jd_keywords = _extract_keywords(jd_text, top_n=20)
    resume_tokens = set(_tokenize(resume_text))
    missing = [k for k in jd_keywords if k not in resume_tokens][:8]
    if not missing:
        return resume_text, ["Resume already covers major JD keywords."]
    tailored = f"{resume_text.rstrip()}\n\nTargeted JD Alignment\n- " + "\n- ".join(missing) + "\n"
    return tailored, [f"Added {len(missing)} JD keywords."]


def _openai_tailor(resume_text: str, jd_text: str) -> Tuple[str, List[str], str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    payload = {
        "model": "gpt-4.1-mini",
        "input": [
            {
                "role": "system",
                "content": (
                    "Rewrite the resume for the provided JD while preserving section order and style. "
                    "Do not invent facts. Return strict JSON with tailored_resume, change_summary (array), notes."
                ),
            },
            {"role": "user", "content": f"RESUME:\n{resume_text}\n\nJOB_DESCRIPTION:\n{jd_text}"},
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

    parsed = _extract_json_object(str(body.get("output_text", "")))
    if not parsed:
        fragments: List[str] = []
        for item in body.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    fragments.append(str(content["text"]))
        parsed = _extract_json_object("\n".join(fragments))
    if not parsed:
        raise ValueError("Could not parse model output")

    tailored = str(parsed.get("tailored_resume", "")).strip()
    if not tailored:
        raise ValueError("Model returned empty tailored resume")
    raw_summary = parsed.get("change_summary", [])
    summary = [str(x).strip() for x in raw_summary] if isinstance(raw_summary, list) else []
    notes = str(parsed.get("notes", "")).strip()
    return tailored, summary, notes


def _render_html_document(text: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Tailored Resume</title></head>"
        "<body><pre style='white-space:pre-wrap;'>"
        + html.escape(text)
        + "</pre></body></html>\n"
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

    resume_text = _read_file(resume_file).strip()
    jd_text = _read_file(jd_file).strip()
    if not resume_text:
        return {"ok": False, "error": "Could not extract resume text."}
    if not jd_text:
        return {"ok": False, "error": "Could not extract JD text."}

    mode = "heuristic"
    notes = ""
    try:
        tailored, summary, notes = _openai_tailor(resume_text, jd_text)
        mode = "openai"
    except Exception as e:
        tailored, summary = _heuristic_tailor(resume_text, jd_text)
        notes = f"Fallback used: {e}"

    output_path, output_ext = _write_output(tailored, Path(output_dir), resume_file.stem, resume_file.suffix.lower())
    return {
        "ok": True,
        "mode": mode,
        "output_path": output_path.as_posix(),
        "output_ext": output_ext,
        "format_preserved": output_ext == resume_file.suffix.lower(),
        "change_summary": summary,
        "notes": notes,
    }
