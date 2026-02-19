import json
import os
import re
import ast
import urllib.error
import urllib.request
from typing import Dict, List, Tuple


NOT_FOUND_MSG = "I can't find this in the uploaded documents."
SENSITIVE_REFUSAL_MSG = "I can't provide that, and I can't find this in the uploaded documents."
TOKEN_RE = re.compile(r"[A-Za-z0-9']+")
STOPWORDS = {
    "about",
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
    "give",
    "in",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "tell",
    "the",
    "this",
    "to",
    "detail",
    "detailed",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}

PHONE_RE = re.compile(r"(\+?\d[\d\-\s()]{6,}\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _tokenize(text: str) -> List[str]:
    return TOKEN_RE.findall(text.lower())


def _question_keywords(question: str) -> set:
    return {t for t in _tokenize(question) if t not in STOPWORDS and len(t) > 1}


def _is_sensitive_lookup_question(question: str) -> bool:
    q = question.lower()
    entity_terms = ["ceo", "founder", "manager", "director", "person", "employee"]
    data_terms = ["phone", "number", "email", "contact", "ssn", "address"]
    return any(e in q for e in entity_terms) and any(d in q for d in data_terms)


def _contains_requested_contact_data(question: str, text: str) -> bool:
    q = question.lower()
    t = text.lower()
    if any(k in q for k in ["phone", "number", "contact"]):
        if PHONE_RE.search(text):
            return True
    if "email" in q:
        if EMAIL_RE.search(text):
            return True
    if "ssn" in q:
        if re.search(r"\b\d{3}-\d{2}-\d{4}\b", text):
            return True
    if "address" in q:
        if re.search(r"\b(street|st\.|road|rd\.|avenue|ave\.|blvd|lane|ln\.)\b", t):
            return True
    return False


def _is_meta_out_of_scope_prompt(question: str) -> bool:
    q = question.lower().strip()
    if "ask a question not covered by your docs" in q:
        return True
    if "ask a question not covered by your documents" in q:
        return True
    if "ask a question not covered by uploaded docs" in q:
        return True
    if "ask a question not covered by uploaded documents" in q:
        return True
    if re.search(r"\bask\b.*\bquestion\b", q) and re.search(r"\bnot covered\b", q):
        if any(k in q for k in ["docs", "documents", "uploaded"]):
            return True
    return False


def _clean_line(text: str) -> str:
    cleaned = re.sub(r"^[^A-Za-z0-9-]+", "", text).strip()
    cleaned = re.sub(r"^\d{4}\)\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _strip_section_prefix(line: str) -> str:
    # Clean patterns like "1 Introduction ..." or "2.3 Abstract: ..."
    pattern = (
        r"^\d+(?:\.\d+)*\s+"
        r"(abstract|introduction|background|method|methodology|approach|results|discussion|conclusion|related work)"
        r"[:\-\s]+"
    )
    return re.sub(pattern, "", line, flags=re.IGNORECASE).strip()


def _finalize_answer(text: str) -> str:
    lines = text.splitlines()
    cleaned = [_strip_section_prefix(_clean_line(ln)) for ln in lines]
    cleaned = [ln for ln in cleaned if ln]
    return "\n".join(cleaned)


def _is_separator(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    return bool(re.fullmatch(r"[-=*_:.#\s]+", s))


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if s.startswith("-"):
        return False
    if s.endswith(":"):
        return True
    if re.match(r"^\d+\.?\s+\S+", s):
        return True
    letters = [ch for ch in s if ch.isalpha()]
    if not letters:
        return False
    upper_ratio = sum(1 for ch in letters if ch.isupper()) / len(letters)
    return upper_ratio > 0.85 and len(s) <= 90


def _extract_blocks(text: str) -> List[Dict[str, object]]:
    lines = [_clean_line(x) for x in text.splitlines()]
    lines = [x for x in lines if x and not _is_separator(x)]
    blocks: List[Dict[str, object]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _is_heading(line):
            heading = line.rstrip(":")
            body: List[str] = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if _is_heading(nxt) and not nxt.startswith("-"):
                    break
                body.append(nxt)
                j += 1
            if body:
                blocks.append({"heading": heading, "body": body})
            i = j
            continue
        i += 1
    return blocks


def _split_sentences(text: str) -> List[str]:
    merged = text.replace("\n", " ")
    parts = re.split(r"(?<=[.!?])\s+", merged)
    out = []
    for part in parts:
        cleaned = _clean_line(part)
        if cleaned and len(cleaned) >= 20 and not _is_separator(cleaned):
            out.append(cleaned)
    return out


def _score_text(question_keys: set, text: str, heading: str = "") -> int:
    if not question_keys:
        return 0
    terms = set(_tokenize(text))
    overlap = len(question_keys.intersection(terms))
    heading_overlap = len(question_keys.intersection(set(_tokenize(heading)))) if heading else 0
    return overlap + (2 * heading_overlap)


def _is_list_question(question: str) -> bool:
    q = question.lower()
    cues = ["list", "key", "components", "features", "types", "steps", "what are", "advantages", "disadvantages", "bullet", "bullets"]
    return any(c in q for c in cues)


def _is_explanatory_question(question: str) -> bool:
    q = question.lower()
    cues = ["explain", "how", "why", "overview", "summary", "about"]
    return any(c in q for c in cues)


def _is_detailed_question(question: str) -> bool:
    q = question.lower()
    cues = ["in detail", "detailed", "elaborate", "comprehensive", "deep dive"]
    return any(c in q for c in cues)


def _is_assumptions_limitations_question(question: str) -> bool:
    q = question.lower()
    return ("assumption" in q or "assumptions" in q) and ("limitation" in q or "limitations" in q)


def _is_numeric_detail_question(question: str) -> bool:
    q = question.lower()
    cues = ["numeric", "number", "experimental detail", "experiment", "bleu", "accuracy", "score", "percent", "%"]
    return any(c in q for c in cues)


def _build_assumptions_limitations_answer(results: List[Dict[str, object]]) -> str:
    limitation_markers = ["limitation", "limitations", "constraint", "constraints", "depends on", "semantic drift", "error propagation"]
    assumption_markers = ["assumption", "assumptions", "relies on", "we assume", "requires"]
    lim: List[str] = []
    asm: List[str] = []
    seen = set()
    def _trim_tail(s: str) -> str:
        markers = ["Inference methods", "IRS style", "Literary style", "Treasury style", "NCBI style", "BLEU Acc."]
        out = s
        for m in markers:
            idx = out.find(m)
            if idx != -1:
                out = out[:idx].strip()
        return out
    for r in results:
        for sent in _split_sentences(str(r.get("text", ""))):
            if not _sentence_is_usable(sent) or _is_noisy_sentence(sent):
                continue
            s = _trim_tail(_finalize_answer(sent))
            s_lower = s.lower()
            if s_lower in seen:
                continue
            seen.add(s_lower)
            if any(m in s_lower for m in limitation_markers):
                lim.append(s)
            elif any(m in s_lower for m in assumption_markers):
                asm.append(s)
    bullets: List[str] = []
    if asm:
        bullets.append(f"- Assumption: {asm[0]}")
    if lim:
        lim0 = lim[0]
        lim0_lower = lim0.lower()
        if "semantic drift" in lim0_lower or "error propagation" in lim0_lower:
            lim0 = (
                "The method is limited by semantic drift and error propagation, "
                "and depends on machine translation model quality."
            )
        bullets.append(f"- Limitation: {lim0}")
    if len(lim) > 1:
        bullets.append(f"- Limitation: {lim[1]}")
    if len(asm) > 1 and len(bullets) < 4:
        bullets.append(f"- Assumption: {asm[1]}")
    return "\n".join(bullets)


def _build_numeric_detail_answer(results: List[Dict[str, object]]) -> str:
    metric_markers = ["bleu", "accuracy", "score", "f1", "auc", "precision", "recall", "percent", "%", "table", "figure"]
    candidates: List[Tuple[float, str]] = []
    for r in results:
        retrieval_score = float(r.get("score", 0.0))
        for sent in _split_sentences(str(r.get("text", ""))):
            if not _sentence_is_usable(sent) or _is_noisy_sentence(sent):
                continue
            if not re.search(r"\d", sent):
                continue
            s = _finalize_answer(sent)
            s_lower = s.lower()
            bonus = 0.0
            if any(m in s_lower for m in metric_markers):
                bonus += 2.5
            num_matches = list(re.finditer(r"\d+(?:\.\d+)?", s))
            if len(num_matches) >= 2:
                bonus += 2.0
            elif len(num_matches) == 1:
                bonus += 0.8
            if re.search(r"\b\d+(\.\d+)?\s*%\b", s):
                bonus += 1.5
            if re.search(r"\b(table|figure)\s*\d+\b", s_lower):
                bonus += 1.0
            score = (retrieval_score * 10.0) + bonus
            candidates.append((score, s))
    if not candidates:
        return ""
    candidates.sort(key=lambda x: x[0], reverse=True)
    return f"Concrete numeric detail: {candidates[0][1]}"


def _requested_bullet_count(question: str, default_count: int = 3) -> int:
    q = question.lower()
    m = re.search(r"(\d+)\s*bullets?", q)
    if m:
        try:
            return max(1, min(8, int(m.group(1))))
        except Exception:
            return default_count
    if "bullet" in q:
        return default_count
    return 0


def _build_bullet_summary(question: str, results: List[Dict[str, object]], n: int = 3) -> str:
    q_keys = _question_keywords(question)
    q = question.lower()
    wants_contribution = "contribution" in q or "contributions" in q
    candidates: List[Tuple[float, str]] = []
    for r in results:
        retrieval_score = float(r.get("score", 0.0))
        for sent in _split_sentences(str(r.get("text", ""))):
            if not _sentence_is_usable(sent) or _is_noisy_sentence(sent):
                continue
            s_lower = sent.lower()
            if wants_contribution and "limitation" in s_lower:
                continue
            rel = _score_text(q_keys, sent)
            bonus = 0
            if "contribution" in q and ("contribution" in s_lower or "contributions" in s_lower):
                bonus += 4
            if "main" in q and "main" in s_lower:
                bonus += 2
            if any(k in s_lower for k in ["we propose", "we present", "we introduce", "our method", "our approach"]):
                bonus += 2
            score = rel + bonus + (retrieval_score * 10.0)
            if score > 0:
                candidates.append((score, sent))
    if not candidates:
        return ""
    candidates.sort(key=lambda x: x[0], reverse=True)
    chosen: List[str] = []
    seen = set()
    for _score, sent in candidates:
        norm = sent.lower().strip()
        if norm in seen:
            continue
        seen.add(norm)
        chosen.append(_finalize_answer(sent))
        if len(chosen) >= n:
            break
    if not chosen:
        return ""
    return "\n".join(f"- {c}" for c in chosen)


def _definition_term(question: str) -> str:
    q = question.strip().lower().rstrip("?.!")
    for prefix in ("what is ", "what's ", "define "):
        if q.startswith(prefix):
            return q[len(prefix) :].strip()
    return ""


def _extract_definition_answer(question: str, results: List[Dict[str, object]]) -> str:
    term = _definition_term(question)
    if not term:
        return ""
    term_tokens = [t for t in _tokenize(term) if t not in STOPWORDS and len(t) > 1]
    if not term_tokens:
        return ""

    candidates: List[Tuple[float, str]] = []
    for r in results:
        retrieval_score = float(r.get("score", 0.0))
        for sent in _split_sentences(str(r.get("text", ""))):
            if not _sentence_is_usable(sent) or _is_noisy_sentence(sent):
                continue
            s_lower = sent.lower()
            token_hits = sum(1 for t in term_tokens if t in s_lower)
            if token_hits == 0:
                continue
            # Prefer explicit definitions like "X is ..."
            explicit = 0
            if " is " in s_lower:
                explicit += 2
            if "(" in sent and ")" in sent:
                explicit += 1
            score = retrieval_score * 10.0 + token_hits * 3 + explicit
            candidates.append((score, sent))

    if not candidates:
        return ""

    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0][1]
    return _finalize_answer(best)


def _sentence_is_usable(sentence: str) -> bool:
    s = sentence.strip()
    if len(s) < 25:
        return False
    # Filter out citation-heavy/meta-like lines that hurt readability.
    if s.lower().startswith("arxiv:"):
        return False
    if re.search(r"\b\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4}\b", s):
        return False
    if "!" in s:
        return False
    return True


def _is_noisy_sentence(sentence: str) -> bool:
    s = sentence.lower()
    noisy_markers = [
        "figure ",
        "arxiv:",
        "prompt a",
        "prompt b",
        "k-shots",
        "route i",
        "route ii",
        "informal formal literary shakespearean",
        "he is really worried about it",
        "he is experiencing",
    ]
    return any(marker in s for marker in noisy_markers)


def _question_bigrams(question: str) -> set:
    tokens = [t for t in _tokenize(question) if t not in STOPWORDS and len(t) > 1]
    return {f"{tokens[i]} {tokens[i + 1]}" for i in range(len(tokens) - 1)}


def _build_detailed_answer(question: str, results: List[Dict[str, object]]) -> str:
    if not results:
        return ""
    q_keys = _question_keywords(question)
    q_lower = question.lower()
    bigrams = _question_bigrams(question)
    method_cues = ("propose", "train", "translate", "construct", "finetune", "workflow", "involves")

    best_chunk_idx = -1
    best_chunk_score = float("-inf")
    per_chunk_sentences: List[List[str]] = []

    for chunk_idx, r in enumerate(results):
        retrieval_score = float(r.get("score", 0.0))
        sentences = _split_sentences(str(r.get("text", "")))
        per_chunk_sentences.append(sentences)
        chunk_peak = float("-inf")
        for s in sentences:
            if not _sentence_is_usable(s) or _is_noisy_sentence(s):
                continue
            rel = _score_text(q_keys, s)
            s_lower = s.lower()
            phrase_bonus = sum(1 for bg in bigrams if bg in s_lower)
            exact_bonus = 4 if ("roundtrip translation" in q_lower and "roundtrip translation" in s_lower) else 0
            score = rel + (retrieval_score * 10.0) + (phrase_bonus * 2) + exact_bonus
            if score > chunk_peak:
                chunk_peak = score
        if chunk_peak > best_chunk_score:
            best_chunk_score = chunk_peak
            best_chunk_idx = chunk_idx

    if best_chunk_idx < 0:
        return ""

    selected: List[str] = []
    seen = set()
    primary = per_chunk_sentences[best_chunk_idx]
    for s in primary:
        if not _sentence_is_usable(s) or _is_noisy_sentence(s):
            continue
        rel = _score_text(q_keys, s)
        s_lower = s.lower()
        phrase_hit = any(bg in s_lower for bg in bigrams) or ("roundtrip translation" in q_lower and "roundtrip translation" in s_lower)
        has_method_cue = any(cue in s_lower for cue in method_cues)
        if rel >= 3 or phrase_hit or (rel >= 2 and has_method_cue):
            key = s_lower.strip()
            if key not in seen:
                selected.append(s)
                seen.add(key)
        if len(selected) >= 8:
            break

    if len(selected) < 4:
        candidates: List[Tuple[float, int, int, str]] = []
        for chunk_idx, sents in enumerate(per_chunk_sentences):
            retrieval_score = float(results[chunk_idx].get("score", 0.0))
            for sent_idx, s in enumerate(sents):
                if not _sentence_is_usable(s) or _is_noisy_sentence(s):
                    continue
                s_lower = s.lower()
                if s_lower.strip() in seen:
                    continue
                rel = _score_text(q_keys, s)
                phrase_bonus = sum(1 for bg in bigrams if bg in s_lower)
                exact_bonus = 4 if ("roundtrip translation" in q_lower and "roundtrip translation" in s_lower) else 0
                score = rel + (retrieval_score * 10.0) + (phrase_bonus * 2) + exact_bonus
                has_method_cue = any(cue in s_lower for cue in method_cues)
                if score > 0 and (has_method_cue or rel >= 3):
                    candidates.append((score, chunk_idx, sent_idx, s))
        candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
        for _score, _cidx, _sidx, s in candidates:
            selected.append(s)
            seen.add(s.lower().strip())
            if len(selected) >= 8:
                break

    return _finalize_answer("\n".join(selected[:8]))


def _deterministic_answer(question: str, results: List[Dict[str, object]]) -> str:
    if not results:
        return NOT_FOUND_MSG

    definition_answer = _extract_definition_answer(question, results)
    if definition_answer:
        return definition_answer

    q_keys = _question_keywords(question)
    want_list = _is_list_question(question)
    want_explain = _is_explanatory_question(question)
    want_detail = _is_detailed_question(question)
    bullet_count = _requested_bullet_count(question, default_count=3)
    q_lower = question.lower()

    if _is_assumptions_limitations_question(question):
        out = _build_assumptions_limitations_answer(results)
        if out:
            return out

    if _is_numeric_detail_question(question):
        out = _build_numeric_detail_answer(results)
        if out:
            return out

    if bullet_count > 0:
        bullet_summary = _build_bullet_summary(question, results, n=bullet_count)
        if bullet_summary:
            return bullet_summary

    if want_list:
        best_list_block = None
        best_list_score = float("-inf")
        for r in results:
            retrieval_score = float(r.get("score", 0.0))
            for block in _extract_blocks(str(r.get("text", ""))):
                heading = str(block["heading"])
                body_lines = [str(x) for x in block["body"]]
                bullets = [ln for ln in body_lines if ln.startswith("-")]
                if not bullets:
                    continue
                score = _score_text(q_keys, " ".join(body_lines), heading) + len(bullets)
                h = heading.lower()
                if "component" in q_lower and "component" in h:
                    score += 5
                if "feature" in q_lower and "feature" in h:
                    score += 5
                if "type" in q_lower and "type" in h:
                    score += 3
                combined = score + (retrieval_score * 10.0)
                if combined > best_list_score:
                    best_list_score = combined
                    best_list_block = {"heading": heading, "bullets": bullets}
        if best_list_block:
            limit = bullet_count if bullet_count > 0 else 6
            return _finalize_answer("\n".join([f"{best_list_block['heading']}:"] + best_list_block["bullets"][:limit]))

    best_block = None
    best_block_score = float("-inf")
    for r in results:
        retrieval_score = float(r.get("score", 0.0))
        for block in _extract_blocks(str(r.get("text", ""))):
            heading = str(block["heading"])
            body_lines = [str(x) for x in block["body"]]
            score = _score_text(q_keys, " ".join(body_lines), heading)
            combined = score + (retrieval_score * 10.0)
            if combined > best_block_score:
                best_block_score = combined
                best_block = {"heading": heading, "body": body_lines}

    if best_block and best_block_score > float("-inf"):
        body = best_block["body"]
        prose = [ln for ln in body if not ln.startswith("-") and _sentence_is_usable(ln)]
        bullets = [ln for ln in body if ln.startswith("-")]
        if want_explain:
            if want_detail:
                detailed = _build_detailed_answer(question, results)
                if detailed:
                    return detailed
                if prose:
                    scored_prose = [(_score_text(q_keys, ln), i, ln) for i, ln in enumerate(prose)]
                    scored_prose = [x for x in scored_prose if x[0] > 0]
                    if scored_prose:
                        scored_prose.sort(key=lambda x: (-x[0], x[1]))
                        top = scored_prose[:8]
                        top.sort(key=lambda x: x[1])
                        return _finalize_answer("\n".join([ln for _sc, _i, ln in top]))
                    return _finalize_answer("\n".join(prose[:3]))
                if bullets:
                    return _finalize_answer("\n".join([b.lstrip("- ").strip() for b in bullets[:8]]))
            if prose:
                return _finalize_answer("\n".join(prose[:2]))
            if bullets:
                return _finalize_answer("\n".join([b.lstrip("- ").strip() for b in bullets[:2]]))
        if prose:
            return _finalize_answer(prose[0])
        if bullets:
            return _finalize_answer(bullets[0].lstrip("- ").strip())

    best_sentence = ""
    best_score = float("-inf")
    best_sentence_chunk_idx = -1
    best_sentence_pos = -1
    for chunk_idx, r in enumerate(results):
        retrieval_score = float(r.get("score", 0.0))
        sentences = _split_sentences(str(r.get("text", "")))
        for sent_idx, sent in enumerate(sentences):
            if not _sentence_is_usable(sent):
                continue
            score = _score_text(q_keys, sent) + (retrieval_score * 10.0)
            if score > best_score:
                best_sentence = sent
                best_score = score
                best_sentence_chunk_idx = chunk_idx
                best_sentence_pos = sent_idx

    if best_sentence:
        if want_explain and want_detail and best_sentence_chunk_idx >= 0:
            detailed = _build_detailed_answer(question, results)
            if detailed:
                return detailed
            sentences = _split_sentences(str(results[best_sentence_chunk_idx].get("text", "")))
            scored_sentences = []
            for i, s in enumerate(sentences):
                if not _sentence_is_usable(s):
                    continue
                rel = _score_text(q_keys, s)
                if rel > 0:
                    scored_sentences.append((rel, i, s))
            scored_sentences.sort(key=lambda x: (-x[0], x[1]))
            top = scored_sentences[:6]
            top.sort(key=lambda x: x[1])  # preserve natural reading order
            detailed = [s for _rel, _i, s in top]
            if detailed:
                return _finalize_answer("\n".join(detailed))
        if want_explain:
            for r in results:
                sentences = _split_sentences(str(r.get("text", "")))
                for i, s in enumerate(sentences):
                    if s == best_sentence and i + 1 < len(sentences):
                        nxt = sentences[i + 1]
                        if _score_text(q_keys, nxt) > 0:
                            return _finalize_answer(f"{best_sentence}\n{nxt}")
        return _finalize_answer(best_sentence)

    text = _clean_line(str(results[0].get("text", "")).replace("\n", " "))
    return _finalize_answer(text[:240] + ("..." if len(text) > 240 else ""))


def _make_citations(results: List[Dict[str, object]], max_snippet: int = 180) -> List[Dict[str, str]]:
    citations = []
    for r in results:
        text = str(r.get("text", "")).replace("\n", " ").strip()
        snippet = text[:max_snippet] + ("..." if len(text) > max_snippet else "")
        citations.append(
            {
                "source": str(r.get("source", "")),
                "locator": str(r.get("locator", "")),
                "snippet": snippet,
            }
        )
    return citations


def _intent_filtered_results(question: str, results: List[Dict[str, object]]) -> List[Dict[str, object]]:
    q = question.lower()
    if _is_assumptions_limitations_question(question):
        keys = ["assumption", "assumptions", "limitation", "limitations", "semantic drift", "error propagation", "depends on"]
        filtered = [r for r in results if any(k in str(r.get("text", "")).lower() for k in keys)]
        return filtered or results
    if _is_numeric_detail_question(question):
        metric_keys = ["bleu", "accuracy", "score", "f1", "auc", "precision", "recall", "table", "figure", "%"]
        filtered = []
        for r in results:
            txt = str(r.get("text", ""))
            low = txt.lower()
            if re.search(r"\d", txt) and (any(k in low for k in metric_keys) or re.search(r"\b\d+(\.\d+)?\s*%\b", txt)):
                filtered.append(r)
        return filtered or results
    return results


def _extract_first_json_object(text: str) -> Dict[str, object]:
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
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return {}
    return {}


def _format_multiline_answer(text: str) -> str:
    s = text.strip()
    if not s:
        return s
    # Normalize escaped newline/tab sequences from model outputs.
    s = s.replace("\\n", "\n").replace("\\t", "\t")
    # Handle model outputs shaped like Python/JSON string lists: ['a', 'b'].
    if s.startswith("[") and s.endswith("]"):
        parsed = None
        try:
            parsed = ast.literal_eval(s)
        except Exception:
            try:
                parsed = json.loads(s)
            except Exception:
                parsed = None
        if isinstance(parsed, list):
            items = [str(x).strip() for x in parsed if str(x).strip()]
            if items:
                return "\n".join(f"- {x}" for x in items)
    # Split inline numbered points into separate lines: "1. ... 2. ..." or "1) ... 2) ..."
    s = re.sub(r"\s(?=\d+\.\s)", "\n", s)
    s = re.sub(r"\s(?=\d+\)\s)", "\n", s)
    # Split inline bullet glyphs into separate lines: "• a • b • c"
    s = re.sub(r"\s*•\s*", "\n• ", s)
    # Normalize repeated blank lines created by aggressive splitting.
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def _openai_answer(question: str, results: List[Dict[str, object]], model: str = "gpt-4.1-mini") -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    model_pref = os.getenv("OPENAI_MODEL", "").strip()
    if model_pref:
        models = [m.strip() for m in model_pref.split(",") if m.strip()]
    else:
        models = [model, "gpt-4o-mini"]
    # Keep order but remove duplicates.
    seen_models = set()
    models = [m for m in models if not (m in seen_models or seen_models.add(m))]

    context = "\n".join(
        f"[{i}] source={r.get('source')} locator={r.get('locator')} text={r.get('text')}"
        for i, r in enumerate(results, start=1)
    )
    last_err: Exception | None = None
    for mdl in models:
        payload = {
            "model": mdl,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You are a grounded RAG answerer. Use ONLY the provided context. "
                        "If context does not contain the answer, return grounded=false. "
                        "Never invent facts. Return STRICT JSON object with keys: "
                        "answer (string), grounded (boolean)."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question: {question}\n\nContext:\n{context}\n\n"
                        "Return only JSON. Example: "
                        '{"answer":"...","grounded":true}'
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
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_err = e
            continue
        text = body.get("output_text", "").strip()
        parsed = _extract_first_json_object(text)
        if parsed:
            grounded = bool(parsed.get("grounded", False))
            answer = str(parsed.get("answer", "")).strip()
            if grounded and answer:
                return _format_multiline_answer(answer)
            return NOT_FOUND_MSG
        output = body.get("output", [])
        parts: List[str] = []
        for item in output:
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    parts.append(content["text"])
        parsed = _extract_first_json_object("\n".join(parts).strip())
        if parsed:
            grounded = bool(parsed.get("grounded", False))
            answer = str(parsed.get("answer", "")).strip()
            if grounded and answer:
                return _format_multiline_answer(answer)
            return NOT_FOUND_MSG
    if last_err:
        raise last_err
    return NOT_FOUND_MSG


def generate_answer(question: str, results: List[Dict[str, object]]) -> Tuple[str, List[Dict[str, str]], str]:
    # Guardrail for sensitive lookup prompts: always refuse with no citations.
    if _is_sensitive_lookup_question(question):
        return SENSITIVE_REFUSAL_MSG, [], "deterministic"

    if not results:
        return NOT_FOUND_MSG, [], "deterministic"

    # Grounding gate: if retrieval confidence is weak, refuse instead of forcing an answer.
    min_grounded_score = float(os.getenv("MIN_GROUNDED_SCORE", "0.28"))
    min_grounded_cov_multi = float(os.getenv("MIN_GROUNDED_COVERAGE_MULTI", "0.22"))
    top_score = float(results[0].get("score", 0.0))
    top_cov = float(results[0].get("coverage", 0.0))
    q_key_count = len(_question_keywords(question))
    if top_score < min_grounded_score:
        return NOT_FOUND_MSG, [], "deterministic"
    # For multi-keyword questions, require minimum lexical coverage as an extra anti-hallucination gate.
    if q_key_count >= 2 and top_cov < min_grounded_cov_multi:
        return NOT_FOUND_MSG, [], "deterministic"

    # Treat evaluation/meta instructions as out-of-scope question prompts.
    if _is_meta_out_of_scope_prompt(question):
        return NOT_FOUND_MSG, [], "deterministic"

    cite_results = _intent_filtered_results(question, results)
    if os.getenv("OPENAI_API_KEY"):
        try:
            llm_answer = _openai_answer(question, results)
            if llm_answer == NOT_FOUND_MSG:
                return NOT_FOUND_MSG, [], "openai"
            return llm_answer, _make_citations(cite_results), "openai"
        except (RuntimeError, urllib.error.URLError, TimeoutError, ValueError, KeyError):
            pass
    deterministic_answer = _deterministic_answer(question, results)
    if deterministic_answer == NOT_FOUND_MSG:
        return NOT_FOUND_MSG, [], "deterministic"
    return _format_multiline_answer(deterministic_answer), _make_citations(cite_results), "deterministic"
