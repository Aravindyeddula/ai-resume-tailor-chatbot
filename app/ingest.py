import html
import json
import math
import pickle
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Tuple


TOKEN_RE = re.compile(r"[A-Za-z0-9']+")


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


def _tokenize(text: str) -> List[str]:
    return TOKEN_RE.findall(text.lower())


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_html_file(path: Path) -> str:
    parser = _SimpleHTMLTextExtractor()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    return html.unescape(parser.get_text())


def _read_pdf_file(path: Path) -> str:
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


def _read_supported_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return _read_text_file(path)
    if suffix in {".html", ".htm"}:
        return _read_html_file(path)
    if suffix == ".pdf":
        return _read_pdf_file(path)
    return ""


def _normalize_text(text: str) -> str:
    # Join line-broken hyphenated words from PDF extraction: "train-\ning" -> "training".
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    # Preserve paragraph boundaries, but normalize single newlines within paragraphs.
    paragraphs = [re.sub(r"\s+", " ", p.strip()) for p in re.split(r"\n\s*\n", text) if p.strip()]
    return "\n\n".join(paragraphs)


def _split_sentences(paragraph: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", paragraph.strip())
    return [p.strip() for p in parts if p.strip()]


def _split_long_sentence(sentence: str, max_chars: int) -> List[str]:
    words = sentence.split()
    if not words:
        return []
    pieces: List[str] = []
    cur = words[0]
    for w in words[1:]:
        candidate = f"{cur} {w}"
        if len(candidate) <= max_chars:
            cur = candidate
        else:
            pieces.append(cur)
            cur = w
    if cur:
        pieces.append(cur)
    return pieces


def _tail_overlap_words(text: str, overlap_chars: int) -> str:
    words = text.split()
    if not words:
        return ""
    tail: List[str] = []
    total = 0
    for w in reversed(words):
        add = len(w) if not tail else len(w) + 1
        if total + add > overlap_chars:
            break
        tail.append(w)
        total += add
    return " ".join(reversed(tail))


def _chunk_text(text: str, max_chars: int = 700, overlap: int = 120) -> List[str]:
    text = _normalize_text(text)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []

    chunks: List[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for para in paragraphs:
        sentences = _split_sentences(para)
        if not sentences:
            sentences = [para]

        for sent in sentences:
            parts = [sent] if len(sent) <= max_chars else _split_long_sentence(sent, max_chars)
            for part in parts:
                candidate = part if not current else f"{current} {part}"
                if len(candidate) <= max_chars:
                    current = candidate
                else:
                    prev = current
                    flush()
                    overlap_tail = _tail_overlap_words(prev, overlap)
                    current = f"{overlap_tail} {part}".strip() if overlap_tail else part
                    if len(current) > max_chars:
                        # Safety fallback for pathological tokens.
                        current = current[:max_chars].rsplit(" ", 1)[0] or current[:max_chars]
    flush()
    return chunks


def _read_docs(input_dir: Path) -> List[Path]:
    supported = {".txt", ".md", ".html", ".htm", ".pdf"}
    files: List[Path] = []
    for path in sorted(input_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in supported and path.name.lower() != "readme.md":
            files.append(path)
    return files


def _build_tfidf(chunks: List[Dict[str, str]]) -> Tuple[Dict[str, int], List[float], List[List[float]]]:
    docs = [_tokenize(c["text"]) for c in chunks]
    vocab: Dict[str, int] = {}
    doc_freq: Dict[str, int] = {}

    for tokens in docs:
        for token in set(tokens):
            doc_freq[token] = doc_freq.get(token, 0) + 1

    for token in sorted(doc_freq.keys()):
        vocab[token] = len(vocab)

    n_docs = len(docs)
    idf = [0.0] * len(vocab)
    for token, idx in vocab.items():
        idf[idx] = math.log((1 + n_docs) / (1 + doc_freq[token])) + 1.0

    vectors: List[List[float]] = []
    for tokens in docs:
        if not tokens:
            vectors.append([0.0] * len(vocab))
            continue
        counts: Dict[int, int] = {}
        for token in tokens:
            idx = vocab.get(token)
            if idx is not None:
                counts[idx] = counts.get(idx, 0) + 1
        total = float(len(tokens))
        vec = [0.0] * len(vocab)
        for idx, cnt in counts.items():
            vec[idx] = (cnt / total) * idf[idx]
        vectors.append(vec)
    return vocab, idf, vectors


def build_index(input_dir: str = "sample_docs", data_dir: str = "data") -> Dict[str, object]:
    source_dir = Path(input_dir)
    out_dir = Path(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    docs = _read_docs(source_dir)
    chunks: List[Dict[str, str]] = []
    chunk_id = 1

    for path in docs:
        text = _read_supported_file(path)
        if not text.strip():
            continue
        for chunk in _chunk_text(text):
            chunks.append(
                {
                    "chunk_id": f"chunk_{chunk_id}",
                    "source": path.as_posix(),
                    "locator": f"chunk_{chunk_id}",
                    "text": chunk,
                }
            )
            chunk_id += 1

    vocab, idf, vectors = _build_tfidf(chunks) if chunks else ({}, [], [])
    (out_dir / "index.json").write_text(json.dumps(chunks, indent=2), encoding="utf-8")
    with (out_dir / "vectorizer.pkl").open("wb") as f:
        pickle.dump({"vocab": vocab, "idf": idf}, f)
    (out_dir / "matrix.npz").write_text(json.dumps({"vectors": vectors}), encoding="utf-8")

    return {
        "documents_indexed": len(docs),
        "chunks_indexed": len(chunks),
        "data_dir": out_dir.as_posix(),
    }
