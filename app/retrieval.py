import json
import math
import pickle
import re
from pathlib import Path
from typing import Dict, List


TOKEN_RE = re.compile(r"[A-Za-z0-9']+")
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
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}

QUERY_EXPANSIONS = {
    "rag": ["retrieval", "augmented", "generation"],
    "llm": ["large", "language", "model"],
    "nmt": ["neural", "machine", "translation"],
    "tst": ["text", "style", "transfer"],
}


def _tokenize(text: str) -> List[str]:
    return TOKEN_RE.findall(text.lower())


def _content_tokens(text: str) -> set:
    return {t for t in _tokenize(text) if t not in STOPWORDS and len(t) > 1}


def _expand_query_terms(tokens: List[str]) -> List[str]:
    expanded: List[str] = []
    for token in tokens:
        expanded.append(token)
        for extra in QUERY_EXPANSIONS.get(token, []):
            if extra not in expanded:
                expanded.append(extra)
    return expanded


def _coverage_ratio(query_terms: List[str], chunk_tokens: set) -> float:
    if not query_terms:
        return 0.0
    overlap = len(set(query_terms).intersection(chunk_tokens))
    return overlap / max(1, len(set(query_terms)))


def _fuzzy_term_hits(query_terms: List[str], chunk_tokens: List[str]) -> int:
    if not query_terms or not chunk_tokens:
        return 0
    hits = 0
    token_set = set(chunk_tokens)
    for q in set(query_terms):
        if q in token_set:
            hits += 1
            continue
        # Handle OCR-merged forms like "contributionsare" for query term "contribution".
        if len(q) >= 5 and any((tok.startswith(q) or q in tok) for tok in chunk_tokens):
            hits += 1
    return hits


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _vectorize_query(query: str, vocab: Dict[str, int], idf: List[float]) -> List[float]:
    tokens = _tokenize(query)
    vec = [0.0] * len(vocab)
    if not tokens:
        return vec

    counts: Dict[int, int] = {}
    for t in tokens:
        idx = vocab.get(t)
        if idx is not None:
            counts[idx] = counts.get(idx, 0) + 1
    total = float(len(tokens))
    for idx, cnt in counts.items():
        vec[idx] = (cnt / total) * idf[idx]
    return vec


def _bm25_idf(n_docs: int, doc_freq: int) -> float:
    return math.log(1.0 + (n_docs - doc_freq + 0.5) / (doc_freq + 0.5))


def _bm25_score(
    query_terms: List[str],
    doc_tokens: List[str],
    doc_freq: Dict[str, int],
    n_docs: int,
    avg_doc_len: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    if not query_terms or not doc_tokens or n_docs == 0:
        return 0.0

    tf: Dict[str, int] = {}
    for token in doc_tokens:
        tf[token] = tf.get(token, 0) + 1

    dl = len(doc_tokens)
    denom_norm = k1 * (1.0 - b + b * (dl / max(avg_doc_len, 1e-9)))
    score = 0.0
    for term in set(query_terms):
        freq = tf.get(term, 0)
        if freq == 0:
            continue
        idf = _bm25_idf(n_docs, doc_freq.get(term, 0))
        score += idf * ((freq * (k1 + 1.0)) / (freq + denom_norm))
    return score


def retrieve(
    question: str,
    top_k: int = 1,
    min_score: float = 0.02,
    data_dir: str = "data",
    fill_to_top_k: bool = False,
) -> List[Dict[str, object]]:
    data_path = Path(data_dir)
    index_file = data_path / "index.json"
    vectorizer_file = data_path / "vectorizer.pkl"
    matrix_file = data_path / "matrix.npz"

    if not index_file.exists() or not vectorizer_file.exists() or not matrix_file.exists():
        return []

    chunks = json.loads(index_file.read_text(encoding="utf-8"))
    with vectorizer_file.open("rb") as f:
        vec_meta = pickle.load(f)
    vectors = json.loads(matrix_file.read_text(encoding="utf-8")).get("vectors", [])

    vocab = vec_meta.get("vocab", {})
    idf = vec_meta.get("idf", [])

    query_vec = _vectorize_query(question, vocab, idf)
    raw_query_terms = [t for t in _tokenize(question) if t not in STOPWORDS and len(t) > 1]
    query_terms = _expand_query_terms(raw_query_terms)
    query_term_set = set(query_terms)
    query_bigrams = {f"{query_terms[i]} {query_terms[i + 1]}" for i in range(len(query_terms) - 1)}

    doc_tokens_list = [_tokenize(str(c.get("text", ""))) for c in chunks]
    n_docs = len(doc_tokens_list)
    avg_doc_len = sum(len(t) for t in doc_tokens_list) / max(n_docs, 1)
    doc_freq: Dict[str, int] = {}
    for toks in doc_tokens_list:
        for token in set(toks):
            doc_freq[token] = doc_freq.get(token, 0) + 1

    scored: List[Dict[str, object]] = []
    for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
        chunk_text = str(chunk.get("text", ""))
        chunk_tokens = _content_tokens(chunk_text)
        chunk_token_list = _tokenize(chunk_text)
        cosine_score = _cosine(query_vec, vec)
        bm25_score = _bm25_score(query_terms, doc_tokens_list[i], doc_freq, n_docs, avg_doc_len)
        overlap = _fuzzy_term_hits(query_terms, chunk_token_list)
        coverage = overlap / max(1, len(set(query_terms)))
        scored.append(
            {
                "chunk_id": chunk.get("chunk_id", ""),
                "source": chunk.get("source", ""),
                "locator": chunk.get("locator", ""),
                "text": chunk_text,
                "cosine_score": cosine_score,
                "bm25_score": bm25_score,
                "overlap": overlap,
                "coverage": coverage,
            }
        )

    max_bm25 = max((x["bm25_score"] for x in scored), default=0.0)
    q_lower = question.lower()
    wants_contribution = "contribution" in q_lower or "contributions" in q_lower
    for item in scored:
        bm25_norm = item["bm25_score"] / max_bm25 if max_bm25 > 0 else 0.0
        base = (0.45 * item["cosine_score"]) + (0.35 * bm25_norm) + (0.20 * float(item.get("coverage", 0.0)))
        text_lower = str(item.get("text", "")).lower()
        phrase_hits = sum(1 for bg in query_bigrams if bg in text_lower)
        phrase_bonus = min(0.18, 0.03 * phrase_hits)
        intent_bonus = 0.0
        if wants_contribution and ("contribution" in text_lower or "contributions" in text_lower):
            intent_bonus += 0.22
        if wants_contribution and "limitation" in text_lower:
            intent_bonus -= 0.18

        noise_penalty = 0.0
        if "arxiv:" in text_lower:
            noise_penalty += 0.20
        if "informal formal literary shakespearean" in text_lower:
            noise_penalty += 0.20
        if "figure " in text_lower and "workflow" not in text_lower:
            noise_penalty += 0.08

        raw_score = max(0.0, base + phrase_bonus + intent_bonus - noise_penalty)
        # Calibrate to spread strong matches upward while keeping weak matches near zero.
        item["score"] = 1.0 / (1.0 + math.exp(-6.0 * (raw_score - 0.28)))

    scored.sort(key=lambda x: x["score"], reverse=True)
    # Respect requested top_k exactly (up to available chunks). First prefer relevant matches.
    selected = [x for x in scored if x["score"] >= min_score and x["overlap"] > 0][:top_k]
    if fill_to_top_k and len(selected) < top_k:
        chosen_ids = {x["chunk_id"] for x in selected}
        for item in scored:
            if item["chunk_id"] in chosen_ids:
                continue
            selected.append(item)
            if len(selected) >= top_k:
                break
    return selected
