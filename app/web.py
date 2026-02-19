from pathlib import Path
from typing import Any, Dict

from flask import Flask, render_template, request
from werkzeug.utils import secure_filename

from .ingest import build_index
from .memory import decide_memory, write_memory
from .qa import generate_answer
from .retrieval import retrieve


UPLOAD_DIR = Path("uploads")
ALLOWED = {".txt", ".md", ".html", ".htm", ".pdf"}


def _total_index_chunks(data_dir: str = "data") -> int:
    index_file = Path(data_dir) / "index.json"
    if not index_file.exists():
        return 0
    try:
        import json

        return len(json.loads(index_file.read_text(encoding="utf-8")))
    except Exception:
        return 0


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

    @app.get("/")
    def home():
        return render_template("index.html", state={})

    @app.post("/upload")
    def upload():
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        saved = []
        for file in request.files.getlist("files"):
            if not file or not file.filename:
                continue
            name = secure_filename(file.filename)
            ext = Path(name).suffix.lower()
            if ext not in ALLOWED:
                continue
            target = UPLOAD_DIR / name
            file.save(target)
            saved.append(target.as_posix())

        result = build_index(input_dir=UPLOAD_DIR.as_posix(), data_dir="data")
        state: Dict[str, Any] = {"upload_message": f"Saved {len(saved)} file(s).", "saved_files": saved, "ingest_result": result}
        return render_template("index.html", state=state)

    @app.post("/ask")
    def ask():
        question = request.form.get("question", "").strip()
        top_k = int(request.form.get("top_k", "1") or "1")
        results = retrieve(question, top_k=top_k, data_dir="data", fill_to_top_k=True)
        answer, citations, mode = generate_answer(question, results)
        best_chunk = None
        if results:
            top = results[0]
            best_chunk = {
                "locator": top.get("locator", ""),
                "source": top.get("source", ""),
                "score": round(float(top.get("score", 0.0)), 4),
            }
        state = {
            "question": question,
            "answer": answer,
            "mode": mode,
            "citations": citations,
            "top_k": top_k,
            "returned_k": len(results),
            "total_chunks_indexed": _total_index_chunks("data"),
            "best_chunk": best_chunk,
        }
        return render_template("index.html", state=state)

    @app.post("/remember")
    def remember():
        text = request.form.get("text", "").strip()
        decision = decide_memory(text)
        write_result = write_memory(decision)
        state = {
            "memory_text": text,
            "decision": {
                "should_write": decision.should_write,
                "target": decision.target,
                "summary": decision.summary,
                "confidence": decision.confidence,
            },
            "write_result": write_result,
        }
        return render_template("index.html", state=state)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
