import json
import os
import re
import shutil
import urllib.request
from pathlib import Path
from typing import Dict, List, Tuple

from .resume_tailor import _extract_json_object, _extract_keywords, _read_file


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "latex"
DEFAULT_MODEL = "gpt-4.1-mini"
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]{1,}")
JD_FILTER_TERMS = {
    "ability",
    "role",
    "roles",
    "position",
    "positions",
    "job",
    "responsibilities",
    "responsibility",
    "requirements",
    "requirement",
    "requiring",
    "require",
    "required",
    "preferred",
    "must",
    "strong",
    "qualification",
    "qualifications",
    "candidate",
    "skill",
    "skills",
    "team",
    "teams",
    "experience",
    "work",
    "years",
    "senior",
    "junior",
    "lead",
    "principal",
    "staff",
    "analyst",
    "scientist",
    "engineer",
    "manager",
    "data",
}

JD_SKILL_HINTS: List[Tuple[str, str, str]] = [
    ("python", "Python", "Programming Languages & Data Manipulation"),
    ("sql", "SQL", "Programming Languages & Data Manipulation"),
    ("pyspark", "PySpark", "Programming Languages & Data Manipulation"),
    ("spark", "Apache Spark", "Programming Languages & Data Manipulation"),
    ("pandas", "Pandas", "Programming Languages & Data Manipulation"),
    ("numpy", "NumPy", "Programming Languages & Data Manipulation"),
    ("dbt", "dbt", "Data Engineering & Pipelines"),
    ("etl", "ETL", "Data Engineering & Pipelines"),
    ("elt", "ELT", "Data Engineering & Pipelines"),
    ("airflow", "Airflow", "Workflow Orchestration"),
    ("kafka", "Kafka", "Data Engineering & Pipelines"),
    ("databricks", "Databricks", "Cloud Platforms"),
    ("snowflake", "Snowflake", "Data Warehousing"),
    ("redshift", "Redshift", "Data Warehousing"),
    ("bigquery", "BigQuery", "Data Warehousing"),
    ("aws", "AWS", "Cloud Platforms"),
    ("azure", "Azure", "Cloud Platforms"),
    ("gcp", "GCP", "Cloud Platforms"),
    ("power bi", "Power BI", "Data Visualization"),
    ("tableau", "Tableau", "Data Visualization"),
    ("looker", "Looker", "Data Visualization"),
    ("excel", "Excel", "Data Visualization"),
    ("dashboarding", "Dashboarding", "Data Visualization"),
    ("dashboard", "Dashboarding", "Data Visualization"),
    ("reporting", "Reporting", "Data Visualization"),
    ("metadata", "Metadata Management", "Data Governance & Quality"),
    ("governance", "Data Governance", "Data Governance & Quality"),
    ("data quality", "Data Quality", "Data Governance & Quality"),
    ("lineage", "Data Lineage", "Data Governance & Quality"),
    ("catalog", "Data Catalog", "Data Governance & Quality"),
    ("quality", "Data Quality", "Data Governance & Quality"),
    ("statistics", "Statistics", "Analytics & Machine Learning"),
    ("machine learning", "Machine Learning", "Analytics & Machine Learning"),
    ("nlp", "NLP", "Analytics & Machine Learning"),
]

MONTH_DATE_RE = re.compile(
    r"(?i)\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\s+\d{4}\s*[-–]\s*(?:present|current|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\s+\d{4})\b"
)
YEAR_DATE_RE = re.compile(r"\b(?:19|20)\d{2}\s*[-–]\s*(?:present|current|(?:19|20)\d{2})\b", re.I)


def _latex_escape(text: str) -> str:
    out = str(text)
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for old, new in replacements:
        out = out.replace(old, new)
    return out


def _fix_text_artifacts(text: str) -> str:
    s = str(text)
    replacements = {
        "•": "-",
        "–": "-",
        "—": "-",
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "â€¢": "•",
        "â€“": "-",
        "â€”": "-",
        "â€™": "'",
        "â€˜": "'",
        "â€œ": '"',
        "â€": '"',
        "Â": "",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    return s


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", _fix_text_artifacts(str(line)).strip())


def _truncate_text(text: str, max_len: int = 260) -> str:
    s = _clean_line(text)
    if len(s) <= max_len:
        return s
    cut = s[:max_len].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;") + "..."


def _normalize_list(value: object) -> List[str]:
    if isinstance(value, list):
        return [_clean_line(v) for v in value if _clean_line(v)]
    if isinstance(value, str):
        if not value.strip():
            return []
        if "\n" in value:
            return [_clean_line(x) for x in value.splitlines() if _clean_line(x)]
        return [_clean_line(value)]
    return []


def _normalize_structured_resume(data: Dict[str, object]) -> Dict[str, object]:
    def _norm_skill_list(items: object) -> List[Dict[str, object]]:
        out: List[Dict[str, object]] = []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    category = _clean_line(item.get("category", "Core Skills"))
                    vals = _normalize_list(item.get("items", []))
                    if category and vals:
                        out.append({"category": category, "items": vals})
                elif isinstance(item, str):
                    vals = [x.strip() for x in re.split(r"[|,]", item) if x.strip()]
                    if vals:
                        out.append({"category": "Core Skills", "items": vals})
        return out

    def _norm_projects(items: object) -> List[Dict[str, object]]:
        out: List[Dict[str, object]] = []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                title = _clean_line(item.get("title", "Project"))
                bullets = _normalize_list(item.get("bullets", []))
                tech = _normalize_list(item.get("tech_stack", item.get("tech", [])))
                link = _clean_line(item.get("link", ""))
                if title:
                    out.append({"title": title, "bullets": bullets, "tech_stack": tech, "link": link})
        return out

    def _norm_experience(items: object) -> List[Dict[str, object]]:
        out: List[Dict[str, object]] = []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                company = _clean_line(item.get("company", ""))
                role = _clean_line(item.get("role", item.get("title", "")))
                dates = _clean_line(item.get("dates", item.get("date_range", "")))
                location = _clean_line(item.get("location", ""))
                bullets = _normalize_list(item.get("bullets", item.get("responsibilities", [])))
                if company or role or bullets:
                    out.append(
                        {
                            "company": company or "Experience",
                            "role": role,
                            "dates": dates,
                            "location": location,
                            "bullets": bullets,
                        }
                    )
        return out

    def _norm_education(items: object) -> List[Dict[str, object]]:
        out: List[Dict[str, object]] = []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                out.append(
                    {
                        "degree": _clean_line(item.get("degree", "")),
                        "institution": _clean_line(item.get("institution", "")),
                        "dates": _clean_line(item.get("dates", item.get("date_range", ""))),
                        "details": _normalize_list(item.get("details", [])),
                    }
                )
        return [x for x in out if x["degree"] or x["institution"]]

    name = _clean_line(data.get("name", "Candidate"))
    contact_line = _clean_line(data.get("contact_line", data.get("contact", "")))
    summary = _clean_line(data.get("summary", ""))

    normalized = {
        "name": name or "Candidate",
        "contact_line": contact_line,
        "summary": summary,
        "skills": _norm_skill_list(data.get("skills", [])),
        "certifications": _normalize_list(data.get("certifications", [])),
        "achievements": _normalize_list(data.get("achievements", data.get("awards", data.get("honors", [])))),
        "projects": _norm_projects(data.get("projects", [])),
        "experience": _norm_experience(data.get("experience", [])),
        "education": _norm_education(data.get("education", [])),
    }
    return normalized


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in TOKEN_RE.findall(str(text))]


def _jd_keywords_for_alignment(jd_text: str, top_n: int = 12) -> List[str]:
    if not jd_text.strip():
        return []
    kws = [k.lower() for k in _extract_keywords(jd_text, top_n=top_n * 2)]
    out: List[str] = []
    for k in kws:
        if k in JD_FILTER_TERMS:
            continue
        if len(k) < 3:
            continue
        if k not in out:
            out.append(k)
        if len(out) >= top_n:
            break
    return out


def _extract_jd_skill_mentions(jd_text: str) -> List[Tuple[str, str]]:
    low = " " + _clean_line(jd_text).lower() + " "
    found: List[Tuple[str, str]] = []
    for needle, skill_name, category in JD_SKILL_HINTS:
        if len(needle) <= 4 or needle in {"sql", "aws", "gcp", "dbt", "etl", "elt", "nlp"}:
            matched = bool(re.search(rf"(?<![A-Za-z]){re.escape(needle)}(?![A-Za-z])", low))
        else:
            matched = needle in low
        if matched and (skill_name, category) not in found:
            found.append((skill_name, category))
    return found


def _augment_skills_from_jd(structured: Dict[str, object], jd_text: str) -> List[str]:
    if not jd_text.strip():
        return []
    skills_obj = structured.get("skills", [])
    if not isinstance(skills_obj, list):
        return []

    existing_items = set()
    category_map: Dict[str, Dict[str, object]] = {}
    for row in skills_obj:
        if not isinstance(row, dict):
            continue
        category = _clean_line(row.get("category", "Core Skills")) or "Core Skills"
        row["category"] = category
        items = row.get("items", [])
        if not isinstance(items, list):
            items = []
            row["items"] = items
        for item in items:
            existing_items.add(_clean_line(item).lower())
        category_map[category.lower()] = row

    added: List[str] = []
    for skill_name, category in _extract_jd_skill_mentions(jd_text):
        norm = skill_name.lower()
        if norm in existing_items:
            continue
        row = category_map.get(category.lower())
        if row is None:
            row = {"category": category, "items": []}
            skills_obj.append(row)
            category_map[category.lower()] = row
        items = row.get("items", [])
        if not isinstance(items, list):
            items = []
            row["items"] = items
        items.append(skill_name)
        existing_items.add(norm)
        added.append(skill_name)
        if len(added) >= 10:
            break

    if added:
        return [f"Added {len(added)} JD-relevant skills/adjacent terms to Technical Skills."]
    return []


def _text_overlap_keywords(text: str, jd_keywords: List[str]) -> List[str]:
    tokens = set(_tokenize(text))
    return [k for k in jd_keywords if k in tokens]


def _bullet_jd_score(text: str, jd_keywords: List[str]) -> float:
    overlap = _text_overlap_keywords(text, jd_keywords)
    score = float(len(overlap) * 3)
    if re.search(r"\b\d+(\.\d+)?%?\b", str(text)):
        score += 1.0
    if re.search(r"\b(built|developed|designed|implemented|automated|led|improved|created|analyzed)\b", str(text).lower()):
        score += 0.5
    return score


def _append_jd_focus_to_summary(summary: str, jd_keywords: List[str]) -> Tuple[str, bool]:
    if not jd_keywords:
        return summary, False

    focus = jd_keywords[:4]
    if not summary.strip():
        summary = "Data professional with experience building analytics, reporting, and data pipeline solutions."

    summary = re.sub(r"\s*Focused for role keywords:\s*[^.]+\.?", "", summary, flags=re.IGNORECASE).strip()
    summary = re.sub(r"\s*Targeting roles emphasizing\s+[^.]+\.?", "", summary, flags=re.IGNORECASE).strip()
    summary = re.sub(r"\s*Aligned to roles focused on\s+[^.]+\.?", "", summary, flags=re.IGNORECASE).strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", summary) if s.strip()]
    if len(sentences) > 2:
        summary = " ".join(sentences[:2]).strip()
    summary = _truncate_text(summary, max_len=320)

    low = summary.lower()
    if "targeting roles emphasizing" in low or "aligned for roles requiring" in low:
        return summary, False

    matched_focus = [k for k in focus if k in set(_tokenize(summary))]
    ordered_focus = matched_focus + [k for k in focus if k not in matched_focus]
    ordered_focus = ordered_focus[:4]

    if len(ordered_focus) == 1:
        focus_phrase = ordered_focus[0]
    elif len(ordered_focus) == 2:
        focus_phrase = f"{ordered_focus[0]} and {ordered_focus[1]}"
    else:
        focus_phrase = ", ".join(ordered_focus[:-1]) + f", and {ordered_focus[-1]}"

    updated = summary.rstrip().rstrip(".") + f". Aligned to roles focused on {focus_phrase}."
    updated = _truncate_text(updated, max_len=360)
    return updated, True


def _ensure_role_bullets_jd_aligned(
    experience: List[Dict[str, object]],
    jd_keywords: List[str],
    force_visible: bool = False,
) -> Tuple[List[Dict[str, object]], int]:
    if not jd_keywords or not experience:
        return experience, 0

    changed_roles = 0
    for exp in experience:
        raw_bullets = exp.get("bullets", [])
        bullets = [str(b).strip() for b in raw_bullets if str(b).strip()] if isinstance(raw_bullets, list) else []
        if not bullets:
            continue

        scored = [(_bullet_jd_score(b, jd_keywords), i, b, _text_overlap_keywords(b, jd_keywords)) for i, b in enumerate(bullets)]
        reordered = [x[2] for x in sorted(scored, key=lambda x: (x[0], -x[1]), reverse=True)]
        role_changed = reordered != bullets

        any_overlap = any(x[3] for x in scored)
        if not any_overlap:
            focus = jd_keywords[:3]
            if focus and reordered:
                prefix = "Relevant to " + ", ".join(focus[:2]) + " priorities: "
                if not reordered[0].lower().startswith("relevant to "):
                    reordered[0] = prefix + reordered[0]
                    role_changed = True
        elif force_visible and reordered:
            top_overlap = _text_overlap_keywords(reordered[0], jd_keywords)
            if top_overlap and "aligned to " not in reordered[0].lower():
                marker = "; aligned to " + ", ".join(top_overlap[:2]) + " priorities"
                if reordered[0].endswith("."):
                    reordered[0] = reordered[0][:-1] + marker + "."
                else:
                    reordered[0] = reordered[0] + marker + "."
                role_changed = True

        cleaned: List[str] = []
        seen = set()
        for bullet in reordered:
            b = _truncate_text(bullet, max_len=190)
            key = re.sub(r"[^a-z0-9]+", "", b.lower())
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append(b)
            if len(cleaned) >= 6:
                break
        if not cleaned:
            cleaned = reordered[:6]

        if role_changed or cleaned != bullets:
            exp["bullets"] = cleaned
            changed_roles += 1

    return experience, changed_roles


def _enforce_structured_jd_alignment(
    structured: Dict[str, object],
    jd_text: str,
    force_visible: bool = False,
) -> Tuple[Dict[str, object], List[str]]:
    if not jd_text.strip():
        return structured, []

    jd_keywords = _jd_keywords_for_alignment(jd_text, top_n=12)
    if not jd_keywords:
        jd_keywords = []

    notes: List[str] = []
    notes.extend(_augment_skills_from_jd(structured, jd_text))

    summary_text = str(structured.get("summary", "") or "")
    if jd_keywords:
        updated_summary, summary_changed = _append_jd_focus_to_summary(summary_text, jd_keywords)
        if summary_changed:
            structured["summary"] = updated_summary
            notes.append("Updated summary with JD-focused targeting language.")

    experience = structured.get("experience", [])
    if jd_keywords and isinstance(experience, list):
        _, changed_roles = _ensure_role_bullets_jd_aligned(experience, jd_keywords, force_visible=force_visible)
        if changed_roles:
            notes.append(f"Reordered/retargeted responsibilities for {changed_roles} role(s) using JD keywords.")

    return structured, notes


def _extract_resume_structured_openai(resume_text: str, jd_text: str = "") -> Tuple[Dict[str, object], str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    jd_block = jd_text.strip()
    jd_instruction = (
        "If JOB_DESCRIPTION is provided, align wording of summary, technical skills, and experience bullets to the JD while preserving facts. "
        "Do not invent companies, titles, dates, skills, certifications, achievements, or metrics."
    )

    payload = {
        "model": DEFAULT_MODEL,
        "input": [
            {
                "role": "system",
                "content": (
                    "You convert raw resume text into structured resume JSON for LaTeX rendering. "
                    + jd_instruction
                    + " Return STRICT JSON with keys: name, contact_line, summary, skills, experience, projects, education, certifications, achievements. "
                    "Schema: skills=[{category,items[]}], projects=[{title,link,tech_stack[],bullets[]}], "
                    "experience=[{company,role,dates,location,bullets[]}], education=[{degree,institution,dates,details[]}], "
                    "certifications=[...], achievements=[...]. "
                    "Keep summary concise (2 sentences max) and bullets concise. Preserve all roles/responsibilities present in the resume. "
                    "If JOB_DESCRIPTION is provided, update the summary, technical skills, and each experience entry's bullets to emphasize JD-relevant wording. "
                    "Preserve achievements from the source resume if present."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"RESUME_TEXT:\n{resume_text}\n\nJOB_DESCRIPTION:\n{jd_block if jd_block else '<none>'}\n\n"
                    "Return only JSON."
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

    parsed = _extract_json_object(str(body.get("output_text", "")))
    if not parsed:
        chunks: List[str] = []
        for item in body.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    chunks.append(str(content["text"]))
        parsed = _extract_json_object("\n".join(chunks))
    if not parsed:
        raise ValueError("Could not parse structured resume JSON from model output")

    return _normalize_structured_resume(parsed), DEFAULT_MODEL


def _find_contact_line(lines: List[str]) -> str:
    for line in lines[:8]:
        low = line.lower()
        if "@" in line or "linkedin" in low or "github" in low or re.search(r"\+?\d[\d()\-\s]{7,}", line):
            return line
    return ""


def _split_heading_sections(lines: List[str]) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {"_preamble": []}
    current = "_preamble"
    heading_map = {
        "summary": "summary",
        "professional experience": "experience",
        "experience": "experience",
        "work experience": "experience",
        "technical skills": "skills",
        "skills": "skills",
        "projects": "projects",
        "certifications": "certifications",
        "achievements": "achievements",
        "achievement": "achievements",
        "awards": "achievements",
        "accomplishments": "achievements",
        "honors": "achievements",
        "education": "education",
    }
    for line in lines:
        normalized = re.sub(r"[^a-z ]", "", line.lower()).strip()
        matched = None
        for key, target in heading_map.items():
            if normalized == key or normalized.startswith(key + " "):
                matched = target
                break
        if matched:
            current = matched
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _extract_skills_heuristic(text: str) -> List[Dict[str, object]]:
    # Try colon-separated categories first.
    skills: List[Dict[str, object]] = []
    for raw in text.splitlines():
        line = _clean_line(raw)
        if ":" not in line or len(line) < 6:
            continue
        left, right = line.split(":", 1)
        category = re.sub(r"^(?:â€¢|[•\-\*\s])+", "", _clean_line(left))
        items = [x.strip(" .") for x in re.split(r"[|,]", right) if x.strip(" .")]
        if category and items and len(items) >= 2:
            skills.append({"category": category, "items": items[:12]})
    if skills:
        return skills[:8]

    known = [
        "Python",
        "SQL",
        "PySpark",
        "TensorFlow",
        "Keras",
        "XGBoost",
        "Azure",
        "AWS",
        "Databricks",
        "Snowflake",
        "Power BI",
        "Tableau",
        "Docker",
        "Kubernetes",
        "Airflow",
        "Kafka",
    ]
    low = text.lower()
    found = [k for k in known if k.lower() in low]
    return [{"category": "Core Skills", "items": found}] if found else []


def _extract_bullets_or_sentences(section_lines: List[str], limit: int = 8) -> List[str]:
    bullets: List[str] = []
    for line in section_lines:
        s = _clean_line(line)
        if not s:
            continue
        if s.startswith(("-", "*", "•")):
            bullets.append(s.lstrip("-*• ").strip())
        elif len(s) > 40 and re.search(r"\b(implemented|built|developed|designed|led|improved|created|analyzed|automated)\b", s.lower()):
            bullets.append(s)
    if not bullets:
        merged = " ".join(section_lines)
        parts = re.split(r"(?<=[.!?])\s+", merged)
        bullets = [_clean_line(p) for p in parts if len(_clean_line(p)) > 35]
    return bullets[:limit]


def _extract_experience_heuristic(section_lines: List[str]) -> List[Dict[str, object]]:
    if not section_lines:
        return []
    # Very lightweight grouping: split on lines that look like company headers or date-bearing lines.
    groups: List[List[str]] = []
    current: List[str] = []
    for raw in section_lines:
        line = _clean_line(raw)
        if not line:
            continue
        headerish = bool(
            re.search(r"\b(20\d{2}|19\d{2}|present|current|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b", line.lower())
            or re.search(r"\b(inc|corp|llc|technologies|university|company)\b", line.lower())
        )
        if headerish and current and len(current) >= 2:
            groups.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        groups.append(current)

    items: List[Dict[str, object]] = []
    for g in groups[:8]:
        header = g[0]
        role = g[1] if len(g) > 1 and len(g[1]) < 120 else ""
        bullets = _extract_bullets_or_sentences(g[1:] if role else g[1:], limit=6)
        items.append({"company": header, "role": role, "dates": "", "location": "", "bullets": bullets})
    return items


def _extract_projects_heuristic(section_lines: List[str]) -> List[Dict[str, object]]:
    if not section_lines:
        return []
    projects: List[Dict[str, object]] = []
    current_title = ""
    current_lines: List[str] = []
    for raw in section_lines:
        line = _clean_line(raw)
        if not line:
            continue
        is_title = len(line) < 140 and not line.startswith(("-", "*", "•")) and line[:1].isupper()
        if is_title and current_title and current_lines:
            projects.append(
                {
                    "title": current_title,
                    "link": "",
                    "tech_stack": [],
                    "bullets": _extract_bullets_or_sentences(current_lines, limit=5),
                }
            )
            current_title, current_lines = line, []
            continue
        if not current_title:
            current_title = line
        else:
            current_lines.append(line)
    if current_title:
        projects.append(
            {"title": current_title, "link": "", "tech_stack": [], "bullets": _extract_bullets_or_sentences(current_lines, limit=5)}
        )
    return projects[:6]


def _extract_education_heuristic(section_lines: List[str]) -> List[Dict[str, object]]:
    text = " ".join(_clean_line(x) for x in section_lines if _clean_line(x))
    if not text:
        return []

    # Split concatenated education entries on common degree starters.
    degree_start_re = re.compile(r"(?i)(?=\b(?:bachelor|master|doctor|phd|b\.?tech|m\.?tech|b\.?e|m\.?e)\b)")
    chunks = [c.strip(" |,;") for c in degree_start_re.split(text) if c.strip(" |,;")]
    if not chunks:
        chunks = [text]

    items: List[Dict[str, object]] = []
    for chunk in chunks[:6]:
        main = _clean_line(chunk)
        details: List[str] = []

        gpa_match = re.search(r"(?i)\bGPA\s*:\s*[^,;|]+", main)
        if gpa_match:
            details.append(_clean_line(gpa_match.group(0)))
            main = _clean_line((main[: gpa_match.start()] + ' ' + main[gpa_match.end() :]).strip(' ,;|'))

        main_wo_dates, dates = _extract_date_range_from_text(main)

        degree = main_wo_dates
        institution = ""
        if "," in main_wo_dates:
            left, right = [x.strip() for x in main_wo_dates.split(",", 1)]
            if any(k in left.lower() for k in ["bachelor", "master", "doctor", "phd", "b.tech", "m.tech", "b.e", "m.e", "bs", "ms", "mba"]):
                degree, institution = left, right

        items.append({"degree": degree, "institution": institution, "dates": dates, "details": details})

    return [x for x in items if x.get('degree') or x.get('institution')][:5]


def _extract_achievements_heuristic(section_lines: List[str]) -> List[str]:
    if not section_lines:
        return []
    bullets = _extract_bullets_or_sentences(section_lines, limit=10)
    if bullets:
        return bullets
    return [_clean_line(x) for x in section_lines if _clean_line(x)][:10]


def _extract_resume_structured_heuristic(resume_text: str, jd_text: str = "") -> Dict[str, object]:
    lines = [_clean_line(x) for x in resume_text.splitlines() if _clean_line(x)]
    name = lines[0] if lines else "Candidate"
    contact_line = _find_contact_line(lines)
    sections = _split_heading_sections(lines)

    summary_lines = sections.get("summary", [])
    if not summary_lines:
        # Fallback: use first few long lines after contact.
        long_lines = [x for x in lines[1:12] if len(x) > 40]
        summary_lines = long_lines[:3]
    summary = " ".join(summary_lines[:3]).strip()

    skills_text = "\n".join(sections.get("skills", []) or lines)
    skills = _extract_skills_heuristic(skills_text)

    experience = _extract_experience_heuristic(sections.get("experience", []))
    projects = _extract_projects_heuristic(sections.get("projects", []))
    education = _extract_education_heuristic(sections.get("education", []))
    certifications = _normalize_list(sections.get("certifications", []))
    achievements = _extract_achievements_heuristic(sections.get("achievements", []))

    # If JD provided, append a small alignment note to summary to make relevance explicit.
    if jd_text.strip():
        jd_tokens = [t for t in TOKEN_RE.findall(jd_text) if len(t) > 3][:6]
        if jd_tokens:
            uniq = list(dict.fromkeys([t.lower() for t in jd_tokens]))
            add = " Focused for role keywords: " + ", ".join(uniq[:4])
            summary = (summary + add).strip()

    return _normalize_structured_resume(
        {
            "name": name,
            "contact_line": contact_line,
            "summary": summary,
            "skills": skills,
            "certifications": certifications,
            "projects": projects,
            "experience": experience,
            "education": education,
            "achievements": achievements,
        }
    )


def _latex_itemize(items: List[str], itemsep: str = "-2pt") -> str:
    if not items:
        return ""
    # Spacing is controlled globally via enumitem in the LaTeX preamble.
    lines = [r"\begin{itemize}"]
    for item in items:
        lines.append(r"\item " + _latex_escape(item))
    lines.append(r"\end{itemize}")
    return "\n".join(lines)


def _latex_url(url: str) -> str:
    u = _clean_line(url).strip("()[]<>")
    if not u:
        return ""
    if u.lower().startswith(("http://", "https://", "mailto:")):
        return u
    if "@" in u and "mailto:" not in u.lower():
        return "mailto:" + u
    if u.lower().startswith("www."):
        return "https://" + u
    if "linkedin.com" in u.lower() or "github.com" in u.lower():
        return "https://" + u.lstrip("/")
    return u


def _render_contact_line_latex(contact_line: str) -> str:
    line = _clean_line(contact_line)
    if not line:
        return ""
    parts = [p.strip() for p in re.split(r"\s+\|\s+|\s+(?:\u2014|\u2013)\s+|\s+-\s+", line) if p.strip()]
    if not parts:
        parts = [line]

    out_parts: List[str] = []
    for part in parts:
        email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", part)
        url_match = re.search(r"((?:https?://|www\.)\S+|(?:linkedin\.com|github\.com)\S*)", part, flags=re.I)
        low = part.lower()

        if email_match:
            email = email_match.group(0)
            out_parts.append(rf"\href{{{_latex_url(email)}}}{{{_latex_escape(email)}}}")
            continue
        if url_match:
            raw_url = url_match.group(1).rstrip(".,)")
            url = _latex_url(raw_url)
            label = "LinkedIn" if "linkedin" in low else ("GitHub" if "github" in low else raw_url)
            out_parts.append(rf"\href{{{url}}}{{{_latex_escape(label)}}}")
            continue
        if "linkedin" in low or "github" in low:
            # No URL present in extracted text; cannot create a real hyperlink.
            out_parts.append(_latex_escape(part))
            continue
        out_parts.append(_latex_escape(part))
    return " | ".join(out_parts)


def _location_is_duplicate(company: str, location: str) -> bool:
    comp = _clean_line(company).lower()
    loc = _clean_line(location).lower()
    if not loc:
        return True
    if loc in comp:
        return True
    loc_parts = [p.strip() for p in re.split(r"[,/|-]", loc) if len(p.strip()) >= 3]
    if loc_parts and all(part in comp for part in loc_parts):
        return True
    return False


def _extract_date_range_from_text(text: str) -> Tuple[str, str]:
    s = _clean_line(text)
    if not s:
        return "", ""
    m = MONTH_DATE_RE.search(s) or YEAR_DATE_RE.search(s)
    if not m:
        return s, ""
    date_text = _clean_line(m.group(0))
    left = _clean_line((s[: m.start()] + " " + s[m.end() :]).strip(" ,|-"))
    return left, date_text


def _split_education_entry_for_render(edu: Dict[str, object]) -> Tuple[str, str, str, List[str]]:
    degree = _clean_line(edu.get("degree", ""))
    institution = _clean_line(edu.get("institution", ""))
    dates = _clean_line(edu.get("dates", ""))
    details = [_clean_line(x) for x in edu.get("details", []) if _clean_line(x)] if isinstance(edu.get("details", []), list) else []

    if not dates and institution:
        institution, dates = _extract_date_range_from_text(institution)
    if not dates and degree:
        degree, dates = _extract_date_range_from_text(degree)

    degree_keywords = ("bachelor", "master", "phd", "doctor", "b.tech", "m.tech", "bs", "ms", "mba", "b.e", "m.e")
    if not institution and "," in degree:
        left, right = [x.strip() for x in degree.split(",", 1)]
        if any(k in left.lower() for k in degree_keywords):
            degree, institution = left, right
            if not dates and institution:
                institution, dates = _extract_date_range_from_text(institution)

    if "gpa:" in degree.lower():
        left, _, right = degree.partition("GPA:")
        degree = _clean_line(left.rstrip(","))
        if right.strip():
            details.insert(0, "GPA: " + _clean_line(right))

    if degree and institution and degree.lower() == institution.lower():
        institution = ""

    return degree, institution, dates, details


def _extract_urls_from_pdf_annotations(pdf_path: Path) -> List[str]:
    if pdf_path.suffix.lower() != ".pdf" or not pdf_path.exists():
        return []
    try:
        import fitz  # type: ignore
    except Exception:
        return []

    urls: List[str] = []
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return []
    try:
        for page_index in range(min(2, doc.page_count)):
            page = doc[page_index]
            for link in page.get_links():
                uri = _clean_line(link.get("uri", ""))
                if uri and uri not in urls:
                    urls.append(uri)
    finally:
        doc.close()
    return urls


def _enrich_contact_line_with_urls(contact_line: str, urls: List[str]) -> str:
    line = _clean_line(contact_line)
    if not line or not urls:
        return line

    linkedin_url = next((u for u in urls if "linkedin.com" in u.lower()), "")
    github_url = next((u for u in urls if "github.com" in u.lower()), "")

    if linkedin_url and "linkedin.com" not in line.lower():
        if re.search(r"\blinkedin\b", line, flags=re.I):
            line = re.sub(r"\blinkedin\b", linkedin_url, line, count=1, flags=re.I)
        else:
            line = line + " | " + linkedin_url
    if github_url and "github.com" not in line.lower():
        if re.search(r"\bgithub\b", line, flags=re.I):
            line = re.sub(r"\bgithub\b", github_url, line, count=1, flags=re.I)
        else:
            line = line + " | " + github_url
    return line


def _render_skills_section(skills: List[Dict[str, object]]) -> str:
    if not skills:
        return ""
    lines = [r"\begin{rSection}{TECHNICAL SKILLS}"]
    for row in skills:
        category = _latex_escape(str(row.get("category", "Skills")))
        items = [ _latex_escape(str(x)) for x in row.get("items", []) if str(x).strip() ]
        if not items:
            continue
        lines.append(rf"\textbf{{{category}}}: " + r" $|$ ".join(items) + r" \\")
    lines.append(r"\end{rSection}")
    return "\n".join(lines)


def _render_certifications_section(certs: List[str]) -> str:
    if not certs:
        return ""
    body = r" $|$ ".join(_latex_escape(c) for c in certs)
    return "\n".join(
        [
            r"\begin{rSection}{CERTIFICATIONS}",
            body,
            r"\end{rSection}",
        ]
    )


def _render_achievements_section(achievements: List[str]) -> str:
    if not achievements:
        return ""
    lines = [r"\begin{rSection}{ACHIEVEMENTS}"]
    lines.append(_latex_itemize([str(x) for x in achievements if str(x).strip()]))
    lines.append(r"\end{rSection}")
    return "\n".join(lines)


def _render_projects_section(projects: List[Dict[str, object]]) -> str:
    if not projects:
        return ""
    lines = [r"\begin{rSection}{PROJECTS}"]
    for p in projects:
        title = _latex_escape(str(p.get("title", "Project")))
        link = str(p.get("link", "")).strip()
        tech = [ _latex_escape(str(x)) for x in p.get("tech_stack", []) if str(x).strip() ]
        if link and re.match(r"(https?://|www\.|(?:linkedin\.com|github\.com))", link, flags=re.I):
            header = rf"\href{{{_latex_url(link)}}}{{\textbf{{{title}}}}}"
        else:
            header = rf"\textbf{{{title}}}"
        if tech:
            lines.append(header + r" " + r"(" + r" $|$ ".join(tech) + r")" + r" \\")
        else:
            lines.append(header + r" \\")
        bullets = [str(x) for x in p.get("bullets", []) if str(x).strip()]
        if bullets:
            if lines and lines[-1].endswith(" \\\\"):
                lines[-1] = lines[-1][:-3]
            lines.append(_latex_itemize(bullets))
    lines.append(r"\end{rSection}")
    return "\n".join(lines)


def _render_experience_section(experience: List[Dict[str, object]]) -> str:
    if not experience:
        return ""
    lines = [r"\begin{rSection}{EXPERIENCE}"]
    for exp in experience:
        company = _latex_escape(str(exp.get("company", "Experience")))
        role = _latex_escape(str(exp.get("role", "")))
        dates = _latex_escape(str(exp.get("dates", "")))
        location_raw = str(exp.get("location", ""))
        show_location = _clean_line(location_raw) and not _location_is_duplicate(str(exp.get("company", "")), location_raw)
        company_line = rf"\textbf{{{company}}}"
        if show_location:
            company_line += r" \hfill {" + _latex_escape(location_raw) + r"}"
        lines.append(company_line + r" \\")
        if role or dates:
            role_line = r"\textit{{" + role + r"}}"
            if dates:
                role_line += r" \hfill{" + dates + r"}"
            lines.append(role_line + r" \\")
        bullets = [str(x) for x in exp.get("bullets", []) if str(x).strip()]
        if bullets:
            if lines and lines[-1].endswith(" \\\\"):
                lines[-1] = lines[-1][:-3]
            lines.append(_latex_itemize(bullets, itemsep="-1pt"))
    lines.append(r"\end{rSection}")
    return "\n".join(lines)


def _render_education_section(education: List[Dict[str, object]]) -> str:
    if not education:
        return ""
    lines = [r"\begin{rSection}{Education}"]
    for edu in education:
        degree_raw, institution_raw, dates_raw, details_raw = _split_education_entry_for_render(edu)
        degree = _latex_escape(degree_raw)
        institution = _latex_escape(institution_raw)
        dates = _latex_escape(dates_raw)
        details = [_latex_escape(x) for x in details_raw]

        if degree:
            lines.append(rf"{{\bf {degree}}}" + r"\\")

        second_line = institution
        if dates:
            if second_line:
                second_line += rf" \hfill {{{dates}}}"
            else:
                second_line = rf"{{{dates}}}"
        if second_line:
            lines.append(second_line + r"\\")

        for d in details:
            lines.append(d + r"\\")
    lines.append(r"\end{rSection}")
    return "\n".join(lines)


def render_latex_resume(structured: Dict[str, object]) -> str:
    name = _latex_escape(str(structured.get("name", "Candidate")))
    contact_line = _render_contact_line_latex(str(structured.get("contact_line", "")))
    summary = _latex_escape(str(structured.get("summary", "")))

    sections: List[str] = []
    if summary:
        sections.append(
            "\n".join(
                [
                    r"\begin{rSection}{SUMMARY}",
                    summary,
                    r"\end{rSection}",
                ]
            )
        )

    sections.append(_render_skills_section(structured.get("skills", [])))  # type: ignore[arg-type]
    sections.append(_render_experience_section(structured.get("experience", [])))  # type: ignore[arg-type]
    sections.append(_render_projects_section(structured.get("projects", [])))  # type: ignore[arg-type]
    sections.append(_render_education_section(structured.get("education", [])))  # type: ignore[arg-type]
    sections.append(_render_certifications_section(structured.get("certifications", [])))  # type: ignore[arg-type]
    sections.append(_render_achievements_section(structured.get("achievements", [])))  # type: ignore[arg-type]
    # Avoid blank paragraphs between sections (parskip adds visible vertical gaps).
    section_text = "\n".join(s for s in sections if s.strip())

    tex = rf"""\documentclass{{resume}}
\renewcommand{{\familydefault}}{{\sfdefault}}
\usepackage[left=0.3in,top=0.15in,right=0.5in,bottom=0.2in]{{geometry}}
\usepackage{{hyperref}}
\usepackage{{enumitem}}
\setlist[itemize]{{leftmargin=*, noitemsep, topsep=0pt, partopsep=0pt, parsep=0pt}}
\newcommand{{\tab}}[1]{{\hspace{{.2667\textwidth}}\rlap{{#1}}}}
\newcommand{{\itab}}[1]{{\hspace{{0em}}\rlap{{#1}}}}
\name{{{name}}}
\address{{{contact_line}}}

\begin{{document}}
\small
{section_text}
\end{{document}}
"""
    return tex


def _copy_latex_assets(output_dir: Path) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    copied: Dict[str, str] = {}
    for fname in ("resume.cls", "resume_faangpath.tex"):
        src = TEMPLATE_DIR / fname
        if src.exists():
            dst = output_dir / fname
            shutil.copyfile(src, dst)
            copied[fname] = dst.as_posix()
    return copied


def generate_latex_resume_from_file(
    resume_path: str,
    jd_text: str = "",
    output_dir: str = "artifacts",
) -> Dict[str, object]:
    resume_file = Path(resume_path)
    if not resume_file.exists():
        return {"ok": False, "error": f"Resume file not found: {resume_file.as_posix()}"}

    resume_text = _read_file(resume_file).strip()
    if not resume_text:
        return {"ok": False, "error": "Could not extract text from uploaded resume."}

    mode = "heuristic"
    notes = ""
    model_used = ""
    try:
        structured, model_used = _extract_resume_structured_openai(resume_text, jd_text)
        mode = "openai"
        notes = "Structured extraction and role/responsibility formatting done via OpenAI."
    except Exception as e:
        structured = _extract_resume_structured_heuristic(resume_text, jd_text)
        notes = f"Heuristic extraction fallback used: {e}"

    structured, jd_notes = _enforce_structured_jd_alignment(structured, jd_text, force_visible=(mode == "heuristic"))
    if jd_notes:
        notes = (notes + " | " + " ".join(jd_notes)).strip(" |")

    contact_line = str(structured.get("contact_line", "") or "")
    enriched_contact = _enrich_contact_line_with_urls(contact_line, _extract_urls_from_pdf_annotations(resume_file))
    if enriched_contact and enriched_contact != contact_line:
        structured["contact_line"] = enriched_contact
        notes = (notes + " | " + "Enriched contact line with link URLs extracted from PDF annotations.").strip(" |")

    tex = render_latex_resume(structured)

    out_dir = Path(output_dir) / "latex"
    out_dir.mkdir(parents=True, exist_ok=True)
    tex_path = out_dir / f"{resume_file.stem}_templated.tex"
    tex_path.write_text(tex, encoding="utf-8")
    assets = _copy_latex_assets(out_dir)

    return {
        "ok": True,
        "mode": mode,
        "model": model_used,
        "notes": notes,
        "resume_source": resume_file.as_posix(),
        "tex_path": tex_path.as_posix(),
        "asset_paths": assets,
        "sections": {
            "skills": len(structured.get("skills", [])),
            "experience": len(structured.get("experience", [])),
            "projects": len(structured.get("projects", [])),
            "education": len(structured.get("education", [])),
            "certifications": len(structured.get("certifications", [])),
            "achievements": len(structured.get("achievements", [])),
        },
    }
