import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict


SENSITIVE_PATTERNS = [
    r"\bpassword\b",
    r"\bapi[_ -]?key\b",
    r"\bsecret\b",
    r"\bssn\b",
    r"\bcredit card\b",
    r"\bprivate key\b",
    r"\btoken\b",
]

LOW_SIGNAL_PATTERNS = [
    r"\bhello\b",
    r"\bhi\b",
    r"\bthanks?\b",
    r"\bok(ay)?\b",
    r"\btest(ing)?\b",
]

USER_SIGNAL_KEYS = [
    "i am",
    "i'm",
    "my role",
    "i prefer",
    "i like",
    "every monday",
    "weekly",
    "daily",
    "monthly",
    "i work as",
    "i work at",
    "i work in",
]

COMPANY_SIGNAL_KEYS = [
    "workflow",
    "bottleneck",
    "recurring",
    "process",
    "team",
    "asset management",
    "approval",
    "pipeline",
    "policy",
    "interfaces often with",
    "cross-team",
]


@dataclass
class MemoryDecision:
    should_write: bool
    target: str
    summary: str
    confidence: float


def _looks_like_transcript_dump(text: str) -> bool:
    lower = text.lower()
    if len(text) > 350:
        return True
    turns = sum(1 for marker in ["user:", "assistant:", "system:", "q:", "a:"] if marker in lower)
    if turns >= 2:
        return True
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 6:
        return True
    return False


def _clean_summary(text: str, max_len: int = 140) -> str:
    s = re.sub(r"\s+", " ", text.strip())
    s = re.sub(r"^[\-\*\d\.\)\s]+", "", s)
    s = s.rstrip(".")
    if len(s) <= max_len:
        return s
    cut = s[:max_len].rsplit(" ", 1)[0].strip()
    return cut if cut else s[:max_len]


def _normalize_input(text: str) -> str:
    # Normalize smart quotes/apostrophes to improve rule matching.
    return text.replace("’", "'").replace("`", "'").replace("“", '"').replace("”", '"')


def _normalized_fact(text: str) -> str:
    t = text.lower()
    t = re.sub(r"^\-\s*\d{4}-\d{2}-\d{2}:\s*", "", t)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def decide_memory(text: str) -> MemoryDecision:
    raw = _normalize_input(text).strip()
    lower = raw.lower()
    if not raw:
        return MemoryDecision(False, "USER", "", 0.0)

    if _looks_like_transcript_dump(raw):
        return MemoryDecision(False, "USER", "", 0.0)

    for pat in SENSITIVE_PATTERNS:
        if re.search(pat, lower):
            return MemoryDecision(False, "USER", "", 0.0)

    if any(re.search(pat, lower) for pat in LOW_SIGNAL_PATTERNS):
        if len(lower.split()) <= 8:
            return MemoryDecision(False, "USER", "", 0.1)

    # Personal profile/role statements should always map to USER memory.
    personal_role_patterns = [
        r"^\s*i\s*am\s+a\s+.+",
        r"^\s*i[' ]?m\s+a\s+.+",
        r"^\s*my\s+role\s+is\s+.+",
        r"^\s*i\s+work\s+as\s+.+",
        r"^\s*i\s+work\s+at\s+.+",
        r"^\s*i\s+work\s+in\s+.+",
    ]
    if any(re.search(p, lower) for p in personal_role_patterns):
        return MemoryDecision(True, "USER", _clean_summary(raw), 0.94)

    # Company memory requires org/process context, not just department words.
    company_phrase_patterns = [
        r"\bworkflow bottleneck\b",
        r"\brecurring workflow\b",
        r"\basset management\b.*\bproject finance\b",
        r"\bproject finance\b.*\basset management\b",
        r"\binterfaces often with\b",
        r"\bapproval(s)?\b.*\bdelay(ed)?\b",
        r"\bprocess\b.*\bteam\b",
    ]
    if any(re.search(p, lower) for p in company_phrase_patterns):
        return MemoryDecision(True, "COMPANY", _clean_summary(raw), 0.9)

    user_hits = sum(1 for k in USER_SIGNAL_KEYS if k in lower)
    company_hits = sum(1 for k in COMPANY_SIGNAL_KEYS if k in lower)
    summary = _clean_summary(raw)

    if user_hits == 0 and company_hits == 0:
        return MemoryDecision(False, "USER", "", 0.2)

    if user_hits >= company_hits:
        confidence = min(0.98, 0.78 + (0.08 * user_hits))
        return MemoryDecision(True, "USER", summary, confidence)

    confidence = min(0.95, 0.72 + (0.06 * company_hits))
    return MemoryDecision(True, "COMPANY", summary, confidence)


def _append_unique(path: Path, line: str) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing:
        new_fact = _normalized_fact(line)
        for existing_line in existing.splitlines():
            if not existing_line.strip():
                continue
            old_fact = _normalized_fact(existing_line)
            if new_fact == old_fact:
                return False
            new_tokens = set(new_fact.split())
            old_tokens = set(old_fact.split())
            if new_tokens and old_tokens:
                overlap = len(new_tokens.intersection(old_tokens)) / max(len(new_tokens), len(old_tokens))
                if overlap >= 0.88:
                    return False
    with path.open("a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(line + "\n")
    return True


def write_memory(decision: MemoryDecision, user_path: str = "USER_MEMORY.md", company_path: str = "COMPANY_MEMORY.md") -> Dict[str, str]:
    if not decision.should_write or not decision.summary:
        return {"written": "false", "target": decision.target, "summary": ""}

    line = f"- {datetime.now().strftime('%Y-%m-%d')}: {decision.summary}"
    target_file = Path(user_path) if decision.target == "USER" else Path(company_path)
    wrote = _append_unique(target_file, line)
    return {"written": "true" if wrote else "false", "target": decision.target, "summary": decision.summary}
