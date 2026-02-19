from pathlib import Path
from typing import Dict, List

import streamlit as st

from app.ingest import build_index
from app.memory import decide_memory, write_memory
from app.qa import generate_answer
from app.resume_tailor import tailor_resume
from app.retrieval import retrieve


UPLOAD_DIR = Path("uploads")
DATA_DIR = "data"


def _looks_like_question(text: str) -> bool:
    t = text.strip().lower()
    if "?" in t:
        return True
    cues = ("what ", "why ", "how ", "when ", "where ", "who ", "which ", "tell me", "explain", "summarize", "give ")
    return any(t.startswith(c) for c in cues)


def _inject_styles() -> None:
    st.markdown(
        """
<style>
.stApp {
  background:
    radial-gradient(circle at 12% 8%, rgba(255, 209, 102, 0.28), transparent 34%),
    radial-gradient(circle at 88% 14%, rgba(58, 134, 255, 0.22), transparent 35%),
    radial-gradient(circle at 72% 84%, rgba(6, 214, 160, 0.14), transparent 32%),
    linear-gradient(150deg, #f4f8ff 0%, #f7fbff 45%, #f3fcf8 100%);
  color: #10253f;
}
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #f9fcff 0%, #f4f9ff 100%);
  border-right: 1px solid #d7e4f3;
}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
  gap: 0.65rem;
}
[data-testid="stSidebar"] .stButton > button,
.stButton > button {
  border: 0;
  border-radius: 12px;
  color: #ffffff;
  background: linear-gradient(135deg, #2864dc 0%, #1f74e0 55%, #2398de 100%);
  font-weight: 600;
  box-shadow: 0 8px 22px rgba(31, 98, 214, 0.23);
}
[data-testid="stSidebar"] .stButton > button:hover,
.stButton > button:hover {
  filter: brightness(1.04);
}
.hero-wrap {
  margin-top: 0.15rem;
  margin-bottom: 0.55rem;
  padding: 1.1rem 1.25rem;
  border-radius: 18px;
  border: 1px solid rgba(181, 203, 227, 0.66);
  background: linear-gradient(125deg, rgba(255,255,255,0.82), rgba(246,251,255,0.7));
  box-shadow: 0 12px 26px rgba(47, 98, 157, 0.10);
}
.brand-title {
  font-size: 2.15rem;
  font-weight: 700;
  letter-spacing: 0.005em;
  margin: 0 0 0.25rem 0;
  color: #10253f;
}
.brand-sub {
  margin: 0;
  color: #49627f;
  font-size: 1.1rem;
}
.pill {
  display: inline-block;
  background: linear-gradient(120deg, #e7f0ff 0%, #e8f6ff 100%);
  border: 1px solid #bfd4ff;
  color: #18479b;
  border-radius: 999px;
  padding: 0.25rem 0.75rem;
  font-size: 0.86rem;
  margin-right: 0.4rem;
  margin-bottom: 0.3rem;
}
.stChatMessage {
  border: 1px solid #d6e2ef;
  border-radius: 16px;
  box-shadow: 0 8px 20px rgba(28, 59, 94, 0.08);
}
.stChatMessage[data-testid="stChatMessage-user"] {
  background: linear-gradient(180deg, #ffffff 0%, #f9fcff 100%);
}
.stChatMessage[data-testid="stChatMessage-assistant"] {
  background: linear-gradient(180deg, #f5faff 0%, #f8fff9 100%);
}
[data-testid="stChatInputTextArea"] textarea {
  font-size: 1.02rem !important;
}
.stMarkdown p, .stMarkdown li, .stCaption {
  font-size: 1.03rem;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def _save_uploaded_files(files: List[object]) -> List[str]:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved: List[str] = []
    for f in files:
        if not f:
            continue
        target = UPLOAD_DIR / f.name
        target.write_bytes(f.getbuffer())
        saved.append(target.as_posix())
    return saved


def _save_uploaded_file(file_obj: object, prefix: str = "") -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = getattr(file_obj, "name", "upload.txt")
    safe_name = f"{prefix}_{name}" if prefix else name
    target = UPLOAD_DIR / safe_name
    target.write_bytes(file_obj.getbuffer())
    return target.as_posix()


def _render_sidebar() -> Dict[str, object]:
    st.sidebar.markdown("## Knowledge Base")
    uploaded = st.sidebar.file_uploader(
        "Upload files",
        type=["txt", "md", "html", "htm", "pdf"],
        accept_multiple_files=True,
        help="Suitable file formats: txt, md, html, htm, pdf",
    )
    top_k = st.sidebar.slider("Chunks to retrieve", min_value=1, max_value=10, value=5, step=1)

    status: Dict[str, object] = {"top_k": top_k, "upload_result": None, "saved_files": []}

    if st.sidebar.button("Upload & Index", use_container_width=True):
        files = uploaded or []
        saved = _save_uploaded_files(files)
        ingest = build_index(input_dir=UPLOAD_DIR.as_posix(), data_dir=DATA_DIR)
        st.session_state["latest_upload"] = {"saved_files": saved, "ingest_result": ingest}
        status["saved_files"] = saved
        status["upload_result"] = ingest

    latest_upload = st.session_state.get("latest_upload")
    if latest_upload and latest_upload.get("saved_files"):
        st.sidebar.markdown("### Uploaded Files")
        for i, p in enumerate(latest_upload["saved_files"], start=1):
            st.sidebar.markdown(f"{i}. `{p}`")
        ingest = latest_upload.get("ingest_result", {})
        if ingest:
            st.sidebar.caption(
                f"Documents: {ingest.get('documents_indexed', 0)} | Chunks: {ingest.get('chunks_indexed', 0)}"
            )

    st.sidebar.markdown("---")
    st.sidebar.markdown("## Write Memory")
    memory_text = st.sidebar.text_area(
        "High-signal fact",
        placeholder="I'm a Project Finance Analyst.",
        height=110,
    )
    if st.sidebar.button("Save Memory", use_container_width=True):
        decision = decide_memory(memory_text)
        write_result = write_memory(decision)
        if write_result.get("written") == "true":
            st.sidebar.success(f"Saved to {write_result['target']}: {write_result['summary']}")
        else:
            st.sidebar.warning("Not saved (low signal, duplicate, or sensitive).")

    st.sidebar.markdown("---")
    st.sidebar.markdown("## Resume Tailor")
    st.sidebar.caption("Upload 1 resume + 1 JD file. Output preserves extension for txt/md/html; pdf falls back to txt.")
    resume_file = st.sidebar.file_uploader(
        "Resume file",
        type=["txt", "md", "html", "htm", "pdf"],
        accept_multiple_files=False,
        key="resume_tailor_resume",
    )
    jd_file = st.sidebar.file_uploader(
        "Job description file",
        type=["txt", "md", "html", "htm", "pdf"],
        accept_multiple_files=False,
        key="resume_tailor_jd",
    )
    if st.sidebar.button("Tailor Resume", use_container_width=True):
        if not resume_file or not jd_file:
            st.sidebar.error("Please upload both resume and JD files.")
        else:
            saved_resume = _save_uploaded_file(resume_file, prefix="resume")
            saved_jd = _save_uploaded_file(jd_file, prefix="jd")
            result = tailor_resume(resume_path=saved_resume, jd_path=saved_jd, output_dir="artifacts")
            st.session_state["latest_tailored_resume"] = result

    latest_tailored = st.session_state.get("latest_tailored_resume")
    if latest_tailored:
        if latest_tailored.get("ok"):
            output_path = latest_tailored.get("output_path", "")
            st.sidebar.success(f"Tailoring complete ({latest_tailored.get('mode')}).")
            if output_path and Path(str(output_path)).exists():
                out_path = Path(str(output_path))
                st.sidebar.download_button(
                    "Download tailored resume",
                    data=out_path.read_bytes(),
                    file_name=out_path.name,
                    mime="application/octet-stream",
                    use_container_width=True,
                )
            if latest_tailored.get("change_summary"):
                st.sidebar.markdown("### Change Summary")
                for item in latest_tailored["change_summary"]:
                    st.sidebar.markdown(f"- {item}")
            notes = latest_tailored.get("notes")
            if notes:
                st.sidebar.caption(str(notes))
            if not latest_tailored.get("format_preserved", True):
                st.sidebar.warning("Original extension was not preserved for output.")
        else:
            st.sidebar.error(str(latest_tailored.get("error", "Tailoring failed.")))

    return status


def _render_assistant_meta(meta: Dict[str, object]) -> None:
    citations = meta.get("citations", [])
    mode = meta.get("mode", "deterministic")
    requested = meta.get("requested_k", 0)
    returned = meta.get("returned_k", 0)
    cited = meta.get("cited_k", len(citations))
    total = meta.get("total_chunks_indexed", 0)
    best = meta.get("best_chunk")

    st.markdown(
        f"<span class='pill'>mode: {mode}</span>"
        f"<span class='pill'>requested: {requested}</span>"
        f"<span class='pill'>retrieved: {returned}</span>"
        f"<span class='pill'>cited: {cited}</span>"
        f"<span class='pill'>indexed: {total}</span>",
        unsafe_allow_html=True,
    )
    if int(cited) < int(returned):
        st.caption("Citations are relevance-filtered; not every retrieved chunk is shown as a citation.")

    if best:
        st.caption(f"Best chunk: {best.get('locator')} | {best.get('source')} | score={best.get('score')}")

    if citations:
        with st.expander("Citations", expanded=False):
            for i, c in enumerate(citations, start=1):
                st.markdown(f"{i}. `{c.get('source')}` | `{c.get('locator')}`")
                st.caption(f"Snippet: {c.get('snippet')}")


def _render_memory_suggestion() -> None:
    pending = st.session_state.get("pending_memory")
    if not pending:
        return
    decision = pending.get("decision", {})
    text = pending.get("text", "")
    if not decision.get("should_write"):
        return

    st.markdown("### Memory Suggestion")
    st.info(
        f"I detected a high-signal fact from your last message.\n\n"
        f"- Target: `{decision.get('target')}`\n"
        f"- Summary: {decision.get('summary')}\n"
        f"- Confidence: {round(float(decision.get('confidence', 0.0)), 2)}"
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save Suggested Memory", key="save_suggested_memory", use_container_width=True):
            write_result = write_memory(decide_memory(text))
            if write_result.get("written") == "true":
                st.success(f"Saved to {write_result['target']}: {write_result['summary']}")
            else:
                st.warning("Not saved (duplicate or policy-filtered).")
            st.session_state["pending_memory"] = None
    with c2:
        if st.button("Skip", key="skip_suggested_memory", use_container_width=True):
            st.session_state["pending_memory"] = None
            st.caption("Suggestion skipped.")


def main() -> None:
    st.set_page_config(page_title="Agentic RAG Chatbot", page_icon="💬", layout="wide")
    _inject_styles()

    sidebar_state = _render_sidebar()
    top_k = int(sidebar_state["top_k"])

    st.markdown(
        """
<div class="hero-wrap">
  <h1 class="brand-title">Agentic RAG Chatbot</h1>
  <p class="brand-sub">Ask grounded questions on uploaded files with source-linked citations and selective memory.</p>
</div>
        """,
        unsafe_allow_html=True,
    )

    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = [
            {
                "role": "assistant",
                "content": "Upload files in the sidebar, click Upload & Index, then ask your question here.",
                "meta": {},
            }
        ]

    for msg in st.session_state["chat_messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant" and msg.get("meta"):
                _render_assistant_meta(msg["meta"])

    _render_memory_suggestion()

    prompt = st.chat_input("Ask a question about the indexed documents...")
    if not prompt:
        return

    st.session_state["chat_messages"].append({"role": "user", "content": prompt, "meta": {}})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Conversation-based memory selectivity: suggest memory writes from user statements.
    decision = decide_memory(prompt)
    st.session_state["pending_memory"] = {
        "text": prompt,
        "decision": {
            "should_write": decision.should_write,
            "target": decision.target,
            "summary": decision.summary,
            "confidence": decision.confidence,
        },
    }
    # If user shared a high-signal statement (not a question), prioritize memory suggestion and skip RAG answer.
    if decision.should_write and not _looks_like_question(prompt):
        assistant_msg = (
            f"I detected a memory candidate: `{decision.summary}`.\n"
            f"Use **Save Suggested Memory** to store it in `{decision.target}_MEMORY.md`."
        )
        st.session_state["chat_messages"].append({"role": "assistant", "content": assistant_msg, "meta": {}})
        with st.chat_message("assistant"):
            st.markdown(assistant_msg)
        st.rerun()
        return

    results = retrieve(prompt, top_k=top_k, data_dir=DATA_DIR, fill_to_top_k=True)
    answer, citations, mode = generate_answer(prompt, results)
    best = None
    if results:
        best = {
            "locator": results[0].get("locator", ""),
            "source": results[0].get("source", ""),
            "score": round(float(results[0].get("score", 0.0)), 4),
        }

    total_chunks = 0
    index_file = Path(DATA_DIR) / "index.json"
    if index_file.exists():
        import json

        try:
            total_chunks = len(json.loads(index_file.read_text(encoding="utf-8")))
        except Exception:
            total_chunks = 0

    meta = {
        "citations": citations,
        "mode": mode,
        "requested_k": top_k,
        "returned_k": len(results),
        "cited_k": len(citations),
        "total_chunks_indexed": total_chunks,
        "best_chunk": best,
    }

    st.session_state["chat_messages"].append({"role": "assistant", "content": answer, "meta": meta})
    with st.chat_message("assistant"):
        st.markdown(answer)
        _render_assistant_meta(meta)


if __name__ == "__main__":
    main()
